"""Derived features: values computed from observations that link every raw input (spec §9).

A feature names its transformation and version, and lists each input observation with its
observation id, raw payload digest, source family, record and metric definition. Its digest covers
all of them, so a feature cannot be compared or replayed without the exact inputs that produced it.
A feature never becomes an observation and never writes anywhere.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from pydantic import AwareDatetime

from r2.advanced_creative.digests import digest_canonical
from r2.contracts.advanced_creative import LearningObservation, M8ContractModel, Sha256Digest


class FeatureInput(M8ContractModel):
    observation_id: str
    raw_payload_digest: Sha256Digest
    source_family: str
    source_record_id: str
    metric_name: str
    metric_definition_version: str


class DerivedFeature(M8ContractModel):
    name: str
    transformation: str
    transformation_version: str
    value: Decimal | None
    unit: str
    inputs: tuple[FeatureInput, ...]
    as_of: AwareDatetime
    feature_digest: Sha256Digest


class FeatureInputError(ValueError):
    """The inputs do not fit the transformation."""


def _input(observation: LearningObservation) -> FeatureInput:
    return FeatureInput(
        observation_id=observation.observation_id,
        raw_payload_digest=observation.raw_payload_digest,
        source_family=observation.source_family,
        source_record_id=observation.source_record_id,
        metric_name=observation.metric_name,
        metric_definition_version=observation.metric_definition_version,
    )


def _feature(
    *,
    name: str,
    transformation: str,
    version: str,
    value: Decimal | None,
    unit: str,
    inputs: Sequence[LearningObservation],
    as_of: datetime,
) -> DerivedFeature:
    linked = tuple(sorted((_input(item) for item in inputs), key=lambda item: item.observation_id))
    if len({item.observation_id for item in linked}) != len(linked):
        raise FeatureInputError("a feature input appears twice")
    body = {
        "name": name,
        "transformation": transformation,
        "transformation_version": version,
        "value": value,
        "unit": unit,
        "inputs": linked,
        "as_of": as_of,
    }
    return DerivedFeature(**body, feature_digest=digest_canonical(body))


def _single_metric(inputs: Sequence[LearningObservation], metric: str) -> None:
    if not inputs:
        raise FeatureInputError("a feature needs at least one input")
    if {(item.source_family, item.metric_name, item.metric_definition_version) for item in inputs} != {
        (inputs[0].source_family, metric, inputs[0].metric_definition_version)
    }:
        raise FeatureInputError(f"inputs must all be one family's {metric} under one definition")


def mean_daily(inputs: Sequence[LearningObservation], *, metric: str, as_of: datetime) -> DerivedFeature:
    """The mean of daily-summed values over distinct days; any missing day makes the feature missing."""
    _single_metric(inputs, metric)
    if any(item.window.aggregation != "sum_day" for item in inputs):
        raise FeatureInputError("mean_daily needs day-summed windows")
    if len({item.window.starts_at for item in inputs}) != len(inputs):
        raise FeatureInputError("mean_daily needs distinct days")
    values = [item.metric_value for item in inputs]
    value = None if any(v is None for v in values) else sum(v for v in values if v is not None) / Decimal(len(values))
    return _feature(
        name=f"mean_daily_{metric}",
        transformation="mean_daily",
        version="1",
        value=value,
        unit=inputs[0].metric_unit + "/day",
        inputs=inputs,
        as_of=as_of,
    )


def ratio(numerator: LearningObservation, denominator: LearningObservation, *, as_of: datetime) -> DerivedFeature:
    """``numerator / denominator`` read from the same record and window (for example likes per view)."""
    if (numerator.source_family, numerator.source_record_id, numerator.window) != (
        denominator.source_family,
        denominator.source_record_id,
        denominator.window,
    ):
        raise FeatureInputError("a ratio reads one record over one window")
    if numerator.metric_name == denominator.metric_name:
        raise FeatureInputError("a ratio needs two metrics")
    value = (
        None
        if numerator.metric_value is None or denominator.metric_value in (None, Decimal(0))
        else numerator.metric_value / denominator.metric_value
    )
    return _feature(
        name=f"{numerator.metric_name}_per_{denominator.metric_name}",
        transformation="ratio",
        version="1",
        value=value,
        unit="ratio",
        inputs=(numerator, denominator),
        as_of=as_of,
    )


__all__ = ["DerivedFeature", "FeatureInput", "FeatureInputError", "mean_daily", "ratio"]
