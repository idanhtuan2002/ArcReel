# R2-M10 Quality Evidence and Export Packaging Design

**Status:** Proposed for independent design review. This document authorizes
planning only; it does not authorize implementation or production activity.

## 1. Goal and boundary

M10 turns an exact ApprovedMaster into inspectable quality evidence, a Human
Final Cut disposition, an immutable package selection and a deterministic local
export bundle. It implements ADR-0080 and proposed ADR-0082 inside ArcReel, with
PostgreSQL as metadata authority and M7 as execution/receipt substrate.

M10 adds no Canon, NarrativePlan, factual, Production Approval, provider,
credential, upload, publish, scheduling, public-visibility or analytics
authority. License analysis is outside selection, design, review and acceptance.

Implementation starts only from an independently accepted predecessor chain:
M8 implementation, M9 implementation, durable Factual Authority, M7 execution
and one Alembic head. A0 must resolve the actual seams on that exact clean HEAD.
If candidate evolution, artifact identity, execution receipts or factual reads
do not match this design, it stops `POST_M8_BASE_SEAM_CHANGED`; it does not patch
the predecessor opportunistically.

## 2. Reuse disposition

| Source | Reuse | Constraint |
|---|---|---|
| ArcReel host | identity, artifact lineage, subtitles, manifest, PostgreSQL and secure subprocess behavior | existing `QualityReport` is legacy evidence, not M10 disposition |
| M7 | bounded execution, attempts, receipts, recovery and resource evidence | no M10 queue or parallel execution truth |
| M8 | canonical JSON/digests and accepted candidate revision/preview/promotion mechanics | extend only through accepted schema evolution; never target `ARTIFACT_SLOT` |
| Factual Authority | current claim/research evidence projection | read/receipt seam only; M10 cannot change claim truth |
| OpenMontage `08e2151fa02de28a5d6a312b3d575692bf147ad7` | export layout, chapter formatting and packaging fixtures | no filesystem or `publish_log` authority |
| Kalinga `e4b5a217` | vertical profile corpus, cheap-first checks, repair routing and export variants | no self-score, skipped gate or Markdown authority |
| FFmpeg/ffprobe | deterministic local probes | fixed argv, local-file protocol, deadline and resource ceiling |
| Netflix VMAF | named-reference render/transcode regression | forbidden when reference comparability is not proven |

Every donor surface uses the accepted `R2-DEC-031` parity contract with exact
pin, reachable behavior inventory, same-fixture tests, defect fixtures, resource
evidence and independently recomputed verdicts. License is excluded.

## 3. Canonical vocabulary and invariants

- **QualityProfile**: immutable policy revision for one cohort and product
  surface. It declares required assessors and thresholds; it is not a user score.
- **QualityRun**: immutable closure over exact subject, profile and observations.
- **QualityObservation**: typed evidence emitted by one declared assessor.
- **QualityDisposition**: Human authority decision `PASS`, `REWORK` or `WAIVE`.
- **PackageSelection**: append-only selection of one `PackagingCandidate`
  revision at `PACKAGING_SLOT`; it is not Production Approval.
- **ExportBundle**: deterministic local projection with a content-addressed
  manifest; it is not uploaded, published, scheduled or public.

All public models are frozen, extra-field-forbid Pydantic v2 models. IDs are
opaque repository-standard UUIDv7 strings. Timestamps are aware UTC. Digests are
lowercase `sha256:<64 hex>` over versioned canonical UTF-8 JSON. Every read and
mutation scopes by `(user_id, project_name)`; foreign and unknown identifiers are
indistinguishable. Exact command replay returns its receipt before stale checks;
same key with different semantics conflicts.

No metric, LLM, VMAF result, donor checkpoint, file presence or successful tool
exit may create a disposition or package selection. Missing, invalid, stale or
inapplicable evidence is explicit and never folded to zero or `PASS`.

## 4. Fixed contract families

The M10-A shapes below are normative at the field and invariant level. Task A0
may adjust import paths only after recording the accepted predecessor seam.
Packaging/export obligations are recorded separately in §4.2, but their exact
Pydantic union, target enum and digest schemas are deliberately **not** frozen by
M10-A design acceptance; M10-B freezes them only after accepted M10-A and a fresh
verification of the implemented M8 extension seam.

### 4.1 M10-A frozen contracts

```python
class AssessorKind(StrEnum):
    TECHNICAL = "TECHNICAL"
    FACTUAL = "FACTUAL"
    NARRATIVE = "NARRATIVE"
    CONTINUITY = "CONTINUITY"
    PERCEPTUAL = "PERCEPTUAL"
    ACCESSIBILITY = "ACCESSIBILITY"

class ObservationStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INAPPLICABLE = "INAPPLICABLE"
    INDETERMINATE = "INDETERMINATE"

class DispositionDecision(StrEnum):
    PASS = "PASS"
    REWORK = "REWORK"
    WAIVE = "WAIVE"

class AssessorClass(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    AUTHORITY = "AUTHORITY"
    MODEL = "MODEL"
    HUMAN = "HUMAN"

class RequirementMode(StrEnum):
    ALL = "ALL"
    N_OF_M = "N_OF_M"

class SupersessionEffect(StrEnum):
    HISTORICAL_ONLY = "HISTORICAL_ONLY"
    REEVALUATE_CURRENT = "REEVALUATE_CURRENT"

class AssessmentSlot(M10ContractModel):
    slot_id: str
    kind: AssessorKind
    assessor_class: AssessorClass
    qualification_policy_id: str
    qualification_policy_digest: Sha256Digest
    rule_ids: tuple[str, ...]
    allowed_applicability_states: tuple[ObservationStatus, ...]
    producer_conflict_forbidden: bool
    required_independence_groups: int = Field(ge=1)

class AssessmentRequirement(M10ContractModel):
    requirement_id: str
    mode: RequirementMode
    slots: tuple[AssessmentSlot, ...]
    minimum_satisfied_slots: int = Field(ge=1)
    disagreement_policy_id: str
    disagreement_policy_digest: Sha256Digest
    escalation_requirement_id: str | None

class ProbeRule(M10ContractModel):
    rule_id: str
    probe_kind: str
    tool_identity: str
    tool_version_constraint: str
    config_schema_id: str
    config_digest: Sha256Digest
    applicability_policy_id: str
    applicability_policy_digest: Sha256Digest
    threshold_policy_id: str
    threshold_policy_digest: Sha256Digest
    max_runtime_ms: int = Field(gt=0)
    max_output_bytes: int = Field(gt=0)

class FreshnessRule(M10ContractModel):
    rule_id: str
    evidence_kind: AssessorKind
    max_age_seconds: int = Field(gt=0)
    supersession_effect: SupersessionEffect

class DispositionRule(M10ContractModel):
    max_disposition_ttl_seconds: int = Field(gt=0, le=604800)
    max_waiver_ttl_seconds: int = Field(gt=0, le=86400)
    waiverable_rule_ids: tuple[str, ...]
    non_waiverable_failure_codes: tuple[str, ...]

class AccessibilityRule(M10ContractModel):
    conformance_target: str
    language: str
    caption_rubric_id: str
    caption_rubric_digest: Sha256Digest
    audio_description_policy_id: str
    audio_description_policy_digest: Sha256Digest

class QualityPolicyV1(M10ContractModel):
    schema_id: Literal["m10.quality-policy.v1"]
    probe_rules: tuple[ProbeRule, ...]
    assessment_requirements: tuple[AssessmentRequirement, ...]
    freshness_rules: tuple[FreshnessRule, ...]
    disposition_rule: DispositionRule
    accessibility_rules: tuple[AccessibilityRule, ...]
    reference_eligibility_policy_id: str
    reference_eligibility_policy_digest: Sha256Digest

class QualityProfileRevision(M10ContractModel):
    profile_id: str
    revision: int
    cohort_id: str
    product_surface: str
    policy: QualityPolicyV1
    policy_digest: Sha256Digest
    profile_digest: Sha256Digest
    parent_revision: int | None
    supersession_effect: SupersessionEffect
    publication_authorization_id: str
    publication_policy_id: str
    publication_policy_version: str
    publication_evidence_digest: Sha256Digest
    publication_admitted_at: AwareDatetime
    created_by: str
    created_at: AwareDatetime

class AssessedSubject(M10ContractModel):
    approved_master_id: str
    artifact_ref: str
    artifact_digest: Sha256Digest
    content_basis_digest: Sha256Digest
    caption_digest: Sha256Digest | None
    audio_digest: Sha256Digest | None

class ObservationType(StrEnum):
    TECHNICAL = "TECHNICAL"
    FACTUAL = "FACTUAL"
    NARRATIVE = "NARRATIVE"
    CONTINUITY = "CONTINUITY"
    PERCEPTUAL_REGRESSION = "PERCEPTUAL_REGRESSION"
    PERCEPTUAL_REVIEW = "PERCEPTUAL_REVIEW"
    ACCESSIBILITY = "ACCESSIBILITY"

class QualityFinding(M10ContractModel):
    finding_id: str
    rule_id: str
    severity: Literal["BLOCKING", "ADVISORY"]
    subject_locator: str
    evidence_digest: Sha256Digest

class ObservationBase(M10ContractModel):
    observation_id: str
    observation_type: ObservationType
    requirement_id: str
    slot_id: str
    assessor_identity: str
    assessor_version: str
    assessor_qualification_ref: str
    assessor_qualification_digest: Sha256Digest
    independence_group: str
    producer_conflict: bool
    config_digest: Sha256Digest
    subject_digest: Sha256Digest
    status: ObservationStatus
    findings: tuple[QualityFinding, ...]
    evidence_refs: tuple[str, ...]
    evidence_digest: Sha256Digest
    observed_at: AwareDatetime

class TechnicalObservation(ObservationBase):
    observation_type: Literal[ObservationType.TECHNICAL]
    rule_id: str
    probe_receipt_ref: str
    probe_receipt_digest: Sha256Digest
    tool_identity_digest: Sha256Digest
    measurement_schema_id: str
    measurement_digest: Sha256Digest
    interval_evidence_digest: Sha256Digest | None

class FactualObservation(ObservationBase):
    observation_type: Literal[ObservationType.FACTUAL]
    claim_ledger_projection_ref: str
    claim_ledger_projection_digest: Sha256Digest
    research_pack_ref: str
    research_pack_digest: Sha256Digest
    correction_head_digest: Sha256Digest
    coverage_digest: Sha256Digest
    withdrawn: bool

class NarrativeObservation(ObservationBase):
    observation_type: Literal[ObservationType.NARRATIVE]
    rubric_id: str
    rubric_digest: Sha256Digest
    segment_closure_digest: Sha256Digest
    reviewer_evidence_digest: Sha256Digest

class ContinuityObservation(ObservationBase):
    observation_type: Literal[ObservationType.CONTINUITY]
    canon_projection_digest: Sha256Digest
    epistemic_projection_digest: Sha256Digest
    visual_identity_projection_digest: Sha256Digest
    invariant_ids: tuple[str, ...]

class PerceptualRegressionObservation(ObservationBase):
    observation_type: Literal[ObservationType.PERCEPTUAL_REGRESSION]
    reference_relationship: str
    reference_subject_digest: Sha256Digest
    distorted_subject_digest: Sha256Digest
    alignment_policy_digest: Sha256Digest
    model_identity_digest: Sha256Digest
    segment_result_digest: Sha256Digest

class PerceptualReviewObservation(ObservationBase):
    observation_type: Literal[ObservationType.PERCEPTUAL_REVIEW]
    rubric_id: str
    rubric_digest: Sha256Digest
    model_or_human_identity_digest: Sha256Digest
    calibration_cohort_digest: Sha256Digest
    sampling_policy_digest: Sha256Digest

class AccessibilityObservation(ObservationBase):
    observation_type: Literal[ObservationType.ACCESSIBILITY]
    conformance_target: str
    language: str
    caption_artifact_digest: Sha256Digest | None
    audio_description_artifact_digest: Sha256Digest | None
    speech_coverage_digest: Sha256Digest
    non_speech_coverage_digest: Sha256Digest
    synchronization_digest: Sha256Digest
    legibility_collision_digest: Sha256Digest

QualityObservation = Annotated[
    TechnicalObservation
    | FactualObservation
    | NarrativeObservation
    | ContinuityObservation
    | PerceptualRegressionObservation
    | PerceptualReviewObservation
    | AccessibilityObservation,
    Field(discriminator="observation_type"),
]

class AssessmentSlotResult(M10ContractModel):
    requirement_id: str
    slot_id: str
    observation_refs: tuple[str, ...]
    observation_digests: tuple[Sha256Digest, ...]
    distinct_independence_groups: tuple[str, ...]
    state: Literal["SATISFIED", "NOT_APPLICABLE", "FAILED", "INDETERMINATE"]
    escalation_observation_refs: tuple[str, ...]

class QualityRun(M10ContractModel):
    run_id: str
    subject: AssessedSubject
    subject_digest: Sha256Digest
    profile_id: str
    profile_revision: int
    profile_digest: Sha256Digest
    observation_refs: tuple[str, ...]
    observation_closure_digest: Sha256Digest
    slot_results: tuple[AssessmentSlotResult, ...]
    requirements_digest: Sha256Digest
    execution_refs: tuple[str, ...]
    completed_at: AwareDatetime

class WaiverBinding(M10ContractModel):
    rule_id: str
    finding_id: str | None
    scope: str
    justification: str

class CommandEnvelope(M10ContractModel):
    user_id: str
    project_name: str
    actor_id: str
    operation: str
    command_id: str
    request_digest: Sha256Digest

class CommandReceipt(M10ContractModel):
    command: CommandEnvelope
    result_ref: str
    result_digest: Sha256Digest
    committed_at: AwareDatetime

class ProfilePublicationAuthorizationLease(M10ContractModel):
    authorization_id: str
    action: Literal["PROFILE_PUBLICATION"]
    user_id: str
    project_name: str
    actor_id: str
    command_id: str
    request_digest: Sha256Digest
    subject_digest: Sha256Digest
    policy_id: str
    policy_version: str
    evidence_digest: Sha256Digest
    issued_at: AwareDatetime
    admit_not_after: AwareDatetime

class DispositionAuthorizationLease(M10ContractModel):
    authorization_id: str
    action: Literal["QUALITY_DISPOSITION"]
    user_id: str
    project_name: str
    actor_id: str
    command_id: str
    request_digest: Sha256Digest
    subject_digest: Sha256Digest
    policy_id: str
    policy_version: str
    evidence_digest: Sha256Digest
    issued_at: AwareDatetime
    admit_not_after: AwareDatetime

class QualityDisposition(M10ContractModel):
    disposition_id: str
    subject_digest: Sha256Digest
    quality_run_id: str
    quality_run_digest: Sha256Digest
    profile_digest: Sha256Digest
    decision: DispositionDecision
    waiver_bindings: tuple[WaiverBinding, ...]
    issuer_id: str
    custodian_authorization_id: str
    custodian_policy_id: str
    custodian_policy_version: str
    custodian_evidence_digest: Sha256Digest
    custodian_admitted_at: AwareDatetime
    reason: str
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    supersedes_disposition_id: str | None
```

Profile publication uses append-only revisions plus an explicit CAS head.
Every rule, requirement and slot ID is non-empty and unique within the profile.
`minimum_satisfied_slots` cannot exceed the number of slots; `ALL` requires it
to equal that number; escalation references must exist and the escalation graph
must be acyclic. The server recomputes both `policy_digest` and `profile_digest`
before persistence and rejects caller mismatch.
`AssessmentRequirement` and its stable `slot_id` values—not a tuple of assessor
kinds—are completeness authority. `ALL` requires every slot; `N_OF_M` requires
the declared minimum, qualification and distinct-independence-group count.
Disagreement may activate only the named escalation requirement. Every slot
result binds its observations and independence groups; `INDETERMINATE` blocks
`PASS`, while `NOT_APPLICABLE` is legal only when both the slot and observation
carry a policy-allowed applicability state. Observation identity/config,
qualification, evidence and subject are included in the closure digest.

`PASS` requires complete current evidence and no failing required observation.
`REWORK` binds the same closure and carries repair routing in its evidence.
Every disposition expires: `issued_at < expires_at`, bounded by the profile and
never beyond seven days. `WAIVE` requires non-empty `WaiverBinding` rows whose
stable `rule_id`, optional `finding_id`, scope and justification are all allowed
by `DispositionRule`, plus a decision reason and
a stricter maximum of 24 hours; it cannot waive identity, subject-integrity,
authority, missing closure or stale-evidence failures. Narrative, continuity,
perceptual and accessibility Human evidence must come from a qualified
independence group distinct from the artifact producer; model-produced evidence
records `producer_conflict` and cannot satisfy a required independent-Human row.

### 4.2 M10-B minimum contract obligations, not frozen by M10-A

The following shapes specify required bindings for the later M10-B design
amendment. They are not part of the M10-A contract module or digest-vector set.
M10-B must rederive the exact candidate union, promotion target and repository
shape from accepted M8 code, then independently review and freeze the amendment.

```python
class PackagingAsset(M10ContractModel):
    role: str
    source_ref: str
    content_digest: Sha256Digest
    media_type: str
    constraint_rule_id: str

class PackagingAssessedSubject(M10ContractModel):
    base_subject_digest: Sha256Digest
    packaging_candidate_id: str
    packaging_candidate_revision: int = Field(ge=1)
    packaging_candidate_digest: Sha256Digest
    constraint_snapshot_digest: Sha256Digest

class LocalizedPackagingMetadata(M10ContractModel):
    locale: str
    title: str
    description: str
    tags: tuple[str, ...]
    hashtags: tuple[str, ...]
    chapters_digest: Sha256Digest

class AudienceClassification(M10ContractModel):
    audience_category: str
    age_restriction: str | None
    classification_policy_digest: Sha256Digest

class DisclosureSet(M10ContractModel):
    synthetic_media: bool
    paid_promotion: bool
    disclosure_policy_digest: Sha256Digest

class PackagingObservation(M10ContractModel):
    observation_type: Literal["PACKAGING"]
    requirement_id: str
    slot_id: str
    packaging_candidate_digest: Sha256Digest
    constraint_snapshot_digest: Sha256Digest
    rule_results_digest: Sha256Digest
    findings: tuple[QualityFinding, ...]
    evidence_digest: Sha256Digest

class PackagingSelectionAuthorizationLease(M10ContractModel):
    authorization_id: str
    action: Literal["PACKAGING_SELECTION"]
    user_id: str
    project_name: str
    actor_id: str
    command_id: str
    request_digest: Sha256Digest
    subject_digest: Sha256Digest
    policy_id: str
    policy_version: str
    evidence_digest: Sha256Digest
    issued_at: AwareDatetime
    admit_not_after: AwareDatetime

class PackagingCandidate(M10ContractModel):
    kind: Literal["PACKAGING"]
    approved_master_id: str
    approved_master_digest: Sha256Digest
    content_closure_digest: Sha256Digest
    presentation_closure_digest: Sha256Digest
    quality_profile_id: str
    quality_profile_digest: Sha256Digest
    platform_profile_id: str
    platform_profile_revision: str
    constraint_snapshot_digest: Sha256Digest
    title: str
    description: str
    tags: tuple[str, ...]
    hashtags: tuple[str, ...]
    chapters: tuple[CanonicalJsonObject, ...]
    localization_variants: tuple[LocalizedPackagingMetadata, ...]
    audience_classification: AudienceClassification
    disclosure: DisclosureSet
    assets: tuple[PackagingAsset, ...]
    payload_digest: Sha256Digest

class PackageSelection(M10ContractModel):
    receipt_id: str
    command_id: str
    request_digest: Sha256Digest
    candidate_id: str
    candidate_revision: int
    candidate_payload_digest: Sha256Digest
    approved_master_digest: Sha256Digest
    quality_disposition_id: str
    quality_disposition_digest: Sha256Digest
    expected_packaging_head_version: int
    selected_by: str
    selection_authorization_id: str
    selection_policy_id: str
    selection_policy_version: str
    selection_evidence_digest: Sha256Digest
    selection_admitted_at: AwareDatetime
    selected_at: AwareDatetime

class ExportManifestEntry(M10ContractModel):
    relative_path: str
    role: str
    media_type: str
    byte_size: int
    content_digest: Sha256Digest

class ExportManifest(M10ContractModel):
    schema_id: Literal["m10.export-manifest.v1"]
    package_selection_digest: Sha256Digest
    quality_disposition_digest: Sha256Digest
    exporter_implementation: str
    exporter_version: str
    exporter_config_digest: Sha256Digest
    entries: tuple[ExportManifestEntry, ...]
    manifest_digest: Sha256Digest

class ExportBundleReceipt(M10ContractModel):
    receipt_id: str
    command_id: str
    request_digest: Sha256Digest
    manifest: ExportManifest
    manifest_digest: Sha256Digest
    execution_ref: str
    exported_at: AwareDatetime
```

No candidate-supplied boolean controls asset requiredness. M10-B recomputes each
asset's required/optional state from the exact profile constraint snapshot and
rejects undeclared or missing required roles. `PackagingCandidate` becomes part
of the candidate union only through an
accepted M8 schema evolution. `PACKAGING_SLOT` is a new closed target owned by
M10 Packaging Authority. Preview and selection bind exact candidate revision,
payload, ApprovedMaster, current disposition, scope and expected packaging-head
CAS. Paths are normalized, relative, unique and traversal-free. Bundle output is
staged, hashed, fsynced and atomically made visible after complete verification;
an exact replay returns the original receipt.

The M10-B amendment must extend the accepted observation union with
`PackagingObservation` using every common assessor/qualification/independence/
subject/status field from M10-A; the abbreviated shape above lists only its
additional package-specific bindings. It must not add package fields to the
already accepted M10-A `AssessedSubject`; it uses `PackagingAssessedSubject`.

## 5. Digest domains, command identity and validity

### 5.1 Domains frozen by M10-A

Every request hash begins with its domain tag and schema version. Server-issued
receipt IDs and commit timestamps are excluded from request digests and included
only in result/receipt digests. `CommandEnvelope.request_digest` covers the full
semantic request excluding `command_id`; the durable receipt key remains
`(user_id, actor_id, operation, command_id)`. M10 reuses the accepted
predecessor canonical JSON byte algorithm, but owns these domain tags:

| Domain | Required closure |
|---|---|
| `m10.quality-policy.v1` | entire frozen `QualityPolicyV1`, including rules, slots, qualifications, independence, freshness, disposition and accessibility |
| `m10.quality-profile.v1` | scope, profile identity/revision/parent, cohort/product surface, `policy_digest`, supersession effect, publication authorization/policy/evidence/admitted-time binding, creator and creation time |
| `m10.assessed-subject.v1` | exact ApprovedMaster, artifact/content basis, caption and audio identities/digests; no package fields |
| `m10.technical-observation.v1` | common observation binding plus probe receipt, tool, rule, measurement and interval evidence |
| `m10.factual-observation.v1` | common binding plus ClaimLedger/ResearchPack projections, correction head, coverage and withdrawal state |
| `m10.narrative-observation.v1` | common binding plus rubric, segment closure and reviewer evidence |
| `m10.continuity-observation.v1` | common binding plus Canon/epistemic/visual projections and invariant IDs |
| `m10.perceptual-regression-observation.v1` | common binding plus exact reference relationship, alignment, model and segment evidence |
| `m10.perceptual-review-observation.v1` | common binding plus rubric, assessor, calibration cohort and sampling policy |
| `m10.accessibility-observation.v1` | common binding plus conformance/language and caption/audio-description/coverage/synchronization/legibility evidence |
| `m10.assessment-requirements.v1` | ordered requirement/slot graph, N-of-M rules, qualifications, independence and escalation policy |
| `m10.quality-run.v1` | subject/profile, sorted variant-tagged observation closure, slot results, requirement digest and execution refs |
| `m10.waiver-binding.v1` | stable rule/finding identity, scope and justification |
| `m10.quality-disposition.v1` | run/subject/profile, decision, sorted waiver bindings, issuer/custodian authority, reason, issue/expiry and supersession |
| `m10.profile-publication-subject.v1` | exact scope/actor, profile identity/parent, policy digest, supersession effect and expected head |
| `m10.disposition-subject.v1` | exact scope/actor, subject/run/profile, decision, sorted waivers, reason, expiry and expected head |
| `m10.profile-publication-request.v1` | command scope/actor, profile identity/parent, policy/profile payload and expected head |
| `m10.run-completion-request.v1` | command scope/actor, subject/profile and exact observation/execution closure |
| `m10.disposition-request.v1` | command scope/actor, subject/run/profile, decision/waivers/reason, expiry and expected head |
| `m10.command-key-guard.v1` | exact user/actor/operation/command tuple; truncated advisory hash serializes only and is never identity |

`policy_digest` is exactly `m10.quality-policy.v1` over `QualityPolicyV1`.
`profile_digest` is exactly `m10.quality-profile.v1` and includes
`policy_digest`; the two names are never aliases.

### 5.2 Domains reserved for the M10-B amendment

`m10.packaging-observation.v1`, `m10.packaging-candidate.v1`,
`m10.package-selection-request.v1`, `m10.package-selection.v1`,
`m10.export-request.v1`, `m10.export-manifest.v1` and
`m10.export-execution.v1` are reserved names, not M10-A frozen vectors. M10-B
defines exact closures after seam verification. At minimum the manifest domain
must bind package selection, disposition, exporter implementation/version/config
and sorted path/role/media-type/size/content-digest rows; the execution domain
must bind that manifest, exact M7 execution receipt and final byte verification.

A validity projection returns `CURRENT`, `STALE`, `EXPIRED`, `SUPERSEDED` or
`INVALIDATED`; it never rewrites history. A newer profile head invalidates
current readiness only when the applicable new revision declares
`REEVALUATE_CURRENT`; `HISTORICAL_ONLY` preserves current readiness until its
normal evidence/disposition expiry. Any bound subject/run digest drift,
deletion/invalidation, required reevaluation, disposition expiry or explicit
supersession fails closed.

## 6. Deep modules and seams

Public seams remain small:

```python
class QualityProbePort(Protocol):
    async def observe(self, request: ProbeRequest) -> ProbeReceipt: ...

class QualityRunService(Protocol):
    async def complete(self, command: CompleteRunCommand) -> QualityRun: ...

class ProfilePublicationCustodianPort(Protocol):
    async def authorize_publication(
        self, request: ProfilePublicationAuthorizationRequest
    ) -> ProfilePublicationAuthorizationLease: ...

class QualityDispositionCustodianPort(Protocol):
    async def authorize_disposition(
        self, request: DispositionAuthorizationRequest
    ) -> DispositionAuthorizationLease: ...

# M10-B only; absent from the M10-A implementation surface.
class PackagingSelectionCustodianPort(Protocol):
    async def authorize_selection(
        self, request: PackagingSelectionAuthorizationRequest
    ) -> PackagingSelectionAuthorizationLease: ...

class PackagingService(Protocol):
    async def preview(self, command: PackagePreviewCommand) -> PackagePreview: ...
    async def select(self, command: PackageSelectionCommand) -> PackageSelection: ...

class ExportBundlePort(Protocol):
    async def materialize(self, command: ExportBundleCommand) -> ExportBundleReceipt: ...
```

Probe adapters hide tool invocation and parsing; callers receive typed evidence,
not raw subprocess behavior. QualityRun owns closure validation. Disposition
Authority owns decisions. Packaging owns only its head. Export owns deterministic
local materialization. No module receives a network or Production Authority
write port.

The factual adapter reads an exact current ClaimLedger/ResearchPack projection
and returns its identity, digest, correction head, withdrawal state and validity
receipt. Withdrawn, corrected-without-current-review or stale factual evidence
invalidates the observation closure; M10 has no factual write port.

Custodian authorization happens outside the transaction and returns a lease
binding actor, command, subject, decision, policy revision and expiry. Admission
uses database time and a maximum 30-second lease window. Finalization first
checks the scoped command receipt, then the command-key advisory guard, then
locks profile/run/subject/current-disposition heads in stable order, revalidates
the lease and appends decision, receipt and outbox event atomically.

Packaging selection uses receipt-first replay, command-key guard, then candidate
head, preview, ApprovedMaster projection, disposition head and packaging head.
It performs no external I/O in the transaction. Export prepares from a current
selection, executes through M7 outside its metadata transaction, then finalizes
only after recomputing every byte digest and current binding.

## 7. Deterministic probes and assessor policy

Initial technical probes are declared by the profile and run cheap-first:
container/stream conformance, duration/dimensions/frame rate, decoding failure,
black/freeze/silence intervals, loudness/true peak and caption parse/timing
bounds. Package asset integrity is added only by the M10-B amendment. Commands use a fixed executable and argv allowlist,
no shell, local-file-only protocol, bounded input/output/runtime/process count,
captured tool version/config and sanitized evidence. Timeout, nonzero exit,
truncated output and parse ambiguity are typed failures.

Profile policy also fixes assessor qualification/independence rules, caption
language and accessibility conformance target, VMAF reference relationships and
alignment tolerances, evidence freshness and tool/calibration supersession.
M10-B adds a typed platform-constraint snapshot to its profile amendment;
changed first-party packaging constraints produce a newly published revision,
never mutate old evidence and never grant network authority.

VMAF is allowed only when the profile declares a named reference relationship
and the adapter proves comparable content, timing and geometry. It remains a
`PERCEPTUAL` or technical-regression observation, never a disposition.

Factual observations consume current Factual Authority projections. Narrative,
continuity, perceptual and accessibility observations declare reviewer/model
identity, calibration corpus, conflicts and independence class. ASR text alone
cannot satisfy caption accessibility. Cohort-specific thresholds and rubrics do
not silently pool Western explainer, vertical factual Short and `zh-shuang`.

## 8. Persistence and isolation

M10 owns profile revisions/heads, commands/receipts, probe attempts, observation
metadata, run closures, dispositions/heads, packaging candidate extension rows,
package selections/heads, export manifests and outbox events. Large or
retention-sensitive evidence stays behind an opaque evidence-store reference;
PostgreSQL stores integrity and policy-permitted metadata.

All mutations use expected-version CAS and append-only records. Repository
methods take explicit `user_id` and `project_name`. Logs/events contain bounded
IDs, enums and digests, never media bytes, prompts, captions, credentials or
review prose. Metric labels are limited to operation, assessor kind, state and
stop code.

## 9. Stop codes

| Code | Meaning |
|---|---|
| `M10_DESIGN_NOT_ACCEPTED` | ADR/spec acceptance is absent or invalid |
| `M10_PREREQUISITE_NOT_ACCEPTED` | accepted M9/M8/M7/Factual chain is absent |
| `POST_M8_BASE_SEAM_CHANGED` | live accepted predecessor differs materially |
| `M10_SCHEMA_CHANGE_REQUIRED` | accepted contract/migration needs additive evolution |
| `M10_PROFILE_STALE` | bound profile is invalid or an applicable newer revision requires `REEVALUATE_CURRENT` |
| `M10_PROFILE_PUBLICATION_UNAUTHORIZED` | profile-publication Human lease/action/subject/policy binding is absent or invalid |
| `M10_SUBJECT_STALE` | ApprovedMaster or assessed-subject closure changed |
| `M10_REQUIRED_EVIDENCE_MISSING` | required observation/evidence closure is incomplete |
| `M10_REFERENCE_INVALID` | reference-based metric lacks proven comparability |
| `M10_PROBE_FAILED` | deterministic probe cannot produce valid complete evidence |
| `M10_OPERATIONAL_ENVELOPE_EXCEEDED` | declared resource bound is exceeded |
| `M10_DISPOSITION_UNAUTHORIZED` | Human custodian lease is absent/invalid |
| `M10_DISPOSITION_STALE` | disposition is expired, superseded or binding-stale |
| `M10_WAIVER_FORBIDDEN` | requested waiver scope/time is not permitted |
| `M10_PACKAGING_TARGET_FORBIDDEN` | target is not `PACKAGING_SLOT` |
| `M10_COMMAND_REPLAY_CONFLICT` | command key was reused with different semantics |
| `M10_STALE_HEAD` | expected CAS head differs |
| `M10_EXPORT_INTEGRITY_FAILED` | staged bundle differs from manifest/source closure |
| `M10_NETWORK_SIDE_EFFECT_FORBIDDEN` | operation attempts provider/network publication |
| `M10_DONOR_PARITY_INCOMPLETE` | required parity evidence is not accepted |

## 10. Packet sequence and acceptance

1. **M10-A Quality-evidence foundation:** prerequisite verifier, frozen
   contracts/digests/stop codes, profile publication, secure deterministic
   probes, typed multi-assessor closure, validity/readiness projection, Human
   disposition and donor-parity/resource evidence. It creates no packaging
   candidate, export directory or network interface.
2. **M10-B Packaging and deterministic export:** accepted M8 schema evolution,
   `PackagingCandidate`, `PACKAGING_SLOT`, preview/selection, package-scoped
   quality closure, deterministic bundle/verifier and Western explainer →
   vertical factual Short → `zh-shuang` export-only pilots.
3. **M10-C Integrated acceptance (conditional):** if repository convention
   requires a separate integration packet, bind accepted A/B heads, migrations,
   parity, resource and pilot evidence without broadening the domain model.

Only M10-A may be authored before accepted prerequisites, and then only with an
A0 read-only preflight that writes no production file on failure. M10-B/C are
released from accepted predecessor code, not guessed now.

The design-acceptance candidate—not M10-A implementation—must include
`scripts/r2/verify_m10_bootstrap.py` and tests as hash-bound acceptance
artifacts. That script verifies the design acceptance envelope and offers a
repository-read-only `--preflight` mode for prerequisite lineage, clean owned
paths and singleton migration head. On failure it prints a structured receipt
and may write `/tmp/r2-m10-stop.json`; it never writes inside the repository.
Only after this bootstrap returns `IMPLEMENTATION_ELIGIBLE` may Task A0 create
the distinct implementation-time `scripts/r2/verify_m10_scope.py`.

Design acceptance requires the ADR, research, this design, umbrella/M10-A
plans, bootstrap verifier and its tests to be hash-bound to one candidate HEAD;
two fresh independent reviews use
the same frozen rubric; acceptance is a separate custodian commit. Required
review checks include authority separation, predecessor reality, contract/digest
completeness, validity/waiver semantics, transaction/replay order, probe safety,
packaging target isolation, export determinism, no-network proof and executable
acceptance custody.

M10 completion requires all packets independently accepted in sequence, a
single reversible migration lineage, zero required skips/material unknowns,
donor parity for selected surfaces, all three export-only pilots and explicit
proof that no network or Production Authority write route is reachable.
