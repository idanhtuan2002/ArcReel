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
from lib.custom_provider import is_custom_provider, parse_provider_id
from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from lib.pricing.price_compiler import compile_custom_pricing, compile_pricing
from lib.pricing.request_metering import PriceTable
from r2.host_hardening.paid_routes import PaidRoute, PaidRouteUnqualifiedError, require_paid_route, route_binding
from server.story_authoring.cloud import CLOUD_ADAPTERS, CLOUD_ENDPOINT, OPENAI_ENDPOINT
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


#: Built-in providers whose text models a story route can use, with the endpoint their API speaks.
BUILTIN_STORY_ENDPOINTS: dict[str, str] = {"gemini-aistudio": CLOUD_ENDPOINT, "openai": OPENAI_ENDPOINT}
DEFAULT_BASE_URLS: dict[str, str] = {
    CLOUD_ENDPOINT: "https://generativelanguage.googleapis.com",
    OPENAI_ENDPOINT: "https://api.openai.com/v1",
}


def _token_prices(table: object) -> CloudPriceBounds:
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


def _prices(provider_id: str, model_id: str) -> CloudPriceBounds:
    info = model_info_for(provider_id, model_id)
    if info is None or info.hidden or info.media_type != "text":
        raise ValueError("cloud model is not selectable")
    return _token_prices(compile_pricing(info.pricing, model_id=model_id))


def _https_base_url(base_url: str) -> str:
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
    return base_url


async def _builtin(factory: Factory, provider_id: str, model_id: str) -> tuple[str, str, str, CloudPriceBounds, dict]:
    endpoint = BUILTIN_STORY_ENDPOINTS.get(provider_id)
    if endpoint is None:
        raise ValueError("cloud story adapter is not available for this provider")
    prices = _prices(provider_id, model_id)
    async with ConfigResolver(factory).session() as resolver:
        config = await resolver.provider_config(provider_id)
    credential = config.get("api_key") or ""
    if not credential:
        raise ValueError("MISSING_CREDENTIAL")
    raw = config.get("base_url") or ""
    base_url = (ensure_google_base_url(raw) if endpoint == CLOUD_ENDPOINT else raw.strip()) or DEFAULT_BASE_URLS[
        endpoint
    ]
    binding = {key: value for key, value in config.items() if not _TUNING_KEY_RE.search(key)}
    return endpoint, _https_base_url(base_url), credential, prices, binding


async def _custom(factory: Factory, provider_id: str, model_id: str) -> tuple[str, str, str, CloudPriceBounds, dict]:
    async with factory() as session:
        repo = CustomProviderRepository(session)
        provider = await repo.get_provider(parse_provider_id(provider_id))
        model = await repo.get_model_by_ids(provider.id, model_id) if provider is not None else None
    if provider is None or model is None or not model.is_enabled or model.endpoint not in CLOUD_ADAPTERS:
        raise ValueError("cloud story adapter is not available for this route")
    prices = _token_prices(
        compile_custom_pricing(
            price_unit=model.price_unit,
            price_input=model.price_input,
            price_output=model.price_output,
            currency=model.currency,
        )
    )
    if not provider.api_key:
        raise ValueError("MISSING_CREDENTIAL")
    base_url = provider.base_url.strip() or DEFAULT_BASE_URLS[model.endpoint]
    if model.endpoint == CLOUD_ENDPOINT:
        base_url = ensure_google_base_url(base_url) or DEFAULT_BASE_URLS[CLOUD_ENDPOINT]
    binding = {"base_url": base_url, "api_key": provider.api_key, "endpoint": model.endpoint}
    return model.endpoint, _https_base_url(base_url), provider.api_key, prices, binding


async def resolve_cloud_route(factory: Factory, provider_id: str, model_id: str) -> ResolvedCloudRoute:
    """A paid story route of any text model that speaks a cloud endpoint and has USD token prices.

    The model is not on a list: a built-in Gemini or OpenAI model, or any custom-provider model on the
    ``gemini-generate`` or ``openai-chat`` endpoint, is usable once its price is set and, in a release
    deployment, its route has passed the paid-route qualification for this exact configuration.
    """
    try:
        source = _custom if is_custom_provider(provider_id) else _builtin
        endpoint, base_url, credential, prices, config = await source(factory, provider_id, model_id)
    except LookupError:
        raise ValueError("cloud story adapter is not available for this route") from None
    adapter = CLOUD_ADAPTERS[endpoint]
    config_binding = route_binding(provider_id=provider_id, media_type="text", **config)
    selection = StoryModelSelection.create(
        provider_id=provider_id, model_id=model_id, endpoint=endpoint, base_url=base_url, has_credential=True
    )
    binding = route_binding(configuration=config_binding, workload=adapter, prices=prices.model_dump(mode="json"))
    require_paid_route(PaidRoute("story", provider_id=provider_id), model_id=model_id, binding=binding)
    profile = CloudRouteProfile(
        selection_digest=selection.config_digest, binding=binding, adapter_version=adapter, prices=prices
    )
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


async def _cloud_row(factory: Factory, provider_id: str, model_id: str, label: str) -> dict[str, Any]:
    reason = None
    try:
        await resolve_cloud_route(factory, provider_id, model_id)
    except PaidRouteUnqualifiedError:
        reason = "NOT_QUALIFIED"
    except ValueError as exc:
        reason = "MISSING_CREDENTIAL" if str(exc) == "MISSING_CREDENTIAL" else "UNAVAILABLE"
    return {
        "provider_id": provider_id,
        "model_id": model_id,
        "label": label,
        "enabled": reason is None,
        "reason": reason,
        "cloud": True,
    }


async def story_routes(factory: Factory) -> list[dict[str, Any]]:
    """Every text model a story can use: local Ollama models, and cloud models of the configured providers."""
    async with factory() as session:
        providers = await CustomProviderRepository(session).list_providers_with_models()
    rows: list[dict[str, Any]] = []
    for provider, models in providers:
        for model in models:
            if not model.is_enabled:
                continue
            label = f"{provider.display_name} · {model.display_name or model.model_id}"
            if model.endpoint == "ollama-chat":
                rows.append(
                    {
                        "provider_id": f"custom-{provider.id}",
                        "model_id": model.model_id,
                        "label": label,
                        "enabled": True,
                        "reason": None,
                        "cloud": False,
                    }
                )
            elif model.endpoint in CLOUD_ADAPTERS:
                rows.append(await _cloud_row(factory, f"custom-{provider.id}", model.model_id, label))
    for provider_id in BUILTIN_STORY_ENDPOINTS:
        meta = PROVIDER_REGISTRY.get(provider_id)
        if meta is None:
            continue
        for model_id, info in meta.models.items():
            if info.hidden or info.media_type != "text":
                continue
            rows.append(await _cloud_row(factory, provider_id, model_id, f"{meta.display_name} · {info.display_name}"))
    return rows
