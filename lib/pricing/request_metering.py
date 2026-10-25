"""Validated reference arithmetic for explicit physical requests.

Price facts and usage grant no dispatch permission or conservative budget bound.
Provider parsing, request identity and money writes remain with their existing owners.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import cast

from lib.pricing._metering_core import metering as _core
from lib.pricing._metering_core.metering import Priced, Unpriced, UnpricedReason, Usage
from lib.pricing._metering_core.model import Meter, PriceRow, PriceTable
from lib.pricing._metering_core.vocabulary import CURRENCIES, DIMENSIONS, METERS, is_valid_dimension_value

__all__ = [
    "Meter",
    "PriceRow",
    "PriceTable",
    "Priced",
    "Unpriced",
    "UnpricedReason",
    "Usage",
    "price_requests",
    "token_usage",
    "validate_price_table",
]


def _number(value: object) -> None:
    if type(value) not in (int, float):
        raise ValueError("metering numbers must be int or float, excluding bool")
    try:
        valid = math.isfinite(cast(float, value)) and cast(float, value) >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("metering numbers must be finite and nonnegative")


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be a sequence")
    return cast(Sequence[object], value)


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return {_string(key, label): item for key, item in cast(Mapping[object, object], value).items()}


def _boolean(value: object) -> None:
    if type(value) is not bool:
        raise ValueError("metering options must be bool")


def _quantities(value: object) -> tuple[Mapping[str, float], bool]:
    copied = _mapping(value, "quantities")
    for amount in copied.values():
        _number(amount)
    return MappingProxyType({key: cast(float, amount) for key, amount in copied.items()}), all(
        key in METERS for key in copied
    )


def _text(value: object) -> str | None:
    return None if value is None else _string(value, "usage text")


def _dimensions(values: object) -> tuple[Mapping[str, object], bool]:
    copied = _mapping(values, "dimensions")
    known = all(key in DIMENSIONS and is_valid_dimension_value(key, value) for key, value in copied.items())
    return MappingProxyType(copied), known


def _usage(value: object) -> tuple[Usage, bool]:
    if not isinstance(value, Usage):
        raise ValueError("request requires usage facts")
    quantities, valid_quantities = _quantities(value.quantities)
    text = _text(value.text)
    if text is not None and "characters" in quantities:
        raise ValueError("characters must have one source: text or quantity")
    dimensions, known = _dimensions(value.dimensions)
    return Usage(quantities=quantities, dimensions=dimensions, text=text), known and valid_quantities


def _table(value: object) -> tuple[PriceTable, bool]:
    if not isinstance(value, PriceTable):
        raise ValueError("expected a price table")
    currency = _string(value.currency, "currency")
    known = currency in CURRENCIES
    meters = []
    seen = set()
    for meter in _sequence(value.meters, "price meters"):
        if not isinstance(meter, Meter):
            raise ValueError("price table requires named meters")
        name = _string(meter.meter, "meter name")
        if name in seen:
            raise ValueError("duplicate billing meter")
        seen.add(name)
        dims = tuple(_string(dim, "dimension") for dim in _sequence(meter.dims, "meter dimensions"))
        if len(set(dims)) != len(dims):
            raise ValueError("duplicate dimension declaration")
        if type(meter.cjk_double) is not bool:
            raise ValueError("character counting option must be bool")
        if meter.free_allowance is not None:
            _number(meter.free_allowance)
        defaults, valid_defaults = _dimensions(meter.defaults)
        known = (
            known
            and meter.meter in METERS
            and all(d in DIMENSIONS for d in dims)
            and valid_defaults
            and set(defaults).issubset(dims)
        )
        rows = []
        for row in _sequence(meter.rows, "price rows"):
            if not isinstance(row, PriceRow):
                raise ValueError("meter rows must be price rows")
            _number(row.price)
            when, valid_when = _dimensions(row.when)
            known = known and valid_when and set(when).issubset(dims)
            rows.append(PriceRow(when=when, price=row.price))
        meters.append(
            Meter(
                meter=meter.meter,
                dims=dims,
                rows=tuple(rows),
                defaults=defaults,
                free_allowance=meter.free_allowance,
                cjk_double=meter.cjk_double,
            )
        )
    return PriceTable(currency=currency, meters=tuple(meters)), known


def validate_price_table(table: PriceTable) -> PriceTable | Unpriced:
    """Snapshot recognized price facts without evaluating usage or permission."""
    copied, known = _table(table)
    return copied if known else Unpriced(UnpricedReason.UNRECOGNIZED_TERMS)


def price_requests(
    table: PriceTable | None,
    requests: Sequence[Usage],
    *,
    entry_found: bool = True,
    estimate: bool = False,
) -> Priced | Unpriced:
    """Price complete declared axes, keeping each explicit request separate."""
    _boolean(entry_found)
    _boolean(estimate)
    snapshots = [_usage(usage) for usage in _sequence(requests, "requests")]
    copied, known = _table(table) if table is not None else (None, True)
    if not entry_found:
        return Unpriced(UnpricedReason.NO_ENTRY)
    if copied is None:
        return Unpriced(UnpricedReason.NO_PRICE_TABLE)
    if not known or not all(valid for _, valid in snapshots):
        return Unpriced(UnpricedReason.UNRECOGNIZED_TERMS)
    missing = UnpricedReason.NO_USAGE_ESTIMATE if estimate else UnpricedReason.MISSING_RATE
    if not snapshots:
        return Unpriced(missing)
    for usage, _ in snapshots:
        if any(
            meter.meter not in usage.quantities and not (meter.meter == "characters" and usage.text is not None)
            for meter in copied.meters
        ):
            return Unpriced(missing)
    cost = _core.price_requests(copied, [usage for usage, _ in snapshots], multiplier=1, estimate=estimate)
    if isinstance(cost, Priced):
        _number(cost.amount)
    return cost


def token_usage(
    *,
    input_tokens: int | None,
    output_tokens: int | None,
    cache_read_tokens: int | None = None,
    cache_write_5m_tokens: int | None = None,
    cache_write_1h_tokens: int | None = None,
    output_meter: str = "output_tokens",
) -> dict[str, float]:
    """Derive uncached input only from a complete reported cache partition."""
    output_meter = _string(output_meter, "output token meter")
    if output_meter not in {"output_tokens", "image_output_tokens", "audio_output_tokens"}:
        raise ValueError("unknown output token meter")
    caches = {
        "cache_read_tokens": cache_read_tokens,
        "cache_write_5m_tokens": cache_write_5m_tokens,
        "cache_write_1h_tokens": cache_write_1h_tokens,
    }
    for value in (input_tokens, output_tokens, *caches.values()):
        if value is not None:
            if type(value) is not int:
                raise ValueError("token counts must be exact integers, excluding bool")
            _number(value)
    subtotal = sum(value for value in caches.values() if value is not None)
    if input_tokens is not None and subtotal > input_tokens:
        raise ValueError("reported cache exceeds total input tokens")
    result: dict[str, float] = {key: value for key, value in caches.items() if value is not None}
    if input_tokens is not None and all(value is not None for value in caches.values()):
        result["uncached_input_tokens"] = input_tokens - subtotal
    if output_tokens is not None:
        result[output_meter] = output_tokens
    return result
