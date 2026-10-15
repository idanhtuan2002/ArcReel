# R2-M9 Opportunity and Research Intelligence Design

**Status:** Proposed for independent design review on 2026-09-14. This document
does not authorize implementation, migrations, credentials, provider calls,
runtime activation, publication or production activity.

**Decision basis:** proposed ADR-0081 and
`docs/research/2026-09-14-r2-m9-opportunity-research-intelligence.md`.

**Design baseline:** ArcReel commit
`7d271f7833ed84a4b8a4aeee62c837a831a668c8`. This is research lineage, not M9
design or implementation acceptance.

**V2 revalidation (2026-10-15):** this design was revalidated against V2 commit
`23cf146a`, where the M8 implementation was accepted
(`docs/research/2026-10-15-r2-m9-prerequisite-path.md`). It still awaits
independent design review. The revalidation changes four things:

1. **Factual Authority gate.** The accepted durable Factual Authority is required
   at the M9-D release gate, not before M9-A. Only M9-D calls
   `FactualAuthorityPort`. M9-A to M9-C start from the accepted M8 implementation
   and the accepted M9 design.
2. **Creative profile identities.** Cohort profiles name creative profiles by the
   exact identities the M8 lineage carries (ADR-0105): `WESTERN_GENERIC` (label
   `generic-western`), `CN_SHORT_DRAMA_SHUANGWEN` (label `zh-shuang`), or the host
   profile `arcreel.host` for a project without an admitted screenplay.
3. **The Canvas seed.** The seed is created server-side under a lineage the server
   resolves (§12). It never passes through the client append route, which ADR-0107
   restricts to server-resolved episode lineages.
4. **Reviewers.** By sponsor decision, the two required author-independent,
   mutually blind design reviewers are fresh model agents. The review policy and
   the rubric are unchanged.

## 1. Goal and authority boundary

M9 adds an evidence-first Opportunity Intelligence module to the ArcReel host.
It turns declared source queries into immutable snapshots, source-native
observations, policy-bound opportunity signals, versioned opportunity candidates
and a Human Greenlight that may seed M8 Canvas exploration.

M9 owns:

- persisted immutable copies of consumed host-issued capability grants, declared queries,
  acquisition attempts and immutable snapshot metadata;
- append-only project-scoped opportunity cohort profiles and CAS heads;
- lossless normalized source observations and separately derived opportunity
  signals;
- `OpportunityCandidate` append-only revisions and CAS heads;
- Human Greenlight decisions and their current validity projection;
- deletion/invalidation traversal for M9-owned evidence; and
- narrow adapters to M8 Canvas, M8 Learning reads and Factual Authority.

M9 does not own credentials, token refresh, Factual Authority, ResearchPack or
Claim approval, M8 observations/recommendations, M8 promotion, Canon,
NarrativePlan, CreativePolicy, routing, production artifacts, ApprovedMaster,
quality disposition, publication or platform analytics ingestion.

The V2 lineage has an accepted M8 implementation (`23cf146a`) but no verified
durable Factual Authority service (FA-1 delivers it before M9-D). Design and
planning may continue. M9-A remains
`PACKET_AUTHORED_FOR_REVIEW` and `PACKET_EXECUTION_BLOCKED`: only its read-only
A0 preflight may run before exact accepted prerequisite evidence exists, and it
may emit an uncommitted stop receipt; no production-file creation may begin.

## 2. Deep-module shape and seams

The public Opportunity Intelligence interface is deliberately small:

```python
class OpportunityIntelligence(Protocol):
    async def publish_cohort_profile(self, command: PublishOpportunityCohortProfile) -> CohortProfileReceipt: ...
    async def declare_query(self, command: DeclareSourceQuery) -> QueryReceipt: ...
    async def acquire(self, command: AcquireSourceQuery) -> AcquisitionReceipt: ...
    async def build_candidate(self, command: BuildOpportunityCandidate) -> CandidateReceipt: ...
    async def decide_greenlight(self, command: DecideGreenlight) -> GreenlightReceipt: ...
    async def seed_canvas(self, command: SeedCanvasFromGreenlight) -> CanvasSeedReceipt: ...
    async def submit_factual_evidence(self, command: SubmitFactualEvidence) -> FactualBridgeReceipt: ...
    async def invalidate_source(self, command: InvalidateSourceEvidence) -> InvalidationReceipt: ...

class OpportunityIntelligenceReader(Protocol):
    async def list_capabilities(self, request: OpportunityReadPage) -> tuple[SourceCapabilityGrant, ...]: ...
    async def list_cohort_profiles(self, request: OpportunityReadPage) -> tuple[OpportunityCohortProfile, ...]: ...
    async def get_cohort_profile(self, request: OpportunityIdentityRead) -> OpportunityCohortProfile: ...
    async def get_query(self, request: OpportunityIdentityRead) -> SourceQuery: ...
    async def list_snapshots(self, request: SnapshotReadPage) -> tuple[SourceSnapshotView, ...]: ...
    async def get_snapshot(self, request: OpportunityIdentityRead) -> SourceSnapshotView: ...
    async def list_candidates(self, request: OpportunityReadPage) -> tuple[OpportunityCandidateView, ...]: ...
    async def get_candidate(self, request: OpportunityIdentityRead) -> OpportunityCandidateView: ...
    async def get_greenlight(self, request: OpportunityIdentityRead) -> GreenlightDecisionView | None: ...
```

Callers do not orchestrate pagination, canonical hashing, policy checks,
normalization, dependency closure, currentness, CAS, replay or invalidation.
Those behaviors stay behind this interface. Read interfaces expose scoped,
cursor-bounded immutable contracts and projections; they never return mutable
ORM rows. `after_id` is an opaque stable repository cursor; callers cannot infer
business recency from ID order, and explicit timestamps remain display truth.
List operations return one current head revision per logical identity, ordered
by the stable cursor. `get_*` with `revision=None` returns the current head;
supplying a revision returns that immutable historical revision plus any
applicable validity projection.

Internal seams exist only where behavior actually varies:

```python
class MarketSourcePort(Protocol):
    async def fetch_page(self, request: SourcePageRequest) -> SourcePageResult: ...

class SourceCapabilityPort(Protocol):
    async def resolve_grant(self, ref: str) -> SourceCapabilityGrant: ...
    async def evaluate(self, request: CapabilityEvaluationRequest) -> EffectiveCapabilityEvaluation: ...

class GreenlightCustodianPort(Protocol):
    async def authorize_decision(self, command_id: str, subject: GreenlightSubject) -> CustodianAuthorizationLease: ...

class OpportunityProfileCustodianPort(Protocol):
    async def authorize_publication(self, command_id: str, subject: ProfilePublicationSubject) -> CustodianAuthorizationLease: ...

class InvalidationCustodianPort(Protocol):
    async def authorize_invalidation(self, command_id: str, subject: InvalidationSubject) -> CustodianAuthorizationLease: ...

class FactualAuthorityPort(Protocol):
    async def submit_evidence(self, submission: FactualEvidenceSubmission) -> FactualEvidenceReceipt: ...
    async def invalidate_evidence(self, request: FactualEvidenceInvalidation) -> FactualInvalidationReceipt: ...

class M8LearningReadPort(Protocol):
    async def read_evidence(self, request: M8LearningEvidenceRequest) -> M8LearningEvidenceBundle: ...

class M8CanvasSeedPort(Protocol):
    async def create_seed(self, request: M8CanvasSeedRequest) -> M8CanvasSeedReceipt: ...

class SnapshotEvidenceStore(Protocol):
    async def put_if_absent(self, payload: ErasableEvidencePayload) -> PayloadRef: ...
    async def verify_and_read(self, payload_ref: str, integrity_ref: str) -> bytes: ...
    async def delete_exact(self, request: PayloadDeletionRequest) -> PayloadDeletionResult: ...
```

The host owns credential custody and capability issuance. M9 consumes opaque
references and never sees token material. The initial `ManualImportSource`
adapter and fixture `InMemorySnapshotEvidenceStore` make the seams real before
any network adapter is enabled.

## 3. Canonical vocabulary

- **Source capability grant:** host-issued, account/purpose-specific evidence
  that an adapter may perform named operations under named policy obligations.
- **Source query:** immutable declaration of what M9 intends to retrieve; it is
  not proof that the source universe is complete.
- **Acquisition attempt:** one durable identity for one possible external query
  execution or manual import.
- **Source snapshot:** immutable evidence of what was returned or imported under
  one exact query/attempt, including coverage and missingness.
- **Normalized source observation:** lossless representation of one provider-
  native field or metric with its original meaning intact.
- **Derived opportunity signal:** a separately versioned transformation over an
  exact input closure, permitted by a named policy basis.
- **Opportunity candidate:** an append-only creative/commercial opportunity
  proposal; factual claims inside it remain unverified unless Factual Authority
  says otherwise.
- **Greenlight:** a Human decision allowing one exact candidate and evidence
  closure to enter Canvas exploration.
- **Canvas seed:** the immutable M8 Canvas revision created from a current
  Greenlight. It is exploration history, not Production Truth.

## 4. Contract foundation

Public contracts are frozen, extra-field-forbid Pydantic v2 models. M9 reuses
the accepted M8 `M8ContractModel`, `CanonicalJsonObject` and `Sha256Digest`
implementation only after exact M8 implementation acceptance. If their module
path or semantics differ from the design assumption, stop with
`POST_M8_BASE_SEAM_CHANGED`; do not copy a divergent canonicalizer.

All IDs are repository-standard UUIDv7 strings. All timestamps are aware UTC.
All digests are lowercase `sha256:<64 hex>` over versioned canonical UTF-8 JSON
as implemented by the accepted shared canonical module. Contract values
are deep-frozen before hashing or persistence.

```python
from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Protocol

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from r2.contracts.advanced_creative import (
    CanonicalJsonObject,
    M8ContractModel,
    Sha256Digest,
)

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
RawPageBytes = Annotated[bytes, Field(max_length=2_097_152)]

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

class OpportunityReadPage(M8ContractModel):
    user_id: str
    project_name: str
    after_id: str | None
    limit: int = Field(default=50, ge=1, le=100)

class SnapshotReadPage(OpportunityReadPage):
    query_id: str

class OpportunityIdentityRead(M8ContractModel):
    user_id: str
    project_name: str
    identity: str
    revision: int | None = Field(default=None, ge=1)
```

Provider/source identities use versioned slug strings rather than a closed enum,
so a new adapter does not require a public schema change. The capability registry
still rejects unknown source/operation/schema-version combinations.

### 4.1 Fixed internal seam models

These models cross internal seams and are frozen even though they are not exposed
as HTTP contracts. `raw_payload` exists only in process between the source
adapter and erasable evidence store; it must never enter logs, events, command
receipts or PostgreSQL rows.

```python
class SourcePageRequest(M8ContractModel):
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

class CapabilityEvaluationRequest(M8ContractModel):
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

class SourcePageResult(M8ContractModel):
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

class ErasableEvidencePayload(M8ContractModel):
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

class PayloadRef(M8ContractModel):
    payload_ref: str
    payload_integrity_ref: str
    source_identity_refs: tuple[str, ...]
    retained_content_digest: Sha256Digest | None
    raw_size_bytes: int = Field(ge=0, le=2_097_152)

class PayloadDeletionRequest(M8ContractModel):
    user_id: str
    project_name: str
    invalidation_job_id: str
    payload_refs: tuple[str, ...]
    source_identity_refs: tuple[str, ...]
    payload_integrity_refs: tuple[str, ...]
    retain_permitted_digest_proofs: bool

class PayloadDeletionResult(M8ContractModel):
    erased_payload_refs: tuple[str, ...]
    erased_identity_refs: tuple[str, ...]
    erased_integrity_refs: tuple[str, ...]
    retained_proof_digests: tuple[Sha256Digest, ...]
    result_digest: Sha256Digest
    completed_at: AwareDatetime

class GreenlightSubject(M8ContractModel):
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

class ProfilePublicationSubject(M8ContractModel):
    user_id: str
    project_name: str
    actor_id: str
    profile_id: str
    parent_revision: int | None
    payload_digest: Sha256Digest

class CustodianAuthorizationLease(M8ContractModel):
    authorization_id: str
    command_id: str
    authorized: bool
    subject_digest: Sha256Digest
    custodian_policy_id: str
    custodian_policy_version: str
    custodian_evidence_digest: Sha256Digest
    issued_at: AwareDatetime
    admit_not_after: AwareDatetime

class FactualEvidenceSubmission(M8ContractModel):
    command_id: str
    user_id: str
    project_name: str
    actor_id: str
    factual_scope: str
    selections: tuple[ResolvedFactualEvidenceSelection, ...]
    selection_closure_digest: Sha256Digest

class FactualEvidenceReceipt(M8ContractModel):
    receipt_id: str
    source_record_refs: tuple[str, ...]
    evidence_record_refs: tuple[str, ...]
    result_digest: Sha256Digest
    committed_at: AwareDatetime

class FactualEvidenceInvalidation(M8ContractModel):
    command_id: str
    user_id: str
    project_name: str
    invalidation_job_id: str
    evidence_record_refs: tuple[str, ...]
    reason: str

class FactualInvalidationReceipt(M8ContractModel):
    receipt_id: str
    invalidated_evidence_refs: tuple[str, ...]
    result_digest: Sha256Digest
    committed_at: AwareDatetime

class M8LearningEvidenceRequest(M8ContractModel):
    user_id: str
    project_name: str
    evidence_refs: tuple[str, ...]

class M8LearningEvidenceEntry(M8ContractModel):
    ref: str
    kind: Literal["OBSERVATION", "RECOMMENDATION", "DECISION"]
    m8_digest: Sha256Digest
    state: Literal["CURRENT", "SUPERSEDED", "DISPOSED"]
    superseding_ref: str | None
    expires_at: AwareDatetime | None
    creative_profile_id: str
    creative_profile_version: str
    creative_policy_pack_digest: Sha256Digest

class M8LearningEvidenceBundle(M8ContractModel):
    entries: tuple[M8LearningEvidenceEntry, ...]
    evidence_closure_digest: Sha256Digest
    earliest_expiry: AwareDatetime | None

class M8CanvasSeedRequest(M8ContractModel):
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

class BridgeIntent(M8ContractModel):
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

class M8CanvasSeedReceipt(M8ContractModel):
    m8_candidate_id: str
    m8_candidate_revision: int = Field(ge=1)
    m8_payload_digest: Sha256Digest
    result_digest: Sha256Digest
    committed_at: AwareDatetime
```

Forward references are rebuilt after all contracts are declared. Adapters
deep-copy these values and reject token-like fields in parameters, page results
and exception details before any durable/logging path.

## 5. Fixed evidence contracts

```python
class PolicyDocumentEvidence(M8ContractModel):
    document_id: str
    canonical_url: str
    document_digest: Sha256Digest
    assessed_at: AwareDatetime
    effective_at: AwareDatetime | None
    expires_at: AwareDatetime

class SourceDataRule(M8ContractModel):
    data_class: Slug
    refresh_interval_seconds: int | None = Field(default=None, ge=1)
    retention_seconds: int | None = Field(default=None, ge=1)
    delete_on_revoke: bool
    digest_proof_may_be_retained: bool

class SourceCapabilityGrant(M8ContractModel):
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

class EffectiveCapabilityEvaluation(M8ContractModel):
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

class CohortSourceRule(M8ContractModel):
    source_kind: Slug
    required: bool
    allowed_intents: tuple[QueryIntent, ...]
    allowed_data_classes: tuple[Slug, ...]
    minimum_coverage: CoverageState
    maximum_age_seconds: int = Field(ge=1)
    compatibility_key: str

class CohortDimensionRule(M8ContractModel):
    dimension: OpportunityDimension
    required: bool
    transform_id: Slug
    transform_version: str
    calibration_ref: str
    missingness_policy: CanonicalJsonObject

class ReviewerQualificationRule(M8ContractModel):
    rubric_version: str
    languages: tuple[str, ...]
    cultural_cohort: Slug
    minimum_blind_reviewers: int = Field(ge=2)
    qualification_evidence_schema: CanonicalJsonObject

class OpportunityCohortProfilePayload(M8ContractModel):
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

class OpportunityCohortProfile(M8ContractModel):
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

class OpportunityCohortProfileHead(M8ContractModel):
    profile_id: str
    current_revision: int = Field(ge=1)
    head_version: int = Field(ge=1)

class SourceQuery(M8ContractModel):
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

class SourceQueryHead(M8ContractModel):
    query_id: str
    current_revision: int = Field(ge=1)
    head_version: int = Field(ge=1)

class AcquisitionAttempt(M8ContractModel):
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

class EvidenceDataClassClock(M8ContractModel):
    data_class: Slug
    captured_at: AwareDatetime  # database time when this page is accepted
    refresh_due_at: AwareDatetime | None
    retention_due_at: AwareDatetime | None

class SnapshotPage(M8ContractModel):
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

class SourceSnapshot(M8ContractModel):
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

class SourceSnapshotHead(M8ContractModel):
    snapshot_id: str
    current_revision: int = Field(ge=1)
    head_version: int = Field(ge=1)

class NormalizedSourceObservation(M8ContractModel):
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

class SourceObservationHead(M8ContractModel):
    observation_id: str
    current_revision: int = Field(ge=1)
    head_version: int = Field(ge=1)

class DerivedOpportunitySignal(M8ContractModel):
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
    input_observation_ids: tuple[str, ...]
    input_closure_digest: Sha256Digest
    transform_id: Slug
    transform_version: str
    parameters: CanonicalJsonObject
    result_schema_version: str
    result_ref: str
    result_integrity_ref: str
    retained_signal_result_digest: Sha256Digest | None
    policy_basis_grant_ids: tuple[str, ...]
    policy_basis_digest: Sha256Digest
    applicability: CanonicalJsonObject
    exclusions: tuple[str, ...]
    signal_digest: Sha256Digest
    evaluated_by: str
    evaluated_at: AwareDatetime
    expires_at: AwareDatetime

class OpportunitySignalHead(M8ContractModel):
    signal_id: str
    current_revision: int = Field(ge=1)
    head_version: int = Field(ge=1)

class InvalidationOrigin(StrEnum):
    HUMAN_REQUEST = "HUMAN_REQUEST"
    RETENTION_SWEEP = "RETENTION_SWEEP"
    GRANT_REVOKED = "GRANT_REVOKED"
    M8_CORRECTION = "M8_CORRECTION"

class InvalidationSubject(M8ContractModel):
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

class InvalidationJob(M8ContractModel):
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
```

`InvalidateSourceEvidence.m8_learning_evidence_refs` and the corresponding job
field contain upstream dependency inputs, not M8 deletion targets. An
M8/M12-owned append-only correction or disposition is the authority that
invalidates an M8 observation or recommendation. M9 reads that result through
`M8LearningReadPort`, locates dependent M9 signals and candidates, and
invalidates only its own closure; it has no M8 write port.

`SourceCapabilityGrant` is evidence consumed from the host; M9 cannot issue or
mutate it. `PermissionDisposition.CONDITIONAL` requires non-empty structured
`conditions` and is not executable permission: the resolver must prove every
condition and return an effective `PERMITTED` evaluation before acquisition or
derivation. `FORBIDDEN` is never executable but retains the named operations and
purposes it denies for auditable policy evaluation; `PERMITTED` has empty
conditions. Data-class rules are unique and are copied into snapshot/observation
retention evaluation; raw pages use the earliest applicable refresh/retention
deadline among their declared classes. A `None` refresh/retention interval means
the governing evidence explicitly imposes no elapsed-time limit of that kind; it
never means that policy research or the data-class rule is missing.

M9 enforces these deadlines itself; M9-B delivers the clocks and read/use
checks, and M9-E delivers system jobs and invalidation integration:

- **Anchor and calculation.** Each successfully finalized page freezes database
  `captured_at` at first acceptance, after external I/O. There is exactly one
  `EvidenceDataClassClock` per declared `data_class`; all anchors equal that
  page's `captured_at`. For its bound grant rule, `refresh_due_at = captured_at +
  refresh_interval_seconds` and `retention_due_at = captured_at + retention_seconds`;
  a `None` interval produces a `None` deadline. Missing rules are forbidden.
  Replay never resets clocks, and provider timestamps never anchor them. These
  fields and the bound grant/evaluation digests are covered by `snapshot_digest`.
- **Closure fold.** A raw page uses the minimum non-null refresh and retention
  deadline over all its classes. An observation uses its own class clock from
  its page. Signals, assessments, candidates, selections and decisions recursively
  take the minima over every input they actually consume. Unknown page/class
  lineage fails closed; an empty set of finite deadlines alone means no
  elapsed-time limit. No derived object starts a fresh retention interval.
  Effective operational expiry additionally includes profile maximum age,
  candidate expiry, grant `refresh_after`/`expires_at`, policy-document expiry and
  capability-evaluation expiry; Greenlight TTL cannot exceed this minimum.
- **Refresh expiry.** At database time `now >= refresh_due_at`, retained evidence
  remains available only as a historical `STALE` view. New normalization,
  derivation, candidate, approval or bridge admission fails `M9_EVIDENCE_STALE`.
  Refresh requires a new acquisition and immutable snapshot; neither rereading
  nor reevaluating the grant renews an old page's anchor. Grant refresh expiry
  also requires a new effective grant evaluation before further use.
- **Retention expiry.** At `now >= retention_due_at`, every content read/use
  refuses `M9_EVIDENCE_RETENTION_EXPIRED` before dereferencing the store, even if
  no sweep ran. Metadata-only history can return a `STALE` view with
  `erasable_content_available=False` before propagation starts; during a covering
  non-`COMPLETE` job it returns `M9_INVALIDATION_INCOMPLETE`, and after completion
  it returns `INVALIDATED`. No expired payload is served through a historical
  route. Retention deletion targets only classes whose policy requires erasure;
  dependent metadata/projections become non-authorizing.
- **Revocation.** Evaluation and the sweep query `SourceCapabilityPort` and
  persist the earliest database `revocation_detected_at` per exact grant
  identity/version/digest. A known revoked grant blocks every new operational
  use with `M9_SOURCE_CAPABILITY_UNAVAILABLE`; classes with `delete_on_revoke`
  additionally block payload access with `M9_EVIDENCE_RETENTION_EXPIRED` and
  enter deletion. Other classes keep only policy-permitted historical access.
  Until detection, reads enforce persisted elapsed deadlines. The host sweep
  runs at most 60 seconds apart when enabled, records last successful evaluation
  and lag, and stops new use of affected grants if that bound is exceeded.
- **Sweep and deletion deadline.** `SweepRetention` creates `RETENTION_SWEEP`
  jobs for expired classes and `GRANT_REVOKED` jobs for delete-on-revoke classes.
  The policy deletion deadline is the earliest triggering retention deadline or
  persisted revocation detection time, plus the bound grant's
  `deletion_deadline_seconds`. `propagation_deadline` is the earlier of that time
  and job `requested_at + 24 hours`. A late sweep never extends the deadline:
  an already overdue job enters `NEEDS_OPERATOR`, remains unreadable and retains
  the original deadline during remediation. Refresh expiry alone does not
  delete data. Exact origin-key deduplication and command replay follow §13.

The `(value_ref, value_integrity_ref)` pair resolves through
`SnapshotEvidenceStore` to one canonical object containing the native value,
source shape and qualifiers. The value is not inline in the append-only contract.
Normalization cannot add rankings, sentiment, ratios, category inference or
opportunity meaning.

## 6. Opportunity candidate and Greenlight contracts

```python
class DimensionAssessment(M8ContractModel):
    dimension: OpportunityDimension
    signal_ids: tuple[str, ...]
    signal_closure_digest: Sha256Digest
    assessment_schema_version: str
    assessment_ref: str
    assessment_integrity_ref: str
    retained_assessment_digest: Sha256Digest | None
    calibration_ref: str

class OpportunityPayload(M8ContractModel):
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
    snapshot_ids: tuple[str, ...]
    signal_ids: tuple[str, ...]
    evidence_closure_digest: Sha256Digest
    m8_learning_evidence_refs: tuple[str, ...]
    unverified_claim_candidate_refs: tuple[str, ...]
    uncertainties: tuple[str, ...]
    open_questions: tuple[str, ...]

class OpportunityCandidateRevision(M8ContractModel):
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

class OpportunityCandidateHead(M8ContractModel):
    candidate_id: str
    current_revision: int = Field(ge=1)
    head_version: int = Field(ge=1)

class GreenlightDecision(M8ContractModel):
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

class GreenlightHead(M8ContractModel):
    candidate_id: str
    current_decision_id: str
    head_version: int = Field(ge=1)

class GreenlightReceipt(M8ContractModel):
    command_id: str
    request_digest: Sha256Digest
    decision: GreenlightDecision
    result_digest: Sha256Digest
    committed_at: AwareDatetime

class CanvasSeedReceipt(M8ContractModel):
    command_id: str
    request_digest: Sha256Digest
    greenlight_decision_id: str
    greenlight_binding_digest: Sha256Digest
    m8_candidate_id: str
    m8_candidate_revision: int = Field(ge=1)
    m8_payload_digest: Sha256Digest
    result_digest: Sha256Digest
    committed_at: AwareDatetime

class EvidenceValidityProjection(M8ContractModel):
    state: EvidenceValidityState
    invalidation_job_id: str | None
    reason_code: str | None
    invalidated_at: AwareDatetime | None
    erasable_content_available: bool
    projection_digest: Sha256Digest

class SourceSnapshotView(M8ContractModel):
    snapshot: SourceSnapshot
    validity: EvidenceValidityProjection

class OpportunityCandidateView(M8ContractModel):
    candidate: OpportunityCandidateRevision
    validity: EvidenceValidityProjection

class GreenlightDecisionView(M8ContractModel):
    decision: GreenlightDecision
    validity: EvidenceValidityProjection
```

`OpportunityPayload.assessments` contains exactly one row for every required
dimension declared by the cohort profile and no duplicate dimensions. Score,
confidence, rationale, uncertainty and contraindications live together in the
versioned erasable assessment payload; the append-only candidate keeps its
schema/integrity ref and a digest only when every input rule permits retaining
that proof. V1 has no overall score. UI sorting may resolve one current,
unexpired assessment dimension but cannot persist a hidden weighted rank.

Title, premise, angle, audience and creator intent are project-owned creative
content. They may cite evidence refs but cannot copy provider-native identities,
titles, descriptions, comments, excerpts or retention-sensitive derived values.
Unverified factual material is represented by erasable evidence refs, never
inlined into the append-only candidate payload.

`get_greenlight` returns `GreenlightDecisionView` for current and historical
decisions. It returns `M9_INVALIDATION_INCOMPLETE` while a covering job is not
`COMPLETE`; a completed invalidation returns the immutable decision plus its
`INVALIDATED` projection. A bare historical `APPROVE` is never an authorization.

An invalidation never appends a `GreenlightDecision`: decisions are custodian
authority only. When an invalidation job covers a decision's evidence closure,
the decision's `EvidenceValidityProjection` becomes `INVALIDATED` bound to the
job, and every Greenlight, seed or bridge check that reads the decision refuses
an `INVALIDATED` projection. A Human `EXPIRE`/`SUPERSEDE` remains a custodian
decision.

Greenlight `APPROVE` has a maximum TTL of 24 hours or the earliest input,
capability-evaluation or grant expiry, whichever comes first. `REJECT`, `EXPIRE`
and `SUPERSEDE` are historical
decisions and do not authorize Canvas. A newer candidate revision never inherits
an older decision.

## 7. Fixed command and receipt contracts

Every public command carries one frozen scope/actor envelope. The authenticated
request principal must exactly equal `actor_id`; the server never accepts an
actor supplied independently of authentication. In the V2 host, `user_id` is
`CurrentUserInfo.id` (the data owner) and `actor_id` is `CurrentUserInfo.sub`
(the authenticated principal, also the ADR-0103 grant principal). Custodied
commands (profile publication, Greenlight, Human invalidation) are served only
through `get_current_interactive_user`; API keys and the auth-disabled anonymous
user cannot reach them. System commands (`SweepRetention`, `IntakeM8Correction`)
use the fixed actors `m9.retention-sweep` and `m9.m8-correction-intake`, are
invoked only by the host worker, never by HTTP, and create no custodian authority.

```python
class CommandContext(M8ContractModel):
    command_id: str
    user_id: str
    project_name: str
    actor_id: str

class PublishOpportunityCohortProfile(M8ContractModel):
    context: CommandContext
    profile_id: str
    parent_revision: int | None
    expected_head_version: int | None
    payload: OpportunityCohortProfilePayload

class SourceQueryDraft(M8ContractModel):
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

class DeclareSourceQuery(M8ContractModel):
    context: CommandContext
    query_id: str
    parent_revision: int | None
    expected_head_version: int | None
    draft: SourceQueryDraft

class AcquireSourceQuery(M8ContractModel):
    context: CommandContext
    query_id: str
    query_revision: int = Field(ge=1)
    query_digest: Sha256Digest
    expected_query_head_version: int = Field(ge=1)

class BuildOpportunityCandidate(M8ContractModel):
    context: CommandContext
    candidate_id: str
    parent_revision: int | None
    expected_candidate_head_version: int | None
    payload: OpportunityPayload

class DecideGreenlight(M8ContractModel):
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

class SeedCanvasFromGreenlight(M8ContractModel):
    context: CommandContext
    decision_id: str
    greenlight_binding_digest: Sha256Digest
    expected_greenlight_head_version: int = Field(ge=1)

class FactualEvidenceSelection(M8ContractModel):
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

class SubmitFactualEvidence(M8ContractModel):
    context: CommandContext
    selections: tuple[FactualEvidenceSelection, ...]
    factual_scope: str

class InvalidateSourceEvidence(M8ContractModel):
    context: CommandContext
    source_kind: Slug
    snapshot_ids: tuple[str, ...]
    payload_refs: tuple[str, ...]
    m8_learning_evidence_refs: tuple[str, ...]
    factual_authority_evidence_refs: tuple[str, ...]
    capability_grant_id: str
    capability_grant_digest: Sha256Digest
    reason: str
    requested_at: AwareDatetime

class SweepRetention(M8ContractModel):
    command_id: str  # UUIDv7; scoped system-command receipt key
    user_id: str
    project_name: str

class IntakeM8Correction(M8ContractModel):
    command_id: str  # UUIDv7; scoped system-command receipt key
    user_id: str
    project_name: str
    m8_superseded_ref: str
    m8_superseding_ref: str | None
    m8_disposition_ref: str | None

class QueryReceipt(M8ContractModel):
    command_id: str
    request_digest: Sha256Digest
    query: SourceQuery
    head: SourceQueryHead
    result_digest: Sha256Digest
    committed_at: AwareDatetime

class CohortProfileReceipt(M8ContractModel):
    command_id: str
    request_digest: Sha256Digest
    profile: OpportunityCohortProfile
    head: OpportunityCohortProfileHead
    result_digest: Sha256Digest
    committed_at: AwareDatetime

class AcquisitionReceipt(M8ContractModel):
    command_id: str
    request_digest: Sha256Digest
    attempt_id: str
    attempt_version: int = Field(ge=1)
    state: AttemptState
    snapshot_ids: tuple[str, ...]
    snapshot_digests: tuple[Sha256Digest, ...]
    result_digest: Sha256Digest
    committed_at: AwareDatetime

class CandidateReceipt(M8ContractModel):
    command_id: str
    request_digest: Sha256Digest
    candidate: OpportunityCandidateRevision
    head: OpportunityCandidateHead
    result_digest: Sha256Digest
    committed_at: AwareDatetime

class FactualBridgeReceipt(M8ContractModel):
    command_id: str
    request_digest: Sha256Digest
    selection_closure_digest: Sha256Digest
    factual_authority_receipt_id: str
    factual_source_record_refs: tuple[str, ...]
    factual_evidence_record_refs: tuple[str, ...]
    factual_authority_result_digest: Sha256Digest
    result_digest: Sha256Digest
    committed_at: AwareDatetime

class InvalidationReceipt(M8ContractModel):
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
```

Genesis requires `parent_revision is None` and
`expected_*_head_version is None`; append requires both non-null and exact.
`supersedes_candidate_id` is permitted only on candidate genesis and cannot
equal the new candidate ID; every later revision preserves it exactly.
Empty factual selections, invalidation target lists, reasons and Canvas/factual
scopes are rejected. Tuples that participate in closure hashes are canonicalized
and duplicate-free; caller order never changes identity unless the contract says
page order is semantically significant.

`requested_expires_at` is an upper bound. The server computes the effective
Greenlight expiry from the 24-hour maximum and earliest evidence/grant expiry.
The authenticated Human cannot lengthen evidence freshness by requesting a later
time.

### 7.1 Normative cross-field validation

- Reference tuples are sorted and unique unless order is explicitly semantic.
  Empty tuples are allowed only for a zero-result/missing page or snapshot, an
  optional M8 evidence family, a failed acquisition receipt, or an erasure result
  with zero members of that class. `SourceSnapshot.pages` is order-sensitive; ordinals
  begin at one, are contiguous, and match tuple order. Commands that submit
  factual evidence or invalidate evidence require at least one total target.
- Grant operations, purposes, policy documents and data classes are unique.
  At operation time, an effective `ENABLED` evaluation requires unexpired
  documents, `refresh_after` still in the future, at least one applicable
  operation/purpose/data rule and effective permission. Historical expired
  grants remain parseable evidence. Credential-ref and account-binding presence
  must match the adapter declaration.
- Cohort-profile source kinds and dimensions are unique. At least one dimension
  is required. The profile payload digest and envelope digest must recompute;
  genesis/append lineage and Human profile-custodian authorization/policy/
  evidence identity must be exact.
  Changing profile content creates a new revision. It is an M9 schema change
  only when the profile contract or a digest domain changes, not when a valid
  profile revision changes its governed values.
- Query credential ref, source, operation, purpose and scope must exactly match
  both the consumed grant and an unexpired effective capability evaluation. Its
  cohort/profile identity, revision and digest must resolve to one current
  published profile whose source rule permits the query intent and data classes.
  Query parent/head nullability follows genesis/append rules.
- Snapshot page count, record count and byte totals equal their page rows and
  stay inside both query and V1 ceilings. Capture completion is not before start;
  provider-observed time may differ and is never substituted for capture time.
  Page data-class clocks are unique, exactly cover the declared classes and
  recompute from database capture time plus the bound grant's rules. Every
  observation's `page_ordinal` resolves to its exact snapshot page and class.
- Identity, payload and integrity refs are random opaque identifiers with no raw
  provider value embedded. A retained source-payload digest is present if and only if every
  applicable data-class rule permits it; otherwise only the erasable integrity
  ref is persisted in the append-only row.
- An observation has either a complete `(value_ref, value_integrity_ref)` pair or
  a `missing_reason`, never both. A retained normalized-value digest is allowed only by its
  data-class rule. Its window is ordered and its `data_class` exists in the bound
  grant. Corrections cannot point to self and preserve source identity.
- Signal input refs are non-empty and their recomputed closure/policy digests
  match. Evaluation precedes expiry. The erasable result payload schema keeps
  result and uncertainty separate and its retained digest follows every input
  data-class rule.
- Candidate assessments have unique dimensions and exactly match the required
  cohort profile set. Every assessment signal belongs to its dimension and
  cohort. Candidate snapshot/signal/M8 refs recompute to the payload closure.
- `APPROVE` requires no current approval unless it explicitly supersedes it.
  `EXPIRE`/`SUPERSEDE` require the exact prior decision; `REJECT` cannot
  authorize Canvas. Decision issue precedes effective expiry.
- Profile, Greenlight and invalidation authorization leases recompute `subject_digest` from
  the exact request subject. A lease must bind the exact command and custodian
  policy identity/version, be admitted no later than `admit_not_after`, and have
  a window no longer than 30 seconds. A lease for any other actor, scope,
  candidate, profile payload or disposition is unusable.
- Every receipt recomputes its request/result digest and exactly matches the
  committed identities. Empty reasons, locators, scopes, identifiers and
  human-visible titles/premises are rejected after Unicode normalization.

## 8. Canonical digest domains

Every hash input begins with a domain tag and schema version. Server-assigned
receipt IDs/timestamps are excluded from request digests and included in result
digests.

| Digest | Exact semantic coverage |
|---|---|
| `grant_digest` | `m9.capability-grant.v1`, scope, source/schema, account binding, credential ref, operations, purposes, permission/conditions/state, ordered policy-document identities/digests, data-class refresh/retention/deletion rules, grant identity/version, all policy-document fields, `refresh_after`, `deletion_deadline_seconds`, issuer, issue time and expiry (all grant fields except `grant_digest`) |
| `evaluation_digest` | `m9.capability-evaluation.v1`, scope/actor, exact grant identity/version/digest, source/operation/purpose/account binding, effective permission, ordered condition evidence/digest, evaluated time and expiry |
| cohort-profile `payload_digest` | `m9.cohort-profile-payload.v1` plus the entire frozen `OpportunityCohortProfilePayload` |
| `profile_digest` | `m9.cohort-profile.v1`, scope, profile identity/revision/parent, payload digest, creator identity, custodian authorization/policy/evidence identity, admitted time and creation time |
| `query_digest` | `m9.source-query.v1`, scope, source/schema/operation, intent, canonical parameters, exact cohort-profile identity/revision/digest, exact grant and capability-evaluation identities/digests, opaque credential ref, page/record/quota budgets |
| `snapshot_digest` | `m9.source-snapshot.v1`, scope, exact query/attempt, opaque source-identity refs in canonical order, ordered page metadata/integrity refs/permitted retained proof digests, coverage/missingness, capture/provider times, adapter version, grant digest and `capability_evaluation_digest`; all snapshot fields except `snapshot_digest`, including persisted page data-class clocks |
| `observation_digest` | `m9.source-observation.v1`, scope, data class, snapshot/digest/page ordinal, opaque source-identity ref, native field/definition/version, erasable value/integrity refs, permitted retained normalized-value digest, unit/window/missingness, payload-integrity ref, permitted retained source-payload digest and normalization version |
| `input_closure_digest` | `m9.signal-input-closure.v1` plus sorted `(observation_id, observation_digest)` tuples and correction heads |
| `signal_digest` | `m9.opportunity-signal.v1`, scope/cohort, data class, exact cohort-profile identity/revision/digest, dimension, exact input closure, transform/version/parameters, erasable result schema/ref/integrity, permitted retained signal-result digest, policy basis, applicability/exclusions and expiry |
| `evidence_closure_digest` | `m9.candidate-evidence-closure.v1` plus sorted snapshot, signal and M8-learning evidence identities, digests, current revisions/states and expiries; M8 entries bind `(creative_profile_id, creative_profile_version, creative_policy_pack_digest)`, which must equal the bound cohort profile's full creative-policy tuple or the closure is refused with `M9_COHORT_LEAKAGE` |
| `creative_content_digest` | `m9.creative-content.v1`, exact title, premise, angle, audience and creator intent; it excludes provider-native or retention-sensitive evidence values |
| `payload_digest` | `m9.opportunity-payload.v1` plus the entire frozen `OpportunityPayload` |
| `lineage_digest` | `m9.opportunity-lineage.v1`, candidate/revision/parent/superseded candidate, payload digest, scope, exact cohort-profile identity/revision/digest and evidence closure |
| profile-publication `subject_digest` | `m9.profile-publication-subject.v1`, exact user/project/actor, profile identity/parent and profile-payload digest |
| Greenlight `subject_digest` | `m9.greenlight-subject.v1`, exact user/project/actor, candidate identity/revision/payload, requested disposition, Canvas scope, superseded decision, reason and requested expiry |
| `command_guard_key` | `m9.command-key-guard.v1`, exact user/actor/operation/command tuple; first eight SHA-256 bytes become two signed big-endian 32-bit PostgreSQL advisory-lock integers and never become identity or evidence |
| `binding_digest` | `m9.greenlight-binding.v1`, scope, candidate/revision/payload, evidence/freshness closure, disposition, Canvas scope, issuer, custodian authorization/policy/evidence identity, admitted time, reason, issued time, expiry and supersession |
| `projection_digest` | `m9.evidence-validity-projection.v1`, scope, logical identity/revision, validity state, invalidation job/reason/time and content-availability flag |
| `job_digest` | `m9.invalidation-job.v1`, scope, origin and origin key, source, exact target refs, grant identity/digest when present, custodian authorization/policy/evidence/admitted time when present, version/state/reason, dependency closure, counts, request/deadline/update times and qualified operator reason |
| invalidation `subject_digest` | `m9.invalidation-subject.v1` plus the entire frozen `InvalidationSubject` |
| `frozen_request_digest` | `m9.bridge-frozen-request.v1`, intent kind and the canonical frozen request (for a seed, the complete M8 `ExplorationRevision` and the M8 append command id; for a factual submission, the selections as evidence-store refs and digests) |
| M8 entry closure in `evidence_closure_digest` | each M8 entry contributes `(ref, kind, m8_digest, state, superseding_ref, expires_at, creative_profile_id, creative_profile_version, creative_policy_pack_digest)` |
| `condition_evidence_digest` | `m9.capability-condition-evidence.v1`, exact grant identity/version/digest and the ordered canonical `condition_evidence` objects |
| `policy_basis_digest` | `m9.signal-policy-basis.v1` plus sorted `(grant_id, grant_version, grant_digest, evaluation_id, evaluation_digest)` tuples for every grant named in `policy_basis_grant_ids` |
| `signal_closure_digest` | `m9.assessment-signal-closure.v1` plus sorted `(signal_id, revision, signal_digest)` tuples of the assessment's `signal_ids` |
| `freshness_policy_digest` | `m9.greenlight-freshness-policy.v1`, the bound cohort profile identity/revision/digest, its canonical `freshness_policy`, and the evaluated earliest expiry over the evidence closure |
| `selected_content_digest` | `m9.factual-selected-content.v1`, snapshot identity/digest, page ordinal, source-identity ref, locator, evidence type, selected-content ref/integrity ref and the canonical selected content resolved through `SnapshotEvidenceStore` |
| `selection_closure_digest` | `m9.factual-selection-closure.v1`, factual scope and sorted `(snapshot_id, snapshot_digest, page_ordinal, source_identity_ref, locator, selected_content_ref, selected_content_integrity_ref, selected_content_digest, evidence_type)` tuples |
| receipt `request_digest` | `m9.command-request.v1`, operation, the full `(user_id, actor_id, operation, command_id)` tuple and the canonical command body; server-assigned ids and times are excluded |
| receipt `result_digest` | `m9.command-result.v1`, operation, `request_digest` and the canonical receipt body without `result_digest`; server-assigned ids and times are included |
| `dependency_closure_digest` | `m9.invalidation-dependency-closure.v1`, scope, job identity and sorted `(record_kind, logical_id, revision, digest, dependency_refs)` tuples at every traversed layer, including bridge intents/receipts and Factual invalidation receipts; job progress fields are excluded to avoid self-reference |
| BridgeIntent `closure_digest` | `m9.bridge-closure.v1`, scope, intent kind, exact candidate/decision/profile and evidence or selection closure digests plus their frozen dependency refs |
| BridgeIntent `request_digest` | the originating `m9.command-request.v1` digest verbatim; the downstream seed/submission request is covered by `frozen_request_digest` |
| M8LearningEvidenceBundle `evidence_closure_digest` | `m9.m8-learning-evidence-closure.v1`, scope and sorted complete M8 entry tuples defined by the M8-entry-closure row; earliest expiry is recomputed from those entries |
| cursor digests | `m9.page-cursor.v1`, scope, query identity/revision/digest, adapter version and canonical cursor value; the same cursor has the same digest in an attempt and a page, first/terminal absence is null; sensitive cursor bytes stay erasable and sources forbidding retained cursor proof are refused |
| system-command `request_digest` / `result_digest` | `m9.system-command-request.v1` / `m9.system-command-result.v1`, exact scoped system receipt key and canonical command or result body excluding its own digest; only the result covers server-frozen times |

Digests produced by a port (`PayloadDeletionResult.result_digest`,
`FactualEvidenceReceipt.result_digest`, `M8CanvasSeedReceipt.result_digest`,
`m8_payload_digest`, `custodian_evidence_digest`) belong to the port owner's
domain. M9 stores them verbatim and never recomputes them under an M9 tag.

Raw payload deletion does not change an old snapshot digest. Source identities,
raw bytes and integrity digests subject to erasure live behind random opaque
identity/payload/integrity refs in the erasable store. A retained content digest is
populated only when the exact data-class rule permits keeping a non-reversible
proof after deletion; otherwise the digest exists only behind the erasable
integrity ref. A correction or invalidation record becomes the current evidence
head and blocks use of the old snapshot. Sources that forbid even the retained
opaque audit refs required by this contract are incompatible and fail with
`M9_SOURCE_POLICY_FORBIDDEN` before acquisition.

`PayloadRef.retained_content_digest` is the evidence-store's generic return
name. Typed contracts name the same value by semantic class:
`retained_source_payload_digest`, `retained_normalized_value_digest`,
`retained_signal_result_digest` or `retained_assessment_digest`. The typed value
must byte-equal the store result and is never recomputed under a second domain.

Interactive receipts intentionally omit `project_name` from their unique
`(user_id, actor_id, operation, command_id)` key: project remains in the canonical
request body. Reusing a command UUID across projects by the same owner/principal
and operation is a replay conflict, never a cross-project receipt disclosure.
System receipts use the separate scoped key in §13.

## 9. Command idempotency and CAS

Every interactive mutation accepts an actor-scoped `command_id` and computes a request
digest. System commands use the separate §13 key. The interactive durable key is `(user_id, actor_id, operation, command_id)`; the full
tuple plus request digest remains authority.

1. A receipt preflight reads the full key without currentness checks. Same key
   and request digest returns the original completed receipt immediately; same
   key and a different digest returns `M9_COMMAND_REPLAY_CONFLICT`.
2. Only an absent receipt may proceed to required external I/O. Custodian
   authorization is called outside a database transaction and is replayed by
   the exact command ID and subject digest. Simultaneous first calls and a crash
   after authorization may repeat transport, so the custodian operation must be
   duplicate-safe and return the same still-valid lease; changed-subject replay
   fails closed.
3. Finalization opens one transaction and first acquires a PostgreSQL
   transaction-scoped advisory guard. Canonicalize
   `m9.command-key-guard.v1` plus the full command tuple, SHA-256 it, interpret
   the first eight bytes as two signed big-endian 32-bit integers, and pass them
   to `pg_advisory_xact_lock`. Hash collision may serialize unrelated commands
   but cannot authorize or identify a receipt.
4. Under the guard, M9 re-reads the full receipt key. A concurrently committed
   equal digest returns the original receipt; a different digest conflicts. Only
   an absent receipt continues.
5. M9 validates the exact authorization lease, records database time as
   `custodian_admitted_at`, requires admission no later than `admit_not_after`
   and a lease window no longer than 30 seconds, then revalidates scope, grants,
   current heads, evidence closure and expected versions.
6. The mutation, head CAS, event and command receipt commit atomically. A crash
   before commit leaves none of them; loss of the commit acknowledgement is
   resolved by receipt preflight without external I/O.

**Host custodian (decided 2026-10-15).** The profile and Greenlight custodians are
one host adapter over the ADR-0103 governance grants:

- **When it issues a lease.** It issues a `CustodianAuthorizationLease` only to an
  interactive session whose principal (`actor_id`) holds a current
  `HUMAN_SHOWRUNNER` grant for `GrantScopeV1(user_id, project_name, principal=actor_id)`,
  read through `CurrentShowrunnerGrantReader`. It serves profile publication,
  Greenlight and Human invalidation.
- **Policy identity.** `custodian_policy_id` is `arcreel.showrunner-grant` and
  `custodian_policy_version` is the grant schema version
  (`governance.showrunner_grant_event.v1`). M9 compares both with these fixed
  expected values.
- **Evidence.** `custodian_evidence_digest` is the grant event digest.
- **Replay state.** Leases are stored durably by the host in
  `host_custodian_leases`, unique on `(user_id, project_name, actor_id,
  operation, command_id)` with the subject digest stored, so replay returns the
  same lease and a changed subject is refused.
- **Bounds.** `admit_not_after` is at most 30 seconds after issue and never later
  than the grant's `expires_at`. Unlike ADR-0103 services, which recheck the grant
  under their own locks, M9 admits the bounded lease inside the transaction. That
  trade-off is deliberate: the lease window is short, and the grant is revalidated
  when the lease is issued. M9-A delivers the adapter and its
  table because profile publication needs it first; M9-D reuses it.

The host-owned custodian defines an issued lease as authorizing the one exact
command until `admit_not_after`; later policy changes prevent new leases but do
not reinterpret an already admitted transaction. If the host cannot provide
this bounded, replayable guarantee, M9 stops with the applicable unauthorized
code. An expired unadmitted lease is not refreshed under the same command ID;
the Human must authorize a new command. A denial is not an authorizing lease and
produces no authority mutation.

`current_revision` is the immutable logical revision selected by a head;
`head_version` is the mutable row CAS. Appending revision N+1 requires both
`parent_revision == current_revision` and `expected_head_version == head_version`,
then increments each by one. Decision heads have an independent CAS because a
decision may expire/supersede without changing candidate content.

Global lock rank is normative whenever a transaction touches more than one row:

1. transaction-scoped command-key advisory guard, then command receipt;
1a. **From M9-E onward**, project invalidation guard: `pg_advisory_xact_lock` (exclusive) for a
    transaction that starts or advances an invalidation job, and
    `pg_advisory_xact_lock_shared` for every transaction that creates or uses a
    dependent of erasable evidence: acquisition finalize (observations), signal
    derivation, candidate append, `decide_greenlight`, `seed_canvas` and
    `submit_factual_evidence` prepare/finalize, and each bridge-intent
    `PENDING -> DISPATCHED` transition. Under the shared guard such a
    transaction refuses any input covered by a non-`COMPLETE` job with
    `M9_INVALIDATION_INCOMPLETE`. The key is
    `m9.invalidation-guard.v1` over `(user_id, project_name)`, derived like the
    command guard. An approval or bridge step therefore never interleaves with the
    start of an invalidation of its closure;
2. source capability/policy evidence, ordered by ID;
3. opportunity cohort-profile head;
4. source query head;
5. acquisition attempt;
6. snapshot/correction head, ordered by ID;
7. observation and signal correction heads, ordered by type then ID;
8. opportunity candidate head;
9. Greenlight head;
10. bridge intent, then Canvas-seed or Factual-bridge receipt;
11. invalidation job, then its dependency edges ordered by ID.

M9-B/C/D implement elapsed-time freshness/retention and grant checks without
querying future invalidation tables. They are accepted intermediate packets;
source invalidation routes/workers are unavailable until M9-E. M9-E owns the
rank-1a guard, non-COMPLETE-job coverage checks and regression tests in
`acquisition.py`, `signals.py`, `candidates.py`, `greenlight.py`, `bridges.py`
and all applicable readers. Its migration creates job/edge/projection tables,
backfills dependencies from accepted metadata under an exclusive project guard,
and installs every integration check before any invalidation entry point is
enabled. Before E, views derive CURRENT/STALE from existing clocks/correction
heads without future-table queries. Final M9 acceptance requires E's integrated
guarantee; intermediate packets do not authorize production activation.

Transactions acquire only the ranks they need, always ascending and with IDs
sorted lexicographically inside a rank. No database transaction spans provider,
model, filesystem, evidence-store, custodian or M8/Factual port I/O.

## 10. Acquisition protocol and recovery

`declare_query` validates source/operation/schema against the adapter registry,
resolves the exact host grant and effective capability evaluation, rejects token
material, freezes parameters and appends a query revision. Acquisition
re-evaluates current capability before every external page; a changed evaluation
does not rewrite the query and instead stops or requires a new query revision.

`acquire` runs as prepare / I/O / finalize:

1. transaction under the §9 command guard: receipt preflight, then the
   attempt lookup by the full command key `(user_id, actor_id, "acquire",
   command_id)` (unique on the attempt table). An existing attempt with the same
   `request_digest` is returned as is and no new provider call starts; a
   different digest is `M9_COMMAND_REPLAY_CONFLICT`. Only an absent attempt
   continues to query/grant/currentness validation and the commit of
   `AcquisitionAttempt(PLANNED)` bound to that key. Concurrent first calls
   serialize on the guard, so at most one attempt exists per command;
2. outside transaction: mark RUNNING through CAS, call `MarketSourcePort` page by
   page, persist each raw page idempotently by digest, and retain cursor/request
   identity;
3. transaction: revalidate query and grant, create one immutable snapshot with
   explicit coverage, append observations only after integrity-ref verification,
   finalize attempt and receipt atomically.

A retry of the same command while its attempt is `RUNNING`, `OUTCOME_UNKNOWN`
or `NEEDS_OPERATOR` returns that attempt's current state; only reconciliation
by a stable provider request ID or a qualified-operator receipt moves it.

Before every page, the acquisition service also revalidates the exact cohort
profile identity/revision/digest bound to the query. If capability expires or is
revoked between pages and no call is in flight, the attempt becomes `FAILED`
with `CAPABILITY_EXPIRED` or `CAPABILITY_REVOKED` and preserves an explicit
partial snapshot. If a request may have reached the provider and its response
cannot be proven, the attempt becomes `OUTCOME_UNKNOWN` with
`RESPONSE_OUTCOME_UNKNOWN`; revocation never converts an uncertain call into a
known failure.

Timeout before a verified response produces `OUTCOME_UNKNOWN`; retry never
pretends the call did not happen. For read-only provider operations, a qualified
operator may authorize a new attempt, but the old attempt and possible quota
consumption remain recorded. If the adapter exposes a stable request/search ID,
reconciliation must use it first. Otherwise the attempt enters `NEEDS_OPERATOR`.

Attempt transitions are monotonic:

```text
PLANNED -> RUNNING | FAILED
RUNNING -> SUCCEEDED | FAILED | OUTCOME_UNKNOWN
OUTCOME_UNKNOWN -> SUCCEEDED | FAILED | NEEDS_OPERATOR
NEEDS_OPERATOR -> SUCCEEDED | FAILED
```

`SUCCEEDED` and `FAILED` are terminal. Leaving `NEEDS_OPERATOR` requires an
immutable qualified-operator receipt modeled on M7 and bound to the exact
attempt version and external evidence. It cannot reset the attempt to
`PLANNED`/`RUNNING` or authorize blind replay as the same attempt. Cancellation
is absent from V1 because acquisition pages are bounded read calls; stopping
before the next page produces an explicit partial snapshot and never rewrites an
already issued request.

Manual import uses the same attempt/snapshot path without a credential. Its grant
must name `manual-import`, the Human uploader, declared origin and payload
policy. Filesystem presence alone is not evidence; bytes are hashed and stored
through `SnapshotEvidenceStore` before finalization.

Snapshot coverage is always relative to declared bounds. A provider-ranked
search can be `COMPLETE_WITHIN_DECLARED_BOUNDS` but never claims completeness of
the market. Cursor loops, duplicate pages, page-order drift, quota exhaustion and
record-limit truncation are persisted explicitly. A candidate profile may
require a minimum coverage state; otherwise partial evidence remains visible.

## 11. Normalization, derivation and candidate construction

Normalization adapters are pure fixture-to-contract transforms. They preserve
native field name, definition/version, opaque source identity, erasable
value/integrity refs, any permitted retained proof digest, unit, window,
missingness and transform version. They reject unknown definitions, non-finite
numbers, unit ambiguity and any output not traceable to one exact raw field.

Derivation occurs only after an effective permission evaluation for every input.
The engine rejects mixed-source composites if any grant is forbidden, expired,
revoked, unresolved or purpose-incompatible. Calling a transform “creative,”
mixing provider data with local data, or hiding values behind embeddings does
not change the source policy.

Each cohort profile freezes:

- required and optional dimensions;
- allowed source classes and compatibility rules;
- transform/calibration identities;
- missingness treatment;
- originality corpus and time window;
- reviewer language/cultural qualifications; and
- freshness and candidate-expiry rules.

The profile is an M9-owned append-only aggregate published only after
`OpportunityProfileCustodianPort` authorizes the exact payload digest. Source
and dimension rules are validated at publication; every query, signal,
candidate and Greenlight binds the exact profile identity/revision/digest. A
new profile revision never changes the interpretation of historical evidence.
Publishing revision N+1 makes N non-current for new query, derivation,
candidate, Greenlight and seed commands; historical reads keep the exact bound
revision and digest.

`generic-western` (`WESTERN_GENERIC`) and `zh-shuang`
(`CN_SHORT_DRAMA_SHUANGWEN`) are distinct profile lineages. The payload's
`creative_profile_id` holds the exact M6 identity, or `arcreel.host`, never the
label. `creative_policy_pack_digest` is the exact M6 `policy_pack_digest`,
or `host_policy_digest()` for `arcreel.host`; it is not a new M9 policy hash.
Publication, query declaration, evidence use, candidate/Greenlight admission and
seed prepare compare the full creative-policy tuple with the server-resolved
project profile (ADR-0105). A mismatch is `M9_COHORT_LEAKAGE`. M8 learning entries
read this tuple from observation/recommendation `LineageBinding`, resolving a
decision through its exact recommendation and digest; no actor-supplied tuple
is trusted. The tuple flows through profile, query, signal, candidate closure,
payload, lineage and Greenlight digests, and is rechecked at seed prepare.
Huohuo fields
may provide `zh-shuang` creative-fit vocabulary and fixtures, not popularity or
truth. OpenMontage landscape/gap/audience/angle sections and Kalinga topic
suggestions supply proposal/fixture shapes, not scores or Greenlight.

Candidate construction is deterministic for the same frozen inputs and profile.
Model-generated titles, angles or rationales are untrusted proposed payloads;
the model identity, prompt/input digest and output digest become evidence, and
schema/duplicate/cohort checks run before persistence. Model output can never
issue a decision.

## 12. Greenlight and bridge protocols

`decide_greenlight` requires `expected_candidate_head_version` and
`expected_greenlight_head_version`. Under the fixed lock order it revalidates:

- authenticated Human custodian permission for exact user/project;
- candidate revision/head and payload/lineage digests;
- complete evidence closure and all correction heads;
- cohort profile, grant, signal and snapshot freshness;
- no incomplete deletion/invalidation traversal;
- disposition-specific fields, reason, Canvas scope and TTL.

It obtains and admits `CustodianAuthorizationLease` through the same §9
preflight/authorize/guard/finalize protocol used by profile publication.

`seed_canvas` accepts a new actor-scoped command, exact decision identity and
binding digest. It revalidates current `APPROVE`, scope and expiry, commits an
outbox/bridge intent, invokes `M8CanvasSeedPort` outside the database transaction,
then reconciles and records the exact `CanvasSeedReceipt`. The prepare
transaction resolves the seed lineage (below), runs the cohort check and
freezes the complete M8 `ExplorationRevision` (candidate id, revision 1,
`created_at`, `created_by=user_id` (the M8 data owner), lineage, payload and
payload digest) and its M8 append command id
in a `BridgeIntent(kind=CANVAS_SEED, state=PENDING)`. M9 retains the authenticated
`actor_id` in the frozen seed request, command receipt and event; it never
substitutes that principal for the M8 owner. The port appends that
revision verbatim through the server-side M8 exploration service, whose exact
replay returns the same head after a lost acknowledgement; reconciliation never
re-resolves. Intent transitions are monotonic: `PENDING -> DISPATCHED |
CANCELLED_BY_INVALIDATION`, `DISPATCHED -> RECONCILED | NEEDS_OPERATOR`,
`NEEDS_OPERATOR -> RECONCILED` through a qualified-operator receipt. The M8 seed is a
Canvas node with type `M9_OPPORTUNITY_SEED` and an immutable body containing the
candidate, Greenlight and evidence-closure identities/digests. It cannot invoke
M8 promotion or target an artifact slot.

Apart from the additive ADR-0109 resolver that M9-D delivers as an explicit M8
evolution, M9 does not change M8 code.

The accepted M8 design declares `CanvasNode.node_type` as an extensible `str`;
the M9 `Literal` narrows only this bridge request and does not extend an M8
payload union. Task A0 must nevertheless verify the exact accepted M8
implementation accepts this registered node type without changing M8 contract
or digest semantics. If it uses a closed node-type union or rejects the value,
execution stops with `POST_M8_BASE_SEAM_CHANGED`; M9 must not patch M8 under this
packet.

The seed's M8 `LineageBinding` is resolved on the server in the `seed_canvas`
prepare transaction, under the shared invalidation guard, and frozen in the
bridge intent.

- **Profile.** It reads the project's creative profile with the ADR-0105 rule
  (`project_profile` over the user's effective screenplay admissions):
  - no admission gives `arcreel.host`;
  - one admission gives its M6 profile and policy pack;
  - two or more give `M8_LINEAGE_AMBIGUOUS`.
- **Cohort check.** The seed is refused with `M9_COHORT_LEAKAGE` unless the bound
  cohort profile's `(creative_profile_id, creative_profile_version,
  creative_policy_pack_digest)` equals the server-resolved lineage's
  `(creative_profile_id, creative_profile_version, policy_digest)`.
- **Content basis.** The seed uses M8 lineage resolution v3 (ADR-0109): the
  `content_basis_digest` is the M8 canonical digest of
  `{"basis_kind": "m9_opportunity_seed", "creative_content_digest",
  "greenlight_decision_id", "greenlight_binding_digest"}`, produced by an additive
  M8 resolver function that M9-D delivers as an explicit M8 evolution with M8
  tests. Earlier resolutions keep their bytes.
- **Refusals.** M8 lineage refusals (`M8_LINEAGE_AMBIGUOUS`,
  `M8_LINEAGE_EPISODE_OUT_OF_SCOPE`) map to `M9_COHORT_LEAKAGE` and create no
  seed.
- **Master.** `approved_master_id` and `approved_master_digest` are null.
- **Node body.** It separately binds the candidate, Greenlight and
  evidence-closure identities/digests.

The seed uses the server-side M8 exploration service, never the client append
route (ADR-0107).

Exact replay returns the original decision/seed receipt even if its evidence has
since expired; that is historical idempotency, not renewed authorization. A new
seed command against an expired/superseded decision fails. Existing Canvas
history remains immutable and visible with stale-source status; M9 does not
delete or mutate it.

The Factual bridge is separate. It maps selected source/snapshot material into
`SourceRecord` and `EvidenceRecord` submissions with exact locators and digests.
`FactualAuthorityPort` decides acceptance and any later Claim/ResearchPack
workflow. Its bridge intent stores only evidence-store refs and digests for the
selected content, never the content itself. Each selection carries an existing
`selected_content_ref`/`selected_content_integrity_ref` pair from the scoped
erasable store; prepare resolves and verifies the selected canonical object
against the exact snapshot page, identity and locator and recomputes
`selected_content_digest`. The pair, digest and `selection_closure_digest` are
frozen into the intent and request digest. A changed ref, integrity ref, locator
or content under the same command conflicts. Call time rechecks the closure's
deadlines and resolves the same pair, verifies its integrity and recomputes the
same digest; absent, erased or stale content cannot be submitted. Only then
does the adapter construct `ResolvedFactualEvidenceSelection` for the transient
`FactualEvidenceSubmission` port call. M9 never persists or logs that resolved
object; its intent keeps `FactualEvidenceSelection` refs alone. Selected
content and its integrity material inherit every source deletion/refresh rule
and are included in invalidation traversal. A completed exact replay returns the
original receipt without dereferencing deleted content. For an already dispatched
unknown outcome, use downstream command lookup first: if the content was erased,
only lookup/reconciliation/invalidation is permitted; never reconstruct or resubmit
the payload. The bridge is unavailable unless the capability grant permits factual
use and retention of the exact selection proof required by Factual Authority.
Greenlight state is not an input that can elevate claim status.
Submission uses the same prepare/outbox/call/reconcile pattern as the Canvas
bridge. Both downstream ports must provide exact command-id replay or qualified
lookup by the bridge intent identity; an ambiguous outcome remains pending or
`NEEDS_OPERATOR` and is never blindly submitted under a new authority identity.

## 13. Deletion and invalidation

The host, the M9 retention sweep or later M12 code requests deletion through an
idempotent M9 port; it never writes M9 tables directly. A host request
(`InvalidateSourceEvidence`) is a Human command authorized by
`InvalidationCustodianPort.authorize_invalidation` under §9, with the
`InvalidationSubject` digest, and exposed by M9-E as a scoped interactive route.
A denial is `M9_INVALIDATION_UNAUTHORIZED`. System commands use UUIDv7 command
IDs and immutable receipts unique on `(user_id, project_name, operation,
command_id)`, with exact request-digest conflict checks and a command-key guard
over that same tuple under `m9.system-command-key-guard.v1`. They carry no Human
actor and are callable only by the composed host worker. First sweep admission
freezes database `swept_at` in its system receipt outcome; it is not a caller
field or part of the request digest. Retries return that receipt rather than reading a
new clock. Each job also has a scoped unique `(user_id, project_name, origin,
origin_key)`, so a new polling command cannot duplicate the same job:

- `RETENTION_SWEEP`: `origin_key = digest(m9.retention-origin.v1, snapshot_id,
  snapshot_digest, sorted(data_class, retention_due_at) triggering pairs)`;
- `GRANT_REVOKED`: `origin_key = digest(m9.revocation-origin.v1, snapshot_id,
  snapshot_digest, grant_id, grant_version, grant_digest, revocation_detected_at)`;
- `M8_CORRECTION`: `origin_key = digest(m9.m8-correction-origin.v1, superseded_ref,
  superseding_ref, disposition_ref)`.

The first two use the persisted §5 clocks; M8 correction/disposition identity
comes from `M8LearningReadPort`, not worker claims. Intake polls entries that
turned `SUPERSEDED` or `DISPOSED`; repeated events resolve the existing job. System-origin jobs carry no custodian fields, and
`M8_CORRECTION` jobs carry no capability grant. Propagation re-enumerates
dependents under the exclusive guard until two passes find the same closure
before `COMPLETE`. M9 creates an `InvalidationJob` binding source,
payload, policy grant, request identity and deadline. The propagation deadline
is the earlier of the policy deadline and 24 hours after the accepted request.

Traversal follows indexed dependencies:

```text
raw/identity/value/result/assessment payload
  -> snapshot -> observation -> signal
M8 correction/disposition -> M8 learning evidence ref -> M9 signal
  -> opportunity candidate -> Greenlight validity
  -> Factual bridge receipt -> Factual Authority invalidation
```

Pending bridge intents whose request depends on the invalidated closure are
cancelled (`CANCELLED_BY_INVALIDATION`) before any port call; an intent already
dispatched is reconciled. A Canvas seed that was nevertheless created remains
immutable historical exploration with M9 stale-source status; Canvas has no
invalidate port. A factual record created in that race is invalidated through
`FactualAuthorityPort`, and the authority receipt is required for job completion. If propagation
misses the job deadline, the job becomes `NEEDS_OPERATOR` and every dependent
read stays fail-closed.

Payload/identity/integrity deletion happens through
`SnapshotEvidenceStore.delete_exact`. Then M9
appends correction/tombstone records and sets the validity projections of
dependent signals, candidates and Greenlight decisions to `INVALIDATED` (§6; it
appends no custodian decision). It calls
`FactualAuthorityPort.invalidate_evidence` for every M9-submitted factual ref and
records the returned authority receipt; M9 never edits factual tables. Incoming
M8 evidence invalidation is verified through `M8LearningReadPort` and expires
only the dependent M9 closure; M9 never edits M8 tables. The job records counts
and closure digest at every layer. Until the closure is complete, all reads that
could depend on the source return
`M9_INVALIDATION_INCOMPLETE`; they never serve a partially invalidated result.

After `COMPLETE`, snapshot, candidate and Greenlight reads remain historical and return an
`EvidenceValidityProjection(state=INVALIDATED,
erasable_content_available=False)` bound to the completed job. They do not
dereference erased content. Every operational use of such a snapshot or
candidate—including normalization, derivation, candidate append, Greenlight,
Canvas seed and Factual submission—fails with `M9_EVIDENCE_STALE`. This is
distinct from foreign/unknown identity, which remains indistinguishable
not-found. `STALE` is used for expired or superseded but not policy-erased
evidence and is likewise non-authorizing.

The tombstone may retain request/time/outcome, non-sensitive source identity,
policy identity and permitted digest proof. It cannot retain raw bytes,
reversible embeddings, excerpts or derived surrogates forbidden by policy.
Replay of a completed deletion returns the same receipt.

Invalidation transitions are:

```text
PLANNED -> ERASING_PAYLOAD | NEEDS_OPERATOR
ERASING_PAYLOAD -> PROPAGATING | NEEDS_OPERATOR
PROPAGATING -> COMPLETE | NEEDS_OPERATOR
NEEDS_OPERATOR -> ERASING_PAYLOAD | PROPAGATING | COMPLETE
```

Leaving `NEEDS_OPERATOR` requires a receipt bound to the exact job version and
proof of the completed or resumed step. No transition may return to `PLANNED` or
make a partial closure readable.

## 14. Persistence and migration boundary

All authoritative metadata lives in PostgreSQL under these M9-owned table
families:

- `m9_source_queries`, `m9_source_query_heads`;
- `m9_cohort_profiles`, `m9_cohort_profile_heads`;
- `m9_consumed_capability_grants`, `m9_capability_evaluations`;
- `m9_acquisition_attempts`, `m9_snapshot_pages`, `m9_source_snapshots`;
- `m9_source_observations`, `m9_observation_heads`;
- `m9_opportunity_signals`, `m9_signal_heads`;
- `m9_opportunity_candidates`, `m9_candidate_heads`;
- `m9_greenlight_decisions`, `m9_greenlight_heads`;
- `m9_bridge_intents`, `m9_bridge_receipts`, `m9_command_receipts`
  (`host_custodian_leases` is host-owned replay state, not an M9 table family);
- `m9_invalidation_jobs`, `m9_invalidation_edges`, `m9_events`;
- `m9_system_command_receipts` (M9-E), with explicit `operation`, `command_id`,
  request/result digests, immutable outcome refs and database committed time,
  unique `(user_id, project_name, operation, command_id)`.

Every table carries user/project scope; global unique constraints include scope
where identity is not globally UUID-bound. Foreign/unknown identities produce
indistinguishable not-found responses. Append-only tables deny update/delete in
repositories except policy-required payload erasure through the dedicated
deletion path. Raw bytes, retention-sensitive source identities and non-retained
integrity digests are outside ORM rows behind `SnapshotEvidenceStore`;
PostgreSQL retains authoritative opaque refs, permitted proofs and status.

M9 uses one linear Alembic chain based on the exact accepted predecessor. Schema
creation, downgrade and backup/restore evidence run only in an isolated test
database. No migration executes during design or planning.

Repositories are internal adapters behind one M9 unit-of-work. They expose only
scoped `get_exact`, `get_head`, append/stage, expected-version transition and
dependency-enumeration operations for their owned aggregate. Repository methods
never commit, call another module, perform provider/payload I/O, issue capability
grants or return live ORM entities. The application module alone owns transaction
begin/commit/rollback and stages the immutable command receipt and outbox event
in the same transaction as each authority mutation.

The repository split is normative:

- cohort-profile repository owns profile revisions and CAS heads;
- query repository owns query revisions and query heads;
- acquisition repository owns attempt version transitions;
- snapshot repository owns snapshot/correction metadata and ordered page rows;
- observation and signal repositories own append-only correction chains;
- candidate repository owns candidate revisions and its CAS head;
- Greenlight repository owns decisions and its independent CAS head;
- bridge-intent repository owns frozen bridge requests and their transitions;
- command/bridge receipt repositories own immutable replay results; and
- invalidation repository owns jobs, dependency edges and progress versions.

No generic repository accepts a caller-selected table/model type. Authority and
invariants remain local to each aggregate while the public interface stays small.

## 15. Initial adapters and provider rules

| Adapter | Initial state | Required evidence and semantics |
|---|---|---|
| `manual-import.v1` | enabled by explicit Human project action | declared origin/uploader, immutable bytes/digest, import policy, same snapshot/normalization path |
| `youtube-data-public.v1` | dormant | exact app/account grant, `search.list`/`videos.list` operations, parts/fields, quota, pages, ETags, 30-day metadata refresh/deletion rules |
| `youtube-derived-analytics.v1` | disabled | separately accepted Analytics & Reporting amendment for exact use; distinguish R2-derived values; policy-bound retention |
| `google-trends-alpha.v1` | unavailable unless accepted tester | alpha grant, exact scaling/interval/geography semantics; baseline cannot depend on it |
| `tiktok-research.v1` | unavailable for commercial baseline | separately eligible approved research project only; archived-data and 48-hour/10-day lag semantics |
| `tiktok-commercial-content.v1` | dormant | approved client, ads/public-advertiser corpus label, `search_id` pagination; never organic demand proxy |
| `m8-learning-read.v1` | prerequisite-bound | exact accepted M8 observation/recommendation identities, disposition and expiry; read only |

Adapters return facts and coverage only. They do not normalize across provider
meanings, calculate opportunity scores, issue capability grants or decisions,
or persist authoritative rows.

## 16. Operational envelope

V1 hard ceilings are intentionally conservative. Declared budgets fail before
external I/O; response-size ceilings fail immediately after a page returns and
before its payload can become authoritative evidence:

- canonical query parameters: 64 KiB;
- 20 pages and 1,000 records per acquisition;
- 2 MiB raw bytes per page and 40 MiB per snapshot (20 × 2 MiB);
- 10,000 observations in one signal input closure;
- 100 snapshots, 256 signals and 32 M8 learning refs per candidate;
- 250 candidate revisions and 250 decisions per logical candidate;
- Greenlight approval TTL: at most 24 hours and never beyond an input expiry.
- Enabled retention/revocation sweep: at most 60 seconds between successful
  evaluations, with lag and last-success evidence; an exceeded bound refuses
  new operational use of the affected grant until reevaluated.

The implementation must benchmark the sponsor-approved production envelope and
record actual p50/p95 latency, peak RSS, database growth, evidence-store bytes,
query count and invalidation traversal time. Raising a ceiling requires an
accepted design amendment and new evidence; configuration may lower ceilings.
The aggregate byte ceiling is checked before accepting each page; crossing it
produces `FAILED/AGGREGATE_BYTE_LIMIT`, retains the already accepted pages as an
explicit partial snapshot and returns `M9_OPERATIONAL_ENVELOPE_EXCEEDED`. At 250
revisions or decisions, the next append fails with the same stop code before any
write. V1 has no archive-and-reuse operation; a Human may start a distinct
candidate identity and bind the predecessor through `supersedes_candidate_id`.

## 17. UI and accessibility

The project Opportunity Desk exposes:

- source capability state and why an adapter is disabled/unavailable;
- query intent, cohort/profile, exact bounds and estimated quota before acquire;
- snapshot time, coverage, missingness, policy/freshness and correction state;
- candidate comparison with every dimension shown separately, evidence drill-
  down, uncertainty and contraindications;
- a Human Greenlight confirmation showing exact revision, evidence freshness,
  expiry, Canvas scope and required reason; and
- Canvas seed receipt/link without implying production approval.

The UI is a projection and command client only. It never computes authoritative
digests, currentness or permission. All user-facing text receives every locale
under `frontend/src/i18n/`; Darkroom mono kickers remain the documented English
exception. Keyboard navigation, focus order, dialog focus trapping, accessible
names, non-color status cues, reduced motion and screen-reader error summaries
are mandatory. Playwright runs axe-core against empty, loaded, partial,
unavailable, conflict and invalidation states. Playwright is not yet a frontend dependency; M9-F adds it under the
repository dependency rules.

## 18. Events and observability

Every committed mutation emits an outbox event in the same transaction. Events
contain IDs, scope, digests, versions and outcome, never tokens or raw provider
payloads. Minimum event families are cohort profile published, query declared,
attempt state changed,
snapshot committed/corrected, signal derived/expired, candidate appended,
Greenlight decided/expired, bridge reconciled and invalidation completed.

Metrics are bounded-cardinality by source kind, operation, state and stop code;
user/project/query/candidate IDs stay in structured logs/traces, not metric
labels. Logs redact credential refs where host policy requires and always redact
token-like values. Health checks report adapter configuration separately from
capability authorization.

## 19. Normative stop codes

| Stop code | Condition |
|---|---|
| `M9_M8_IMPLEMENTATION_NOT_ACCEPTED` | exact independently accepted M8 implementation lineage is absent |
| `M9_DESIGN_NOT_ACCEPTED` | ADR/spec/plan do not have exact independent M9 design acceptance |
| `POST_M8_BASE_SEAM_CHANGED` | accepted M7/M8/Factual/shared canonical seam differs from the frozen design assumption |
| `M9_FACTUAL_AUTHORITY_UNAVAILABLE` | no accepted durable Factual Authority port backs the typed contracts |
| `M9_SCHEMA_CHANGE_REQUIRED` | implementation requires changing an accepted public M9 contract or digest domain |
| `M9_SOURCE_CAPABILITY_UNAVAILABLE` | requested source/operation/account capability is disabled, unavailable, expired or revoked |
| `M9_SOURCE_POLICY_FORBIDDEN` | the exact acquisition or derivation purpose is forbidden or conditional requirements are unmet |
| `M9_CREDENTIAL_REFERENCE_INVALID` | opaque credential ref is absent, mismatched, expired or exposes token material |
| `M9_COMMAND_REPLAY_CONFLICT` | same actor/operation/command ID carries a different request digest |
| `M9_STALE_HEAD` | query, candidate, decision or correction CAS does not match |
| `M9_ACQUISITION_OUTCOME_UNKNOWN` | external request outcome cannot be proven or reconciled |
| `M9_RAW_DIGEST_MISMATCH` | payload bytes do not match the bound page digest |
| `M9_NORMALIZATION_LOSSY` | native identity/definition/value/unit/window/raw lineage cannot be preserved |
| `M9_DERIVATION_POLICY_UNPROVEN` | any composite input lacks effective permitted-use evidence |
| `M9_COHORT_LEAKAGE` | evidence, calibration or rubric crosses incompatible cohort/profile lineage |
| `M9_PROFILE_PUBLICATION_UNAUTHORIZED` | publisher is not an authenticated Human profile custodian for the exact scope and payload digest |
| `M9_EVIDENCE_STALE` | correction, expiry, missingness or policy state invalidates the requested candidate/decision |
| `M9_GREENLIGHT_UNAUTHORIZED` | issuer is not an authenticated Human custodian for exact scope |
| `M9_GREENLIGHT_EXPIRED` | approval is expired or superseded for a new Canvas seed |
| `M9_INVALIDATION_INCOMPLETE` | a dependent read occurs before deletion/invalidation closure completes |
| `M9_INVALIDATION_UNAUTHORIZED` | a Human invalidation lacks a valid custodian lease |
| `M9_EVIDENCE_RETENTION_EXPIRED` | a read or use reaches erasable evidence past its retention deadline or a revoked delete-on-revoke grant |
| `M9_DONOR_PARITY_INCOMPLETE` | selected donor behavior lacks exact-pin, same-fixture and independent parity evidence |
| `M9_REQUIRED_EVIDENCE_MISSING` | a packet-required Human or environment evidence input is absent or unverified |
| `M9_OPERATIONAL_ENVELOPE_EXCEEDED` | input exceeds a frozen V1 hard ceiling |

Stop codes are stable public evidence values. Human-readable detail is separate
and localized at the UI edge.

## 20. Verification and adversarial gates

### Contract and persistence

- Pydantic extra-field, frozen/deep-copy, aware-time and digest-domain tests;
- cohort-profile publication custody, append/CAS, exact binding and cross-cohort
  isolation tests;
- migration upgrade/downgrade/restore in isolated PostgreSQL;
- foreign/unknown indistinguishability and scope collision tests;
- append-only enforcement, CAS races, exact replay and changed-replay conflict;
- fixed lock-order concurrency test with no deadlock.

### Acquisition and policy

- manual import, success, rejection, rate limit, timeout, cursor loop, duplicate
  page, order drift, partial/truncated result and unknown outcome fixtures;
- grant disabled/expired/revoked, wrong account/purpose/operation and conditional
  requirement failures;
- YouTube raw normalization succeeds while forbidden/unproven derived signals
  fail; an exact permitted amendment fixture enables only its named use;
- a format-valid TikTok Research grant with ineligible commercial/project
  evidence is rejected, not treated as authorization;
- TikTok Research commercial fixture remains unavailable; Commercial Content
  observations retain the ads-corpus label.

### Normalization, candidate and cohort

- raw/native fields survive same-fixture round trip without new meaning;
- missing never becomes zero; unknown definitions/units fail;
- every signal recomputes from its exact closure and policy basis;
- generic-Western and native-language `zh-shuang` corpora cannot cross;
- OpenMontage landscape/gap/audience/angle, Kalinga malformed/duplicate topic and
  Huohuo `爽型` fixtures meet selected parity rows or improve with documented
  donor-defect fixtures.

### Greenlight, bridge and invalidation

- model/provider/donor boolean cannot issue Greenlight;
- stale candidate/evidence/grant/custodian/TTL/CAS fails before write;
- exact retry returns original decision/seed receipt after unknown client
  outcome; changed retry conflicts;
- Canvas bridge can create only `M9_OPPORTUNITY_SEED`, cannot call promotion,
  Production Authority, Canon or Narrative;
- Factual bridge keeps claims unverified and fails atomically on missing refs;
- deletion traversal is idempotent, deadline-bound and fail-closed during partial
  propagation; forbidden raw/derived data is absent after completion.

### Product utility

- end-to-end manual/import workflows for Western generic/factual and native-
  language `zh-shuang` cohorts;
- at least two blind qualified reviewers per cohort artifact, with reviewer
  criteria and `rubric_version` frozen before results;
- candidate usefulness, evidence traceability, disagreement and correction time
  compared against the preregistered baseline;
- operational envelope evidence records exact dataset sizes and actual resource
  results, not only “pass.”

## 21. Donor parity protocol

Each selected donor surface receives a manifest row with immutable URL, SHA,
path, reachable behavior, test/fixture inventory, selected classification,
license ignored by sponsor direction, and R2 interface mapping. The verifier
recomputes every verdict from same-fixture results at the exact integrated HEAD.

Applicable functionality, correctness, determinism, failure safety, integrity,
observability, performance and resource rows must be `PARITY` or `IMPROVED`.
`EXCLUDED` requires an explicit R2 authority/scope reason. A donor defect may be
excluded only with one fixture that fails the donor and passes R2. Repository
popularity, historical green tests, source similarity and one attractive output
are not parity evidence.

## 22. File ownership and packet boundary

The implementation plan must use these ownership paths after checking the
accepted M8 tree. If the accepted M8 contract module lives elsewhere, the plan
records the exact mechanical import adjustment; any semantic contract change
requires design amendment and `POST_M8_BASE_SEAM_CHANGED`:

- `r2/contracts/opportunity.py` — frozen contracts and validators;
- `r2/opportunity/` — deep module, repositories, policy, acquisition,
  normalization, signals, candidates, Greenlight, invalidation and bridges;
- `lib/db/models/` and `lib/db/repositories/` — ArcReel persistence adapters;
- `server/services/m9_custodian.py` and `lib/db/models/host_custodian.py` — the
  host custodian adapter over ADR-0103 grants and its lease replay table (M9-A);
- `r2/advanced_creative/lineage.py` — only the additive ADR-0109 seed resolver,
  as an explicit M8 evolution under M8 tests (M9-D);
- `server/routers/` and request/response schemas — scoped HTTP command/read edge;
- `frontend/src/` — Opportunity Desk projection and command UI;
- `alembic/versions/` — one linear M9 chain from accepted predecessor;
- `tests/` and frontend tests — contract, integration, browser, parity and
  adversarial evidence;
- `docs/r2/evidence/` — design acceptance, execution manifest, stop and final
  acceptance records.

Only one M9 implementation/review packet may be active. Provider adapters,
frontend work or fixtures may not treat a planned repository/interface as
available. Every packet begins from its independently accepted predecessor and
ends with exact HEAD, changed-file allowlist, commands/logs, required skips,
material unknowns and independent review.

## 23. Design acceptance conditions

This design remains proposed until independent review verifies:

1. ADR-0081, this spec, research, validation report, umbrella plan, authored
   M9-A packet, execution contract, design-acceptance contract, acceptance
   schema, sealed-review schema and cross-record verifier/tests are mutually
   consistent and hash-bound;
2. exact prerequisite semantics do not claim current M8 or Factual
   implementation availability;
3. contract fields, digest domains, scope, replay, CAS and lock order are
   unambiguous;
4. provider rules reflect first-party evidence assessed on 2026-09-14 and
   account authorization is separately fail-closed;
5. Western and `zh-shuang` cohort isolation and qualified review are explicit;
6. deletion/invalidation has an append-only lineage, deadline and fail-closed
   partial state;
7. donor parity, operational envelope and UI accessibility evidence are
   executable requirements;
8. all normative stop codes are synchronized with the later plan/manifest; and
9. the M9 design-acceptance schema validates a record bound to the exact
   candidate HEAD/parent, every normative candidate artifact hash and the
   recomputed ADR hash after its status-only acceptance transition; and
10. two author-independent and mutually blind qualified reviewers, using the
   rubric frozen by the M9 design-acceptance contract before either review,
   return PASS on that exact candidate HEAD with sealed output hashes, no
   required skip and no material unknown.

The sealed-review schema requires all ten rubric checks exactly once and PASS,
an empty finding/skip/unknown set, and the exact reviewer, rubric, candidate,
contract and seal metadata. `scripts.r2.verify_m9_design_acceptance` additionally
rejects duplicate JSON keys, recomputes review-output hashes, checks metadata
against the sealed bytes, requires distinct reviewer identities/output refs,
and proves both seal times precede `reviews_shared_at` and that `reviewed_at`
does not precede sharing. JSON Schema validation without this cross-record
verifier is insufficient and must fail the design-acceptance gate.
The normative entry point is
`uv run python scripts/r2/verify_m9_design_acceptance.py` at the acceptance
commit. It reads the acceptance, candidate artifacts, review outputs and both
schemas from their exact Git objects; input dictionaries supplied by a caller
are never treated as repository evidence. The acceptance commit must have the
reviewed candidate as its sole parent and change exactly ADR-0081's status,
`R2_M9_DESIGN_ACCEPTANCE.json`, and the two fixed sealed-review paths.
The record contains no caller-supplied command/output/hash tuple: adjacent
self-attested bytes and hashes prove nothing. The acceptance custodian must
execute the normative verifier and retain its process output outside the
acceptance authority object.

Design acceptance satisfies only the design limb checked by read-only A0; it
does not authorize code or mutate the normative execution contract. M9 code
remains blocked until the combined prerequisite manifest independently validates
the exact accepted M8 implementation and the M9 design acceptance. M9-D also
remains blocked until the durable Factual Authority implementation is accepted
(FA-1, the `packet_release_acceptance` gate of the execution contract).
