"""Authoritative story route projection and frozen cloud-profile revalidation."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from lib.backend_assembly.assembler import _TUNING_KEY_RE
from lib.config.registry import PROVIDER_REGISTRY, model_info_for
from lib.config.resolver import ConfigResolver
from lib.config.url_utils import ensure_google_base_url
from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from lib.pricing.price_compiler import compile_pricing
from lib.pricing.request_metering import PriceTable
from r2.host_hardening.paid_routes import PaidRoute, PaidRouteUnqualifiedError, require_paid_route, route_binding
from server.story_authoring.cloud import CLOUD_ENDPOINT, GEMINI_STORY_MODELS
from server.story_authoring.contracts import CloudPriceBounds, CloudRouteProfile, StoryModelSelection

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from server.story_authoring.driver import StoryBrief

type Factory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True)
class ResolvedCloudRoute:
    selection: StoryModelSelection
    profile: CloudRouteProfile
    credential: str = field(repr=False)


def _prices(provider_id: str, model_id: str) -> CloudPriceBounds:
    info = model_info_for(provider_id, model_id)
    if info is None or info.hidden or info.media_type != "text":
        raise ValueError("cloud model is not selectable")
    table = compile_pricing(info.pricing, model_id=model_id)
    if not isinstance(table, PriceTable) or table.currency != "USD":
        raise ValueError("cloud model needs explicit USD token prices")
    rates = {
        meter.meter: Decimal(str(meter.rows[0].price))
        for meter in table.meters
        if not meter.dims and len(meter.rows) == 1 and not meter.rows[0].when and meter.free_allowance is None
    }
    if set(rates) != {"uncached_input_tokens", "output_tokens"}:
        raise ValueError("cloud model needs simple input/output token prices")
    return CloudPriceBounds(input_per_million=rates["uncached_input_tokens"], output_per_million=rates["output_tokens"])


async def resolve_cloud_route(factory: Factory, provider_id: str, model_id: str) -> ResolvedCloudRoute:
    if provider_id != "gemini-aistudio" or model_id not in GEMINI_STORY_MODELS:
        raise ValueError("cloud story adapter is not available for this route")
    prices = _prices(provider_id, model_id)
    async with ConfigResolver(factory).session() as resolver:
        config = await resolver.provider_config(provider_id)
        credential = config.get("api_key") or ""
        if not credential:
            raise ValueError("MISSING_CREDENTIAL")
        base_url = ensure_google_base_url(config.get("base_url")) or "https://generativelanguage.googleapis.com"
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("cloud base URL must be HTTPS without embedded credentials, query or fragment")
        config_binding = route_binding(
            provider_id=provider_id,
            media_type="text",
            **{key: value for key, value in config.items() if not _TUNING_KEY_RE.search(key)},
        )
    selection = StoryModelSelection.create(
        provider_id=provider_id, model_id=model_id, endpoint=CLOUD_ENDPOINT, base_url=base_url, has_credential=True
    )
    binding = route_binding(
        configuration=config_binding, workload="gemini-story-v1", prices=prices.model_dump(mode="json")
    )
    require_paid_route(PaidRoute("story", provider_id=provider_id), model_id=model_id, binding=binding)
    profile = CloudRouteProfile(selection_digest=selection.config_digest, binding=binding, prices=prices)
    return ResolvedCloudRoute(selection, profile, credential)


def max_prices(profiles: tuple[CloudRouteProfile, ...]) -> CloudPriceBounds:
    return CloudPriceBounds(
        input_per_million=max(p.prices.input_per_million for p in profiles),
        output_per_million=max(p.prices.output_per_million for p in profiles),
    )


async def validate_cloud_brief(factory: Factory, brief: StoryBrief) -> None:
    cloud = [selection for selection in (brief.selection, brief.judge) if selection.endpoint != "ollama-chat"]
    if not cloud:
        if brief.cloud_profiles or brief.limits.currency != "LOCAL" or brief.limits.cloud_prices is not None:
            raise ValueError("local brief must retain its local budget profile")
        return
    if not 1 <= brief.limits.max_cost_minor_units <= 10_000:
        raise ValueError("cloud USD cap is outside the approved range")
    resolved = []
    for selection in cloud:
        route = await resolve_cloud_route(factory, selection.provider_id, selection.model_id)
        if route.selection != selection:
            raise ValueError("cloud route changed")
        if route.profile not in brief.cloud_profiles:
            raise ValueError("cloud profile or configuration changed")
        if route.profile not in resolved:
            resolved.append(route.profile)
    if set(resolved) != set(brief.cloud_profiles):
        raise ValueError("unexpected cloud profile")
    if brief.limits.currency != "USD" or brief.limits.cloud_prices != max_prices(brief.cloud_profiles):
        raise ValueError("cloud money bounds changed")


async def story_routes(factory: Factory) -> list[dict[str, Any]]:
    async with factory() as session:
        providers = await CustomProviderRepository(session).list_providers_with_models()
    rows = []
    for provider, models in providers:
        rows.extend(
            {
                "provider_id": f"custom-{provider.id}",
                "model_id": model.model_id,
                "label": f"{provider.display_name} · {model.display_name or model.model_id}",
                "enabled": True,
                "reason": None,
                "cloud": False,
            }
            for model in models
            if model.is_enabled and model.endpoint == "ollama-chat"
        )
    for model_id, info in PROVIDER_REGISTRY["gemini-aistudio"].models.items():
        if model_id not in GEMINI_STORY_MODELS or info.hidden:
            continue
        reason = None
        try:
            await resolve_cloud_route(factory, "gemini-aistudio", model_id)
        except PaidRouteUnqualifiedError:
            reason = "NOT_QUALIFIED"
        except ValueError as exc:
            reason = "MISSING_CREDENTIAL" if str(exc) == "MISSING_CREDENTIAL" else "UNAVAILABLE"
        rows.append(
            {
                "provider_id": "gemini-aistudio",
                "model_id": model_id,
                "label": f"Gemini · {info.display_name}",
                "enabled": reason is None,
                "reason": reason,
                "cloud": True,
            }
        )
    return rows
