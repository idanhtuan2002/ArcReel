"""Pure M8-D observation rules: identity, digest, admission and the cutoff fold."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from r2.contracts.advanced_creative import LearningObservation, LineageBinding, MetricWindow
from r2.learning.observations import (
    ObservationInvalidError,
    current_as_of,
    identity_of,
    ingest_command_digest,
    observation_digest,
    validate_correction,
    validate_observation,
)

DIGEST = "sha256:" + "a" * 64
T0 = datetime(2026, 10, 1, tzinfo=UTC)


def obs(observation_id: str = "o1", **changes) -> LearningObservation:
    base = {
        "observation_id": observation_id,
        "source_family": "youtube.analytics",
        "source_record_id": "video-1",
        "metric_name": "views",
        "metric_definition_version": "2024-01",
        "metric_value": Decimal("120"),
        "metric_unit": "count",
        "window": MetricWindow(
            starts_at=T0, ends_at=T0 + timedelta(days=1), timezone_name="UTC", aggregation="cumulative"
        ),
        "platform_artifact_id": "yt:video-1",
        "format_profile_ref": None,
        "lineage": LineageBinding(
            project_name="demo",
            content_basis_digest=DIGEST,
            approved_master_id=None,
            approved_master_digest=None,
            creative_profile_id="arcreel.host",
            creative_profile_version="1",
            policy_digest=DIGEST,
        ),
        "experiment_design": None,
        "exposure_ref": None,
        "raw_payload_digest": DIGEST,
        "transformation_version": None,
        "correction_of": None,
        "missing_reason": None,
        "observed_at": T0 + timedelta(days=1),
        "ingested_at": T0 + timedelta(days=2),
    }
    base.update(changes)
    return LearningObservation(**base)


def test_digest_ignores_server_ingest_time_but_covers_every_asserted_field() -> None:
    assert observation_digest(obs()) == observation_digest(obs(ingested_at=T0 + timedelta(days=9)))
    assert observation_digest(obs()) != observation_digest(obs(metric_value=Decimal("121")))
    assert observation_digest(obs()) != observation_digest(obs(metric_definition_version="2025-01"))
    assert ingest_command_digest(user_id="u", project_name="demo", observation=obs()) != ingest_command_digest(
        user_id="other", project_name="demo", observation=obs()
    )


def test_identity_is_source_metric_definition_and_exact_window() -> None:
    assert identity_of(obs("o1")) == identity_of(obs("o2", metric_value=Decimal("1")))
    shifted = obs(
        window=MetricWindow(starts_at=T0, ends_at=T0 + timedelta(days=7), timezone_name="UTC", aggregation="cumulative")
    )
    assert identity_of(shifted) != identity_of(obs())
    assert identity_of(obs(metric_definition_version="v2")) != identity_of(obs())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"metric_value": None}, "missing_reason"),
        ({"metric_value": None, "missing_reason": "GONE"}, "missing_reason"),
        ({"missing_reason": "PRIVATE"}, "no missing_reason"),
        ({"correction_of": "o1"}, "itself"),
        ({"source_record_id": ""}, "source_record_id"),
    ],
)
def test_admission_refuses_inadmissible_observations(changes: dict, message: str) -> None:
    with pytest.raises(ObservationInvalidError, match=message):
        validate_observation(obs(**changes), project_name="demo")


def test_admission_accepts_closed_missing_reasons_and_refuses_foreign_lineage_or_empty_window() -> None:
    for reason in ("MISSING", "PRIVATE", "DELETED", "NOT_YET_AVAILABLE"):
        validate_observation(obs(metric_value=None, missing_reason=reason), project_name="demo")
    with pytest.raises(ObservationInvalidError, match="another project"):
        validate_observation(obs(), project_name="other")
    empty = MetricWindow(starts_at=T0, ends_at=T0, timezone_name="UTC", aggregation="cumulative")
    with pytest.raises(ObservationInvalidError, match="positive length"):
        validate_observation(obs(window=empty), project_name="demo")


def test_a_correction_keeps_the_identity_and_names_its_predecessor() -> None:
    validate_correction(obs("o2", correction_of="o1", metric_value=Decimal("130")), obs("o1"))
    with pytest.raises(ObservationInvalidError, match="identity"):
        validate_correction(obs("o2", correction_of="o1", metric_name="likes"), obs("o1"))
    with pytest.raises(ObservationInvalidError, match="predecessor"):
        validate_correction(obs("o3", correction_of="o2"), obs("o1"))


def test_the_cutoff_fold_hides_late_corrections_and_late_originals() -> None:
    original = obs("o1", ingested_at=T0 + timedelta(days=2))
    first = obs("o2", correction_of="o1", metric_value=Decimal("130"), ingested_at=T0 + timedelta(days=3))
    second = obs(
        "o3", correction_of="o2", metric_value=None, missing_reason="DELETED", ingested_at=T0 + timedelta(days=5)
    )
    late_original = obs("x1", source_record_id="video-2", ingested_at=T0 + timedelta(days=6))
    records = [second, late_original, original, first]

    assert current_as_of(records, T0 + timedelta(days=1)) == ()
    assert current_as_of(records, T0 + timedelta(days=2)) == (original,)
    assert current_as_of(records, T0 + timedelta(days=4)) == (first,)
    assert current_as_of(records, T0 + timedelta(days=6)) == (second, late_original)


def test_the_fold_refuses_branched_or_duplicated_chains() -> None:
    with pytest.raises(ObservationInvalidError, match="two corrections"):
        current_as_of([obs("o1"), obs("o2", correction_of="o1"), obs("o3", correction_of="o1")], T0 + timedelta(days=9))
    with pytest.raises(ObservationInvalidError, match="two originals"):
        current_as_of([obs("o1"), obs("o2")], T0 + timedelta(days=9))
    with pytest.raises(ObservationInvalidError, match="duplicate"):
        current_as_of([obs("o1"), obs("o1")], T0 + timedelta(days=9))


def test_identity_compares_window_instants_across_a_dst_fold() -> None:
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/New_York")
    # 2026-11-01 01:30 happens twice in New York; fold=1 is the second, EST instant.
    later = datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=zone)
    window = MetricWindow(
        starts_at=later, ends_at=later + timedelta(hours=1), timezone_name="America/New_York", aggregation="sum"
    )
    stored = LearningObservation.model_validate(obs(window=window).model_dump(mode="json"))

    assert stored.window.starts_at.utcoffset() == timedelta(hours=-5)
    assert identity_of(stored) == identity_of(obs(window=window))
    validate_correction(obs("o2", correction_of="o1", window=window), stored)
