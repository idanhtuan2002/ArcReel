"""Immutable projections of existing model declarations, without provider construction.

The source version names this projection's schema, not a freshness proof or qualification.
Prices are declarations in their original units, not estimates or admission decisions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Any, Literal

from lib.config.registry import model_info_for

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
