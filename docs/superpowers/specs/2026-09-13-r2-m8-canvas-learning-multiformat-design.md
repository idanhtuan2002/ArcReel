# R2-M8 Creative Canvas, Learning, and Multi-format Design

**Status:** Accepted for implementation planning on 2026-09-13. This document does not authorize implementation or production activity.

**Review amendment:** Contract, scoping, idempotency, lock-order, retention and
evaluation ambiguities identified in the 2026-09-13 independent review are
resolved normatively in this revision, before Task A0/A1 execution.

## 1. Goal and boundary

M8 adds a non-authoritative Creative Canvas, explicit preview-bound promotion,
bounded spatial experiments, lineage-bound analytics and recommendations, and
semantic multi-format projections. It uses the integrated port-accelerated
kernel selected by ADR-0079 and must satisfy locked `R2-DEC-031` for every
selected donor surface.

M8 consumes an accepted M7 implementation. The present design branch contains
M7 documents only; an executor must prove an accepted clean M7 HEAD before
creating M8 implementation files. ArcReel remains the host, PostgreSQL the
durable store, existing Production Authority the ApprovedMaster writer, and M7
the durable execution/recovery substrate.

M8 adds no Canon, NarrativePlan, CreativePolicy, Claim, production-master,
queue, provider, cost, or workflow authority. Licensing is outside selection,
scoring, rejection, and sequencing by sponsor direction.

## 2. Reuse disposition

| Source | Reuse | Boundary |
|---|---|---|
| ArcReel | React shell, Zustand, i18n/API conventions, provenance, aspect/media mechanics, QualityReport planes, UsageRepository observations, approval adapter | Existing types keep their meanings; M8 adds typed evidence rather than overloading them |
| M6 | exact `generic-western` and `zh-shuang` profile/policy/content identities and sidecars | no silent pooling or floating “latest” profile |
| M7 | ExecutionAttempt, receipts, recovery, events, resource ceilings, immutable candidates/master CAS | required accepted prerequisite; no M8 queue |
| DramaClaw `b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83` | selected graph/history/group/bookmark/save-decision/payload-limit, save coordinator/recovery, React Flow interaction, spatial normalizers and tests | PostgreSQL replaces donor filesystem authority; direct push/auto-commit/provider/billing/project shell excluded |
| OpenMontage `08e2151fa02de28a5d6a312b3d575692bf147ad7` | composition, crop, validation, replay and decision-evidence mechanics | R2 contracts own identity, execution, semantic parity and promotion |

## 3. Canonical vocabulary and invariants

The glossary definitions in `CONTEXT.md` are normative. Additional implementation
terms below do not replace them.

1. A candidate logical ID has append-only revisions; revision payload bytes and
   digest never change.
2. Browser storage is recovery cache. Server revision/history is exploration
   durability. Production Authority alone creates formal production artifacts.
3. Promotion authorization binds one exact, non-expired preview. The server
   rechecks scope, candidate, revision, payload, target, expected parent/master,
   impact and authorization in the promotion transaction.
4. Exact command replay returns the original receipt before stale checks;
   same key with different semantics is a conflict.
5. Spatial inference preserves visible/inferred/gap classification and never
   becomes fact by confidence, temperature or repetition.
6. Observation corrections append; source-specific metric semantics remain
   recoverable from every normalization and recommendation.
7. Recommendations are proposals. Acceptance creates a governed proposal only.
8. Format projection starts from one exact ApprovedMaster. Semantic change is
   explicit reframe evidence, not hidden renderer behavior.
9. Donor behavior is accepted only with exact-source, same-fixture evidence and
   an integrated-HEAD parity report containing no material unknown or required skip.
10. All persisted timestamps are timezone-aware UTC; hashes are lowercase
    `sha256:<64 hex>` over versioned canonical UTF-8 JSON.

## 4. Fixed contracts

Public contracts are frozen, extra-field-forbid Pydantic v2 models. Every model
below inherits `M8ContractModel`; the code blocks are normative Pydantic shapes,
not standard-library dataclasses. Opaque IDs are repository-standard UUIDv7
strings. Callers may compare but not derive order from IDs. Services deep-copy
validated inputs into canonical JSON snapshots before hashing/persistence; no
contract relies on Python object hashing or caller-owned mutable mappings.
The implementation module begins with `from __future__ import annotations` and
calls `ExplorationRevision.model_rebuild()` after `CandidatePayload` is declared.

```python
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from math import isfinite
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    RootModel,
    StringConstraints,
    model_validator,
)

from r2.contracts.common import R2ContractModel

class ExplorationKind(StrEnum):
    CANVAS = "CANVAS"
    SPATIAL = "SPATIAL"
    FORMAT = "FORMAT"

class EvidenceClass(StrEnum):
    VISIBLE = "VISIBLE"
    INFERRED = "INFERRED"
    GAP = "GAP"

class ExperimentDesign(StrEnum):
    CONCURRENT_RANDOMIZED = "CONCURRENT_RANDOMIZED"
    PLATFORM_MANAGED = "PLATFORM_MANAGED"
    SEQUENTIAL_OBSERVATIONAL = "SEQUENTIAL_OBSERVATIONAL"
    OFFLINE_REPLAY = "OFFLINE_REPLAY"

class RecommendationDisposition(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    DEFER = "DEFER"
    REQUEST_EXPERIMENT = "REQUEST_EXPERIMENT"

class ParityDisposition(StrEnum):
    PARITY = "PARITY"
    IMPROVED = "IMPROVED"
    EXCLUDED = "EXCLUDED"
    UNVERIFIED = "UNVERIFIED"

class ParityVerdict(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"

class PromotionTargetKind(StrEnum):
    ARTIFACT_SLOT = "ARTIFACT_SLOT"
    PRODUCTION_BINDING = "PRODUCTION_BINDING"

Sha256Digest = Annotated[
    str,
    StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$"),
]

# A custom Pydantic RootModel whose root is a recursively immutable, key-sorted
# tuple representation. Its validator accepts JSON mappings, rejects non-string
# keys/non-finite numbers, maps arrays to tuples and maps objects to sorted tuples.
type CanonicalJsonScalar = str | int | Decimal | bool | None
type CanonicalJsonValue = (
    CanonicalJsonScalar | tuple[CanonicalJsonValue, ...] | CanonicalJsonObject
)

def _freeze_json_value(value: object) -> CanonicalJsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("canonical JSON numbers must be finite")
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("canonical JSON numbers must be finite")
        return Decimal(str(value))
    if isinstance(value, Mapping):
        return CanonicalJsonObject.model_validate(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json_value(item) for item in value)
    raise ValueError("value is outside the canonical JSON domain")

class CanonicalJsonObject(RootModel[tuple[tuple[str, CanonicalJsonValue], ...]]):
    model_config = ConfigDict(frozen=True)

    @model_validator(mode="before")
    @classmethod
    def freeze_object(cls, value: object) -> object:
        if isinstance(value, cls):
            return value.root
        if not isinstance(value, Mapping):
            raise ValueError("canonical JSON object root must be a mapping")
        if any(not isinstance(key, str) for key in value):
            raise ValueError("canonical JSON object keys must be strings")
        return tuple(
            (key, _freeze_json_value(item))
            for key, item in sorted(value.items())
        )

class M8ContractModel(R2ContractModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        frozen=True,
        use_enum_values=False,
    )
```

```python
class LineageBinding(M8ContractModel):
    project_name: str
    content_basis_digest: Sha256Digest
    approved_master_id: str | None
    approved_master_digest: Sha256Digest | None
    creative_profile_id: str
    creative_profile_version: str
    policy_digest: Sha256Digest

class CanvasNode(M8ContractModel):
    node_id: str
    node_type: str
    body: CanonicalJsonObject

class CanvasEdge(M8ContractModel):
    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_type: str
    body: CanonicalJsonObject

class CanvasCandidate(M8ContractModel):
    kind: Literal[ExplorationKind.CANVAS]
    graph_schema_version: str
    nodes: tuple[CanvasNode, ...]
    edges: tuple[CanvasEdge, ...]
    groups: tuple[CanonicalJsonObject, ...]
    storyboard_order: tuple[str, ...]
    viewport_bookmarks: tuple[CanonicalJsonObject, ...]

class ExplorationRevision(M8ContractModel):
    candidate_id: str
    revision: int = Field(ge=1)
    kind: ExplorationKind
    parent_revision: int | None
    payload: CandidatePayload
    payload_digest: Sha256Digest
    lineage: LineageBinding
    created_by: str
    created_at: AwareDatetime

    @model_validator(mode="after")
    def require_matching_payload_kind(self) -> Self:
        if self.kind != self.payload.kind:
            raise ValueError("revision kind must equal payload kind")
        return self

class CandidateHead(M8ContractModel):
    candidate_id: str
    current_revision: int = Field(ge=1)
    head_version: int = Field(ge=1)

class PromotionTarget(M8ContractModel):
    kind: PromotionTargetKind
    target_ref: str
    expected_target_version: int = Field(ge=0)

class PromotionPreview(M8ContractModel):
    preview_id: str
    preview_command_id: str
    project_name: str
    candidate_id: str
    candidate_revision: int
    candidate_payload_digest: Sha256Digest
    target: PromotionTarget
    expected_master_id: str | None
    expected_master_digest: Sha256Digest | None
    impact: CanonicalJsonObject
    impact_digest: Sha256Digest
    authorization_scope: str
    issued_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def require_bounded_target_binding(self) -> Self:
        ttl_seconds = (self.expires_at - self.issued_at).total_seconds()
        if not 0 < ttl_seconds <= 3600:
            raise ValueError("preview TTL must be in (0, 3600] seconds")
        has_master = (
            self.expected_master_id is not None
            and self.expected_master_digest is not None
        )
        if self.target.kind is PromotionTargetKind.ARTIFACT_SLOT and not has_master:
            raise ValueError("artifact preview requires exact master identity")
        if self.target.kind is PromotionTargetKind.PRODUCTION_BINDING and (
            self.expected_master_id is not None
            or self.expected_master_digest is not None
        ):
            raise ValueError("binding preview cannot bind a master identity")
        return self

class PromotionAuthorization(M8ContractModel):
    command_id: str
    project_name: str
    preview_id: str
    preview_digest: Sha256Digest
    actor_id: str
    actor_scope: str
    decision: Literal["APPROVE"]
    authorized_at: AwareDatetime

class PromotionReceipt(M8ContractModel):
    receipt_id: str
    command_id: str
    project_name: str
    preview_digest: Sha256Digest
    candidate_id: str
    candidate_revision: int
    target: PromotionTarget
    result_artifact_ref: str
    result_master_id: str | None
    result_digest: Sha256Digest
    promoted_at: AwareDatetime

    @model_validator(mode="after")
    def require_target_specific_result(self) -> Self:
        has_master = self.result_master_id is not None
        expects_master = self.target.kind is PromotionTargetKind.ARTIFACT_SLOT
        if has_master != expects_master:
            raise ValueError("receipt master identity does not match target kind")
        return self
```

```python
class SpatialAssertion(M8ContractModel):
    assertion_id: str
    evidence_class: EvidenceClass
    source_refs: tuple[str, ...]
    relation: str
    subject_refs: tuple[str, ...]
    confidence: float | None
    warnings: tuple[str, ...]

class SpatialPayload(M8ContractModel):
    assertions: tuple[SpatialAssertion, ...]
    seam_locks: tuple[CanonicalJsonObject, ...]
    direction_locks: tuple[CanonicalJsonObject, ...]
    duplicate_warnings: tuple[CanonicalJsonObject, ...]
    execution_id: str | None
    normalizer_version: str

class SpatialCandidate(M8ContractModel):
    kind: Literal[ExplorationKind.SPATIAL]
    spatial: SpatialPayload
```

```python
class MetricWindow(M8ContractModel):
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    timezone_name: str
    aggregation: str

class LearningObservation(M8ContractModel):
    observation_id: str
    source_family: str
    source_record_id: str
    metric_name: str
    metric_definition_version: str
    metric_value: Decimal | None
    metric_unit: str
    window: MetricWindow
    platform_artifact_id: str | None
    format_profile_ref: str | None
    lineage: LineageBinding
    experiment_design: ExperimentDesign | None
    exposure_ref: str | None
    raw_payload_digest: Sha256Digest
    transformation_version: str | None
    correction_of: str | None
    missing_reason: str | None
    observed_at: AwareDatetime
    ingested_at: AwareDatetime

class LearningRecommendation(M8ContractModel):
    recommendation_id: str
    evidence_observation_ids: tuple[str, ...]
    hypothesis: str
    applicability: CanonicalJsonObject
    exclusions: tuple[str, ...]
    confidence: float
    expected_guardrails: tuple[str, ...]
    lineage: LineageBinding
    expires_at: AwareDatetime

class RecommendationDecision(M8ContractModel):
    decision_id: str
    recommendation_id: str
    disposition: RecommendationDisposition
    expected_recommendation_digest: Sha256Digest
    actor_id: str
    reason: str
    governed_proposal_ref: str | None
    decided_at: AwareDatetime
```

```python
class OutputProfile(M8ContractModel):
    profile_ref: str
    platform: str
    surface: str
    width: int
    height: int
    fps: Fraction
    duration_limit_seconds: Decimal | None
    container: str
    video_codec: str
    audio_codec: str | None
    source_refs: tuple[str, ...]
    effective_at: AwareDatetime

class OverlayConstraintSet(M8ContractModel):
    constraint_ref: str
    platform: str
    surface: str
    locale: str
    ui_variant: str
    regions: tuple[CanonicalJsonObject, ...]
    source_refs: tuple[str, ...]
    effective_at: AwareDatetime

class ReframeDecision(M8ContractModel):
    decision_id: str
    kind: str
    source_span: CanonicalJsonObject
    target_span: CanonicalJsonObject
    rationale: str
    semantic_risk: str

class FormatProjectionPlan(M8ContractModel):
    plan_id: str
    source_master_id: str
    source_master_digest: Sha256Digest
    output_profile: OutputProfile
    overlay_constraints: OverlayConstraintSet
    reframe_decisions: tuple[ReframeDecision, ...]
    plan_digest: Sha256Digest

class TechnicalValidationReport(M8ContractModel):
    report_id: str
    plan_digest: Sha256Digest
    artifact_digest: Sha256Digest
    checks: tuple[CanonicalJsonObject, ...]
    passed: bool

class SemanticParityReport(M8ContractModel):
    report_id: str
    plan_digest: Sha256Digest
    source_master_digest: Sha256Digest
    artifact_digest: Sha256Digest
    rubric_version: str
    reviews: tuple[CanonicalJsonObject, ...]
    material_disagreement: bool
    passed: bool

class FormatCandidate(M8ContractModel):
    kind: Literal[ExplorationKind.FORMAT]
    plan_digest: Sha256Digest
    rendered_artifact_ref: str
    rendered_artifact_digest: Sha256Digest
    technical_report_id: str
    technical_report_digest: Sha256Digest
    semantic_report_id: str
    semantic_report_digest: Sha256Digest
    execution_id: str

CandidatePayload = Annotated[
    CanvasCandidate | SpatialCandidate | FormatCandidate,
    Field(discriminator="kind"),
]

ExplorationRevision.model_rebuild()
```

`ExplorationRevision.kind` must equal `payload.kind`; the model validator rejects
every mismatch before digesting or persistence. `SpatialCandidate` and
`FormatCandidate` are the complete payload schemas for their revision kinds;
`SpatialPayload` is nested evidence, not an independently persisted candidate.

```python
class DonorSurfaceRef(M8ContractModel):
    repository_url: str
    commit_sha: str
    selected_paths: tuple[str, ...]
    reachable_surface_digest: Sha256Digest
    runtime_identity: str
    behavior_inventory_digest: Sha256Digest
    donor_test_inventory_digest: Sha256Digest
    fixture_set_digest: Sha256Digest

class BehaviorParityRow(M8ContractModel):
    behavior_id: str
    donor_test_refs: tuple[str, ...]
    fixture_refs: tuple[str, ...]
    intentional_difference: str | None
    functionality: ParityDisposition
    correctness: ParityDisposition
    determinism: ParityDisposition
    failure_safety: ParityDisposition
    data_integrity: ParityDisposition
    observability: ParityDisposition
    performance: ParityDisposition
    resources: ParityDisposition
    evidence_refs: tuple[str, ...]

class DonorParityReport(M8ContractModel):
    contract_version: Literal["1"]
    donor: DonorSurfaceRef
    integrated_head: str
    rows: tuple[BehaviorParityRow, ...]
    commands: tuple[CanonicalJsonObject, ...]
    required_skips: tuple[str, ...]
    material_unknowns: tuple[str, ...]
    reviewer: str
    verdict: ParityVerdict
```

`PASS` requires at least one row, exact current integrated HEAD, zero required
skips and material unknowns, and every applicable dimension `PARITY` or
`IMPROVED`. `EXCLUDED` is legal only for behavior outside the selected reachable
surface and must carry a reason. It cannot hide a dependency required to execute
selected behavior.

`payload_digest` is the version-1 domain digest of canonical
`{contract_version, kind, payload, lineage}`. It excludes candidate/revision IDs,
parent revision, author and timestamps. Consequently a profile, policy, content
basis or ApprovedMaster lineage change changes `payload_digest` even when graph
or media fields are byte-identical. Promotion binds and recomputes this complete
domain, not a payload-only JSON hash.

Candidate genesis stores `current_revision=1` and `head_version=1`. Each
successful append requires both `parent_revision == current_revision` and the
exact `expected_head_version`, then increments both by one. Exact command replay
increments neither. `current_revision` identifies immutable domain content;
`head_version` is the PostgreSQL CAS token and is never inferred from revision.

Promotion targets form a closed universe:

| Candidate | Allowed target | Authority owner | Receipt master |
|---|---|---|---|
| `CanvasCandidate` | `ARTIFACT_SLOT` | M7 Production Authority | required |
| `SpatialCandidate` | `PRODUCTION_BINDING` | existing R2 Production Binding authority | absent |
| `FormatCandidate` | `ARTIFACT_SLOT` | M7 Production Authority | required |

The `PRODUCTION_BINDING` adapter means the binding authority present on the
accepted post-M7 implementation lineage, not the contract class alone. Task A0
must identify its exact service/repository/transaction seam; absence or a
non-atomic seam stops `M8_BASE_SEAM_CHANGED` before M8 files are created.

`target_ref` is the opaque authority-owned artifact-slot or ProductionBinding
identity; `expected_target_version` is that authority's exact CAS version.
Canon, NarrativePlan, CreativePolicy, Claim and governance identities are invalid
promotion targets. `PromotionReceipt.result_master_id` is non-null exactly for
`ARTIFACT_SLOT` and null exactly for `PRODUCTION_BINDING`.

A preview defaults to 900 seconds and validates
`0 < expires_at - issued_at <= 3600 seconds`. Preview configuration may shorten
but never exceed that maximum. `preview_command_id` is idempotent within
actor/user/project scope: exact replay returns the original preview; a different
semantic digest conflicts.

## 5. Ports and write authorities

```python
class ExplorationRepository(Protocol):
    async def append_revision(self, *, user_id: str, project_name: str,
                              candidate: ExplorationRevision,
                              expected_head_version: int | None,
                              command_id: str) -> CandidateHead: ...
    async def get_exact(self, *, user_id: str, project_name: str,
                        candidate_id: str, revision: int) -> ExplorationRevision | None: ...
    async def history(self, *, user_id: str, project_name: str,
                      candidate_id: str, after_revision: int | None,
                      limit: int) -> tuple[ExplorationRevision, ...]: ...

class PromotionPreviewService(Protocol):
    async def create_preview(self, *, user_id: str, project_name: str,
                             candidate_id: str, revision: int,
                             target: PromotionTarget,
                             command_id: str) -> PromotionPreview: ...

class ExplorationPromotionService(Protocol):
    async def promote(self, *, user_id: str, project_name: str,
                      authorization: PromotionAuthorization,
                      expected_candidate_head_version: int) -> PromotionReceipt: ...

class ObservationRepository(Protocol):
    async def ingest(self, *, user_id: str, project_name: str,
                     observation: LearningObservation,
                     command_id: str) -> LearningObservation: ...

class RecommendationService(Protocol):
    async def propose(self, *, user_id: str, project_name: str,
                      recommendation: LearningRecommendation,
                      command_id: str) -> LearningRecommendation: ...
    async def decide(self, *, user_id: str, project_name: str,
                     decision: RecommendationDecision,
                     command_id: str) -> RecommendationDecision: ...
```

Contracts and pure folds import no database, server, provider, renderer, React,
or donor runtime. Only repositories own ORM writes. Only the promotion service
may bridge a candidate into existing Production Authority. Recommendation code
has no production, Canon, Narrative, policy, routing, or governance write port.

## 6. Persistence and transaction rules

PostgreSQL stores candidate heads/revisions, previews, authorizations, promotion
receipts, observations/corrections, recommendations/decisions, output profiles,
overlay constraints, format plans/reports, parity reports, and command receipts.
Payloads and evidence are append-only; mutable heads use explicit expected-version
CAS. All public reads and writes scope by `(user_id, project_name)`; foreign and
unknown IDs are indistinguishable.

Candidate genesis uses a unique logical ID insert; concurrent genesis has one
winner. Revision append locks/rereads the head and validates exact predecessor.
Promotion first performs a scoped command-receipt lookup; an exact completed
replay returns before stale checks. A new command acquires or creates its command
key guard, then locks in this normative order: `(1)` candidate head, `(2)` preview,
`(3)` authority target row, `(4)` master head when the target is `ARTIFACT_SLOT`.
It then rechecks every digest/currentness/expiry field and appends promotion
receipt plus durable event before commit. Preview creation locks only its scoped
command key guard and candidate head, in that order. Every other M8 path that
touches more than one of these rows uses the same relative order.
External render/model work happens before a short transaction and is represented
by M7 execution/candidate evidence. No transaction spans network, renderer, or
media-store I/O.

Observation identity is source-scoped and idempotent. Same identity/same digest
replays; same identity/different digest requires a new correction record. Late
corrections never rewrite the original. Recommendation evidence resolves every
observation and latest correction as of a pinned evaluation cutoff.

## 7. Creative Canvas behavior

The frontend ports selected pure donor graph/history logic before integrating a
React Flow adapter. It preserves grouping, selection, ordering, bounded undo/redo,
bookmarks, multi-generation siblings, explicit clear intent, payload caps,
single in-flight save, edit coalescing, version waiters, canvas-switch isolation,
corrupt-draft rejection, seven-day pruning, and history-first shedding.

Seven-day pruning and history-first shedding apply only to the browser recovery
cache. M8 v1 never prunes server exploration revisions; a future server-retention
policy requires a separate authority decision and may not remove any revision
referenced by a preview, authorization, receipt, evaluation or ApprovedMaster.

Local drafts key by user/project/candidate and server revision, carry a content
signature, and never overwrite server data automatically after conflict. Empty
autosave is rejected unless a user-initiated clear command binds the exact prior
revision. Accessibility includes keyboard graph navigation, focus visibility,
screen-reader labels, localized accessible names, `eslint-plugin-jsx-a11y`
static checks, and automated `axe-core` browser checks. Performance is measured
through a pre-registered graph-size ladder ending at the sponsor-approved
production envelope; the protocol records exact node/edge counts, operation mix,
browser/build/hardware identity, repetitions, p50/p95 latency, peak memory,
bundle delta and pass thresholds before benchmark results exist;
failure blocks the React Flow adapter, not the exploration authority.

## 8. Spatial candidates

Spatial model calls are bounded M7 executions. Raw response digest, model/route
fingerprint, prompt/schema version, source media digests and normalization version
are retained. Deterministic normalization runs only after schema validation.
Visible assertions require source spans; inferred assertions require confidence;
unknown regions remain gaps. Seam/direction locks and duplicate warnings survive
serialization, revision, preview and promotion.

Malformed output, missing source, provider failure or normalization mismatch
creates no revision. A SpatialCandidate may inform a later ProductionBinding only
through preview and explicit promotion; the adapter must translate accepted
assertions and cannot promote gaps as facts.

## 9. Learning lifecycle

V1 implements observations, transparent cohort summaries, rule-based evidence
thresholds, offline replay and Human disposition. A trained ranker is outside V1
until sample size, holdout and calibration evidence justify it.

Internal adapters derive observations from usage, QA, approval and M7 execution
records without duplicating their authorities. Platform adapters retain API
family/scope, retrieval time, raw digest, metric definition, cumulative/windowed
semantics, missing/private/deleted outcomes and late corrections. A derived
feature links all raw inputs and its transformation version.

Only `CONCURRENT_RANDOMIZED` and `PLATFORM_MANAGED` evidence may use causal
language, limited to their measured surface. Sequential and offline observations
remain associative. Holdout is project-disjoint then future-time; sibling
revisions never split across train/evaluation. `generic-western` and `zh-shuang`
use separate corpora and qualified reviewers. At least two blind reviews retain
item evidence and disagreement; a pilot estimates variance/agreement before a
confirmatory sample is fixed.

The pre-registration freezes `rubric_version` and reviewer qualification before
results. Qualification records language/cultural cohort, rubric calibration
fixture results, role and conflict-of-interest declaration; reviewer identity may
be access-controlled but its stable evidence reference is mandatory.

## 10. Multi-format projection

OutputProfile and OverlayConstraintSet are versioned by platform, surface,
locale/UI variant, source references and effective date. Contract validation
fails closed on malformed ratios; it does not inherit convenience fallback.

Render adapters receive an immutable plan and resolved source bytes. M7 identity
binds input master digest, plan/output/overlay versions, reframe decisions,
runtime/codec/fps/duration settings and adapter version. Technical validation
checks dimensions, ratio, codec, duration, streams, corruption and overlay/caption
collisions. Semantic review compares focal subject, action, shot intent, text,
captions, timing and audio against the source master. Both reports must pass for
a FormatCandidate promotion preview.

## 11. Donor parity protocol

Each selected port begins with a baseline manifest generated before implementation:
exact URL/SHA/path hashes, reachable dependency surface, behaviors, tests,
fixtures, runtime/tool versions and resource workload. Donor tests run unmodified
where executable. The port runs the same canonical fixtures; a differential
harness emits one row per behavior and dimension. Donor defects may be corrected
only with a fixture that fails donor and passes the documented stronger R2 result.

Scope expansion automatically invalidates the prior parity report. Source-code
similarity, R2-only tests, historical green logs, manual impressions and optional
required skips cannot pass. Packet evidence names exact commands, exit codes,
logs/artifacts, integrated HEAD and independent reviewer. The verifier recomputes
digests and verdict; report authors cannot assert `PASS` contrary to rows.

## 12. Verification and exit matrix

| Gate | Required proof |
|---|---|
| A — authority | concurrent revision/promotion, stale preview, changed target/master/scope, retry-after-unknown, restart and cross-scope tests |
| B — Canvas | donor differential corpus, every selected donor test, draft/reload/clear/history, accessibility, bundle and graph-size evidence |
| C — Spatial | pinned pure fixtures, malformed/partial/model-failure corpus, deterministic normalization and no-fact/no-direct-write proof |
| D — Learning | source semantic/idempotency/correction fixtures, leakage tests, offline replay, causal-language and authority-boundary tests |
| E — Format | actual `16:9`, `9:16`, `1:1` renders, technical probes, overlay collision, blinded semantic parity and retry/recovery evidence |
| F — utility | profile-isolated end-to-end Western/`zh-shuang` workflows, pre-registered baseline/effect policy, resource and failure evidence |

Global exit requires zero authority bypasses, lost acknowledged edits, stale
promotions, profile leakage, untracked semantic reframes, donor parity regressions,
material unknowns and required skips. All relevant tests and affected repository
gates pass at a clean exact HEAD with machine-readable evidence and independent
review.

## 13. Packet order and stop codes

```text
M8-A exploration/promotion
  -> M8-B Canvas
  -> M8-C Spatial
  -> M8-D Learning
  -> M8-E Multi-format
  -> M8-F integrated utility
```

| Code | Meaning |
|---|---|
| `M8_PREREQUISITE_NOT_ACCEPTED` | exact clean accepted M7 lineage/evidence is absent |
| `M8_BASE_SEAM_CHANGED` | accepted host/M7 seam differs from the spec |
| `M8_DONOR_BASELINE_DRIFT` | donor revision/path/hash/reachable surface differs |
| `M8_DONOR_PARITY_BLOCKED` | material behavior/dimension is unverified or regressed |
| `M8_CANDIDATE_CONFLICT` | revision/head/OCC/currentness check failed |
| `M8_PROMOTION_BINDING_STALE` | preview, authorization, candidate, target or master binding changed/expired |
| `M8_PROFILE_COHORT_LEAK` | evidence crossed an undeclared profile/cohort boundary |
| `M8_FORMAT_PARITY_BLOCKED` | technical or semantic format report did not pass |
| `M8_EVALUATION_NOT_PREREGISTERED` | cohort/baseline/effect/window/exclusions were not locked before results |
| `M8_REQUIRED_EVIDENCE_MISSING` | required command, result, artifact, review or exact-HEAD binding is absent |
| `M8_ACCEPTED_SCHEMA_CHANGE_REQUIRED` | an accepted M8 migration requires a separately designed additive revision |

No packet authorizes live migration, provider/platform calls, credential use,
worker activation, deployment, publication, cleanup, or production approval.
