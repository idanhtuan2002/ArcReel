"""Read exact configured model identities and capability pins without constructing a backend."""

from dataclasses import asdict
from ipaddress import ip_address
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.config.registry import PROVIDER_REGISTRY, model_info_for
from lib.config.resolver import ConfigResolver
from lib.custom_provider import is_custom_endpoint, is_custom_provider, parse_endpoint_key, parse_provider_id
from lib.custom_provider.endpoints import get_endpoint_spec
from lib.db.models.custom_endpoint import CustomEndpoint
from lib.db.models.custom_provider import CustomProvider, CustomProviderModel
from r2.automation.identity import digest_value
from r2.contracts.automation import ModelRoute
from r2.contracts.common import ensure_json_value


def _local_url(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.hostname == "localhost":
        return True
    try:
        return ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        return False


async def inspect_model_route(
    session: AsyncSession, resolver: ConfigResolver, *, route: ModelRoute, project: dict
) -> ModelRoute:
    """Refresh configuration, preserving the run's explicit ceiling and registered model identity.

    The qualification owner resolves the model/weight identity and real corpus receipts. A loopback URL is
    transport locality only; local-only launch also requires the owner-qualified route inventory.
    """
    route = ModelRoute.model_validate(route)
    media_type = {"image": "image", "video": "video", "audio": "audio", "lip_sync": "video"}.get(route.role, "text")
    if is_custom_provider(route.provider_id):
        provider_id = parse_provider_id(route.provider_id)
        if provider_id <= 0 or route.provider_id != f"custom-{provider_id}":
            raise ValueError("PINNED_MODEL_UNAVAILABLE")
        provider = await session.get(CustomProvider, provider_id, populate_existing=True)
        model = (
            await session.execute(
                select(CustomProviderModel)
                .where(CustomProviderModel.provider_id == provider_id, CustomProviderModel.model_id == route.model_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if provider is None or model is None or not model.is_enabled:
            raise ValueError("PINNED_MODEL_UNAVAILABLE")
        if is_custom_endpoint(model.endpoint):
            endpoint = await session.get(CustomEndpoint, parse_endpoint_key(model.endpoint), populate_existing=True)
            if endpoint is None or endpoint.media_type != media_type:
                raise ValueError("PINNED_MODEL_UNAVAILABLE")
            definition = endpoint.definition
            endpoint_media_type = endpoint.media_type
        else:
            spec = get_endpoint_spec(model.endpoint)
            definition = dict(spec.definition) if spec.definition is not None else None
            endpoint_media_type = spec.media_type
        if endpoint_media_type != media_type:
            raise ValueError("PINNED_MODEL_UNAVAILABLE")
        config = {
            "provider_id": route.provider_id,
            "model_id": model.model_id,
            "base_url": provider.base_url,
            "credential": provider.api_key,
            "discovery_format": provider.discovery_format,
            "endpoint": model.endpoint,
            "definition": definition,
            "resolution": model.resolution,
            "supported_durations": model.supported_durations,
            "capability_overrides": model.capability_overrides,
            "price_unit": model.price_unit,
            "price_input": model.price_input,
            "price_output": model.price_output,
            "currency": model.currency,
        }
        base_url = provider.base_url
        currency = model.currency or route.currency
    else:
        info = model_info_for(route.provider_id, route.model_id)
        meta = PROVIDER_REGISTRY.get(route.provider_id)
        if info is None or meta is None or info.hidden or info.media_type != media_type:
            raise ValueError("PINNED_MODEL_UNAVAILABLE")
        provider_config = await resolver.provider_config(route.provider_id)
        base_url = provider_config.get("base_url") or meta.default_base_url or ""
        config = {
            "provider_id": route.provider_id,
            "model_id": route.model_id,
            "provider_config": provider_config,
            "model_info": asdict(info),
            "base_url": base_url,
        }
        currency = route.currency
    if route.role == "video":
        config["video_capabilities"] = await resolver.video_capabilities_for_model(
            route.provider_id, route.model_id, project, capability="i2v"
        )
    config["project_model_settings"] = project.get("model_settings", {})
    config["automation_roles"] = project.get("automation_roles", {})
    digest = digest_value("r2.production-route-config.v1", ensure_json_value(config))
    local = _local_url(base_url)
    # Credentials enter the private digest only. No returned route contains their values or the endpoint URL.
    return ModelRoute.model_validate(
        {
            **route.model_dump(mode="python"),
            "config_digest": digest,
            "local": local,
            "paid": not local,
            "currency": currency,
        }
    )
