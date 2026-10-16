"""Frozen M9 opportunity contracts and local shape invariants (accepted spec §§4–7)."""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, ValidationInfo, field_validator, model_validator

from r2.contracts.advanced_creative import (
    CanonicalJsonObject,
    M8ContractModel,
    Sha256Digest,
)

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
RawPageBytes = Annotated[bytes, Field(max_length=2_097_152)]


_M9_IDS = frozenset(
    {
        "command_id",
        "profile_id",
        "cohort_profile_id",
        "query_id",
        "attempt_id",
        "snapshot_id",
        "observation_id",
        "signal_id",
        "candidate_id",
        "supersedes_candidate_id",
        "decision_id",
        "supersedes_decision_id",
        "greenlight_decision_id",
        "invalidation_job_id",
        "intent_id",
        "authorization_id",
        "custodian_authorization_id",
        "current_decision_id",
        "m8_candidate_id",
        "m8_append_command_id",
    }
)

_UUID_REFERENCE_FIELDS = frozenset({"snapshot_ids", "signal_ids", "input_observation_ids", "policy_basis_grant_ids"})
_REFERENCE_ORDER_FIELDS = {
    "source_rules": ("source_kind",),
    "dimension_rules": ("dimension",),
    "data_rules": ("data_class",),
    "policy_documents": ("document_id",),
    "data_class_clocks": ("data_class",),
    "entries": ("ref",),
    "assessments": ("dimension",),
    "source_rule_evidence": ("source_kind",),
    "snapshots": ("snapshot_id", "snapshot_digest"),
}


def _require_uuid7(value: str) -> None:
    try:
        identity = UUID(value)
    except ValueError as exc:
        raise ValueError("identity must be UUIDv7") from exc
    if identity.version != 7 or str(identity) != value:
        raise ValueError("identity must be canonical UUIDv7")


def _nonempty(value: str) -> str:
    if not unicodedata.normalize("NFC", value).strip():
        raise ValueError("text must be non-empty")
    return value


class M9ContractModel(M8ContractModel):
    @field_validator("*", mode="after")
    @classmethod
    def normalize_scalars(cls, value: object, info: ValidationInfo) -> object:
        name = info.field_name
        if isinstance(value, str):
            value = _nonempty(value)
            if name in _M9_IDS:
                _require_uuid7(value)
        if isinstance(value, datetime):
            value = value.astimezone(UTC)
        return value

    @model_validator(mode="after")
    def normalize_references(self) -> Self:
        # Pages and condition evidence preserve their declared semantic order.
        from r2.advanced_creative.digests import canonical_json_bytes

        for name in type(self).model_fields:
            value: object = getattr(self, name)
            if not isinstance(value, tuple) or name in {"pages", "conditions", "condition_evidence"}:
                continue
            values = tuple(_nonempty(item) if isinstance(item, str) else item for item in value)
            if name in _UUID_REFERENCE_FIELDS:
                for item in values:
                    if isinstance(item, str):
                        _require_uuid7(item)
            order = _REFERENCE_ORDER_FIELDS.get(name)
            encoded = tuple(
                canonical_json_bytes(tuple(getattr(item, key) for key in order) if order else item) for item in values
            )
            if len(set(encoded)) != len(encoded):
                raise ValueError(f"{name} must be unique")
            object.__setattr__(
                self,
                name,
                tuple(item for _, item in sorted(zip(encoded, values, strict=True), key=lambda pair: pair[0])),
            )
        revision: object = getattr(self, "revision", None)
        if isinstance(revision, int) and "parent_revision" in type(self).model_fields:
            parent: object = getattr(self, "parent_revision", None)
            if parent != (None if revision == 1 else revision - 1):
                raise ValueError("revision parent must be the immediate predecessor; genesis has no parent")
        return self


class CapabilityState(StrEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class PermissionDisposition(StrEnum):
    PERMITTED = "PERMITTED"
    FORBIDDEN = "FORBIDDEN"
    CONDITIONAL = "CONDITIONAL"


class QueryIntent(StrEnum):
    LANDSCAPE = "LANDSCAPE"
    AUDIENCE = "AUDIENCE"
    COMPETITOR = "COMPETITOR"
    ORIGINALITY = "ORIGINALITY"
    FACTUAL_RESEARCH = "FACTUAL_RESEARCH"


class AttemptState(StrEnum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    NEEDS_OPERATOR = "NEEDS_OPERATOR"


class AttemptOutcomeReason(StrEnum):
    COMPLETED = "COMPLETED"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    CAPABILITY_EXPIRED = "CAPABILITY_EXPIRED"
    CAPABILITY_REVOKED = "CAPABILITY_REVOKED"
    POLICY_FORBIDDEN = "POLICY_FORBIDDEN"
    AGGREGATE_BYTE_LIMIT = "AGGREGATE_BYTE_LIMIT"
    CLIENT_STOPPED = "CLIENT_STOPPED"
    RESPONSE_OUTCOME_UNKNOWN = "RESPONSE_OUTCOME_UNKNOWN"
    OPERATOR_RESOLVED = "OPERATOR_RESOLVED"


class CoverageState(StrEnum):
    COMPLETE_WITHIN_DECLARED_BOUNDS = "COMPLETE_WITHIN_DECLARED_BOUNDS"
    TRUNCATED = "TRUNCATED"
    SAMPLED = "SAMPLED"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class MissingReason(StrEnum):
    NOT_RETURNED = "NOT_RETURNED"
    PRIVATE = "PRIVATE"
    DELETED = "DELETED"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    POLICY_DELETED = "POLICY_DELETED"
    UNKNOWN = "UNKNOWN"


class OpportunityDimension(StrEnum):
    POPULARITY = "POPULARITY"
    NOVELTY = "NOVELTY"
    CHANNEL_FIT = "CHANNEL_FIT"
    KNOWLEDGE_ADVANTAGE = "KNOWLEDGE_ADVANTAGE"
    PRODUCTION_FEASIBILITY = "PRODUCTION_FEASIBILITY"
    COMMERCIAL_OPPORTUNITY = "COMMERCIAL_OPPORTUNITY"
    CREATIVE_OPPORTUNITY = "CREATIVE_OPPORTUNITY"


class GreenlightDisposition(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    EXPIRE = "EXPIRE"
    SUPERSEDE = "SUPERSEDE"


class CanvasSeedScope(StrEnum):
    OPPORTUNITY_EXPLORATION = "OPPORTUNITY_EXPLORATION"


class EvidenceValidityState(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    INVALIDATED = "INVALIDATED"


class InvalidationState(StrEnum):
    PLANNED = "PLANNED"
    ERASING_PAYLOAD = "ERASING_PAYLOAD"
    PROPAGATING = "PROPAGATING"
    COMPLETE = "COMPLETE"
    NEEDS_OPERATOR = "NEEDS_OPERATOR"


class OpportunityReadPage(M9ContractModel):
    user_id: str
    project_name: str
    after_id: str | None
    limit: int = Field(default=50, ge=1, le=100)


class SnapshotReadPage(OpportunityReadPage):
    query_id: str


class OpportunityIdentityRead(M9ContractModel):
    user_id: str
    project_name: str
    identity: str
    revision: int | None = Field(default=None, ge=1)


class SourcePageRequest(M9ContractModel):
    user_id: str
    project_name: str
    attempt_id: str
    query_id: str
    query_revision: int = Field(ge=1)
    query_digest: Sha256Digest
    source_kind: Slug
    source_contract_version: str
    operation: Slug
    parameters: CanonicalJsonObject
    page_ordinal: int = Field(ge=1, le=20)
    cursor: str | None
    remaining_record_limit: int = Field(ge=1, le=1000)
    remaining_quota_units: int = Field(ge=0)
    credential_ref: str | None
    capability_grant_digest: Sha256Digest
    capability_evaluation_digest: Sha256Digest


class CapabilityEvaluationRequest(M9ContractModel):
    user_id: str
    project_name: str
    actor_id: str
    grant_id: str
    grant_version: int = Field(ge=1)
    grant_digest: Sha256Digest
    source_kind: Slug
    operation: Slug
    purpose: QueryIntent
    account_binding_digest: Sha256Digest | None


class SourcePageResult(M9ContractModel):
    provider_request_id: str | None
    next_cursor: str | None
    raw_payload: RawPageBytes
    raw_media_type: str
    source_native_ids: tuple[str, ...]
    data_classes: tuple[Slug, ...]
    returned_record_count: int = Field(ge=0)
    quota_units_observed: int | None = Field(default=None, ge=0)
    provider_observed_at: AwareDatetime | None
    terminal_page: bool


class ErasableEvidencePayload(M9ContractModel):
    user_id: str
    project_name: str
    attempt_id: str
    page_ordinal: int = Field(ge=1, le=20)
    evidence_kind: Slug
    raw_payload: RawPageBytes
    raw_media_type: str
    source_native_ids: tuple[str, ...]
    data_classes: tuple[Slug, ...]
    retain_digest_proof: bool


class PayloadRef(M9ContractModel):
    payload_ref: str
    payload_integrity_ref: str
    source_identity_refs: tuple[str, ...]
    retained_content_digest: Sha256Digest | None
    raw_size_bytes: int = Field(ge=0, le=2_097_152)


class PayloadDeletionRequest(M9ContractModel):
    user_id: str
    project_name: str
    invalidation_job_id: str
    payload_refs: tuple[str, ...]
    source_identity_refs: tuple[str, ...]
    payload_integrity_refs: tuple[str, ...]
    retain_permitted_digest_proofs: bool


class PayloadDeletionResult(M9ContractModel):
    erased_payload_refs: tuple[str, ...]
    erased_identity_refs: tuple[str, ...]
    erased_integrity_refs: tuple[str, ...]
    retained_proof_digests: tuple[Sha256Digest, ...]
    result_digest: Sha256Digest
    completed_at: AwareDatetime


class GreenlightSubject(M9ContractModel):
    user_id: str
    project_name: str
    actor_id: str
    candidate_id: str
    candidate_revision: int = Field(ge=1)
    candidate_payload_digest: Sha256Digest
    requested_disposition: GreenlightDisposition
    canvas_scope: CanvasSeedScope
    supersedes_decision_id: str | None
    reason: str
    requested_expires_at: AwareDatetime


class ProfilePublicationSubject(M9ContractModel):
    user_id: str
    project_name: str
    actor_id: str
    profile_id: str
    parent_revision: int | None
    payload_digest: Sha256Digest


class CustodianAuthorizationLease(M9ContractModel):
    authorization_id: str
    command_id: str
    authorized: bool
    subject_digest: Sha256Digest
    custodian_policy_id: str
    custodian_policy_version: str
    custodian_evidence_digest: Sha256Digest
    issued_at: AwareDatetime
    admit_not_after: AwareDatetime

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if not timedelta(0) < self.admit_not_after - self.issued_at <= timedelta(seconds=30):
            raise ValueError("lease admission window must be positive and at most 30 seconds")
        return self


class FactualEvidenceSubmission(M9ContractModel):
    command_id: str
    user_id: str
    project_name: str
    actor_id: str
    factual_scope: str
    selections: tuple[ResolvedFactualEvidenceSelection, ...]
    selection_closure_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_selections(self) -> Self:
        if not self.selections:
            raise ValueError("factual submission requires selections")
        return self


class FactualEvidenceReceipt(M9ContractModel):
    receipt_id: str
    source_record_refs: tuple[str, ...]
    evidence_record_refs: tuple[str, ...]
    result_digest: Sha256Digest
    committed_at: AwareDatetime


class FactualEvidenceInvalidation(M9ContractModel):
    command_id: str
    user_id: str
    project_name: str
    invalidation_job_id: str
    evidence_record_refs: tuple[str, ...]
    reason: str


class FactualInvalidationReceipt(M9ContractModel):
    receipt_id: str
    invalidated_evidence_refs: tuple[str, ...]
    result_digest: Sha256Digest
    committed_at: AwareDatetime


class M8LearningEvidenceRequest(M9ContractModel):
    user_id: str
    project_name: str
    evidence_refs: tuple[str, ...]


class M8LearningEvidenceEntry(M9ContractModel):
    ref: str
    kind: Literal["OBSERVATION", "RECOMMENDATION", "DECISION"]
    m8_digest: Sha256Digest
    state: Literal["CURRENT", "SUPERSEDED", "DISPOSED"]
    superseding_ref: str | None
    expires_at: AwareDatetime | None
    creative_profile_id: str
    creative_profile_version: str
    creative_policy_pack_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if (self.state == "CURRENT") != (self.superseding_ref is None):
            raise ValueError("non-current M8 evidence requires its superseding ref")
        if self.superseding_ref == self.ref:
            raise ValueError("M8 evidence cannot supersede itself")
        if self.kind == "DECISION" and self.state != "CURRENT":
            raise ValueError("M8 decisions remain current historical decision evidence")
        return self


class M8LearningEvidenceBundle(M9ContractModel):
    entries: tuple[M8LearningEvidenceEntry, ...]
    evidence_closure_digest: Sha256Digest
    earliest_expiry: AwareDatetime | None

    @model_validator(mode="after")
    def validate_expiry(self) -> Self:
        deadlines = [entry.expires_at for entry in self.entries if entry.expires_at is not None]
        if self.earliest_expiry != min(deadlines, default=None):
            raise ValueError("earliest expiry must recompute from all M8 entries")
        if len({entry.ref for entry in self.entries}) != len(self.entries):
            raise ValueError("M8 refs must be unique")
        return self


class M8CanvasSeedRequest(M9ContractModel):
    command_id: str
    user_id: str
    project_name: str
    actor_id: str
    greenlight_decision_id: str
    greenlight_binding_digest: Sha256Digest
    node_type: Literal["M9_OPPORTUNITY_SEED"]
    node_body: CanonicalJsonObject
    frozen_revision: CanonicalJsonObject  # the complete M8 ExplorationRevision frozen at prepare
    m8_append_command_id: str


class BridgeIntentState(StrEnum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    RECONCILED = "RECONCILED"
    CANCELLED_BY_INVALIDATION = "CANCELLED_BY_INVALIDATION"
    NEEDS_OPERATOR = "NEEDS_OPERATOR"


class BridgeIntent(M9ContractModel):
    intent_id: str
    intent_version: int = Field(ge=1)
    user_id: str
    project_name: str
    kind: Literal["CANVAS_SEED", "FACTUAL_SUBMISSION"]
    command_id: str
    request_digest: Sha256Digest
    frozen_request: CanonicalJsonObject
    frozen_request_digest: Sha256Digest
    closure_digest: Sha256Digest
    state: BridgeIntentState
    created_at: AwareDatetime
    updated_at: AwareDatetime


class M8CanvasSeedReceipt(M9ContractModel):
    m8_candidate_id: str
    m8_candidate_revision: int = Field(ge=1)
    m8_payload_digest: Sha256Digest
    result_digest: Sha256Digest
    committed_at: AwareDatetime


class PolicyDocumentEvidence(M9ContractModel):
    document_id: str
    canonical_url: str
    document_digest: Sha256Digest
    assessed_at: AwareDatetime
    effective_at: AwareDatetime | None
    expires_at: AwareDatetime


class SourceDataRule(M9ContractModel):
    data_class: Slug
    refresh_interval_seconds: int | None = Field(default=None, ge=1)
    retention_seconds: int | None = Field(default=None, ge=1)
    delete_on_revoke: bool
    digest_proof_may_be_retained: bool


class SourceCapabilityGrant(M9ContractModel):
    grant_id: str
    grant_version: int = Field(ge=1)
    user_id: str
    project_name: str
    source_kind: Slug
    source_contract_version: str
    account_binding_digest: Sha256Digest | None
    credential_ref: str | None
    allowed_operations: tuple[Slug, ...]
    allowed_purposes: tuple[QueryIntent, ...]
    permission: PermissionDisposition
    conditions: tuple[CanonicalJsonObject, ...]
    state: CapabilityState
    policy_documents: tuple[PolicyDocumentEvidence, ...]
    data_rules: tuple[SourceDataRule, ...]
    refresh_after: AwareDatetime
    deletion_deadline_seconds: int = Field(ge=1)
    issued_by: str
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    grant_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_permission(self) -> Self:
        if self.permission is PermissionDisposition.CONDITIONAL and not self.conditions:
            raise ValueError("conditional permission requires structured conditions")
        if self.permission is PermissionDisposition.PERMITTED and self.conditions:
            raise ValueError("permitted permission cannot carry unresolved conditions")
        if len({rule.data_class for rule in self.data_rules}) != len(self.data_rules):
            raise ValueError("grant data classes must be unique")
        if len({document.document_id for document in self.policy_documents}) != len(self.policy_documents):
            raise ValueError("grant policy documents must be unique")
        if not (self.allowed_operations and self.allowed_purposes and self.data_rules and self.policy_documents):
            raise ValueError("grant must bind operations, purposes, rules and policy documents")
        if self.expires_at <= self.issued_at or self.refresh_after <= self.issued_at:
            raise ValueError("grant deadlines must follow issue time")
        return self


class EffectiveCapabilityEvaluation(M9ContractModel):
    evaluation_id: str
    user_id: str
    project_name: str
    grant_id: str
    grant_version: int = Field(ge=1)
    grant_digest: Sha256Digest
    source_kind: Slug
    operation: Slug
    purpose: QueryIntent
    account_binding_digest: Sha256Digest | None
    effective_permission: PermissionDisposition
    condition_evidence: tuple[CanonicalJsonObject, ...]
    condition_evidence_digest: Sha256Digest
    evaluated_at: AwareDatetime
    expires_at: AwareDatetime
    evaluation_digest: Sha256Digest


class CohortSourceRule(M9ContractModel):
    source_kind: Slug
    required: bool
    allowed_intents: tuple[QueryIntent, ...]
    allowed_data_classes: tuple[Slug, ...]
    minimum_coverage: CoverageState
    maximum_age_seconds: int = Field(ge=1)
    compatibility_key: str

    @model_validator(mode="after")
    def validate_rule(self) -> Self:
        if self.minimum_coverage is CoverageState.UNAVAILABLE:
            raise ValueError("minimum coverage must be usable")
        if not self.allowed_intents or not self.allowed_data_classes:
            raise ValueError("source rule requires intents and data classes")
        return self


class CohortDimensionRule(M9ContractModel):
    dimension: OpportunityDimension
    required: bool
    transform_id: Slug
    transform_version: str
    calibration_ref: str
    missingness_policy: CanonicalJsonObject


class ReviewerQualificationRule(M9ContractModel):
    rubric_version: str
    languages: tuple[str, ...]
    cultural_cohort: Slug
    minimum_blind_reviewers: int = Field(ge=2)
    qualification_evidence_schema: CanonicalJsonObject


class OpportunityCohortProfilePayload(M9ContractModel):
    cohort_id: Slug
    cohort_version: str
    creative_profile_id: str
    creative_profile_version: str
    creative_policy_pack_digest: Sha256Digest
    source_rules: tuple[CohortSourceRule, ...]
    dimension_rules: tuple[CohortDimensionRule, ...]
    originality_corpus_refs: tuple[str, ...]
    originality_corpus_digest: Sha256Digest
    reviewer_qualification: ReviewerQualificationRule
    freshness_policy: CanonicalJsonObject
    candidate_expiry_seconds: int = Field(ge=1, le=86_400)

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        if self.creative_profile_id not in {"WESTERN_GENERIC", "CN_SHORT_DRAMA_SHUANGWEN", "arcreel.host"}:
            raise ValueError("unknown creative profile identity")
        if not any(rule.required for rule in self.dimension_rules):
            raise ValueError("profile requires a required dimension")
        for rows, keys in (
            (self.source_rules, [row.source_kind for row in self.source_rules]),
            (self.dimension_rules, [row.dimension for row in self.dimension_rules]),
        ):
            if len(set(keys)) != len(rows):
                raise ValueError("profile rule keys must be unique")
        if not self.originality_corpus_refs:
            raise ValueError("originality corpus is required")
        if self.reviewer_qualification.cultural_cohort != self.cohort_id:
            raise ValueError("reviewer rubric must belong to the profile cohort")
        return self


class OpportunityCohortProfile(M9ContractModel):
    profile_id: str
    revision: int = Field(ge=1)
    parent_revision: int | None
    user_id: str
    project_name: str
    payload: OpportunityCohortProfilePayload
    payload_digest: Sha256Digest
    profile_digest: Sha256Digest
    created_by: str
    custodian_authorization_id: str
    custodian_policy_id: str
    custodian_policy_version: str
    custodian_evidence_digest: Sha256Digest
    custodian_admitted_at: AwareDatetime
    created_at: AwareDatetime


class OpportunityCohortProfileHead(M9ContractModel):
    profile_id: str
    current_revision: int = Field(ge=1)
    head_version: int = Field(ge=1)


class SourceQuery(M9ContractModel):
    query_id: str
    revision: int = Field(ge=1)
    parent_revision: int | None
    user_id: str
    project_name: str
    source_kind: Slug
    source_contract_version: str
    operation: Slug
    intent: QueryIntent
    parameters: CanonicalJsonObject
    cohort_id: Slug
    cohort_version: str
    cohort_profile_id: str
    cohort_profile_revision: int = Field(ge=1)
    cohort_profile_digest: Sha256Digest
    capability_grant_id: str
    capability_grant_version: int = Field(ge=1)
    capability_grant_digest: Sha256Digest
    capability_evaluation_id: str
    capability_evaluation_digest: Sha256Digest
    credential_ref: str | None
    max_pages: int = Field(ge=1, le=20)
    max_records: int = Field(ge=1, le=1000)
    max_quota_units: int = Field(ge=0)
    query_digest: Sha256Digest
    created_by: str
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_parameters(self) -> Self:
        from r2.advanced_creative.digests import canonical_json_bytes

        if len(canonical_json_bytes(self.parameters)) > 65_536:
            raise ValueError("canonical query parameters exceed 64 KiB")
        return self


class SourceQueryHead(M9ContractModel):
    query_id: str
    current_revision: int = Field(ge=1)
    head_version: int = Field(ge=1)


class AcquisitionAttempt(M9ContractModel):
    attempt_id: str
    attempt_version: int = Field(ge=1)
    user_id: str
    project_name: str
    actor_id: str
    command_id: str
    request_digest: Sha256Digest
    query_id: str
    query_revision: int = Field(ge=1)
    query_digest: Sha256Digest
    page_cursor_digest: Sha256Digest | None
    state: AttemptState
    adapter_version: str
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    provider_request_id: str | None
    outcome_reason: AttemptOutcomeReason | None


class EvidenceDataClassClock(M9ContractModel):
    data_class: Slug
    captured_at: AwareDatetime  # database time when this page is accepted
    refresh_due_at: AwareDatetime | None
    retention_due_at: AwareDatetime | None

    @model_validator(mode="after")
    def validate_clock(self) -> Self:
        if any(
            deadline is not None and deadline <= self.captured_at
            for deadline in (self.refresh_due_at, self.retention_due_at)
        ):
            raise ValueError("data-class deadlines must follow their capture anchor")
        return self


class SnapshotPage(M9ContractModel):
    ordinal: int = Field(ge=1, le=20)
    request_cursor_digest: Sha256Digest | None
    response_cursor_digest: Sha256Digest | None
    provider_request_id: str | None
    payload_ref: str | None
    payload_integrity_ref: str | None
    retained_source_payload_digest: Sha256Digest | None
    raw_media_type: str | None
    raw_size_bytes: int = Field(ge=0, le=2_097_152)
    data_classes: tuple[Slug, ...]
    data_class_clocks: tuple[EvidenceDataClassClock, ...]
    record_count: int = Field(ge=0)
    captured_at: AwareDatetime
    missing_reason: MissingReason | None

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        if (self.payload_ref is None) != (self.payload_integrity_ref is None):
            raise ValueError("payload and integrity refs must be paired")
        if self.payload_ref is None and self.missing_reason is None:
            raise ValueError("absent page requires explicit missingness")
        if self.payload_ref is not None and self.missing_reason is not None:
            raise ValueError("page cannot be both present and missing")
        if self.payload_ref is None and (
            self.raw_size_bytes or self.record_count or self.retained_source_payload_digest
        ):
            raise ValueError("missing page cannot carry content proofs or counts")
        if len(self.data_class_clocks) != len(self.data_classes) or {
            clock.data_class for clock in self.data_class_clocks
        } != set(self.data_classes):
            raise ValueError("page clocks must uniquely cover every declared data class")
        if any(clock.captured_at != self.captured_at for clock in self.data_class_clocks):
            raise ValueError("class clocks must share database page capture time")
        return self


class SourceSnapshot(M9ContractModel):
    snapshot_id: str
    revision: int = Field(ge=1)
    parent_revision: int | None
    user_id: str
    project_name: str
    query_id: str
    query_revision: int = Field(ge=1)
    query_digest: Sha256Digest
    attempt_id: str
    source_kind: Slug
    source_contract_version: str
    source_identity_refs: tuple[str, ...]
    pages: tuple[SnapshotPage, ...]
    coverage_state: CoverageState
    requested_record_limit: int = Field(ge=1, le=1000)
    returned_record_count: int = Field(ge=0, le=1000)
    coverage_note: str
    provider_observed_at: AwareDatetime | None
    capture_started_at: AwareDatetime
    capture_completed_at: AwareDatetime
    adapter_version: str
    capability_grant_digest: Sha256Digest
    capability_evaluation_digest: Sha256Digest
    snapshot_digest: Sha256Digest
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if len(self.pages) > 20 or tuple(page.ordinal for page in self.pages) != tuple(range(1, len(self.pages) + 1)):
            raise ValueError("page ordinals must be contiguous and ordered from one")
        if (
            self.returned_record_count != sum(page.record_count for page in self.pages)
            or self.returned_record_count > self.requested_record_limit
        ):
            raise ValueError("snapshot counts must equal page counts within requested limit")
        if sum(page.raw_size_bytes for page in self.pages) > 41_943_040:
            raise ValueError("snapshot exceeds aggregate byte ceiling")
        if self.capture_completed_at < self.capture_started_at:
            raise ValueError("snapshot capture window must be ordered")
        if any(not self.capture_started_at <= page.captured_at <= self.capture_completed_at for page in self.pages):
            raise ValueError("page capture must be within snapshot capture window")
        return self


class SourceSnapshotHead(M9ContractModel):
    snapshot_id: str
    current_revision: int = Field(ge=1)
    head_version: int = Field(ge=1)


class NormalizedSourceObservation(M9ContractModel):
    observation_id: str
    revision: int = Field(ge=1)
    parent_revision: int | None
    user_id: str
    project_name: str
    snapshot_id: str
    snapshot_digest: Sha256Digest
    page_ordinal: int = Field(ge=1, le=20)
    source_kind: Slug
    source_identity_ref: str
    native_field_name: str
    native_field_definition: str
    native_field_version: str
    data_class: Slug
    value_ref: str | None
    value_integrity_ref: str | None
    retained_normalized_value_digest: Sha256Digest | None
    unit: str | None
    window_start: AwareDatetime | None
    window_end: AwareDatetime | None
    missing_reason: MissingReason | None
    payload_integrity_ref: str | None
    retained_source_payload_digest: Sha256Digest | None
    normalization_version: str
    observation_digest: Sha256Digest
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_value(self) -> Self:
        if (self.value_ref is None) != (self.value_integrity_ref is None):
            raise ValueError("native value and integrity refs must be paired")
        if (self.value_ref is None) != (self.missing_reason is not None):
            raise ValueError("observation requires a value pair or explicit missingness")
        if self.value_ref is None and self.retained_normalized_value_digest is not None:
            raise ValueError("missing native value cannot have a retained proof")
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("native window endpoints must be paired")
        if self.window_start is not None and self.window_end is not None and self.window_end < self.window_start:
            raise ValueError("native window must be ordered")
        return self


class SourceObservationHead(M9ContractModel):
    observation_id: str
    current_revision: int = Field(ge=1)
    head_version: int = Field(ge=1)


class DerivedOpportunitySignal(M9ContractModel):
    signal_id: str
    revision: int = Field(ge=1)
    parent_revision: int | None
    user_id: str
    project_name: str
    dimension: OpportunityDimension
    data_class: Slug
    cohort_id: Slug
    cohort_version: str
    cohort_profile_id: str
    cohort_profile_revision: int = Field(ge=1)
    cohort_profile_digest: Sha256Digest
    input_observation_ids: tuple[str, ...] = Field(min_length=1, max_length=10_000)
    input_closure_digest: Sha256Digest
    transform_id: Slug
    transform_version: str
    parameters: CanonicalJsonObject
    result_schema_version: str
    result_ref: str
    result_integrity_ref: str
    retained_signal_result_digest: Sha256Digest | None
    policy_basis_grant_ids: tuple[str, ...] = Field(min_length=1)
    policy_basis_digest: Sha256Digest
    applicability: CanonicalJsonObject
    exclusions: tuple[str, ...]
    signal_digest: Sha256Digest
    evaluated_by: str
    evaluated_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_expiry(self) -> Self:
        if self.expires_at <= self.evaluated_at:
            raise ValueError("signal expiry must follow evaluation")
        return self


class OpportunitySignalHead(M9ContractModel):
    signal_id: str
    current_revision: int = Field(ge=1)
    head_version: int = Field(ge=1)


class InvalidationOrigin(StrEnum):
    HUMAN_REQUEST = "HUMAN_REQUEST"
    RETENTION_SWEEP = "RETENTION_SWEEP"
    GRANT_REVOKED = "GRANT_REVOKED"
    M8_CORRECTION = "M8_CORRECTION"


class InvalidationSubject(M9ContractModel):
    user_id: str
    project_name: str
    actor_id: str
    source_kind: Slug
    snapshot_ids: tuple[str, ...]
    payload_refs: tuple[str, ...]
    m8_learning_evidence_refs: tuple[str, ...]
    factual_authority_evidence_refs: tuple[str, ...]
    capability_grant_id: str | None
    capability_grant_digest: Sha256Digest | None
    reason: str

    @model_validator(mode="after")
    def validate_targets(self) -> Self:
        if not (
            self.snapshot_ids
            or self.payload_refs
            or self.m8_learning_evidence_refs
            or self.factual_authority_evidence_refs
        ):
            raise ValueError("invalidation requires at least one target")
        return self


class InvalidationJob(M9ContractModel):
    invalidation_job_id: str
    job_version: int = Field(ge=1)
    user_id: str
    project_name: str
    origin: InvalidationOrigin
    origin_key: str
    source_kind: Slug
    snapshot_ids: tuple[str, ...]
    payload_refs: tuple[str, ...]
    m8_learning_evidence_refs: tuple[str, ...]
    factual_authority_evidence_refs: tuple[str, ...]
    capability_grant_id: str | None
    capability_grant_digest: Sha256Digest | None
    custodian_authorization_id: str | None
    custodian_policy_id: str | None
    custodian_policy_version: str | None
    custodian_evidence_digest: Sha256Digest | None
    custodian_admitted_at: AwareDatetime | None
    state: InvalidationState
    reason: str
    dependency_closure_digest: Sha256Digest | None
    erased_payload_count: int = Field(ge=0)
    invalidated_record_count: int = Field(ge=0)
    requested_at: AwareDatetime
    propagation_deadline: AwareDatetime
    updated_at: AwareDatetime
    operator_reason: str | None
    job_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_origin(self) -> Self:
        authority = (
            self.custodian_authorization_id,
            self.custodian_policy_id,
            self.custodian_policy_version,
            self.custodian_evidence_digest,
            self.custodian_admitted_at,
        )
        if self.origin is InvalidationOrigin.HUMAN_REQUEST:
            if any(value is None for value in authority):
                raise ValueError("Human invalidation requires complete custodian evidence")
        elif any(value is not None for value in authority):
            raise ValueError("system invalidation cannot carry Human authority")
        if self.origin is InvalidationOrigin.M8_CORRECTION:
            if self.capability_grant_id is not None or self.capability_grant_digest is not None:
                raise ValueError("M8 correction cannot carry a source capability grant")
        elif self.capability_grant_id is None or self.capability_grant_digest is None:
            raise ValueError("source invalidation requires the exact grant identity and digest")
        if self.updated_at < self.requested_at or self.propagation_deadline > self.requested_at + timedelta(hours=24):
            raise ValueError("invalidation times violate the frozen request and deadline")
        return self


class DimensionAssessment(M9ContractModel):
    dimension: OpportunityDimension
    signal_ids: tuple[str, ...]
    signal_closure_digest: Sha256Digest
    assessment_schema_version: str
    assessment_ref: str
    assessment_integrity_ref: str
    retained_assessment_digest: Sha256Digest | None
    calibration_ref: str


class SourceRuleSnapshotEvidence(M9ContractModel):
    snapshot_id: str
    snapshot_digest: Sha256Digest
    query_digest: Sha256Digest
    coverage_state: CoverageState
    oldest_capture_at: AwareDatetime
    usable_until: AwareDatetime


class CohortSourceEvidence(M9ContractModel):
    source_kind: Slug
    snapshots: tuple[SourceRuleSnapshotEvidence, ...]
    missing_reason: Literal["NO_SNAPSHOT_IN_CLOSURE"] | None
    result_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_missingness(self) -> Self:
        if bool(self.snapshots) != (self.missing_reason is None):
            raise ValueError("source evidence requires snapshots or explicit missingness")
        if len({row.snapshot_id for row in self.snapshots}) != len(self.snapshots):
            raise ValueError("snapshot identities must be unique")
        return self


class OpportunityPayload(M9ContractModel):
    title: str
    premise: str
    angle: str
    audience: CanonicalJsonObject
    creator_intent: CanonicalJsonObject
    cohort_id: Slug
    cohort_version: str
    cohort_profile_id: str
    cohort_profile_revision: int = Field(ge=1)
    cohort_profile_digest: Sha256Digest
    creative_content_digest: Sha256Digest
    assessments: tuple[DimensionAssessment, ...]
    source_rule_evidence: tuple[CohortSourceEvidence, ...]
    snapshot_ids: tuple[str, ...] = Field(max_length=100)
    signal_ids: tuple[str, ...] = Field(max_length=256)
    evidence_closure_digest: Sha256Digest
    m8_learning_evidence_refs: tuple[str, ...] = Field(max_length=32)
    unverified_claim_candidate_refs: tuple[str, ...]
    uncertainties: tuple[str, ...]
    open_questions: tuple[str, ...]


class OpportunityCandidateRevision(M9ContractModel):
    candidate_id: str
    revision: int = Field(ge=1)
    parent_revision: int | None
    supersedes_candidate_id: str | None
    user_id: str
    project_name: str
    payload: OpportunityPayload
    payload_digest: Sha256Digest
    lineage_digest: Sha256Digest
    created_by: str
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        if self.revision > 250 or self.supersedes_candidate_id == self.candidate_id:
            raise ValueError("candidate exceeds revision ceiling or supersedes itself")
        return self


class OpportunityCandidateHead(M9ContractModel):
    candidate_id: str
    current_revision: int = Field(ge=1)
    head_version: int = Field(ge=1)


class GreenlightDecision(M9ContractModel):
    decision_id: str
    decision_version: int = Field(ge=1)
    supersedes_decision_id: str | None
    user_id: str
    project_name: str
    candidate_id: str
    candidate_revision: int = Field(ge=1)
    candidate_payload_digest: Sha256Digest
    evidence_closure_digest: Sha256Digest
    freshness_policy_digest: Sha256Digest
    disposition: GreenlightDisposition
    canvas_scope: CanvasSeedScope
    issuer_id: str
    custodian_authorization_id: str
    custodian_policy_id: str
    custodian_policy_version: str
    custodian_evidence_digest: Sha256Digest
    custodian_admitted_at: AwareDatetime
    reason: str
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    binding_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if self.decision_version > 250 or self.supersedes_decision_id == self.decision_id:
            raise ValueError("decision exceeds version ceiling or supersedes itself")
        if self.expires_at <= self.issued_at:
            raise ValueError("decision expiry must follow issue time")
        if self.disposition is GreenlightDisposition.APPROVE and self.expires_at - self.issued_at > timedelta(hours=24):
            raise ValueError("approval TTL cannot exceed 24 hours")
        if (
            self.disposition in {GreenlightDisposition.EXPIRE, GreenlightDisposition.SUPERSEDE}
            and self.supersedes_decision_id is None
        ):
            raise ValueError("expiry or supersession must bind the exact prior decision")
        return self


class GreenlightHead(M9ContractModel):
    candidate_id: str
    current_decision_id: str
    head_version: int = Field(ge=1)


class GreenlightReceipt(M9ContractModel):
    command_id: str
    request_digest: Sha256Digest
    decision: GreenlightDecision
    result_digest: Sha256Digest
    committed_at: AwareDatetime


class CanvasSeedReceipt(M9ContractModel):
    command_id: str
    request_digest: Sha256Digest
    greenlight_decision_id: str
    greenlight_binding_digest: Sha256Digest
    m8_candidate_id: str
    m8_candidate_revision: int = Field(ge=1)
    m8_payload_digest: Sha256Digest
    result_digest: Sha256Digest
    committed_at: AwareDatetime


class EvidenceValidityProjection(M9ContractModel):
    state: EvidenceValidityState
    invalidation_job_id: str | None
    reason_code: str | None
    invalidated_at: AwareDatetime | None
    erasable_content_available: bool
    projection_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if self.state is EvidenceValidityState.INVALIDATED:
            if (
                self.erasable_content_available
                or self.invalidation_job_id is None
                or self.invalidated_at is None
                or self.reason_code is None
            ):
                raise ValueError("invalidated evidence requires a job, reason, time and unavailable content")
        elif self.invalidation_job_id is not None or self.invalidated_at is not None:
            raise ValueError("non-invalidated evidence cannot claim completed invalidation")
        return self


class SourceSnapshotView(M9ContractModel):
    snapshot: SourceSnapshot
    validity: EvidenceValidityProjection


class OpportunityCandidateView(M9ContractModel):
    candidate: OpportunityCandidateRevision
    validity: EvidenceValidityProjection


class GreenlightDecisionView(M9ContractModel):
    decision: GreenlightDecision
    validity: EvidenceValidityProjection


class CommandContext(M9ContractModel):
    command_id: str
    user_id: str
    project_name: str
    actor_id: str


class PublishOpportunityCohortProfile(M9ContractModel):
    context: CommandContext
    profile_id: str
    parent_revision: int | None
    expected_head_version: int | None
    payload: OpportunityCohortProfilePayload

    @model_validator(mode="after")
    def validate_append(self) -> Self:
        if (self.parent_revision is None) != (self.expected_head_version is None):
            raise ValueError("genesis requires null parent and head; append requires both")
        if self.parent_revision is not None and (
            self.parent_revision < 1 or self.expected_head_version is None or self.expected_head_version < 1
        ):
            raise ValueError("append versions must be positive")
        return self


class SourceQueryDraft(M9ContractModel):
    source_kind: Slug
    source_contract_version: str
    operation: Slug
    intent: QueryIntent
    parameters: CanonicalJsonObject
    cohort_id: Slug
    cohort_version: str
    cohort_profile_id: str
    cohort_profile_revision: int = Field(ge=1)
    cohort_profile_digest: Sha256Digest
    capability_grant_id: str
    capability_grant_version: int = Field(ge=1)
    capability_grant_digest: Sha256Digest
    capability_evaluation_id: str
    capability_evaluation_digest: Sha256Digest
    credential_ref: str | None
    max_pages: int = Field(ge=1, le=20)
    max_records: int = Field(ge=1, le=1000)
    max_quota_units: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_parameters(self) -> Self:
        from r2.advanced_creative.digests import canonical_json_bytes

        if len(canonical_json_bytes(self.parameters)) > 65_536:
            raise ValueError("canonical query parameters exceed 64 KiB")
        return self


class DeclareSourceQuery(M9ContractModel):
    context: CommandContext
    query_id: str
    parent_revision: int | None
    expected_head_version: int | None
    draft: SourceQueryDraft

    @model_validator(mode="after")
    def validate_append(self) -> Self:
        if (self.parent_revision is None) != (self.expected_head_version is None):
            raise ValueError("genesis requires null parent and head; append requires both")
        if self.parent_revision is not None and (
            self.parent_revision < 1 or self.expected_head_version is None or self.expected_head_version < 1
        ):
            raise ValueError("append versions must be positive")
        return self


class AcquireSourceQuery(M9ContractModel):
    context: CommandContext
    query_id: str
    query_revision: int = Field(ge=1)
    query_digest: Sha256Digest
    expected_query_head_version: int = Field(ge=1)


class BuildOpportunityCandidate(M9ContractModel):
    context: CommandContext
    candidate_id: str
    parent_revision: int | None
    expected_candidate_head_version: int | None
    payload: OpportunityPayload

    @model_validator(mode="after")
    def validate_append(self) -> Self:
        if (self.parent_revision is None) != (self.expected_candidate_head_version is None):
            raise ValueError("genesis requires null parent and head; append requires both")
        if self.parent_revision is not None and (
            self.parent_revision < 1
            or self.expected_candidate_head_version is None
            or self.expected_candidate_head_version < 1
        ):
            raise ValueError("append versions must be positive")
        return self


class DecideGreenlight(M9ContractModel):
    context: CommandContext
    candidate_id: str
    candidate_revision: int = Field(ge=1)
    candidate_payload_digest: Sha256Digest
    expected_candidate_head_version: int = Field(ge=1)
    expected_greenlight_head_version: int | None
    disposition: GreenlightDisposition
    canvas_scope: CanvasSeedScope
    reason: str
    requested_expires_at: AwareDatetime
    supersedes_decision_id: str | None


class SeedCanvasFromGreenlight(M9ContractModel):
    context: CommandContext
    decision_id: str
    greenlight_binding_digest: Sha256Digest
    expected_greenlight_head_version: int = Field(ge=1)


class FactualEvidenceSelection(M9ContractModel):
    snapshot_id: str
    snapshot_digest: Sha256Digest
    page_ordinal: int = Field(ge=1, le=20)
    source_identity_ref: str
    locator: str
    selected_content_ref: str
    selected_content_integrity_ref: str
    selected_content_digest: Sha256Digest
    evidence_type: str


class ResolvedFactualEvidenceSelection(FactualEvidenceSelection):
    selected_content: CanonicalJsonObject  # transient port-call payload; never persisted by M9


class SubmitFactualEvidence(M9ContractModel):
    context: CommandContext
    selections: tuple[FactualEvidenceSelection, ...]
    factual_scope: str

    @model_validator(mode="after")
    def validate_selections(self) -> Self:
        if not self.selections:
            raise ValueError("factual submission requires selections")
        return self


class InvalidateSourceEvidence(M9ContractModel):
    context: CommandContext
    source_kind: Slug
    snapshot_ids: tuple[str, ...]
    payload_refs: tuple[str, ...]
    m8_learning_evidence_refs: tuple[str, ...]
    factual_authority_evidence_refs: tuple[str, ...]
    capability_grant_id: str
    capability_grant_digest: Sha256Digest
    reason: str

    @model_validator(mode="after")
    def validate_targets(self) -> Self:
        if not (
            self.snapshot_ids
            or self.payload_refs
            or self.m8_learning_evidence_refs
            or self.factual_authority_evidence_refs
        ):
            raise ValueError("invalidation requires at least one target")
        return self


class SweepRetention(M9ContractModel):
    command_id: str  # UUIDv7; scoped system-command receipt key
    user_id: str
    project_name: str


class IntakeM8Correction(M9ContractModel):
    command_id: str  # UUIDv7; scoped system-command receipt key
    user_id: str
    project_name: str
    m8_superseded_ref: str
    m8_superseding_ref: str | None
    m8_disposition_ref: str | None


class QueryReceipt(M9ContractModel):
    command_id: str
    request_digest: Sha256Digest
    query: SourceQuery
    head: SourceQueryHead
    result_digest: Sha256Digest
    committed_at: AwareDatetime


class CohortProfileReceipt(M9ContractModel):
    command_id: str
    request_digest: Sha256Digest
    profile: OpportunityCohortProfile
    head: OpportunityCohortProfileHead
    result_digest: Sha256Digest
    committed_at: AwareDatetime


class AcquisitionReceipt(M9ContractModel):
    command_id: str
    request_digest: Sha256Digest
    attempt_id: str
    attempt_version: int = Field(ge=1)
    state: AttemptState
    snapshot_ids: tuple[str, ...]
    snapshot_digests: tuple[Sha256Digest, ...]
    result_digest: Sha256Digest
    committed_at: AwareDatetime


class CandidateReceipt(M9ContractModel):
    command_id: str
    request_digest: Sha256Digest
    candidate: OpportunityCandidateRevision
    head: OpportunityCandidateHead
    result_digest: Sha256Digest
    committed_at: AwareDatetime


class FactualBridgeReceipt(M9ContractModel):
    command_id: str
    request_digest: Sha256Digest
    selection_closure_digest: Sha256Digest
    factual_authority_receipt_id: str
    factual_source_record_refs: tuple[str, ...]
    factual_evidence_record_refs: tuple[str, ...]
    factual_authority_result_digest: Sha256Digest
    result_digest: Sha256Digest
    committed_at: AwareDatetime


class InvalidationReceipt(M9ContractModel):
    command_id: str
    request_digest: Sha256Digest
    invalidation_job_id: str
    state: InvalidationState
    dependency_closure_digest: Sha256Digest | None
    erased_payload_count: int = Field(ge=0)
    invalidated_record_count: int = Field(ge=0)
    propagation_deadline: AwareDatetime
    result_digest: Sha256Digest
    committed_at: AwareDatetime


# Resolve the cross-section factual selection reference after every shape exists.
for _model in tuple(globals().values()):
    if isinstance(_model, type) and issubclass(_model, M9ContractModel):
        _model.model_rebuild()
