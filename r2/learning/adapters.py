"""Source adapters: turn one source record into lineage-bound observations without erasing its semantics.

Every adapter is pure and returns an ``AdaptedRecord``: the canonical raw envelope as retrieved, its
digest, and the observations read from it. The raw envelope is stored next to the observations, so a
recommendation can always recover the full source record (call status, provider and model, QA reviewer,
approval context, the exact platform query) from ``raw_payload_digest``. The caller supplies the
server-resolved ``LineageBinding`` (ADR-0098) and the retrieval time; the repository stamps
``ingested_at``.

Observation ids are deterministic over identity and raw digest, so re-adapting an unchanged record
replays and a changed record yields a new id that the caller submits as a correction. Retrieval time
never enters a stable observation: it lives only in the raw envelope of sources whose values depend on it.

Internal sources (usage, QA, approval, M7 attempts) are point events: their window is the one-second
interval starting at the event, with aggregation ``event``. YouTube Analytics ``day`` rows are Pacific
calendar days; the measurement scope (``ids`` and ``filters``) is part of the record identity. A TikTok
video object carries counts read at retrieval time, kept as a snapshot over ``[publish, retrieval]``.
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
# metric -> (unit, aggregation): views and minutes are summed over the day; the duration is a daily mean.
YOUTUBE_METRICS = {
    "views": ("count", "sum_day"),
    "estimatedMinutesWatched": ("minutes", "sum_day"),
    "averageViewDuration": ("seconds", "mean_day"),
}
TIKTOK_METRICS = {"view_count": "count", "like_count": "count", "comment_count": "count", "share_count": "count"}

_TERMINAL = {
    ExecutionAttemptState.SUCCEEDED,
    ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE,
    ExecutionAttemptState.FAILED,
    ExecutionAttemptState.CANCELLED,
}

PlatformStatus = Literal["PUBLIC", "PRIVATE", "DELETED"]


@dataclass(frozen=True)
class AdaptedRecord:
    """One source record as retrieved and the observations read from it."""

    raw_payload: Mapping[str, object]
    raw_payload_digest: str
    observations: tuple[LearningObservation, ...]


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
    platform_artifact_id: str | None = None
    format_profile_ref: str | None = None

    @property
    def digest(self) -> str:
        return digest_canonical(dict(self.raw))


def _observe(
    source: _Source,
    *,
    metric: str,
    unit: str,
    value: Decimal | None,
    window: MetricWindow,
    observed_at: datetime,
    missing: MissingReason = MissingReason.MISSING,
) -> LearningObservation:
    raw_digest = source.digest
    definition = f"{source.family}/{metric}@{ADAPTER_VERSION}"
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
        # The repository replaces this with its admission time.
        ingested_at=_utc(observed_at),
    )


def _record(source: _Source, observations: tuple[LearningObservation, ...]) -> AdaptedRecord:
    return AdaptedRecord(raw_payload=dict(source.raw), raw_payload_digest=source.digest, observations=observations)


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


def observe_usage(call: UsageCall, *, lineage: LineageBinding) -> AdaptedRecord | None:
    """Cost, latency, tokens and the call outcome; a failed call is observed as failed, not dropped."""
    if call.finished_at is None:
        return None
    raw = {
        "source": "api_calls",
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
    source = _Source(USAGE_FAMILY, f"api_call:{call.call_id}", raw, lineage)
    window = _event_window(call.finished_at)
    at = call.finished_at
    succeeded = Decimal(1) if call.status == "success" else Decimal(0)
    return _record(
        source,
        (
            _observe(source, metric="call_succeeded", unit="boolean", value=succeeded, window=window, observed_at=at),
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
        ),
    )


def observe_quality_report(report: QualityReport, *, lineage: LineageBinding) -> AdaptedRecord:
    raw = {"source": "quality_report", "report": report.model_dump(mode="python")}
    source = _Source(QA_FAMILY, f"quality_report:{report.id}", raw, lineage)
    window = _event_window(report.created_at)
    return _record(
        source,
        (
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


def observe_publish_approval(decision: PublishApproval, *, lineage: LineageBinding) -> AdaptedRecord:
    raw = {
        "source": "gate_publish_approval_decisions",
        "decision_id": decision.decision_id,
        "deliverable_digest": decision.deliverable_digest,
        "platform": decision.platform,
        "visibility": decision.visibility,
        "action": decision.action,
        "sequence": decision.sequence,
        "created_at": _utc(decision.created_at),
    }
    source = _Source(APPROVAL_FAMILY, f"publish_approval:{decision.decision_id}", raw, lineage)
    value = Decimal(1) if decision.action == "APPROVE_PUBLISH" else Decimal(0)
    return _record(
        source,
        (
            _observe(
                source,
                metric="publish_approved",
                unit="boolean",
                value=value,
                window=_event_window(decision.created_at),
                observed_at=decision.created_at,
            ),
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


def observe_attempt(attempt: AttemptRecord, *, lineage: LineageBinding) -> AdaptedRecord | None:
    if attempt.state not in _TERMINAL or attempt.terminal_at is None:
        return None
    raw = {
        "source": "execution_attempts",
        "execution_id": attempt.execution_id,
        "task_id": attempt.task_id,
        "attempt_no": attempt.attempt_no,
        "state": attempt.state,
        "created_at": _utc(attempt.created_at),
        "terminal_at": _utc(attempt.terminal_at),
    }
    source = _Source(ATTEMPT_FAMILY, f"execution:{attempt.execution_id}", raw, lineage)
    window = _event_window(attempt.terminal_at)
    seconds = Decimal(str((_utc(attempt.terminal_at) - _utc(attempt.created_at)).total_seconds()))
    succeeded = Decimal(1) if attempt.state is ExecutionAttemptState.SUCCEEDED else Decimal(0)
    at = attempt.terminal_at
    return _record(
        source,
        (
            _observe(
                source, metric="attempt_succeeded", unit="boolean", value=succeeded, window=window, observed_at=at
            ),
            _observe(source, metric="attempt_seconds", unit="seconds", value=seconds, window=window, observed_at=at),
        ),
    )


# --- platform sources (fixtures only; no live calls) -------------------------------------


def youtube_day_window(day: date, *, aggregation: str = "sum_day") -> MetricWindow:
    """A YouTube Analytics ``day``: 12:00AM to the next 12:00AM Pacific time, DST-aware."""
    zone = ZoneInfo(YOUTUBE_TIMEZONE)
    start = datetime.combine(day, time(0), tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=zone)
    return MetricWindow(
        starts_at=start.astimezone(UTC),
        ends_at=end.astimezone(UTC),
        timezone_name=YOUTUBE_TIMEZONE,
        aggregation=aggregation,
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


def youtube_scope(query: Mapping[str, str]) -> dict[str, str]:
    """The measurement scope of a ``dimensions=day`` query: ``ids`` plus ``filters`` (the video and any slice)."""
    if not query.get("ids"):
        raise ValueError("a YouTube Analytics query names its ids")
    if query.get("dimensions") != "day":
        raise ValueError("the adapter reads dimensions=day reports")
    return {"ids": query["ids"], "dimensions": "day", "filters": query.get("filters", "")}


def observe_youtube_days(
    *,
    video_id: str,
    query: Mapping[str, str],
    requested_days: tuple[date, ...],
    rows: tuple[Mapping[str, object], ...],
    status: PlatformStatus,
    lineage: LineageBinding,
    format_profile_ref: str | None = None,
) -> tuple[AdaptedRecord, ...]:
    """One record per requested day of a ``dimensions=day`` report for one video and scope.

    The record identity includes the query scope, so an all-traffic report and a country slice of the
    same video and day never share an identity. A day without a row is ``PRIVATE`` or ``DELETED`` for a
    video in that state; for a public video it is ``NOT_YET_AVAILABLE`` only after the latest day the
    report returned (the API stops at the last day with complete data), and ``MISSING`` otherwise.
    """
    scope = youtube_scope(query)
    if f"video=={video_id}" not in scope["filters"].split(";"):
        raise ValueError("the query must filter to this video")
    scope_tag = digest_canonical(scope).removeprefix("sha256:")[:16]
    by_day: dict[str, Mapping[str, object]] = {}
    for row in rows:
        day = str(row["day"])
        if day in by_day:
            raise ValueError("duplicate YouTube day row")
        by_day[day] = row
    if set(by_day) - {day.isoformat() for day in requested_days}:
        raise ValueError("YouTube row outside the requested days")
    latest = max((date.fromisoformat(day) for day in by_day), default=None)
    records: list[AdaptedRecord] = []
    for day in requested_days:
        row = by_day.get(day.isoformat())
        if row is not None:
            absent = MissingReason.MISSING
        elif status != "PUBLIC":
            absent = MissingReason(status)
        elif latest is not None and day > latest:
            absent = MissingReason.NOT_YET_AVAILABLE
        else:
            absent = MissingReason.MISSING
        raw = {
            "source": "youtubeAnalytics.reports.query",
            "query": scope,
            "video_id": video_id,
            "day": day.isoformat(),
            # What the report said about this day; the missing reason is derived from it alone.
            "outcome": "ROW_RETURNED" if row is not None else absent.value,
            "row": None if row is None else dict(row),
        }
        source = _Source(
            YOUTUBE_FAMILY,
            f"video:{video_id}:{day.isoformat()}:scope:{scope_tag}",
            raw,
            lineage,
            f"youtube:{video_id}",
            format_profile_ref,
        )
        observations = []
        for metric, (unit, aggregation) in YOUTUBE_METRICS.items():
            window = youtube_day_window(day, aggregation=aggregation)
            observations.append(
                _observe(
                    source,
                    metric=metric,
                    unit=unit,
                    value=None if row is None else _decimal(row.get(metric)),
                    window=window,
                    observed_at=window.ends_at,
                    missing=absent,
                )
            )
        records.append(_record(source, tuple(observations)))
    return tuple(records)


def observe_tiktok_video(
    *,
    video: Mapping[str, object] | None,
    video_id: str,
    status: PlatformStatus,
    published_at: datetime,
    retrieved_at: datetime,
    lineage: LineageBinding,
    format_profile_ref: str | None = None,
) -> AdaptedRecord:
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
    raw = {
        "source": "tiktok.v2.video.query",
        "video_id": video_id,
        "status": status,
        "retrieved_at": _utc(retrieved_at),
        "video": None if video is None else dict(video),
    }
    source = _Source(TIKTOK_FAMILY, f"video:{video_id}", raw, lineage, f"tiktok:{video_id}", format_profile_ref)
    absent = MissingReason.MISSING if status == "PUBLIC" else MissingReason(status)
    return _record(
        source,
        tuple(
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
        ),
    )


__all__ = [
    "ADAPTER_VERSION",
    "APPROVAL_FAMILY",
    "ATTEMPT_FAMILY",
    "QA_FAMILY",
    "TIKTOK_FAMILY",
    "USAGE_FAMILY",
    "YOUTUBE_FAMILY",
    "AdaptedRecord",
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
    "youtube_scope",
]
