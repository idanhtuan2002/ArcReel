"""Custom unit/rate facts stay independent from official model prices."""

from __future__ import annotations

from typing import cast

import pytest

from lib.cost_calculator import CostCalculator
from lib.pricing.price_compiler import compile_custom_pricing
from lib.pricing.request_metering import Priced, PriceTable, Unpriced, UnpricedReason, Usage, price_requests
from lib.pricing.strategies import PricingParams


@pytest.mark.parametrize("currency", ["USD", "CNY"])
def test_independent_input_output_prices_cannot_be_replaced_by_one_multiplier(currency: str) -> None:
    table = compile_custom_pricing(price_unit="token", price_input=0.45, price_output=1.25, currency=currency)
    assert isinstance(table, PriceTable)
    assert {m.meter: m.rows[0].price for m in table.meters} == {"uncached_input_tokens": 0.45, "output_tokens": 1.25}
    usage = Usage(quantities={"uncached_input_tokens": 1000, "output_tokens": 500})
    result = price_requests(table, [usage])
    assert isinstance(result, Priced)
    assert result.amount == pytest.approx(0.001075)
    assert result.currency == currency
    old = CostCalculator().calculate_cost(
        "custom-7",
        PricingParams("text", input_tokens=1000, output_tokens=500),
        custom_price_input=0.45,
        custom_price_output=1.25,
        custom_currency=currency,
    )
    assert result.amount == pytest.approx(old[0])
    assert old[1] == currency


@pytest.mark.parametrize(
    ("unit", "rate", "quantity", "meter", "expected"),
    [
        ("image", 0.1, 3, "output_images", 0.3),
        ("second", 0.5, 8, "output_seconds", 4),
        ("character", 0.8, 100, "characters", 0.008),
    ],
)
def test_single_axis_units_use_explicit_quantity_and_ignore_inactive_output_rate(
    unit: str, rate: float, quantity: float, meter: str, expected: float
) -> None:
    table = compile_custom_pricing(price_unit=unit, price_input=rate, price_output=999, currency="CNY")
    assert isinstance(table, PriceTable)
    assert len(table.meters) == 1
    result = price_requests(table, [Usage(quantities={meter: quantity})])
    assert isinstance(result, Priced)
    assert result.amount == pytest.approx(expected)
    assert result.currency == "CNY"


@pytest.mark.parametrize(("price_input", "price_output"), [(None, 0.2), (0.1, None), (None, None)])
def test_missing_token_price_is_not_zero(price_input: float | None, price_output: float | None) -> None:
    assert compile_custom_pricing(
        price_unit="token", price_input=price_input, price_output=price_output, currency="USD"
    ) == Unpriced(UnpricedReason.MISSING_RATE)


def test_explicit_zero_rates_are_preserved() -> None:
    table = compile_custom_pricing(price_unit="token", price_input=0, price_output=0, currency="CNY")
    assert isinstance(table, PriceTable)
    assert price_requests(table, [Usage(quantities={"uncached_input_tokens": 1000, "output_tokens": 500})]) == Priced(
        0, "CNY"
    )
    assert price_requests(table, [Usage()]) == Unpriced(UnpricedReason.MISSING_RATE)


@pytest.mark.parametrize(
    ("unit", "currency", "expected"),
    [
        (None, "USD", UnpricedReason.UNRECOGNIZED_TERMS),
        ("future", "USD", UnpricedReason.UNRECOGNIZED_TERMS),
        ("token", None, UnpricedReason.NO_PRICE_TABLE),
        ("token", "EUR", UnpricedReason.UNRECOGNIZED_TERMS),
        ("token", "LOCAL", UnpricedReason.UNRECOGNIZED_TERMS),
    ],
)
def test_missing_or_unknown_unit_and_currency_never_choose_defaults(
    unit: str | None, currency: str | None, expected: UnpricedReason
) -> None:
    assert compile_custom_pricing(price_unit=unit, price_input=0.1, price_output=0.2, currency=currency) == Unpriced(
        expected
    )


def test_all_absent_price_facts_remain_absent() -> None:
    assert compile_custom_pricing(price_unit=None, price_input=None, price_output=None, currency=None) == Unpriced(
        UnpricedReason.NO_PRICE_TABLE
    )


@pytest.mark.parametrize("rate", [True, -1, float("nan"), float("inf"), "1"])
@pytest.mark.parametrize("field", ["input", "output"])
def test_invalid_active_rates_are_rejected(rate: object, field: str) -> None:
    with pytest.raises(ValueError, match="metering numbers"):
        compile_custom_pricing(
            price_unit="token",
            price_input=cast(float, rate) if field == "input" else 0.1,
            price_output=cast(float, rate) if field == "output" else 0.2,
            currency="USD",
        )


def test_old_missing_price_and_duration_policies_remain_in_legacy_calculator() -> None:
    calculator = CostCalculator()
    old_missing = calculator.calculate_cost(
        "custom-7", PricingParams("text", input_tokens=1000), custom_price_input=None
    )
    assert old_missing == (0, "USD")
    assert compile_custom_pricing(price_unit="token", price_input=None, price_output=0.2, currency="USD") == Unpriced(
        UnpricedReason.MISSING_RATE
    )
    assert calculator.calculate_cost(
        "custom-7", PricingParams("video", duration_seconds=0), custom_price_input=0.5, custom_currency="CNY"
    ) == (4, "CNY")
    table = compile_custom_pricing(price_unit="second", price_input=0.5, price_output=None, currency="CNY")
    assert isinstance(table, PriceTable)
    assert price_requests(table, [Usage(quantities={"output_seconds": 0})]) == Priced(0, "CNY")


def test_character_counting_keeps_raw_unicode_count() -> None:
    table = compile_custom_pricing(price_unit="character", price_input=0.8, price_output=None, currency="CNY")
    assert isinstance(table, PriceTable)
    assert table.meters[0].cjk_double is False
    result = price_requests(table, [Usage(text="中文ab")])
    assert isinstance(result, Priced)
    assert result.amount == pytest.approx(0.00032)
