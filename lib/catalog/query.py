"""Immutable projections of existing model declarations, without provider construction.

The source version names this projection's schema, not a freshness proof or qualification.
Prices are declarations in their original units, not estimates or admission decisions.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.config.registry import model_info_for
from lib.custom_provider import is_custom_provider, make_provider_id, parse_provider_id
from lib.custom_provider.endpoint_resolution import resolve_endpoint_spec
from lib.db.models.custom_provider import CustomProviderModel
from lib.db.repositories.custom_endpoint_repo import CustomEndpointRepository

PROJECTION_VERSION = "v2-model-facts-v1"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class PriceFacts:
    """Original price shape and units, with recursively immutable declaration details."""

    kind: str
    currency: str | None
    details: Mapping[str, Any]


@dataclass(frozen=True)
class CatalogModel:
    """A descriptive provider/model identity; no credentials or execution permission."""

    provider_id: str
    model_id: str
    api_model_name: str | None
    media_type: str
    display_name: str
    enabled: bool
    hidden: bool
    default: bool
    endpoint: str | None
    capabilities: tuple[str, ...] | None
    supported_durations: tuple[int, ...] | None
    duration_resolution_constraints: Mapping[str, tuple[int, ...]]
    reference_image_durations: tuple[int, ...]
    resolutions: tuple[str, ...]
    pricing: PriceFacts | None
    source: Literal["builtin_registry", "custom_model"]
    source_version: str = PROJECTION_VERSION
    resolution: str | None = None
    capability_overrides: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


def builtin_model(provider_id: str, model_id: str) -> CatalogModel | None:
    """Exact builtin lookup, retaining hidden models and never choosing a fallback."""
    info = model_info_for(provider_id, model_id)
    if info is None:
        return None
    price = None
    if info.pricing is not None:
        details = asdict(info.pricing)
        kind, currency = details.pop("kind"), details.pop("currency")
        price = PriceFacts(kind=kind, currency=currency, details=_freeze(details))
    return CatalogModel(
        provider_id=provider_id,
        model_id=model_id,
        api_model_name=info.api_model_name,
        media_type=info.media_type,
        display_name=info.display_name,
        enabled=True,
        hidden=info.hidden,
        default=info.default,
        endpoint=None,
        capabilities=tuple(info.capabilities),
        supported_durations=tuple(info.supported_durations),
        duration_resolution_constraints=_freeze(info.duration_resolution_constraints),
        reference_image_durations=tuple(info.reference_image_durations),
        resolutions=tuple(info.resolutions),
        pricing=price,
        source="builtin_registry",
    )


def _durations(raw: str | None) -> tuple[int, ...] | None:
    if raw is None:
        return None
    parsed = json.loads(raw)
    if not isinstance(parsed, list) or any(type(item) is not int for item in parsed):
        raise ValueError("custom supported_durations must be an integer list")
    return tuple(parsed)


async def custom_models(session: AsyncSession, *, provider_id: str | None = None) -> tuple[CatalogModel, ...]:
    """Read model columns only, retaining disabled rows and propagating invalid endpoints.

    The optional provider filter is a canonical ``custom-<positive id>`` identity. No filter
    reads all custom models. A caller's pending work is never autoflushed by this query.
    Protocol-derived capabilities are not model-level evidence and remain unknown here;
    the stored overrides are exposed separately without interpreting them as permission.
    """
    model = CustomProviderModel
    statement = select(
        model.provider_id,
        model.model_id,
        model.display_name,
        model.endpoint,
        model.is_enabled,
        model.is_default,
        model.price_unit,
        model.price_input,
        model.price_output,
        model.currency,
        model.supported_durations,
        model.resolution,
        model.capability_overrides,
    ).order_by(model.provider_id, model.model_id)
    if provider_id is not None:
        if not is_custom_provider(provider_id):
            raise ValueError("expected a canonical custom provider identity")
        db_id = parse_provider_id(provider_id)
        if db_id <= 0 or make_provider_id(db_id) != provider_id:
            raise ValueError("expected a canonical custom provider identity")
        statement = statement.where(model.provider_id == db_id)
    views = []
    with session.no_autoflush:
        rows = (await session.execute(statement)).mappings()
        endpoints = CustomEndpointRepository(session)
        for row in rows:
            spec = await resolve_endpoint_spec(row["endpoint"], endpoints.get)
            price = None
            if any(row[key] is not None for key in ("price_unit", "price_input", "price_output", "currency")):
                price = PriceFacts(
                    kind="custom",
                    currency=row["currency"],
                    details=_freeze({key: row[key] for key in ("price_unit", "price_input", "price_output")}),
                )
            views.append(
                CatalogModel(
                    provider_id=make_provider_id(row["provider_id"]),
                    model_id=row["model_id"],
                    api_model_name=None,
                    media_type=spec.media_type,
                    display_name=row["display_name"],
                    enabled=row["is_enabled"],
                    hidden=False,
                    default=row["is_default"],
                    endpoint=row["endpoint"],
                    capabilities=None,
                    supported_durations=_durations(row["supported_durations"]),
                    duration_resolution_constraints=MappingProxyType({}),
                    reference_image_durations=(),
                    resolutions=(),
                    pricing=price,
                    source="custom_model",
                    resolution=row["resolution"],
                    capability_overrides=_freeze(row["capability_overrides"] or {}),
                )
            )
    return tuple(views)
