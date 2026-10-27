"""Measured timing and loudness have strict, immutable canonical representations."""

from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError


def probes():
    try:
        return importlib.import_module("r2.quality.probes")
    except ModuleNotFoundError:
        pytest.fail("Probe measurements are unavailable")


def time(numerator: int, denominator: int = 1):
    return probes().MediaTime(numerator=numerator, denominator=denominator)


def interval(start: int, end: int, *, eof: bool = False):
    return probes().Interval(kind="BLACK", start=time(start), end=time(end), ended_at_eof=eof)


def test_time_reduces_exact_rationals_without_float_conversion() -> None:
    assert time(2, 6) == time(1, 3)
    assert time(-2, 6).model_dump() == {"numerator": -1, "denominator": 3}
    assert time(0, 123).denominator == 1
    assert time(1, 3).as_fraction() * 3 == 1


@pytest.mark.parametrize(("numerator", "denominator"), [(True, 1), (1, True), ("1", 2), (1, "2"), (1, 0), (1, -1)])
def test_time_rejects_coerced_integer_and_nonpositive_denominator(numerator, denominator) -> None:
    with pytest.raises(ValidationError):
        probes().MediaTime(numerator=numerator, denominator=denominator)


def test_measurements_are_frozen_extra_forbid_and_revalidated() -> None:
    measured = time(2, 3)
    with pytest.raises(ValidationError):
        measured.numerator = 5
    with pytest.raises(ValidationError):
        probes().MediaTime(numerator=1, denominator=1, guessed_duration=100)
    forged = measured.model_copy(update={"denominator": 0})
    with pytest.raises(ValidationError):
        probes().MediaTime.model_validate(forged)


@pytest.mark.parametrize(("start", "end"), [(-1, 1), (2, 1)])
def test_interval_refuses_negative_or_reversed_bounds(start: int, end: int) -> None:
    with pytest.raises(ValidationError):
        interval(start, end)


def test_eof_interval_must_close_at_the_independently_measured_duration() -> None:
    facts = probes().IntervalFacts(measured_duration=time(3), intervals=(interval(1, 3, eof=True),))
    assert facts.intervals[0].ended_at_eof is True
    for item in (interval(1, 2, eof=True), interval(1, 4)):
        with pytest.raises(ValidationError):
            probes().IntervalFacts(measured_duration=time(3), intervals=(item,))


def test_interval_input_preserves_explicit_order_and_rejects_duplicates() -> None:
    first, second = interval(0, 1), interval(2, 3)
    for items in [(second, first), (first, first), {first, second}]:
        with pytest.raises((ValidationError, ValueError)):
            probes().IntervalFacts(measured_duration=time(3), intervals=items)
    assert probes().IntervalFacts(measured_duration=time(3), intervals=(first, second)).intervals == (first, second)


@pytest.mark.parametrize(
    ("value", "expected"), [("-23.0000", "-23"), ("-0.000", "0"), ("1e-3", "0.001"), ("+2.500", "2.5")]
)
def test_loudness_decimal_strings_are_canonical(value: str, expected: str) -> None:
    facts = probes().LoudnessFacts(state="FINITE", integrated_lufs=value, true_peak_dbfs="-1.00")
    assert facts.integrated_lufs == expected
    assert facts.true_peak_dbfs == "-1"


@pytest.mark.parametrize("value", [float("nan"), -23.0, "NaN", "Infinity", "-inf", " 1", "1_000", "1e9999", "1e-9999"])
def test_loudness_rejects_nonfinite_nonstrings_and_unbounded_decimal_expansion(value) -> None:
    with pytest.raises(ValidationError):
        probes().LoudnessFacts(state="FINITE", integrated_lufs=value, true_peak_dbfs="-1")


@pytest.mark.parametrize("state", ["SILENT", "UNMEASURABLE"])
def test_absent_numeric_loudness_is_explicit_and_never_zero(state: str) -> None:
    facts = probes().LoudnessFacts(state=state, integrated_lufs=None, true_peak_dbfs=None)
    assert facts.integrated_lufs is None
    for values in [("0", None), (None, "0"), ("0", "0")]:
        with pytest.raises(ValidationError):
            probes().LoudnessFacts(state=state, integrated_lufs=values[0], true_peak_dbfs=values[1])
    with pytest.raises(ValidationError):
        probes().LoudnessFacts(state="FINITE", integrated_lufs=None, true_peak_dbfs=None)


def test_decimal_normalization_does_not_inherit_the_callers_arithmetic_context() -> None:
    from decimal import ROUND_DOWN, DecimalException, localcontext

    with localcontext() as context:
        context.prec = 3
        context.Emax = 3
        context.rounding = ROUND_DOWN
        try:
            result = probes().canonical_decimal("1e4")
        except DecimalException:
            pytest.fail("Measurement normalization inherited an unrelated arithmetic context")
    assert result == "10000"
