"""D10 — Non-authoritative failure semantics and production telemetry.

``FailureRecord`` and ``ProductionEvent`` project authoritative state. They carry
stable reason/disposition codes and safe messages; they never mutate artifact,
approval, method or Canon truth, and they are not a second state engine.
"""

from __future__ import annotations

from pydantic import AwareDatetime, Field

from .common import NonEmptyStr, R2ContractModel
from .enums import FailureClassification, FailureDomain, RetryDisposition
from .provenance import Provenance


class FailureRecord(R2ContractModel):
    failure_id: NonEmptyStr
    occurred_at: AwareDatetime
    domain: FailureDomain
    reason_code: NonEmptyStr
    classification: FailureClassification
    retry_disposition: RetryDisposition
    target_ref: NonEmptyStr
    attempt_ref: NonEmptyStr | None = None
    decision_refs: list[NonEmptyStr] = Field(default_factory=list)
    safe_message: NonEmptyStr
    diagnostic_ref: NonEmptyStr | None = None
    provenance: Provenance


class ProductionEvent(R2ContractModel):
    event_id: NonEmptyStr
    event_type: NonEmptyStr
    timestamp: AwareDatetime
    production_run_id: NonEmptyStr
    target_ref: NonEmptyStr
    stage: NonEmptyStr
    outcome: NonEmptyStr | None = None
    reason_code: NonEmptyStr | None = None
    decision_refs: list[NonEmptyStr] = Field(default_factory=list)
    attempt_ref: NonEmptyStr | None = None
    trace_id: NonEmptyStr | None = None
    span_id: NonEmptyStr | None = None
    provenance: Provenance
