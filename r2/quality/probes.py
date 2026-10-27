"""Immutable deterministic probe measurements; these values grant no quality disposition."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from fractions import Fraction
from math import gcd
from typing import Literal, Self

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from r2.contracts.quality import M10ContractModel


class MediaTime(M10ContractModel):
    numerator: StrictInt = Field(ge=-(2**63) + 1, le=2**63 - 1)
    denominator: StrictInt = Field(gt=0, le=2**31 - 1)

    @model_validator(mode="before")
    @classmethod
    def reduced(cls, value: object) -> object:
        body = dict(value) if isinstance(value, cls) else value
        if isinstance(body, dict):
            numerator, denominator = body.get("numerator"), body.get("denominator")
            if type(numerator) is int and type(denominator) is int and denominator > 0:
                common = gcd(numerator, denominator)
                return body | {"numerator": numerator // common, "denominator": denominator // common}
        return body

    def as_fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


class Interval(M10ContractModel):
    kind: Literal["BLACK", "FREEZE", "SILENCE"]
    start: MediaTime
    end: MediaTime
    ended_at_eof: StrictBool

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if not 0 <= self.start.as_fraction() <= self.end.as_fraction():
            raise ValueError("invalid interval bounds")
        return self


class IntervalFacts(M10ContractModel):
    measured_duration: MediaTime
    intervals: tuple[Interval, ...] = Field(max_length=10_000)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        duration = self.measured_duration.as_fraction()
        if duration < 0:
            raise ValueError("invalid measured duration")
        keys = tuple((item.start.as_fraction(), item.end.as_fraction(), item.kind) for item in self.intervals)
        if len(set(keys)) != len(keys) or keys != tuple(sorted(keys)):
            raise ValueError("intervals require unique canonical order")
        for item in self.intervals:
            if item.end.as_fraction() > duration or (item.ended_at_eof and item.end.as_fraction() != duration):
                raise ValueError("interval exceeds measured duration or EOF binding")
        return self


def canonical_decimal(value: object) -> str:
    """Normalize bounded decimal strings without float conversion or silent rounding."""
    if (
        not isinstance(value, str)
        or len(value) > 128
        or re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value) is None
    ):
        raise ValueError("invalid measured decimal")
    try:
        exact = Decimal(value)
        exponent = exact.as_tuple().exponent
        if not exact.is_finite() or not isinstance(exponent, int) or not -24 <= exponent <= 24:
            raise ValueError("invalid measured decimal")
        with localcontext(Context(prec=24, rounding=ROUND_HALF_EVEN, Emin=-99, Emax=99)):
            normalized = +exact
        if normalized != exact:
            raise ValueError("measured decimal exceeds precision")
    except InvalidOperation:
        raise ValueError("invalid measured decimal") from None
    if normalized.is_zero():
        return "0"
    text = format(normalized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


class LoudnessFacts(M10ContractModel):
    state: Literal["FINITE", "SILENT", "UNMEASURABLE"]
    integrated_lufs: str | None
    true_peak_dbfs: str | None

    @field_validator("integrated_lufs", "true_peak_dbfs", mode="before")
    @classmethod
    def numeric_strings(cls, value: object) -> str | None:
        return None if value is None else canonical_decimal(value)

    @model_validator(mode="after")
    def explicit_state(self) -> Self:
        present = (self.integrated_lufs is not None, self.true_peak_dbfs is not None)
        expected = (True, True) if self.state == "FINITE" else (False, False)
        if present != expected:
            raise ValueError("loudness state and numeric measurements disagree")
        return self
