"""Strict compilation of existing price declarations, without model resolution.

Missing source facts remain unpriced. Existing calculators retain legacy fallback;
compiled tables are immutable reference data and grant no execution permission.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, cast

from lib.pricing.request_metering import Meter, PriceRow, PriceTable, Unpriced, UnpricedReason, validate_price_table
from lib.pricing.types import (
    PerCharacter,
    PerImageByResolution,
    PerImageFlat,
    PerImageOpenAIToken,
    PerSecondMatrix,
    PerSecondTiered,
    PerToken,
    PerTokenVideo,
    PerVideoBucket,
    Pricing,
    ViduDelegate,
)


def _mapping(value: object) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValueError("price declarations must contain mappings")
    return cast(Mapping[object, object], value)


def _select(value: object, model_id: str) -> object:
    rows = _mapping(value)
    return rows[model_id] if model_id in rows else Unpriced(UnpricedReason.NO_ENTRY)


def _pair(value: object) -> tuple[object, object]:
    if not isinstance(value, tuple) or len(value) != 2:
        raise ValueError("dimension keys must be pairs")
    return value[0], value[1]


def _row(when: dict[str, object], rate: object) -> PriceRow:
    return PriceRow(when=when, price=cast(float, rate))


def _flat(name: str, rate: object) -> Meter:
    return Meter(meter=name, dims=(), rows=(_row({}, rate),))


def _finish(currency: str, meters: Sequence[Meter]) -> PriceTable | Unpriced:
    if any(not meter.rows for meter in meters):
        return Unpriced(UnpricedReason.MISSING_RATE)
    result = validate_price_table(PriceTable(currency=currency, meters=tuple(meters)))
    if isinstance(result, Unpriced):
        return result
    for meter in result.meters:
        seen = set()
        for row in meter.rows:
            identity = tuple(
                (key, type(value), value.casefold() if isinstance(value, str) else value)
                for key, value in sorted(row.when.items())
            )
            if identity in seen:
                return Unpriced(UnpricedReason.UNRECOGNIZED_TERMS)
            seen.add(identity)
    return result


def _token_meters(value: object, names: Mapping[str, str], required: set[str]) -> list[Meter] | Unpriced:
    rows = _mapping(value)
    if not required.issubset(rows):
        return Unpriced(UnpricedReason.MISSING_RATE)
    if any(key not in names for key in rows):
        return Unpriced(UnpricedReason.UNRECOGNIZED_TERMS)
    return [_flat(meter, rows[key]) for key, meter in names.items() if key in rows]


def _image(pricing: PerImageOpenAIToken, model_id: str, mode: str) -> PriceTable | Unpriced:
    selected = _select(pricing.token_rates if mode == "tokens" else pricing.fallback_rates, model_id)
    if isinstance(selected, Unpriced):
        return selected
    if mode == "tokens":
        names = {
            "image_in": "uncached_image_input_tokens",
            "image_out": "image_output_tokens",
            "text_in": "uncached_input_tokens",
            "text_out": "output_tokens",
            "image_cached_in": "image_cache_read_tokens",
            "text_cached_in": "cache_read_tokens",
        }
        meters = _token_meters(selected, names, {"image_in", "image_out", "text_in", "text_out"})
        return meters if isinstance(meters, Unpriced) else _finish(pricing.currency, meters)
    rows = []
    for key, rate in _mapping(selected).items():
        quality, size = _pair(key)
        rows.append(_row({"quality": quality, "resolution": size}, rate))
    return _finish(pricing.currency, [Meter(meter="output_images", dims=("quality", "resolution"), rows=tuple(rows))])


def _matrix(pricing: PerSecondMatrix, selected: object) -> PriceTable | Unpriced:
    dims = {"resolution_audio": ("resolution", "audio"), "resolution_only": ("resolution",), "flat": ()}.get(
        pricing.dimensions
    )
    if dims is None:
        return Unpriced(UnpricedReason.UNRECOGNIZED_TERMS)
    rows = []
    for key, rate in _mapping(selected).items():
        resolution, audio = _pair(key)
        when: dict[str, object] = {}
        if pricing.dimensions == "flat":
            if (resolution, audio) != ("", None):
                return Unpriced(UnpricedReason.UNRECOGNIZED_TERMS)
        else:
            when["resolution"] = resolution
            if pricing.dimensions == "resolution_audio":
                when["audio"] = audio
            elif audio is not None:
                return Unpriced(UnpricedReason.UNRECOGNIZED_TERMS)
        rows.append(_row(when, rate))
    return _finish(pricing.currency, [Meter(meter="output_seconds", dims=dims, rows=tuple(rows))])


def _mode(value: object) -> Literal["tokens", "reference"]:
    if value not in ("tokens", "reference"):
        raise ValueError("unknown image price mode")
    return cast(Literal["tokens", "reference"], value)


def _identity(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("model identity must be a nonempty string")
    return value


def compile_pricing(
    pricing: Pricing | None,
    *,
    model_id: str,
    image_mode: Literal["tokens", "reference"] = "tokens",
) -> PriceTable | Unpriced:
    """Compile exact declared rates, without fallback or request normalization."""
    model_id = _identity(model_id)
    mode = _mode(image_mode)
    if mode == "reference" and not isinstance(pricing, PerImageOpenAIToken):
        raise ValueError("reference mode requires image token pricing")
    return _compile(pricing, model_id, mode)


def _compile(pricing: object, model_id: str, mode: str) -> PriceTable | Unpriced:
    if pricing is None:
        return Unpriced(UnpricedReason.NO_PRICE_TABLE)
    if isinstance(pricing, ViduDelegate):
        return Unpriced(UnpricedReason.UNRECOGNIZED_TERMS)
    if isinstance(pricing, PerImageOpenAIToken):
        return _image(pricing, model_id, mode)
    if not isinstance(
        pricing,
        (
            PerToken,
            PerImageFlat,
            PerImageByResolution,
            PerSecondMatrix,
            PerSecondTiered,
            PerVideoBucket,
            PerTokenVideo,
            PerCharacter,
        ),
    ):
        return Unpriced(UnpricedReason.UNRECOGNIZED_TERMS)
    selected = _select(pricing.rates, model_id)
    if isinstance(selected, Unpriced):
        return selected
    if isinstance(pricing, PerToken):
        meters = _token_meters(
            selected, {"input": "uncached_input_tokens", "output": "output_tokens"}, {"input", "output"}
        )
        return meters if isinstance(meters, Unpriced) else _finish(pricing.currency, meters)
    if isinstance(pricing, PerImageFlat):
        return _finish(pricing.currency, [_flat("output_images", selected)])
    if isinstance(pricing, PerCharacter):
        return _finish(pricing.currency, [_flat("characters", selected)])
    if isinstance(pricing, PerImageByResolution):
        rows = tuple(_row({"resolution": resolution}, rate) for resolution, rate in _mapping(selected).items())
        return _finish(pricing.currency, [Meter(meter="output_images", dims=("resolution",), rows=rows)])
    if isinstance(pricing, PerSecondMatrix):
        return _matrix(pricing, selected)
    if isinstance(pricing, PerVideoBucket):
        rows = []
        for key, rate in _mapping(selected).items():
            resolution, duration = _pair(key)
            rows.append(_row({"resolution": resolution, "duration": duration}, rate))
        return _finish(pricing.currency, [Meter(meter="requests", dims=("resolution", "duration"), rows=tuple(rows))])
    rows = []
    for key, rate in _mapping(selected).items():
        tier, audio = _pair(key)
        if isinstance(pricing, PerSecondTiered):
            when = {"quality": tier, "audio": audio}
        else:
            when = {"service_tier": "standard" if tier == "default" else tier, "audio": audio}
        rows.append(_row(when, rate))
    quality = isinstance(pricing, PerSecondTiered)
    return _finish(
        pricing.currency,
        [
            Meter(
                meter="output_seconds" if quality else "video_tokens",
                dims=("quality" if quality else "service_tier", "audio"),
                rows=tuple(rows),
            )
        ],
    )
