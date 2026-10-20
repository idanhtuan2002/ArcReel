"""Additive manual-acquisition lifecycle and provenance contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from r2.contracts.advanced_creative import Sha256Digest
from r2.contracts.opportunity import (
    AcquireSourceQuery,
    AttemptOutcomeReason,
    M9ContractModel,
    SourceSnapshotView,
)


class AttemptStateV2(StrEnum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    NEEDS_OPERATOR = "NEEDS_OPERATOR"
    EXPIRED_UNRECOVERABLE = "EXPIRED_UNRECOVERABLE"


TERMINAL_ATTEMPT_STATES_V2 = frozenset(
    (AttemptStateV2.SUCCEEDED, AttemptStateV2.FAILED, AttemptStateV2.EXPIRED_UNRECOVERABLE)
)


class QuotaDispositionV2(StrEnum):
    UNKNOWN = "UNKNOWN"
    POSSIBLY_CONSUMED = "POSSIBLY_CONSUMED"
    OBSERVED = "OBSERVED"


class ExpiryDispositionV2(StrEnum):
    ADMISSION_RETENTION_EXPIRED = "ADMISSION_RETENTION_EXPIRED"
    OPERATIONAL_EVIDENCE_STALE = "OPERATIONAL_EVIDENCE_STALE"


class SnapshotOriginV2(StrEnum):
    SOURCE_RESPONSE_VERIFIED = "SOURCE_RESPONSE_VERIFIED"
    LOCAL_ADMISSION_RECONSTRUCTION = "LOCAL_ADMISSION_RECONSTRUCTION"


class AcquireSourceQueryV2(AcquireSourceQuery):
    protocol_version: Literal["m9.acquisition.v2"]


class ExpiryClosureV2(M9ContractModel):
    disposition: ExpiryDispositionV2
    original_deadline: AwareDatetime
    closed_at: AwareDatetime
    resolver_id: str
    resolver_version: str
    expected_prior_version: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def validate_closure(self) -> Self:
        if self.closed_at < self.original_deadline:
            raise ValueError("policy closure cannot precede the original deadline")
        return self


def _require_outcome(state: AttemptStateV2, reason: AttemptOutcomeReason | None) -> None:
    if state in (AttemptStateV2.PLANNED, AttemptStateV2.RUNNING):
        valid = reason is None
    elif state == AttemptStateV2.SUCCEEDED:
        valid = reason == AttemptOutcomeReason.COMPLETED
    elif state == AttemptStateV2.FAILED:
        valid = reason not in (
            None,
            AttemptOutcomeReason.COMPLETED,
            AttemptOutcomeReason.RESPONSE_OUTCOME_UNKNOWN,
            AttemptOutcomeReason.OPERATOR_RESOLVED,
        )
    else:
        valid = reason == AttemptOutcomeReason.RESPONSE_OUTCOME_UNKNOWN
    if not valid:
        raise ValueError("attempt state and outcome reason differ")


def _require_quota(disposition: QuotaDispositionV2, units: int | None) -> None:
    if (disposition == QuotaDispositionV2.OBSERVED) != (units is not None):
        raise ValueError("only observed quota can carry measured units")


class AcquisitionAttemptV2(M9ContractModel):
    protocol_version: Literal["m9.acquisition.v2"]
    attempt_id: str
    attempt_version: int = Field(ge=1, strict=True)
    user_id: str
    project_name: str
    actor_id: str
    command_id: str
    request_digest: Sha256Digest
    query_id: str
    query_revision: int = Field(ge=1, strict=True)
    query_digest: Sha256Digest
    page_cursor_digest: Sha256Digest | None
    state: AttemptStateV2
    adapter_version: str
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    provider_request_id: str | None
    outcome_reason: AttemptOutcomeReason | None
    closure: ExpiryClosureV2 | None
    quota_disposition: QuotaDispositionV2
    quota_units_observed: int | None = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        _require_outcome(self.state, self.outcome_reason)
        _require_quota(self.quota_disposition, self.quota_units_observed)
        if (self.state in TERMINAL_ATTEMPT_STATES_V2) != (self.completed_at is not None):
            raise ValueError("only terminal attempts have a local completion time")
        if self.state == AttemptStateV2.PLANNED:
            if self.started_at is not None or self.quota_disposition != QuotaDispositionV2.UNKNOWN:
                raise ValueError("planned attempt cannot claim execution or quota")
        elif self.state != AttemptStateV2.FAILED and self.started_at is None:
            raise ValueError("executing or uncertain attempt requires its original start")
        if self.started_at is not None and self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("local completion cannot precede the original start")
        if (self.state == AttemptStateV2.EXPIRED_UNRECOVERABLE) != (self.closure is not None):
            raise ValueError("only policy-expired attempts carry an expiry closure")
        if self.closure is not None and (
            self.completed_at != self.closure.closed_at
            or self.attempt_version != self.closure.expected_prior_version + 1
        ):
            raise ValueError("expiry closure must bind the exact local transition version and time")
        return self


class AcquisitionReceiptV2(M9ContractModel):
    protocol_version: Literal["m9.acquisition.v2"]
    command_id: str
    request_digest: Sha256Digest
    attempt_id: str
    attempt_version: int = Field(ge=1, strict=True)
    state: AttemptStateV2
    outcome_reason: AttemptOutcomeReason | None
    snapshot_ids: tuple[str, ...] = Field(max_length=1)
    snapshot_digests: tuple[Sha256Digest, ...] = Field(max_length=1)
    snapshot_provenance_digests: tuple[Sha256Digest, ...] = Field(max_length=1)
    closure: ExpiryClosureV2 | None
    quota_disposition: QuotaDispositionV2
    quota_units_observed: int | None = Field(ge=0, strict=True)
    result_digest: Sha256Digest
    committed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        _require_outcome(self.state, self.outcome_reason)
        _require_quota(self.quota_disposition, self.quota_units_observed)
        if len({len(self.snapshot_ids), len(self.snapshot_digests), len(self.snapshot_provenance_digests)}) != 1:
            raise ValueError("snapshot identity, digest and provenance must be paired")
        if self.state in (AttemptStateV2.SUCCEEDED, AttemptStateV2.FAILED) and not self.snapshot_ids:
            raise ValueError("known terminal outcome requires its explicit snapshot")
        if (self.state == AttemptStateV2.EXPIRED_UNRECOVERABLE) != (self.closure is not None):
            raise ValueError("only policy-expired receipts carry an expiry closure")
        if self.closure is not None and (
            self.committed_at != self.closure.closed_at
            or self.attempt_version != self.closure.expected_prior_version + 1
        ):
            raise ValueError("expiry receipt must bind the exact closure version and commit time")
        return self


class SnapshotProvenanceV2(M9ContractModel):
    snapshot_id: str
    snapshot_digest: Sha256Digest
    attempt_id: str
    attempt_version: int = Field(ge=1, strict=True)
    admission_metadata_digest: Sha256Digest
    origin: SnapshotOriginV2
    admitted_at: AwareDatetime
    response_recorded_at: AwareDatetime | None

    @model_validator(mode="after")
    def validate_origin(self) -> Self:
        if self.origin == SnapshotOriginV2.LOCAL_ADMISSION_RECONSTRUCTION:
            if self.response_recorded_at is not None:
                raise ValueError("local reconstruction cannot assert a source response")
        elif self.response_recorded_at is None or self.response_recorded_at < self.admitted_at:
            raise ValueError("verified response requires a response time after original admission")
        return self


class SourceSnapshotViewV2(M9ContractModel):
    protocol_version: Literal["m9.acquisition.v2"]
    snapshot_view: SourceSnapshotView
    provenance: SnapshotProvenanceV2

    @model_validator(mode="after")
    def validate_snapshot_binding(self) -> Self:
        snapshot = self.snapshot_view.snapshot
        provenance = self.provenance
        if (snapshot.snapshot_id, snapshot.snapshot_digest, snapshot.attempt_id) != (
            provenance.snapshot_id,
            provenance.snapshot_digest,
            provenance.attempt_id,
        ):
            raise ValueError("snapshot and provenance identity differ")
        if snapshot.capture_completed_at != provenance.admitted_at or snapshot.created_at < provenance.admitted_at:
            raise ValueError("snapshot must preserve the original admission anchor")
        if any(page.captured_at != provenance.admitted_at for page in snapshot.pages):
            raise ValueError("manual pages must preserve the original admission anchor")
        if provenance.origin == SnapshotOriginV2.LOCAL_ADMISSION_RECONSTRUCTION:
            if snapshot.provider_observed_at is not None:
                raise ValueError("local reconstruction cannot assert a provider observation")
        elif provenance.response_recorded_at is not None and snapshot.created_at < provenance.response_recorded_at:
            raise ValueError("snapshot cannot precede its verified response")
        return self
