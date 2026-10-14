"""Source adapters: turn one source record into lineage-bound observations without erasing its semantics.

Every adapter is pure. The caller supplies the server-resolved ``LineageBinding`` (ADR-0098) and the
retrieval time; the repository later stamps ``ingested_at``. Each observation keeps the source family,
the source record id, a versioned metric definition, the exact window with its time zone and
aggregation, and the digest of the raw record as retrieved. Observation ids are deterministic over
identity and raw digest, so re-adapting the same raw record replays and a changed record yields a new
id that the caller submits as a correction.

Internal sources (usage, QA, approval, M7 attempts) are point events: their window is the one-second
interval starting at the event, with aggregation ``event``. Platform sources keep their own window:
YouTube Analytics ``day`` rows are Pacific-time calendar days summed by the platform; a TikTok video
object carries counts read at retrieval time, kept as a snapshot over ``[create_time, retrieved_at]``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from r2.advanced_creative.digests import canonical_json_bytes, digest_canonical
from r2.contracts.advanced_creative import LearningObservation, LineageBinding, MetricWindow
from r2.contracts.host_hardening import ExecutionAttemptState
from r2.contracts.results import QualityReport
from r2.learning.observations import MissingReason

ADAPTER_VERSION = "1"
EVENT_AGGREGATION = "event"

USAGE_FAMILY = "arcreel.usage"
QA_FAMILY = "arcreel.qa"
APPROVAL_FAMILY = "arcreel.publish_approval"
ATTEMPT_FAMILY = "arcreel.m7_attempt"
YOUTUBE_FAMILY = "youtube.analytics.v2"
TIKTOK_FAMILY = "tiktok.display.v2.video"

YOUTUBE_TIMEZONE = "America/Los_Angeles"
YOUTUBE_METRICS = {"views": "count", "estimatedMinutesWatched": "minutes", "averageViewDuration": "seconds"}
TIKTOK_METRICS = {"view_count": "count", "like_count": "count", "comment_count": "count", "share_count": "count"}

_TERMINAL = {
    ExecutionAttemptState.SUCCEEDED,
    ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE,
    ExecutionAttemptState.FAILED,
    ExecutionAttemptState.CANCELLED,
}

PlatformStatus = Literal["PUBLIC", "PRIVATE", "DELETED"]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("source timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _event_window(at: datetime) -> MetricWindow:
    start = _utc(at).replace(microsecond=0)
    return MetricWindow(
        starts_at=start, ends_at=start + timedelta(seconds=1), timezone_name="UTC", aggregation=EVENT_AGGREGATION
    )


def _observation_id(
    family: str, record_id: str, metric: str, definition: str, window: MetricWindow, raw_digest: str
) -> str:
    key = canonical_json_bytes(
        {
            "family": family,
            "record": record_id,
            "metric": metric,
            "definition": definition,
            "window": window,
            "raw": raw_digest,
        }
    )
    return "obs-" + hashlib.sha256(key).hexdigest()[:40]


@dataclass(frozen=True)
class _Source:
    family: str
    record_id: str
    raw: Mapping[str, object]
    lineage: LineageBinding
    retrieved_at: datetime
    platform_artifact_id: str | None = None
    format_profile_ref: str | None = None


def _observe(
    source: _Source,
    *,
    metric: str,
    unit: str,
    value: Decimal | None,
    window: MetricWindow,
    observed_at: datetime,
    missing: MissingReason | None = None,
) -> LearningObservation:
    raw_digest = digest_canonical(dict(source.raw))
    definition = f"{source.family}/{metric}@{ADAPTER_VERSION}"
    if value is None and missing is None:
        missing = MissingReason.MISSING
    return LearningObservation(
        observation_id=_observation_id(source.family, source.record_id, metric, definition, window, raw_digest),
        source_family=source.family,
        source_record_id=source.record_id,
        metric_name=metric,
        metric_definition_version=definition,
        metric_value=value,
        metric_unit=unit,
        window=window,
        platform_artifact_id=source.platform_artifact_id,
        format_profile_ref=source.format_profile_ref,
        lineage=source.lineage,
        experiment_design=None,
        exposure_ref=None,
        raw_payload_digest=raw_digest,
        transformation_version=None,
        correction_of=None,
        missing_reason=None if value is not None else missing,
        observed_at=_utc(observed_at),
        ingested_at=_utc(source.retrieved_at),
    )


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError("metric values must be numeric")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("metric values must be finite")
    return result


# --- internal sources -------------------------------------------------------------------


@dataclass(frozen=True)
class UsageCall:
    """One ``api_calls`` row as read; only finished calls are observed."""

    call_id: int
    execution_id: str | None
    call_type: str
    provider: str
    model: str
    status: str
    cost_amount: float
    currency: str
    duration_ms: int | None
    usage_tokens: int | None
    started_at: datetime
    finished_at: datetime | None


def observe_usage(
    call: UsageCall, *, lineage: LineageBinding, retrieved_at: datetime
) -> tuple[LearningObservation, ...]:
    if call.finished_at is None:
        return ()
    raw = {
        "call_id": call.call_id,
        "execution_id": call.execution_id,
        "call_type": call.call_type,
        "provider": call.provider,
        "model": call.model,
        "status": call.status,
        "cost_amount": _decimal(call.cost_amount),
        "currency": call.currency,
        "duration_ms": call.duration_ms,
        "usage_tokens": call.usage_tokens,
        "started_at": _utc(call.started_at),
        "finished_at": _utc(call.finished_at),
    }
    source = _Source(USAGE_FAMILY, f"api_call:{call.call_id}", raw, lineage, retrieved_at)
    window = _event_window(call.finished_at)
    at = call.finished_at
    return (
        _observe(
            source,
            metric="provider_cost",
            unit=call.currency,
            value=_decimal(call.cost_amount),
            window=window,
            observed_at=at,
        ),
        _observe(
            source, metric="latency_ms", unit="ms", value=_decimal(call.duration_ms), window=window, observed_at=at
        ),
        _observe(
            source,
            metric="usage_tokens",
            unit="tokens",
            value=_decimal(call.usage_tokens),
            window=window,
            observed_at=at,
        ),
    )


def observe_quality_report(
    report: QualityReport, *, lineage: LineageBinding, retrieved_at: datetime
) -> tuple[LearningObservation, ...]:
    raw = report.model_dump(mode="python")
    source = _Source(QA_FAMILY, f"quality_report:{report.id}", raw, lineage, retrieved_at)
    window = _event_window(report.created_at)
    return (
        _observe(
            source,
            metric="qa_score",
            unit="ratio",
            value=_decimal(report.score),
            window=window,
            observed_at=report.created_at,
        ),
        _observe(
            source,
            metric="qa_blocking_findings",
            unit="count",
            value=Decimal(len(report.blocking_findings)),
            window=window,
            observed_at=report.created_at,
        ),
    )


@dataclass(frozen=True)
class PublishApproval:
    """One ``gate_publish_approval_decisions`` row as read."""

    decision_id: str
    deliverable_digest: str
    platform: str
    visibility: str
    action: Literal["APPROVE_PUBLISH", "REVOKE"]
    sequence: int
    created_at: datetime


def observe_publish_approval(
    decision: PublishApproval, *, lineage: LineageBinding, retrieved_at: datetime
) -> tuple[LearningObservation, ...]:
    raw = {
        "decision_id": decision.decision_id,
        "deliverable_digest": decision.deliverable_digest,
        "platform": decision.platform,
        "visibility": decision.visibility,
        "action": decision.action,
        "sequence": decision.sequence,
        "created_at": _utc(decision.created_at),
    }
    source = _Source(APPROVAL_FAMILY, f"publish_approval:{decision.decision_id}", raw, lineage, retrieved_at)
    value = Decimal(1) if decision.action == "APPROVE_PUBLISH" else Decimal(0)
    return (
        _observe(
            source,
            metric="publish_approved",
            unit="boolean",
            value=value,
            window=_event_window(decision.created_at),
            observed_at=decision.created_at,
        ),
    )


@dataclass(frozen=True)
class AttemptRecord:
    """One M7 ``execution_attempts`` row as read; only terminal attempts are observed."""

    execution_id: str
    task_id: str
    attempt_no: int
    state: ExecutionAttemptState
    created_at: datetime
    terminal_at: datetime | None


def observe_attempt(
    attempt: AttemptRecord, *, lineage: LineageBinding, retrieved_at: datetime
) -> tuple[LearningObservation, ...]:
    if attempt.state not in _TERMINAL or attempt.terminal_at is None:
        return ()
    raw = {
        "execution_id": attempt.execution_id,
        "task_id": attempt.task_id,
        "attempt_no": attempt.attempt_no,
        "state": attempt.state,
        "created_at": _utc(attempt.created_at),
        "terminal_at": _utc(attempt.terminal_at),
    }
    source = _Source(ATTEMPT_FAMILY, f"execution:{attempt.execution_id}", raw, lineage, retrieved_at)
    window = _event_window(attempt.terminal_at)
    seconds = Decimal(str((_utc(attempt.terminal_at) - _utc(attempt.created_at)).total_seconds()))
    succeeded = Decimal(1) if attempt.state is ExecutionAttemptState.SUCCEEDED else Decimal(0)
    return (
        _observe(
            source,
            metric="attempt_succeeded",
            unit="boolean",
            value=succeeded,
            window=window,
            observed_at=attempt.terminal_at,
        ),
        _observe(
            source,
            metric="attempt_seconds",
            unit="seconds",
            value=seconds,
            window=window,
            observed_at=attempt.terminal_at,
        ),
    )


# --- platform sources (fixtures only; no live calls) -------------------------------------


def youtube_day_window(day: date) -> MetricWindow:
    """A YouTube Analytics ``day``: 12:00AM to the next 12:00AM Pacific time, DST-aware."""
    zone = ZoneInfo(YOUTUBE_TIMEZONE)
    start = datetime.combine(day, time(0), tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=zone)
    return MetricWindow(
        starts_at=start.astimezone(UTC),
        ends_at=end.astimezone(UTC),
        timezone_name=YOUTUBE_TIMEZONE,
        aggregation="sum_day",
    )


def youtube_rows(result_table: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    """Rows of a ``youtubeAnalytics#resultTable`` keyed by their ``columnHeaders`` names."""
    if result_table.get("kind") != "youtubeAnalytics#resultTable":
        raise ValueError("not a YouTube Analytics result table")
    headers = result_table.get("columnHeaders")
    if not isinstance(headers, list):
        raise ValueError("result table needs columnHeaders")
    names = [str(header["name"]) for header in headers if isinstance(header, Mapping)]
    if len(names) != len(headers) or len(set(names)) != len(names):
        raise ValueError("result table column headers must be named and unique")
    rows = result_table.get("rows", [])
    if not isinstance(rows, list) or any(not isinstance(row, list) or len(row) != len(names) for row in rows):
        raise ValueError("result table rows must match the column headers")
    return tuple(dict(zip(names, row, strict=True)) for row in rows)


def observe_youtube_days(
    *,
    video_id: str,
    requested_days: tuple[date, ...],
    rows: tuple[Mapping[str, object], ...],
    status: PlatformStatus,
    lineage: LineageBinding,
    retrieved_at: datetime,
    format_profile_ref: str | None = None,
) -> tuple[LearningObservation, ...]:
    """One observation per requested day and metric of a ``dimensions=day`` report filtered to one video.

    A requested day with no row is ``NOT_YET_AVAILABLE`` for a public video (the API omits the most
    recent days), and ``PRIVATE`` or ``DELETED`` for a video in that state. A row present for a day
    keeps its values regardless of the current status.
    """
    by_day: dict[str, Mapping[str, object]] = {}
    for row in rows:
        day = str(row["day"])
        if day in by_day:
            raise ValueError("duplicate YouTube day row")
        by_day[day] = row
    if set(by_day) - {day.isoformat() for day in requested_days}:
        raise ValueError("YouTube row outside the requested days")
    absent = MissingReason.NOT_YET_AVAILABLE if status == "PUBLIC" else MissingReason(status)
    observations: list[LearningObservation] = []
    for day in requested_days:
        row = by_day.get(day.isoformat())
        raw = {
            "video_id": video_id,
            "day": day.isoformat(),
            "status": status,
            "row": None if row is None else dict(row),
        }
        source = _Source(
            YOUTUBE_FAMILY,
            f"video:{video_id}:{day.isoformat()}",
            raw,
            lineage,
            retrieved_at,
            f"youtube:{video_id}",
            format_profile_ref,
        )
        window = youtube_day_window(day)
        for metric, unit in YOUTUBE_METRICS.items():
            value = None if row is None else _decimal(row.get(metric))
            missing = absent if row is None else MissingReason.MISSING
            observations.append(
                _observe(
                    source,
                    metric=metric,
                    unit=unit,
                    value=value,
                    window=window,
                    observed_at=retrieved_at,
                    missing=missing,
                )
            )
    return tuple(observations)


def observe_tiktok_video(
    *,
    video: Mapping[str, object] | None,
    video_id: str,
    status: PlatformStatus,
    published_at: datetime,
    lineage: LineageBinding,
    retrieved_at: datetime,
    format_profile_ref: str | None = None,
) -> tuple[LearningObservation, ...]:
    """Counts read from one TikTok video object, kept as a snapshot over ``[publish, retrieval]``.

    The API documents each field as the number of views, likes, comments or shares and does not
    state a window; the adapter records exactly that: a snapshot read at ``retrieved_at``.
    """
    if video is not None and str(video.get("id")) != video_id:
        raise ValueError("TikTok video object names another video")
    if _utc(published_at) >= _utc(retrieved_at):
        raise ValueError("a snapshot is read after the video was published")
    window = MetricWindow(
        starts_at=_utc(published_at),
        ends_at=_utc(retrieved_at),
        timezone_name="UTC",
        aggregation="snapshot_at_retrieval",
    )
    raw = {"video_id": video_id, "status": status, "video": None if video is None else dict(video)}
    source = _Source(
        TIKTOK_FAMILY, f"video:{video_id}", raw, lineage, retrieved_at, f"tiktok:{video_id}", format_profile_ref
    )
    absent = MissingReason.MISSING if status == "PUBLIC" else MissingReason(status)
    return tuple(
        _observe(
            source,
            metric=metric,
            unit=unit,
            value=None if video is None else _decimal(video.get(metric)),
            window=window,
            observed_at=retrieved_at,
            missing=absent if video is None else MissingReason.MISSING,
        )
        for metric, unit in TIKTOK_METRICS.items()
    )


__all__ = [
    "ADAPTER_VERSION",
    "APPROVAL_FAMILY",
    "ATTEMPT_FAMILY",
    "QA_FAMILY",
    "TIKTOK_FAMILY",
    "USAGE_FAMILY",
    "YOUTUBE_FAMILY",
    "AttemptRecord",
    "PublishApproval",
    "UsageCall",
    "observe_attempt",
    "observe_publish_approval",
    "observe_quality_report",
    "observe_tiktok_video",
    "observe_usage",
    "observe_youtube_days",
    "youtube_day_window",
    "youtube_rows",
]
