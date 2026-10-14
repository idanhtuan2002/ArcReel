"""Source adapters keep source semantics; derived features keep every raw input (plan D2)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from r2.advanced_creative.digests import digest_canonical
from r2.contracts.host_hardening import ExecutionAttemptState
from r2.contracts.results import QualityFinding, QualityReport
from r2.learning.adapters import (
    ATTEMPT_FAMILY,
    TIKTOK_FAMILY,
    YOUTUBE_FAMILY,
    AdaptedRecord,
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
QUERY = {"ids": "channel==MINE", "dimensions": "day", "filters": "video==abc"}


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _by_metric(records) -> dict:
    if isinstance(records, AdaptedRecord):
        records = (records,)
    return {
        (item.source_record_id.split(":scope:")[0], item.metric_name): item
        for record in records
        for item in record.observations
    }


def _days(days, rows, *, status="PUBLIC", query=QUERY):
    return observe_youtube_days(
        video_id="abc", query=query, requested_days=days, rows=rows, status=status, lineage=LINEAGE
    )


def _tiktok(video, *, status="PUBLIC", retrieved_at=RETRIEVED):
    published = datetime.fromtimestamp(int(_load("tiktok_video.json")["create_time"]), UTC)
    return observe_tiktok_video(
        video=video,
        video_id="7300000000000000001",
        status=status,
        published_at=published,
        retrieved_at=retrieved_at,
        lineage=LINEAGE,
    )


def _row(views: int) -> dict:
    return {"day": "2026-11-03", "views": views, "estimatedMinutesWatched": 2 * views, "averageViewDuration": 3}


def test_every_record_keeps_a_raw_envelope_matching_its_digest() -> None:
    records = _days((NOV1, NOV2), youtube_rows(_load("youtube_day_report.json")))
    for record in records:
        assert digest_canonical(dict(record.raw_payload)) == record.raw_payload_digest
        assert {item.raw_payload_digest for item in record.observations} == {record.raw_payload_digest}
        assert record.raw_payload["query"] == QUERY


def test_youtube_days_are_pacific_calendar_days_including_the_dst_change() -> None:
    nov1 = youtube_day_window(NOV1)
    assert nov1.timezone_name == "America/Los_Angeles"
    assert nov1.starts_at == datetime(2026, 11, 1, 7, 0, tzinfo=UTC)
    # US daylight saving time ends on 2026-11-01, so that Pacific day lasts 25 hours.
    assert nov1.ends_at - nov1.starts_at == timedelta(hours=25)
    assert youtube_day_window(NOV2).ends_at - youtube_day_window(NOV2).starts_at == timedelta(hours=24)


def test_youtube_rows_keep_values_units_and_aggregations() -> None:
    table = _by_metric(_days((NOV1, NOV2, NOV3), youtube_rows(_load("youtube_day_report.json"))))

    views = table[("video:abc:2026-11-01", "views")]
    assert (views.metric_value, views.metric_unit, views.window.aggregation) == (Decimal(120), "count", "sum_day")
    assert views.source_family == YOUTUBE_FAMILY
    assert views.platform_artifact_id == "youtube:abc"
    assert views.metric_definition_version == "youtube.analytics.v2/views@1"
    duration = table[("video:abc:2026-11-02", "averageViewDuration")]
    assert (duration.metric_unit, duration.window.aggregation) == ("seconds", "mean_day")
    for item in table.values():
        validate_observation(item, project_name=LINEAGE.project_name)


def test_absent_days_are_not_yet_available_only_after_the_latest_returned_day() -> None:
    rows = youtube_rows(_load("youtube_day_report.json"))
    table = _by_metric(_days((NOV1, NOV2, NOV3), rows[1:]))
    # NOV1 precedes the latest returned day (NOV2), so its absence is not a reporting delay.
    assert table[("video:abc:2026-11-01", "views")].missing_reason == "MISSING"
    assert table[("video:abc:2026-11-03", "views")].missing_reason == "NOT_YET_AVAILABLE"
    assert _by_metric(_days((NOV3,), ()))[("video:abc:2026-11-03", "views")].missing_reason == "MISSING"

    deleted = _by_metric(_days((NOV1, NOV3), rows[:1], status="DELETED"))
    assert deleted[("video:abc:2026-11-01", "views")].metric_value == Decimal(120)
    assert deleted[("video:abc:2026-11-03", "views")].missing_reason == "DELETED"


def test_the_query_scope_is_part_of_the_record_identity() -> None:
    rows = youtube_rows(_load("youtube_day_report.json"))[:1]
    everyone = _days((NOV1,), rows)[0].observations[0]
    sliced = _days((NOV1,), rows, query={**QUERY, "filters": "video==abc;country==US"})[0].observations[0]

    assert identity_of(everyone) != identity_of(sliced)
    with pytest.raises(ValueError, match="filter to this video"):
        _days((NOV1,), rows, query={**QUERY, "filters": "video==other"})
    with pytest.raises(ValueError, match="ids"):
        _days((NOV1,), rows, query={"dimensions": "day", "filters": "video==abc"})


def test_an_unchanged_row_replays_and_a_later_report_is_a_correction() -> None:
    key = ("video:abc:2026-11-03", "views")
    first = _by_metric(_days((NOV3,), (_row(1),)))[key]
    again = _by_metric(_days((NOV3,), (_row(1),)))[key]
    later = _by_metric(_days((NOV3,), (_row(40),)))[key]

    assert again == first
    assert identity_of(first) == identity_of(later)
    assert first.observation_id != later.observation_id
    validate_correction(later.model_copy(update={"correction_of": first.observation_id}), first)


def test_youtube_result_tables_and_rows_are_validated() -> None:
    table = _load("youtube_day_report.json")
    with pytest.raises(ValueError, match="unique"):
        youtube_rows({**table, "columnHeaders": [*table["columnHeaders"], {"name": "views"}]})
    with pytest.raises(ValueError, match="match the column headers"):
        youtube_rows({**table, "rows": [["2026-11-01", 1]]})
    with pytest.raises(ValueError, match="not a YouTube"):
        youtube_rows({**table, "kind": "other"})
    rows = youtube_rows(table)
    with pytest.raises(ValueError, match="duplicate"):
        _days((NOV1,), (rows[0], rows[0]))
    with pytest.raises(ValueError, match="outside the requested days"):
        _days((NOV3,), rows)
    with pytest.raises(ValueError, match="finite"):
        _days((NOV1,), ({**rows[0], "views": "NaN"},))


def test_tiktok_counts_are_a_snapshot_read_at_retrieval() -> None:
    video = _load("tiktok_video.json")
    record = _tiktok(video)
    views = _by_metric(record)[(f"video:{video['id']}", "view_count")]
    published = datetime.fromtimestamp(int(video["create_time"]), UTC)

    assert views.source_family == TIKTOK_FAMILY
    assert (views.window.starts_at, views.window.ends_at, views.window.aggregation) == (
        published,
        RETRIEVED,
        "snapshot_at_retrieval",
    )
    assert views.metric_value == Decimal(5000)
    assert record.raw_payload["retrieved_at"] == RETRIEVED
    assert {item.missing_reason for item in _tiktok(None, status="PRIVATE").observations} == {"PRIVATE"}
    with pytest.raises(ValueError, match="another video"):
        _tiktok({**video, "id": "other"})
    with pytest.raises(ValueError, match="after the video was published"):
        _tiktok(video, retrieved_at=published)


def test_internal_records_keep_outcome_and_context() -> None:
    finished = datetime(2026, 11, 2, 10, 0, 5, 500000, tzinfo=UTC)
    failed = observe_usage(
        UsageCall(
            7,
            "exec-1",
            "video",
            "gemini",
            "veo",
            "failed",
            0.35,
            "USD",
            4200,
            None,
            finished - timedelta(seconds=4),
            finished,
        ),
        lineage=LINEAGE,
    )
    assert failed is not None
    usage = _by_metric(failed)
    assert usage[("api_call:7", "call_succeeded")].metric_value == Decimal(0)
    cost = usage[("api_call:7", "provider_cost")]
    assert (cost.metric_value, cost.metric_unit, cost.window.aggregation) == (Decimal("0.35"), "USD", "event")
    assert cost.window.starts_at == datetime(2026, 11, 2, 10, 0, 5, tzinfo=UTC)
    assert usage[("api_call:7", "usage_tokens")].missing_reason == "MISSING"
    assert (failed.raw_payload["status"], failed.raw_payload["provider"], failed.raw_payload["model"]) == (
        "failed",
        "gemini",
        "veo",
    )
    pending = UsageCall(8, None, "video", "gemini", "veo", "pending", 0.0, "USD", None, None, finished, None)
    assert observe_usage(pending, lineage=LINEAGE) is None

    report = QualityReport(
        id="qa-1",
        target_ref="shot:1",
        score=None,
        blocking_findings=[QualityFinding(code="blur", message="blurred", blocking=True)],
        reviewer_type="HUMAN",
        created_at=finished,
    )
    qa = observe_quality_report(report, lineage=LINEAGE)
    assert _by_metric(qa)[("quality_report:qa-1", "qa_score")].missing_reason == "MISSING"
    assert _by_metric(qa)[("quality_report:qa-1", "qa_blocking_findings")].metric_value == Decimal(1)
    report_raw = qa.raw_payload["report"]
    assert isinstance(report_raw, dict)
    assert report_raw["reviewer_type"] == "HUMAN"

    approval = observe_publish_approval(
        PublishApproval("d-1", "sha256:" + "b" * 64, "youtube", "public", "REVOKE", 2, finished), lineage=LINEAGE
    )
    assert approval.observations[0].metric_value == Decimal(0)
    assert approval.raw_payload["visibility"] == "public"

    running = AttemptRecord("exec-1", "task-1", 1, ExecutionAttemptState.RUNNING, finished, None)
    assert observe_attempt(running, lineage=LINEAGE) is None
    done = observe_attempt(
        AttemptRecord("exec-1", "task-1", 1, ExecutionAttemptState.FAILED, finished - timedelta(seconds=90), finished),
        lineage=LINEAGE,
    )
    assert done is not None
    table = _by_metric(done)
    assert table[("execution:exec-1", "attempt_succeeded")].metric_value == Decimal(0)
    assert table[("execution:exec-1", "attempt_seconds")].metric_value == Decimal(90)
    assert table[("execution:exec-1", "attempt_seconds")].source_family == ATTEMPT_FAMILY


def test_derived_features_link_every_raw_input_and_version() -> None:
    records = _days((NOV1, NOV2), youtube_rows(_load("youtube_day_report.json")))
    views = [item for record in records for item in record.observations if item.metric_name == "views"]
    feature = mean_daily(views, metric="views", as_of=RETRIEVED)

    assert feature.value == Decimal(100)
    assert (feature.transformation, feature.transformation_version, feature.unit) == ("mean_daily", "1", "count/day")
    assert {item.observation_id for item in feature.inputs} == {item.observation_id for item in views}
    assert {item.raw_payload_digest for item in feature.inputs} == {item.raw_payload_digest for item in views}
    assert feature.feature_digest != mean_daily(views[:1], metric="views", as_of=RETRIEVED).feature_digest

    durations = [
        item for record in records for item in record.observations if item.metric_name == "averageViewDuration"
    ]
    with pytest.raises(FeatureInputError, match="day-summed"):
        mean_daily(durations, metric="averageViewDuration", as_of=RETRIEVED)
    with pytest.raises(FeatureInputError, match="one family"):
        mean_daily([*views, durations[0]], metric="views", as_of=RETRIEVED)
    with pytest.raises(FeatureInputError, match="distinct days"):
        mean_daily([views[0], views[0].model_copy(update={"observation_id": "x"})], metric="views", as_of=RETRIEVED)
    with pytest.raises(FeatureInputError, match="at least one"):
        mean_daily([], metric="views", as_of=RETRIEVED)
    missing = _days((NOV3,), ())
    assert mean_daily([*views, missing[0].observations[0]], metric="views", as_of=RETRIEVED).value is None


def test_a_ratio_reads_one_retrieved_record() -> None:
    video = _load("tiktok_video.json")
    snapshot = _by_metric(_tiktok(video))
    likes, views = snapshot[(f"video:{video['id']}", "like_count")], snapshot[(f"video:{video['id']}", "view_count")]
    feature = ratio(likes, views, as_of=RETRIEVED)

    assert feature.value == Decimal("0.082")
    assert {(item.observation_id, item.metric_name) for item in feature.inputs} == {
        (likes.observation_id, "like_count"),
        (views.observation_id, "view_count"),
    }
    later = _by_metric(_tiktok(video, retrieved_at=RETRIEVED + timedelta(days=1)))
    with pytest.raises(FeatureInputError, match="one retrieved record"):
        ratio(likes, later[(f"video:{video['id']}", "view_count")], as_of=RETRIEVED)
    # The same record re-read with other values has another raw digest; the two cannot be mixed.
    revised = _by_metric(_tiktok({**video, "view_count": 6000}))
    with pytest.raises(FeatureInputError, match="one retrieved record"):
        ratio(likes, revised[(f"video:{video['id']}", "view_count")], as_of=RETRIEVED)
    with pytest.raises(FeatureInputError, match="two metrics"):
        ratio(likes, likes, as_of=RETRIEVED)
