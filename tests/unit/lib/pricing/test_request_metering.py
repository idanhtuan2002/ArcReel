"""Public request pricing preserves unknown facts and rejects invalid arithmetic."""

from __future__ import annotations

from typing import cast

import pytest

from lib.pricing.request_metering import (
    Meter,
    Priced,
    PriceRow,
    PriceTable,
    Unpriced,
    UnpricedReason,
    Usage,
    price_requests,
    token_usage,
)


def _seconds(*, rate: float = 0.5, allowance: float | None = None, currency: str = "USD") -> PriceTable:
    return PriceTable(
        currency=currency,
        meters=(
            Meter(meter="output_seconds", dims=(), rows=(PriceRow(when={}, price=rate),), free_allowance=allowance),
        ),
    )


def _tokens() -> PriceTable:
    return PriceTable(
        currency="USD",
        meters=tuple(
            Meter(meter=name, dims=(), rows=(PriceRow(when={}, price=rate),))
            for name, rate in [("uncached_input_tokens", 1), ("output_tokens", 2)]
        ),
    )


def test_physical_requests_are_priced_individually_even_when_equal() -> None:
    usage = Usage(quantities={"output_seconds": 8})
    assert price_requests(_seconds(), [usage]) == Priced(4, "USD")
    assert price_requests(_seconds(), [usage, usage]) == Priced(8, "USD")


@pytest.mark.parametrize(
    ("estimate", "reason"), [(False, UnpricedReason.MISSING_RATE), (True, UnpricedReason.NO_USAGE_ESTIMATE)]
)
def test_missing_usage_on_any_declared_axis_stays_unknown(estimate: bool, reason: UnpricedReason) -> None:
    assert price_requests(
        _tokens(), [Usage(quantities={"uncached_input_tokens": 1000})], estimate=estimate
    ) == Unpriced(reason)
    assert price_requests(_seconds(), [], estimate=estimate) == Unpriced(reason)


def test_zero_is_reported_usage_and_missing_is_not_a_free_call() -> None:
    assert price_requests(_seconds(), [Usage(quantities={"output_seconds": 0})]) == Priced(0, "USD")
    assert price_requests(_seconds(rate=0), [Usage()]) == Unpriced(UnpricedReason.MISSING_RATE)
    assert price_requests(_seconds(rate=0), [Usage(quantities={"output_seconds": 8})]) == Priced(0, "USD")
    assert price_requests(PriceTable(currency="CNY", meters=()), [Usage()]) == Priced(0, "CNY")


def test_missing_table_and_unknown_entry_have_distinct_reasons() -> None:
    assert price_requests(None, [Usage()]) == Unpriced(UnpricedReason.NO_PRICE_TABLE)
    assert price_requests(_seconds(), [Usage()], entry_found=False) == Unpriced(UnpricedReason.NO_ENTRY)


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), 10**400, "1", None])
@pytest.mark.parametrize("field", ["quantity", "rate", "allowance"])
def test_invalid_numbers_never_reach_arithmetic(value: object, field: str) -> None:
    table = (
        _seconds(rate=cast(float, value))
        if field == "rate"
        else _seconds(allowance=cast(float, value))
        if field == "allowance"
        else _seconds()
    )
    quantity = cast(float, value) if field == "quantity" else 8
    if field == "allowance" and value is None:
        assert price_requests(table, [Usage(quantities={"output_seconds": quantity})]) == Priced(4, "USD")
    else:
        with pytest.raises(ValueError, match="metering numbers"):
            price_requests(table, [Usage(quantities={"output_seconds": quantity})])


@pytest.mark.parametrize(
    ("table", "entry_found"),
    [
        (None, False),
        (PriceTable(currency="USD", meters=()), True),
        (_seconds(rate=0), True),
        (_seconds(currency="LOCAL"), True),
    ],
)
def test_unknown_and_free_paths_do_not_bypass_numeric_validation(table: PriceTable | None, entry_found: bool) -> None:
    with pytest.raises(ValueError, match="metering numbers"):
        price_requests(table, [Usage(quantities={"output_seconds": float("nan")})], entry_found=entry_found)


def test_arithmetic_overflow_is_rejected() -> None:
    with pytest.raises(ValueError, match="metering numbers"):
        price_requests(_seconds(rate=1e308), [Usage(quantities={"output_seconds": 1e308})])
    with pytest.raises(ValueError, match="metering numbers"):
        price_requests(_seconds(rate=9e307), [Usage(quantities={"output_seconds": 1})] * 2)


@pytest.mark.parametrize(
    ("table", "usage"),
    [
        (_seconds(currency="LOCAL"), Usage(quantities={"output_seconds": 8})),
        (
            PriceTable(currency="USD", meters=(Meter(meter="credits", dims=(), rows=(PriceRow(when={}, price=1),)),)),
            Usage(quantities={"credits": 1}),
        ),
        (
            PriceTable(
                currency="USD",
                meters=(
                    Meter(
                        meter="output_seconds", dims=("size",), rows=(PriceRow(when={"size": "1024x1024"}, price=1),)
                    ),
                ),
            ),
            Usage(quantities={"output_seconds": 8}),
        ),
        (
            PriceTable(
                currency="USD",
                meters=(
                    Meter(
                        meter="output_seconds",
                        dims=("service_tier",),
                        rows=(PriceRow(when={"service_tier": "std"}, price=1),),
                    ),
                ),
            ),
            Usage(quantities={"output_seconds": 8}, dimensions={"service_tier": "std"}),
        ),
        (_seconds(), Usage(quantities={"output_seconds": 8, "credits": 0})),
    ],
)
def test_unknown_terms_cannot_become_a_price(table: PriceTable, usage: Usage) -> None:
    assert price_requests(table, [usage]) == Unpriced(UnpricedReason.UNRECOGNIZED_TERMS)


def test_duplicate_billing_axes_and_dimension_declarations_are_invalid() -> None:
    meter = _seconds().meters[0]
    with pytest.raises(ValueError, match="duplicate billing meter"):
        price_requests(PriceTable(currency="USD", meters=(meter, meter)), [Usage(quantities={"output_seconds": 8})])
    duplicate = Meter(
        meter="output_seconds",
        dims=("resolution", "resolution"),
        rows=(PriceRow(when={"resolution": "720p"}, price=1),),
    )
    with pytest.raises(ValueError, match="duplicate dimension"):
        price_requests(PriceTable(currency="USD", meters=(duplicate,)), [Usage(quantities={"output_seconds": 8})])


def test_validated_defaults_and_declared_row_priority_survive() -> None:
    rows = (PriceRow(when={"resolution": "720p"}, price=0.5), PriceRow(when={}, price=1))
    for ordered, expected in [(rows, 4), (tuple(reversed(rows)), 8)]:
        meter = Meter(meter="output_seconds", dims=("resolution",), rows=ordered, defaults={"resolution": "720p"})
        assert price_requests(
            PriceTable(currency="USD", meters=(meter,)), [Usage(quantities={"output_seconds": 8})]
        ) == Priced(expected, "USD")


def test_quotes_do_not_mutate_inputs_or_cache_old_values() -> None:
    quantities = {"output_seconds": 8.0}
    when: dict[str, object] = {"resolution": "720p"}
    dimensions: dict[str, object] = {"resolution": "720p"}
    table = PriceTable(
        currency="USD",
        meters=(Meter(meter="output_seconds", dims=("resolution",), rows=(PriceRow(when=when, price=0.5),)),),
    )
    usage = Usage(quantities=quantities, dimensions=dimensions)
    result = price_requests(table, [usage])
    assert result == Priced(4, "USD")
    assert quantities == {"output_seconds": 8}
    assert when == dimensions == {"resolution": "720p"}
    quantities["output_seconds"] = 10
    when["resolution"] = dimensions["resolution"] = "1080p"
    assert result == Priced(4, "USD")
    assert price_requests(table, [usage]) == Priced(5, "USD")


def test_nonbilled_count_and_unpriced_positive_token_axes_remain_distinct() -> None:
    assert price_requests(_seconds(), [Usage(quantities={"output_seconds": 8, "requests": 1})]) == Priced(4, "USD")
    assert price_requests(
        _tokens(), [Usage(quantities={"uncached_input_tokens": 1000, "output_tokens": 50, "cache_read_tokens": 10})]
    ) == Unpriced(UnpricedReason.MISSING_RATE)


def test_raw_text_and_explicit_character_count_cannot_disagree() -> None:
    table = PriceTable(
        currency="CNY", meters=(Meter(meter="characters", dims=(), rows=(PriceRow(when={}, price=0.8),)),)
    )
    assert price_requests(table, [Usage(text="中文ab")]) == Priced(0.00032, "CNY")
    with pytest.raises(ValueError, match="one source"):
        price_requests(table, [Usage(quantities={"characters": 4}, text="中文ab")])


def test_token_partition_preserves_unknown_and_explicit_zero() -> None:
    assert token_usage(input_tokens=100, output_tokens=50) == {"output_tokens": 50}
    assert token_usage(
        input_tokens=100, output_tokens=50, cache_read_tokens=0, cache_write_5m_tokens=0, cache_write_1h_tokens=0
    ) == {
        "uncached_input_tokens": 100,
        "cache_read_tokens": 0,
        "cache_write_5m_tokens": 0,
        "cache_write_1h_tokens": 0,
        "output_tokens": 50,
    }
    assert token_usage(
        input_tokens=100, output_tokens=50, cache_read_tokens=20, cache_write_5m_tokens=10, cache_write_1h_tokens=5
    ) == {
        "uncached_input_tokens": 65,
        "cache_read_tokens": 20,
        "cache_write_5m_tokens": 10,
        "cache_write_1h_tokens": 5,
        "output_tokens": 50,
    }
    assert token_usage(input_tokens=None, output_tokens=None, cache_read_tokens=2) == {"cache_read_tokens": 2}
    with pytest.raises(ValueError, match="cache exceeds total"):
        token_usage(input_tokens=1, output_tokens=0, cache_read_tokens=2)


@pytest.mark.parametrize("value", [True, -1, 1.5, float("inf"), "1"])
def test_token_count_types_cannot_hide_invalid_counts(value: object) -> None:
    with pytest.raises(ValueError, match=r"token counts|metering numbers"):
        token_usage(input_tokens=cast(int, value), output_tokens=0)
    with pytest.raises(ValueError, match=r"token counts|metering numbers"):
        token_usage(input_tokens=100, output_tokens=0, cache_read_tokens=cast(int, value))


def test_output_meter_is_explicit_and_validated() -> None:
    assert token_usage(input_tokens=None, output_tokens=3, output_meter="audio_output_tokens") == {
        "audio_output_tokens": 3
    }
    with pytest.raises(ValueError, match="output token meter"):
        token_usage(input_tokens=None, output_tokens=3, output_meter="credits")


@pytest.mark.parametrize("field", ["entry_found", "estimate"])
def test_options_require_real_booleans(field: str) -> None:
    with pytest.raises(ValueError, match="options must be bool"):
        price_requests(_seconds(), [Usage()], **{field: cast(bool, "yes")})


@pytest.mark.parametrize("field", ["meters", "dims", "rows", "output_meter"])
def test_invalid_sequence_shapes_raise_a_controlled_error(field: str) -> None:
    if field == "output_meter":
        with pytest.raises(ValueError, match="output token meter"):
            token_usage(input_tokens=None, output_tokens=0, output_meter=cast(str, []))
        return
    if field == "meters":
        table = PriceTable(currency="USD", meters=cast(tuple[Meter, ...], None))
    elif field == "dims":
        meter = Meter(meter="output_seconds", dims=cast(tuple[str, ...], None), rows=())
        table = PriceTable(currency="USD", meters=(meter,))
    else:
        meter = Meter(meter="output_seconds", dims=(), rows=cast(tuple[PriceRow, ...], None))
        table = PriceTable(currency="USD", meters=(meter,))
    with pytest.raises(ValueError, match="sequence"):
        price_requests(table, [Usage()])
