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


COMMAND_RECEIPT_ENVELOPE_SCHEMA_VERSION = 1


def command_receipt_result_envelope(*, task_id: str, result: JSONValue) -> dict[str, JSONValue]:
    """Return the exact shape hashed by ``CommandReceipt.result_digest``:
    ``{"schema_version": 1, "task_id": str, "result": object}``."""
    return {"schema_version": COMMAND_RECEIPT_ENVELOPE_SCHEMA_VERSION, "task_id": task_id, "result": result}


__all__ = [
    "COMMAND_RECEIPT_ENVELOPE_SCHEMA_VERSION",
    "TERMINAL_ATTEMPT_STATES",
    "TERMINAL_OBSERVATION_KINDS",
    "AttemptIntegrityIncident",
    "AttemptLeaseFence",
    "AttemptSnapshot",
    "BackupSetState",
    "CommandReceipt",
    "ExecutionAttemptState",
    "OperatorResolutionAction",
    "OperatorResolutionReceipt",
    "PersistedProviderObservation",
    "PlannedExecutionAttempt",
    "ProjectEventType",
    "ProviderCapabilityProfile",
    "ProviderIdempotencyMode",
    "ProviderNotFoundSemantics",
    "ProviderObservation",
    "ProviderObservationKind",
    "ProviderQualificationStatus",
    "ProviderRouteSnapshot",
    "ProviderTokenScope",
    "ReconcileResult",
    "UpstreamDisposition",
    "command_receipt_result_envelope",
]
