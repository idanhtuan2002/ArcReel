"""Source adapters keep source semantics; derived features keep every raw input (plan D2)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from r2.contracts.host_hardening import ExecutionAttemptState
from r2.contracts.results import QualityFinding, QualityReport
from r2.learning.adapters import (
    ATTEMPT_FAMILY,
    TIKTOK_FAMILY,
    YOUTUBE_FAMILY,
    AttemptRecord,
    PublishApproval,
    UsageCall,
    observe_attempt,
    observe_publish_approval,
    observe_quality_report,
    observe_tiktok_video,
    observe_usage,
    observe_youtube_days,
    youtube_day_window,
    youtube_rows,
)
from r2.learning.features import FeatureInputError, mean_daily, ratio
from r2.learning.observations import identity_of, validate_correction, validate_observation
from tests.unit.r2.learning.test_observations import obs

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "r2" / "learning"
LINEAGE = obs().lineage
RETRIEVED = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
NOV1, NOV2, NOV3 = date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3)


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _by_metric(observations) -> dict:
    return {(item.source_record_id, item.metric_name): item for item in observations}


def test_youtube_days_are_pacific_calendar_days_including_the_dst_change() -> None:
    nov1 = youtube_day_window(NOV1)
    assert nov1.timezone_name == "America/Los_Angeles"
    assert nov1.starts_at == datetime(2026, 11, 1, 7, 0, tzinfo=UTC)
    # US daylight saving time ends on 2026-11-01, so that Pacific day lasts 25 hours.
    assert nov1.ends_at - nov1.starts_at == timedelta(hours=25)
    assert youtube_day_window(NOV2).ends_at - youtube_day_window(NOV2).starts_at == timedelta(hours=24)


def test_youtube_report_rows_keep_values_and_absent_recent_days_are_not_yet_available() -> None:
    rows = youtube_rows(_load("youtube_day_report.json"))
    observed = observe_youtube_days(
        video_id="abc",
        requested_days=(NOV1, NOV2, NOV3),
        rows=rows,
        status="PUBLIC",
        lineage=LINEAGE,
        retrieved_at=RETRIEVED,
    )
    table = _by_metric(observed)

    assert len(observed) == 9
    views = table[("video:abc:2026-11-01", "views")]
    assert (views.metric_value, views.metric_unit, views.window.aggregation) == (Decimal(120), "count", "sum_day")
    assert views.source_family == YOUTUBE_FAMILY
    assert views.platform_artifact_id == "youtube:abc"
    assert views.metric_definition_version == "youtube.analytics.v2/views@1"
    assert table[("video:abc:2026-11-02", "averageViewDuration")].metric_unit == "seconds"
    late = table[("video:abc:2026-11-03", "views")]
    assert (late.metric_value, late.missing_reason) == (None, "NOT_YET_AVAILABLE")
    for item in observed:
        validate_observation(item, project_name=LINEAGE.project_name)


def test_a_private_or_deleted_video_reports_its_status_only_for_days_without_rows() -> None:
    rows = youtube_rows(_load("youtube_day_report.json"))
    observed = _by_metric(
        observe_youtube_days(
            video_id="abc",
            requested_days=(NOV1, NOV3),
            rows=rows[:1],
            status="DELETED",
            lineage=LINEAGE,
            retrieved_at=RETRIEVED,
        )
    )
    assert observed[("video:abc:2026-11-01", "views")].metric_value == Decimal(120)
    assert observed[("video:abc:2026-11-03", "views")].missing_reason == "DELETED"
    with pytest.raises(ValueError, match="outside the requested days"):
        observe_youtube_days(
            video_id="abc", requested_days=(NOV3,), rows=rows, status="PUBLIC", lineage=LINEAGE, retrieved_at=RETRIEVED
        )


def test_a_later_report_for_the_same_day_is_a_correction_not_a_new_identity() -> None:
    first = _by_metric(
        observe_youtube_days(
            video_id="abc", requested_days=(NOV3,), rows=(), status="PUBLIC", lineage=LINEAGE, retrieved_at=RETRIEVED
        )
    )[("video:abc:2026-11-03", "views")]
    later = _by_metric(
        observe_youtube_days(
            video_id="abc",
            requested_days=(NOV3,),
            rows=({"day": "2026-11-03", "views": 40, "estimatedMinutesWatched": 70, "averageViewDuration": 120},),
            status="PUBLIC",
            lineage=LINEAGE,
            retrieved_at=RETRIEVED + timedelta(days=2),
        )
    )[("video:abc:2026-11-03", "views")]
    again = _by_metric(
        observe_youtube_days(
            video_id="abc", requested_days=(NOV3,), rows=(), status="PUBLIC", lineage=LINEAGE, retrieved_at=RETRIEVED
        )
    )[("video:abc:2026-11-03", "views")]

    assert identity_of(first) == identity_of(later)
    assert first.observation_id != later.observation_id
    assert again.observation_id == first.observation_id
    validate_correction(later.model_copy(update={"correction_of": first.observation_id}), first)


def test_tiktok_counts_are_a_snapshot_read_at_retrieval() -> None:
    video = _load("tiktok_video.json")
    published = datetime.fromtimestamp(int(video["create_time"]), UTC)
    observed = _by_metric(
        observe_tiktok_video(
            video=video,
            video_id=video["id"],
            status="PUBLIC",
            published_at=published,
            lineage=LINEAGE,
            retrieved_at=RETRIEVED,
        )
    )
    views = observed[(f"video:{video['id']}", "view_count")]
    assert views.source_family == TIKTOK_FAMILY
    assert (views.window.starts_at, views.window.ends_at, views.window.aggregation) == (
        published,
        RETRIEVED,
        "snapshot_at_retrieval",
    )
    assert views.metric_value == Decimal(5000)

    private = observe_tiktok_video(
        video=None,
        video_id=video["id"],
        status="PRIVATE",
        published_at=published,
        lineage=LINEAGE,
        retrieved_at=RETRIEVED,
    )
    assert {item.missing_reason for item in private} == {"PRIVATE"}
    with pytest.raises(ValueError, match="another video"):
        observe_tiktok_video(
            video=video,
            video_id="other",
            status="PUBLIC",
            published_at=published,
            lineage=LINEAGE,
            retrieved_at=RETRIEVED,
        )


def test_internal_usage_qa_approval_and_attempt_records_become_event_observations() -> None:
    finished = datetime(2026, 11, 2, 10, 0, 5, 500000, tzinfo=UTC)
    usage = _by_metric(
        observe_usage(
            UsageCall(
                call_id=7,
                execution_id="exec-1",
                call_type="video",
                provider="gemini",
                model="veo",
                status="success",
                cost_amount=0.35,
                currency="USD",
                duration_ms=4200,
                usage_tokens=None,
                started_at=finished - timedelta(seconds=4),
                finished_at=finished,
            ),
            lineage=LINEAGE,
            retrieved_at=RETRIEVED,
        )
    )
    cost = usage[("api_call:7", "provider_cost")]
    assert (cost.metric_value, cost.metric_unit, cost.window.aggregation) == (Decimal("0.35"), "USD", "event")
    assert cost.window.starts_at == datetime(2026, 11, 2, 10, 0, 5, tzinfo=UTC)
    assert usage[("api_call:7", "usage_tokens")].missing_reason == "MISSING"
    unfinished = UsageCall(7, None, "video", "gemini", "veo", "pending", 0.0, "USD", None, None, finished, None)
    assert observe_usage(unfinished, lineage=LINEAGE, retrieved_at=RETRIEVED) == ()

    report = QualityReport(
        id="qa-1",
        target_ref="shot:1",
        score=None,
        blocking_findings=[QualityFinding(code="blur", message="blurred", blocking=True)],
        reviewer_type="AGENT",
        created_at=finished,
    )
    qa = _by_metric(observe_quality_report(report, lineage=LINEAGE, retrieved_at=RETRIEVED))
    assert qa[("quality_report:qa-1", "qa_score")].missing_reason == "MISSING"
    assert qa[("quality_report:qa-1", "qa_blocking_findings")].metric_value == Decimal(1)

    approval = observe_publish_approval(
        PublishApproval("d-1", "sha256:" + "b" * 64, "youtube", "public", "REVOKE", 2, finished),
        lineage=LINEAGE,
        retrieved_at=RETRIEVED,
    )
    assert approval[0].metric_value == Decimal(0)

    running = AttemptRecord("exec-1", "task-1", 1, ExecutionAttemptState.RUNNING, finished, None)
    assert observe_attempt(running, lineage=LINEAGE, retrieved_at=RETRIEVED) == ()
    done = _by_metric(
        observe_attempt(
            AttemptRecord(
                "exec-1", "task-1", 1, ExecutionAttemptState.FAILED, finished - timedelta(seconds=90), finished
            ),
            lineage=LINEAGE,
            retrieved_at=RETRIEVED,
        )
    )
    assert done[("execution:exec-1", "attempt_succeeded")].metric_value == Decimal(0)
    assert done[("execution:exec-1", "attempt_seconds")].metric_value == Decimal(90)
    assert done[("execution:exec-1", "attempt_seconds")].source_family == ATTEMPT_FAMILY


def test_adapting_the_same_raw_record_twice_yields_identical_observations() -> None:
    rows = youtube_rows(_load("youtube_day_report.json"))
    first = observe_youtube_days(
        video_id="abc", requested_days=(NOV1,), rows=rows[:1], status="PUBLIC", lineage=LINEAGE, retrieved_at=RETRIEVED
    )
    second = observe_youtube_days(
        video_id="abc", requested_days=(NOV1,), rows=rows[:1], status="PUBLIC", lineage=LINEAGE, retrieved_at=RETRIEVED
    )
    assert first == second


def test_derived_features_link_every_raw_input_and_version() -> None:
    rows = youtube_rows(_load("youtube_day_report.json"))
    days = observe_youtube_days(
        video_id="abc", requested_days=(NOV1, NOV2), rows=rows, status="PUBLIC", lineage=LINEAGE, retrieved_at=RETRIEVED
    )
    views = [item for item in days if item.metric_name == "views"]
    feature = mean_daily(views, metric="views", as_of=RETRIEVED)

    assert feature.value == Decimal(100)
    assert (feature.transformation, feature.transformation_version, feature.unit) == ("mean_daily", "1", "count/day")
    assert {item.observation_id for item in feature.inputs} == {item.observation_id for item in views}
    assert {item.raw_payload_digest for item in feature.inputs} == {item.raw_payload_digest for item in views}
    assert feature.feature_digest != mean_daily(views[:1], metric="views", as_of=RETRIEVED).feature_digest

    with pytest.raises(FeatureInputError, match="one family"):
        mean_daily(
            [item for item in days if item.metric_name != "averageViewDuration"], metric="views", as_of=RETRIEVED
        )
    missing = observe_youtube_days(
        video_id="abc", requested_days=(NOV3,), rows=(), status="PUBLIC", lineage=LINEAGE, retrieved_at=RETRIEVED
    )
    assert mean_daily([*views, missing[0]], metric="views", as_of=RETRIEVED).value is None


def test_a_ratio_reads_one_record_and_window() -> None:
    video = _load("tiktok_video.json")
    published = datetime.fromtimestamp(int(video["create_time"]), UTC)
    snapshot = _by_metric(
        observe_tiktok_video(
            video=video,
            video_id=video["id"],
            status="PUBLIC",
            published_at=published,
            lineage=LINEAGE,
            retrieved_at=RETRIEVED,
        )
    )
    likes, views = snapshot[(f"video:{video['id']}", "like_count")], snapshot[(f"video:{video['id']}", "view_count")]
    feature = ratio(likes, views, as_of=RETRIEVED)

    assert feature.value == Decimal("0.082")
    assert {(item.observation_id, item.metric_name) for item in feature.inputs} == {
        (likes.observation_id, "like_count"),
        (views.observation_id, "view_count"),
    }
    later = observe_tiktok_video(
        video=video,
        video_id=video["id"],
        status="PUBLIC",
        published_at=published,
        lineage=LINEAGE,
        retrieved_at=RETRIEVED + timedelta(days=1),
    )
    with pytest.raises(FeatureInputError, match="one record over one window"):
        ratio(likes, next(item for item in later if item.metric_name == "view_count"), as_of=RETRIEVED)
