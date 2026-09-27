"""Provider-neutral host-production-hardening contracts.

Provider-neutral, immutable execution-identity, idempotency, provider-
capability and durable-event shapes for closing H1-H2. No field or contract
name here is optional; ports, services and persistence consume these shapes.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field

from .common import JSONValue, NonEmptyStr, R2ContractModel

# --- enums ---------------------------------------------------------------------------


class ExecutionAttemptState(StrEnum):
    PLANNED = "PLANNED"
    SUBMITTING = "SUBMITTING"
    SUBMIT_OUTCOME_UNKNOWN = "SUBMIT_OUTCOME_UNKNOWN"
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCEL_OUTCOME_UNKNOWN = "CANCEL_OUTCOME_UNKNOWN"
    SUCCEEDED = "SUCCEEDED"
    FAILED_BEFORE_ACCEPTANCE = "FAILED_BEFORE_ACCEPTANCE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    NEEDS_OPERATOR = "NEEDS_OPERATOR"


class ProviderIdempotencyMode(StrEnum):
    NATIVE_TOKEN = "NATIVE_TOKEN"
    LOOKUP_BY_METADATA = "LOOKUP_BY_METADATA"
    NONE = "NONE"


class ProviderTokenScope(StrEnum):
    PROVIDER_ACCOUNT = "PROVIDER_ACCOUNT"
    PROVIDER_ACCOUNT_REGION = "PROVIDER_ACCOUNT_REGION"
    PROVIDER_ACCOUNT_ENDPOINT = "PROVIDER_ACCOUNT_ENDPOINT"


class ProviderNotFoundSemantics(StrEnum):
    NON_AUTHORITATIVE = "NON_AUTHORITATIVE"
    AUTHORITATIVE_AFTER_SETTLING_WINDOW = "AUTHORITATIVE_AFTER_SETTLING_WINDOW"


class ProviderObservationKind(StrEnum):
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    NOT_FOUND = "NOT_FOUND"


class ProjectEventType(StrEnum):
    ATTEMPT_TRANSITIONED = "ATTEMPT_TRANSITIONED"
    CANDIDATE_VERIFIED = "CANDIDATE_VERIFIED"
    MASTER_PROMOTED = "MASTER_PROMOTED"
    USAGE_FINALIZED = "USAGE_FINALIZED"
    RESYNC_REQUIRED = "RESYNC_REQUIRED"


class BackupSetState(StrEnum):
    PREPARING = "PREPARING"
    COMPLETE = "COMPLETE"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ProviderQualificationStatus(StrEnum):
    UNQUALIFIED = "UNQUALIFIED"
    OFFLINE_VERIFIED = "OFFLINE_VERIFIED"
    SANDBOX_VERIFIED = "SANDBOX_VERIFIED"
    QUALIFIED = "QUALIFIED"


class UpstreamDisposition(StrEnum):
    UNCHANGED = "UNCHANGED"
    ADAPTED = "ADAPTED"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"


class OperatorResolutionAction(StrEnum):
    BIND_REMOTE_JOB = "BIND_REMOTE_JOB"
    CONFIRM_NOT_SUBMITTED = "CONFIRM_NOT_SUBMITTED"
    CONFIRM_TERMINAL = "CONFIRM_TERMINAL"


# --- terminal/legal-edge vocabulary shared with r2.host_hardening.transitions --------

TERMINAL_ATTEMPT_STATES: frozenset[ExecutionAttemptState] = frozenset(
    {
        ExecutionAttemptState.SUCCEEDED,
        ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE,
        ExecutionAttemptState.FAILED,
        ExecutionAttemptState.CANCELLED,
    }
)

# Terminal provider facts preserve the first committed terminal truth: the terminal kind
# already recorded always wins over a later-arriving different terminal kind.
TERMINAL_OBSERVATION_KINDS: frozenset[ProviderObservationKind] = frozenset(
    {
        ProviderObservationKind.SUCCEEDED,
        ProviderObservationKind.FAILED,
        ProviderObservationKind.CANCELLED,
    }
)


# --- value objects ---------------------------------------------------------------------


class ProviderRouteSnapshot(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_id: NonEmptyStr
    provider_account_ref: NonEmptyStr
    provider_model_id: NonEmptyStr
    backend_model_id: NonEmptyStr
    endpoint_id: NonEmptyStr | None = None
    submitted_base_url: NonEmptyStr
    adapter_version: NonEmptyStr
    capability_profile_ref: NonEmptyStr


class PlannedExecutionAttempt(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: NonEmptyStr
    task_id: NonEmptyStr
    attempt_no: int = Field(ge=1)
    request_digest: NonEmptyStr
    route: ProviderRouteSnapshot
    client_token: NonEmptyStr | None = None
    trace_id_at_creation: NonEmptyStr | None = None
    created_at: AwareDatetime


class CommandReceipt(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_scope: NonEmptyStr
    command_id: NonEmptyStr
    command_digest: NonEmptyStr
    task_id: NonEmptyStr
    result_digest: NonEmptyStr
    created_at: AwareDatetime


class AttemptSnapshot(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: NonEmptyStr
    task_id: NonEmptyStr
    attempt_no: int = Field(ge=1)
    request_digest: NonEmptyStr
    route: ProviderRouteSnapshot
    client_token: NonEmptyStr | None = None
    provider_job_id: NonEmptyStr | None = None
    state: ExecutionAttemptState
    state_version: int = Field(ge=1)
    lease_owner: NonEmptyStr | None = None
    lease_token: int | None = None
    lease_expires_at: AwareDatetime | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    submitted_at: AwareDatetime | None = None
    last_observed_at: AwareDatetime | None = None
    terminal_at: AwareDatetime | None = None


class ProviderCapabilityProfile(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: NonEmptyStr
    provider_id: NonEmptyStr
    api_version: NonEmptyStr
    adapter_version: NonEmptyStr
    idempotency_mode: ProviderIdempotencyMode
    token_scope: ProviderTokenScope | None = None
    token_scope_value: NonEmptyStr | None = None
    token_ttl_seconds: int | None = Field(default=None, ge=1)
    not_found_semantics: ProviderNotFoundSemantics
    lookup_settling_window_seconds: int | None = Field(default=None, ge=0)
    supports_poll: bool
    supports_cancel: bool
    supports_webhook: Literal[False] = False
    supports_lookup: bool
    provider_sequence_is_monotonic: bool
    evidence_digest: NonEmptyStr


class ProviderObservation(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_id: NonEmptyStr
    kind: ProviderObservationKind
    observed_at: AwareDatetime
    provider_sequence: int | None = None
    provider_job_id: NonEmptyStr | None = None
    reason_code: NonEmptyStr | None = None
    evidence_digest: NonEmptyStr


class PersistedProviderObservation(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    observation: ProviderObservation
    received_seq: int = Field(ge=1)
    received_at: AwareDatetime


class AttemptLeaseFence(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    owner: NonEmptyStr
    token: int = Field(ge=1)


class OperatorResolutionReceipt(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    resolution_id: NonEmptyStr
    execution_id: NonEmptyStr
    expected_attempt_version: int = Field(ge=1)
    operator_id: NonEmptyStr
    action: OperatorResolutionAction
    resolved_state: ExecutionAttemptState
    provider_job_id: NonEmptyStr | None = None
    terminal_kind: ProviderObservationKind | None = None
    evidence_digest: NonEmptyStr
    resolved_at: AwareDatetime


class AttemptIntegrityIncident(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    incident_id: NonEmptyStr
    execution_id: NonEmptyStr
    first_observation_id: NonEmptyStr
    conflicting_observation_id: NonEmptyStr
    evidence_digest: NonEmptyStr
    resolved_by_receipt_id: NonEmptyStr | None = None


class ReconcileResult(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: NonEmptyStr
    state: ExecutionAttemptState
    provider_job_id: NonEmptyStr | None = None
    operator_reason: NonEmptyStr | None = None


class CandidateIdentity(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: NonEmptyStr
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    artifact_key: NonEmptyStr
    expected_content_digest: NonEmptyStr


class VerifiedCandidateObject(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: NonEmptyStr
    project_name: NonEmptyStr
    artifact_key: NonEmptyStr
    object_ref: NonEmptyStr
    byte_size: int = Field(ge=0)
    content_digest: NonEmptyStr
    media_probe_digest: NonEmptyStr


class MasterHeadSnapshot(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_key: NonEmptyStr
    master_version: int = Field(ge=1)
    candidate_id: NonEmptyStr
    object_ref: NonEmptyStr
    content_digest: NonEmptyStr
    approval_record: NonEmptyStr


class PromotionReceipt(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_key: NonEmptyStr
    command_id: NonEmptyStr
    command_digest: NonEmptyStr
    candidate_id: NonEmptyStr
    master_version: int = Field(ge=1)
    approval_record: NonEmptyStr
    created_at: AwareDatetime


class DurableProjectEvent(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: int = Field(ge=1)
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    task_id: NonEmptyStr | None = None
    execution_id: NonEmptyStr | None = None
    event_type: ProjectEventType
    state_version: int | None = Field(default=None, ge=1)
    public_payload: dict[str, JSONValue]
    payload_schema_version: int = Field(ge=1)
    trace_id: NonEmptyStr | None = None
    dedupe_key: NonEmptyStr


class MediaInventoryEntry(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_name: NonEmptyStr
    artifact_key: NonEmptyStr
    object_ref: NonEmptyStr
    object_version: NonEmptyStr | None = None
    byte_size: int = Field(ge=0)
    content_digest: NonEmptyStr


class BackupSetManifest(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    backup_set_id: NonEmptyStr
    source_deployment_id: NonEmptyStr
    release_git_sha: NonEmptyStr
    release_image_digest: NonEmptyStr
    postgres_version: NonEmptyStr
    alembic_head: NonEmptyStr
    database_backup_ref: NonEmptyStr
    recovery_target: NonEmptyStr
    configuration_digest: NonEmptyStr
    media: tuple[MediaInventoryEntry, ...]
    state: BackupSetState


class BackupVerdict(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    backup_set_id: NonEmptyStr
    accepted: bool
    reason_codes: tuple[NonEmptyStr, ...]
    checked_master_count: int = Field(ge=0)
    checked_media_count: int = Field(ge=0)
    measured_rpo_seconds: int | None = Field(default=None, ge=0)
    measured_rto_seconds: int | None = Field(default=None, ge=0)


DEPLOYMENT_BACKUP_SCHEMA_VERSION = 1


class BackupFileEntry(R2ContractModel):
    """One regular file captured from a named deployment data root."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    root: NonEmptyStr
    path: NonEmptyStr
    byte_size: int = Field(ge=0)
    content_digest: NonEmptyStr


class SanitizedTableEntry(R2ContractModel):
    """A table whose rows are captured with credential columns blanked.

    Its data is excluded from the database dump and stored separately as a
    PostgreSQL binary COPY of the sanitized rows.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    table: NonEmptyStr
    blanked_columns: tuple[NonEmptyStr, ...]
    row_count: int = Field(ge=0)
    data_ref: NonEmptyStr
    content_digest: NonEmptyStr


class OfflineFenceEvidence(R2ContractModel):
    """What the offline fence observed before and after capture (ADR-0090)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    other_sessions_before: int = Field(ge=0)
    other_sessions_after: int = Field(ge=0)
    active_tasks_before: int = Field(ge=0)
    active_tasks_after: int = Field(ge=0)
    write_counter_before: int = Field(ge=0)
    write_counter_after: int = Field(ge=0)
    file_fingerprint_before: NonEmptyStr
    file_fingerprint_after: NonEmptyStr
    sequence_fingerprint_before: NonEmptyStr
    sequence_fingerprint_after: NonEmptyStr


class DeploymentBackupManifest(R2ContractModel):
    """A whole-deployment backup set: one database recovery point plus every
    captured data-root file, taken under the offline fence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = DEPLOYMENT_BACKUP_SCHEMA_VERSION
    backup_set_id: NonEmptyStr
    source_deployment_id: NonEmptyStr
    release_git_sha: NonEmptyStr
    release_image_digest: NonEmptyStr
    postgres_version: NonEmptyStr
    alembic_head: NonEmptyStr
    recovery_point: AwareDatetime
    database_backup_ref: NonEmptyStr
    database_backup_digest: NonEmptyStr
    table_row_counts: dict[NonEmptyStr, int]
    sanitized_tables: tuple[SanitizedTableEntry, ...]
    excluded_data_entries: tuple[NonEmptyStr, ...]
    excluded_file_names: tuple[NonEmptyStr, ...]
    files: tuple[BackupFileEntry, ...]
    configuration: dict[NonEmptyStr, JSONValue]
    configuration_digest: NonEmptyStr
    fence: OfflineFenceEvidence


class DeploymentBackupVerdict(R2ContractModel):
    """Automated clean-target checks of one restored deployment backup set.

    A verdict describes one restore target; it never changes the set's own
    lifecycle state. Passing checks are a precondition of attestation, not
    VERIFIED by themselves.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    backup_set_id: NonEmptyStr
    manifest_digest: NonEmptyStr
    target_release_git_sha: NonEmptyStr
    checks_passed: bool
    reason_codes: tuple[NonEmptyStr, ...]
    checked_table_count: int = Field(ge=0)
    checked_file_count: int = Field(ge=0)
    checked_reference_count: int = Field(ge=0)
    probed_media_count: int = Field(ge=0)
    checked_at: AwareDatetime


class GoldenProductResult(R2ContractModel):
    """No-provider read/review/export of one Golden product on the restored target."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_name: NonEmptyStr
    reviewed: bool
    export_digest: NonEmptyStr


class GoldenRestoreEvidence(R2ContractModel):
    """Evidence that the Golden products were read, reviewed and exported on the restored target."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    backup_set_id: NonEmptyStr
    manifest_digest: NonEmptyStr
    passed: bool
    products: tuple[GoldenProductResult, ...]


class DeploymentBackupAttestation(R2ContractModel):
    """The record that moves a backup set to VERIFIED (spec §8 step 7)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    backup_set_id: NonEmptyStr
    manifest_digest: NonEmptyStr
    verdict_digest: NonEmptyStr
    golden_evidence_digest: NonEmptyStr
    measured_rpo_seconds: int = Field(ge=0)
    measured_rto_seconds: int = Field(ge=0)
    verified_at: AwareDatetime


COMMAND_RECEIPT_ENVELOPE_SCHEMA_VERSION = 1


def command_receipt_result_envelope(*, task_id: str, result: JSONValue) -> dict[str, JSONValue]:
    """Return the exact shape hashed by ``CommandReceipt.result_digest``:
    ``{"schema_version": 1, "task_id": str, "result": object}``."""
    return {"schema_version": COMMAND_RECEIPT_ENVELOPE_SCHEMA_VERSION, "task_id": task_id, "result": result}


__all__ = [
    "COMMAND_RECEIPT_ENVELOPE_SCHEMA_VERSION",
    "DEPLOYMENT_BACKUP_SCHEMA_VERSION",
    "TERMINAL_ATTEMPT_STATES",
    "TERMINAL_OBSERVATION_KINDS",
    "AttemptIntegrityIncident",
    "AttemptLeaseFence",
    "AttemptSnapshot",
    "BackupFileEntry",
    "BackupSetManifest",
    "BackupSetState",
    "BackupVerdict",
    "CandidateIdentity",
    "CommandReceipt",
    "DeploymentBackupAttestation",
    "DeploymentBackupManifest",
    "DeploymentBackupVerdict",
    "DurableProjectEvent",
    "ExecutionAttemptState",
    "GoldenProductResult",
    "GoldenRestoreEvidence",
    "MasterHeadSnapshot",
    "MediaInventoryEntry",
    "OfflineFenceEvidence",
    "OperatorResolutionAction",
    "OperatorResolutionReceipt",
    "PersistedProviderObservation",
    "PlannedExecutionAttempt",
    "ProjectEventType",
    "PromotionReceipt",
    "ProviderCapabilityProfile",
    "ProviderIdempotencyMode",
    "ProviderNotFoundSemantics",
    "ProviderObservation",
    "ProviderObservationKind",
    "ProviderQualificationStatus",
    "ProviderRouteSnapshot",
    "ProviderTokenScope",
    "ReconcileResult",
    "SanitizedTableEntry",
    "UpstreamDisposition",
    "VerifiedCandidateObject",
    "command_receipt_result_envelope",
]
