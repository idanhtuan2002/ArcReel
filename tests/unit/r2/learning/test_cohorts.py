"""Cohort summaries, the V1 rule, causal language, holdout and pre-registered replay (plan D3a)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from r2.contracts.advanced_creative import LearningObservation, MetricWindow
from r2.learning.cohorts import (
    CausalLanguageError,
    CohortLeakError,
    RuleParams,
    check_hypothesis_language,
    cohort_key,
    compare_cohorts,
    proposal_key,
    recommendation_from,
    summarize,
)
from r2.learning.replay import EvaluationNotPreregisteredError, Protocol, replay, split_holdout
from tests.unit.r2.learning.test_observations import T0, obs

PARAMS = RuleParams(arm_a="16x9", arm_b="9x16", min_per_arm=3, min_relative_lift=Decimal("0.10"))
EXPIRES = datetime(2027, 1, 1, tzinfo=UTC)


def arm(
    format_ref: str,
    values: list[str | None],
    *,
    prefix: str | None = None,
    project: str = "demo",
    profile: str = "generic-western",
    day: int = 0,
    ingested: datetime | None = None,
    **changes,
) -> list[LearningObservation]:
    lineage = obs().lineage.model_copy(update={"project_name": project, "creative_profile_id": profile})
    start = T0 + timedelta(days=day)
    window = MetricWindow(
        starts_at=start, ends_at=start + timedelta(days=1), timezone_name="UTC", aggregation="sum_day"
    )
    return [
        obs(
            f"{prefix or format_ref}-{project}-{day}-{index}",
            source_record_id=f"{project}-{format_ref}-{index}",
            format_profile_ref=format_ref,
            metric_value=None if value is None else Decimal(value),
            missing_reason="PRIVATE" if value is None else None,
            lineage=lineage,
            window=window,
            ingested_at=ingested or start + timedelta(days=2),
            **changes,
        )
        for index, value in enumerate(values)
    ]


def test_a_summary_counts_missing_by_reason_and_never_imputes() -> None:
    summary = summarize(arm("16x9", ["10", "20", None, "30"]), arm="16x9")

    assert (summary.n, summary.present, summary.missing) == (4, 3, (("PRIVATE", 1),))
    assert (summary.mean, summary.median, summary.minimum, summary.maximum) == (
        Decimal(20),
        Decimal(20),
        Decimal(10),
        Decimal(30),
    )
    assert summary.as_json()["mean"] == "20"


def test_profiles_and_metrics_are_never_pooled() -> None:
    western = arm("16x9", ["10", "20"])
    shuang = arm("9x16", ["10", "20"], profile="zh-shuang")
    with pytest.raises(CohortLeakError):
        summarize([*western, *shuang])
    with pytest.raises(CohortLeakError):
        compare_cohorts([*western, *arm("9x16", ["1", "2"], metric_name="likes")], PARAMS)
    assert cohort_key(western[0]) != cohort_key(shuang[0])


def test_the_rule_fires_only_with_enough_values_and_lift() -> None:
    base = arm("16x9", ["100", "100", "100"])
    fired = compare_cohorts([*base, *arm("9x16", ["120", "120", "120"])], PARAMS)
    assert (fired.fired, fired.relative_lift) == (True, Decimal("0.2"))
    small = compare_cohorts([*base, *arm("9x16", ["105", "105", "105"])], PARAMS)
    assert (small.fired, small.reason) == (False, "lift below threshold")
    thin = compare_cohorts([*base, *arm("9x16", ["150", "150", None])], PARAMS)
    assert (thin.fired, thin.reason) == (False, "insufficient present values")


def test_observational_evidence_yields_associative_language_only() -> None:
    evidence = [*arm("16x9", ["100", "100", "100"]), *arm("9x16", ["80", "80", "80", None])]
    result = compare_cohorts(evidence, PARAMS)
    recommendation = recommendation_from(result, evidence, recommendation_id="rec-1", expires_at=EXPIRES)

    assert "is associated with" in recommendation.hypothesis
    assert "20.0% lower" in recommendation.hypothesis
    assert set(recommendation.evidence_observation_ids) == {item.observation_id for item in evidence}
    assert recommendation.exclusions == ("9x16: 1 PRIVATE",)
    assert recommendation.confidence == pytest.approx(6 / 7)
    assert recommendation.lineage.creative_profile_id == "generic-western"
    with pytest.raises(CausalLanguageError):
        check_hypothesis_language("Vertical framing increases views", causal_allowed=False)
    with pytest.raises(CausalLanguageError):
        check_hypothesis_language("竖屏导致观看提高", causal_allowed=False)
    with pytest.raises(CausalLanguageError):
        check_hypothesis_language("Khung dọc làm tăng lượt xem", causal_allowed=False)
    check_hypothesis_language("Vertical framing increases views", causal_allowed=True)


def test_only_one_randomized_surface_may_use_causal_language() -> None:
    randomized = {"experiment_design": "CONCURRENT_RANDOMIZED", "exposure_ref": "yt-test-1"}
    evidence = [*arm("16x9", ["100"] * 3, **randomized), *arm("9x16", ["130"] * 3, **randomized)]
    assert (
        "caused"
        in recommendation_from(
            compare_cohorts(evidence, PARAMS), evidence, recommendation_id="r", expires_at=EXPIRES
        ).hypothesis
    )

    mixed = [
        *arm("16x9", ["100"] * 3, **randomized),
        *arm("9x16", ["130"] * 3, experiment_design="CONCURRENT_RANDOMIZED", exposure_ref="other"),
    ]
    assert (
        "is associated with"
        in recommendation_from(
            compare_cohorts(mixed, PARAMS), mixed, recommendation_id="r", expires_at=EXPIRES
        ).hypothesis
    )
    sequential = [
        *arm("16x9", ["100"] * 3, experiment_design="SEQUENTIAL_OBSERVATIONAL", exposure_ref="s"),
        *arm("9x16", ["130"] * 3, experiment_design="SEQUENTIAL_OBSERVATIONAL", exposure_ref="s"),
    ]
    assert compare_cohorts(sequential, PARAMS).causal is False


def test_the_proposal_key_ignores_evidence_and_summaries() -> None:
    first = [*arm("16x9", ["100"] * 3), *arm("9x16", ["120"] * 3)]
    more = [*first, *arm("9x16", ["130"] * 3, day=3)]
    one = recommendation_from(compare_cohorts(first, PARAMS), first, recommendation_id="a", expires_at=EXPIRES)
    two = recommendation_from(compare_cohorts(more, PARAMS), more, recommendation_id="b", expires_at=EXPIRES)

    assert one.applicability != two.applicability
    assert proposal_key(one) == proposal_key(two)


def test_holdout_keeps_projects_whole_and_evaluation_in_the_future() -> None:
    projects = [f"p{index}" for index in range(12)]
    data = [item for name in projects for day in (0, 10) for item in arm("16x9", ["1", "2"], project=name, day=day)]
    holdout = split_holdout(data, evaluation_share=Decimal("0.5"), train_cutoff=T0 + timedelta(days=5), salt="s1")

    assert holdout.train_projects
    assert holdout.evaluation_projects
    assert not set(holdout.train_projects) & set(holdout.evaluation_projects)
    assert {item.lineage.project_name for item in holdout.train} <= set(holdout.train_projects)
    assert {item.lineage.project_name for item in holdout.evaluation} <= set(holdout.evaluation_projects)
    assert all(item.window.ends_at <= T0 + timedelta(days=5) for item in holdout.train)
    assert all(item.window.starts_at > T0 + timedelta(days=5) for item in holdout.evaluation)
    assert (
        split_holdout(data, evaluation_share=Decimal("0.5"), train_cutoff=T0 + timedelta(days=5), salt="s1") == holdout
    )


def _replay_data(registered: datetime) -> tuple[Protocol, list[LearningObservation]]:
    data: list[LearningObservation] = []
    for index in range(16):
        project, day = f"p{index}", (0 if index % 2 else 10)
        late = registered + timedelta(hours=1) if day == 10 else None
        data += arm("16x9", ["100", "100"], project=project, day=day, ingested=late)
        data += arm("9x16", ["125", "125"], project=project, day=day, ingested=late)
    protocol = Protocol(
        cohort=cohort_key(data[0]),
        params=RuleParams(arm_a="16x9", arm_b="9x16", min_per_arm=2, min_relative_lift=Decimal("0.10")),
        baseline_arm="16x9",
        window_starts_at=T0,
        window_ends_at=T0 + timedelta(days=30),
        exclusions=(),
        registered_at=registered,
    )
    return protocol, data


def test_replay_checks_the_trained_direction_on_a_preregistered_future_holdout() -> None:
    protocol, data = _replay_data(T0 + timedelta(days=8))
    holdout = split_holdout(data, evaluation_share=Decimal("0.5"), train_cutoff=T0 + timedelta(days=5), salt="s2")
    report = replay(protocol, holdout)

    assert report.train_fired
    assert report.direction_held
    assert report.evaluation_lift == Decimal("0.25")
    assert not set(report.train_ids) & set(report.evaluation_ids)
    assert report.protocol_digest == protocol.digest


def test_replay_refuses_an_evaluation_that_existed_before_registration() -> None:
    protocol, data = _replay_data(T0 + timedelta(days=20))
    holdout = split_holdout(data, evaluation_share=Decimal("0.5"), train_cutoff=T0 + timedelta(days=5), salt="s2")
    shifted = Protocol(**{**protocol.__dict__, "registered_at": T0 + timedelta(days=40)})

    with pytest.raises(EvaluationNotPreregisteredError):
        replay(shifted, holdout)
