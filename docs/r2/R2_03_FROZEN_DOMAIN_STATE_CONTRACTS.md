# R2.3 — Frozen Domain & State Contracts

**Project:** Content & Narrative Production OS  
**Phase:** R2 — Architecture Freeze  
**Date:** 2026-09-06  
**Status:** **FROZEN v1**  
**Approval:** Human Showrunner approved R2.3 on 2026-09-06  
**Depends on:** `R2_01_FROZEN_ARCHITECTURE.md`, `R2_02_FROZEN_RESPONSIBILITY_MATRIX.md`

---

# 1. Purpose

R2.3 freezes the domain boundaries and state semantics that all implementation work must preserve.

This document is authoritative for:
- contract families;
- stable identity/version semantics;
- state-machine separation;
- ContentBasis;
- narrative/canon/adaptation boundaries;
- SceneSpec/ShotSpec neutrality;
- ProductionBinding;
- readiness;
- method and prompt/provider separation;
- candidate/master semantics;
- fingerprints;
- dependency graph rules;
- provenance.

This document intentionally does **not** freeze SQL tables or ORM layout.

---

# 2. Contract design principles

## 2.1 Domain-first

Contracts describe the system's meaning first.

Implementation mapping follows later:

```text
R2 domain contract
→ application interface
→ ArcReel/PostgreSQL/storage mapping
```

Do not design domain semantics around donor table layout.

---

## 2.2 Stable identity vs revision

Every durable logical object uses:

```text
logical_id = stable identity
version    = monotonic object revision
```

Example:

```text
shot_id = SH042
version = 7
```

Do not encode revision into the logical ID.

---

## 2.3 Schema version is independent

```text
schema_version ≠ object version
```

Example:

```text
shot_id        = SH042
version        = 7
schema_version = "2.1"
```

Schema migration and object revision are independent concerns.

---

# 3. Common contract metadata

Cross-authority and durable R2 contracts support a common metadata shape where applicable:

```text
ContractMetadata
  id
  contract_type
  schema_version

  project_id

  version
  created_at
  created_by

  provenance

  content_basis?   # required at production boundary
```

Not every internal value object must carry the complete envelope.

---

# 4. Contract families

R2 freezes seven primary contract families:

1. Factual Authority
2. Canon / Narrative Authority
3. Authorial Intent
4. Narrative Working / Proposal
5. Adaptation
6. Universal Production
7. Production Preparation / Execution / Result

---

# 5. Factual Authority contracts

Primary contracts:

```text
SourceRecord
EvidenceRecord
ResearchPack
Claim
ClaimLedger
```

## 5.1 SourceRecord

```text
SourceRecord
  source_id
  source_type
  title?
  origin
  captured_at

  author?
  published_at?
  retrieved_at?

  source_fingerprint
  provenance
```

SourceRecord stores source identity/provenance, not an interpreted claim.

---

## 5.2 EvidenceRecord

```text
EvidenceRecord
  evidence_id
  source_ref

  locator
  excerpt_or_structured_fact?

  evidence_type
  captured_at

  provenance
```

Evidence is addressable independently so claims can reference exact evidence rather than a whole source.

---

## 5.3 ResearchPack

```text
ResearchPack
  research_pack_id
  version

  topic
  scope
  source_refs[]
  evidence_refs[]

  synthesis
  uncertainties[]
  open_questions[]

  provenance
```

ResearchPack is factual working authority, not fiction Canon.

---

## 5.4 Claim

```text
Claim
  claim_id
  version

  statement

  evidence_refs[]
  confidence

  status:
    PROPOSED
    VERIFIED
    DISPUTED
    RETIRED

  valid_from?
  valid_until?

  provenance
```

---

## 5.5 ClaimLedger

```text
ClaimLedger
  ledger_id
  version

  research_pack_ref
  claims[]
```

Production uses claim references through ContentBasis rather than copying factual truth into ShotSpec.

---

# 6. Canon / Narrative Authority contracts

Primary contracts:

```text
CanonBranch
CanonVersion

Entity
Fact
Event

TemporalRelation
CausalRelation

CharacterState
RelationshipState
ObjectState
LocationState

KnowledgeState
WorldRule
PlotThreadTruth
```

---

## 6.1 CanonBranch

```text
CanonBranch
  branch_id
  branch_type:
    MAIN
    NARRATIVE_BRANCH

  parent_branch_id?
  parent_version?

  created_at
  created_by
```

Adaptation branches are handled separately.

---

## 6.2 CanonVersion

```text
CanonVersion
  canon_version_id
  branch_id
  version

  parent_version_id?

  committed_delta_ref
  committed_at
  committed_by

  content_hash
```

A CanonVersion is immutable once committed.

---

## 6.3 Entity

```text
Entity
  entity_id
  entity_type:
    CHARACTER
    LOCATION
    OBJECT
    ORGANIZATION
    CONCEPT
    OTHER

  canonical_name
  aliases[]
```

Entity identity is semantic identity, not production asset identity.

---

## 6.4 Fact

```text
Fact
  fact_id
  subject_ref
  predicate
  object_or_value

  effective_from?
  effective_until?

  source_event_refs[]
```

---

## 6.5 Event

```text
Event
  event_id

  event_type
  participants[]
  location_ref?

  temporal_anchor
  causal_refs[]

  state_effect_refs[]
```

---

## 6.6 KnowledgeState

Knowledge is first-class.

```text
KnowledgeState
  knowledge_state_id

  subject_entity_id
  proposition_ref

  epistemic_state:
    KNOWN
    SUSPECTED
    FALSE_BELIEF
    UNKNOWN

  effective_from
  effective_until?

  evidence_event_refs[]
```

Knowledge must not be hidden in character summaries.

---

# 7. Authorial Intent contracts

Frozen hierarchy:

```text
StoryFrame
→ VolumePlan / EpisodePlan
→ ArcPlan
→ ChapterPlan
→ SceneContract
```

Not every medium uses every layer.

---

## 7.1 StoryFrame

```text
StoryFrame
  story_frame_id
  version

  premise
  core_conflict
  thematic_intent

  major_character_refs[]
  major_thread_refs[]

  target_medium_profile?
```

---

## 7.2 VolumePlan / EpisodePlan / ArcPlan / ChapterPlan

Each plan contract contains:
- stable logical ID;
- version;
- parent plan ref;
- intent;
- expected progression;
- contained child refs;
- constraints;
- approval metadata.

Planned future outcomes are not Canon facts.

---

## 7.3 SceneContract

Primary creative execution/review unit:

```text
SceneContract
  scene_contract_id
  version

  purpose
  pov?

  location_ref?
  temporal_window?

  participants[]

  required_events[]
  forbidden_events[]

  required_reveals[]
  forbidden_knowledge[]

  entry_state_constraints[]
  exit_state_targets[]

  active_threads[]
  promise_payoff_refs[]

  creative_constraints[]
```

SceneContract describes authorial intent, not committed narrative truth.

---

## 7.4 CreativePolicy

```text
CreativePolicy
  creative_policy_id
  version

  genre
  tone
  style_constraints[]

  pov_policy?
  pacing_policy?
  violence_policy?
  visual_policy?
  dialogue_policy?

  format_constraints[]
```

Analytics cannot directly mutate CreativePolicy.

---

# 8. Narrative Working / Proposal contracts

These contracts are non-authoritative until committed through the correct authority.

```text
NarrativeContextPack
SimulationScenario
SimulationEvent
DraftCandidate
NarrativeRevision
NarrativeReviewReport
NarrativeChangeSet
CanonDelta
```

---

## 8.1 NarrativeContextPack

```text
NarrativeContextPack
  context_pack_id

  base_canon_version
  epistemic_view_ref
  narrative_plan_refs[]
  creative_policy_ref

  scene_contract_ref
  pov
  temporal_context

  recent_accepted_context[]
  retrieved_context[]

  token_budget
  compiler_version
```

This object is rebuildable and is not authority.

---

## 8.2 SimulationEvent

```text
SimulationEvent
  simulation_event_id
  simulation_scenario_ref

  participants[]
  perceived_context
  candidate_action
  candidate_outcome

  generated_by
```

Invariant:

```text
SimulationEvent ≠ Canon Event
```

---

## 8.3 DraftCandidate

```text
DraftCandidate
  draft_id
  version

  scene_contract_ref
  context_pack_ref

  content
  writer_metadata

  provenance
```

---

## 8.4 NarrativeRevision

```text
NarrativeRevision
  revision_id
  base_draft_ref

  revised_content
  review_refs[]

  accepted_for_delta_compilation: boolean
```

Acceptance for delta compilation is not Canon commit.

---

## 8.5 NarrativeChangeSet

```text
NarrativeChangeSet
  change_set_id

  base_canon_version
  source_revision_id
  source_spans[]

  changes[]:
    change_id
    kind

    entity_refs[]

    precondition?
    trigger?
    process?
    outcome?

    before_state?
    after_state?

    knowledge_effects[]
    relationship_effects[]
    object_effects[]
    location_effects[]
    thread_effects[]

    temporal_effects[]
    causal_refs[]

    confidence
    evidence_spans[]
```

Invariant:

```text
NarrativeChangeSet ≠ CanonDelta
```

NarrativeChangeSet describes what a revision appears to change.

CanonDelta describes what R2 explicitly proposes to commit.

---

## 8.6 CanonDelta

```text
CanonDelta
  canon_delta_id

  base_canon_version
  target_branch_id

  operations[]:
    ADD_ENTITY
    UPDATE_ENTITY
    ADD_FACT
    RETIRE_FACT
    ADD_EVENT
    UPDATE_STATE
    UPDATE_KNOWLEDGE
    UPDATE_RELATIONSHIP
    UPDATE_OBJECT
    UPDATE_LOCATION
    UPDATE_THREAD
    ADD_TEMPORAL_RELATION
    ADD_CAUSAL_RELATION

  source_change_set_refs[]
  author_decision_refs[]

  validation_report_refs[]
```

Only CanonTransactionService can commit it.

---

# 9. Adaptation contracts

Primary contracts:

```text
AdaptationBranch
AdaptationBrief
AdaptationMap
ScreenplayArtifact
```

---

## 9.1 AdaptationBranch

```text
AdaptationBranch
  branch_id
  version

  parent_branch_id
  parent_canon_version

  medium

  adaptation_policy:
    STRICT
    FAITHFUL
    FREE
    INSPIRED_BY

  overlay_version

  created_at
  created_by
```

Adaptation branch does not overwrite source Canon.

---

## 9.2 AdaptationMapEntry

```text
AdaptationMapEntry
  entry_id

  source_refs[]
  target_refs[]

  operation:
    PRESERVE
    EXTERNALIZE
    CONDENSE
    COMBINE
    SPLIT
    OMIT
    REORDER
    REFRAME_POV
    MODIFY_FOR_MEDIUM

  rationale
  fidelity_risk

  approval_status
```

---

## 9.3 AdaptationMap

```text
AdaptationMap
  adaptation_map_id
  version

  adaptation_branch_ref
  entries[]
```

---

## 9.4 ScreenplayArtifact

```text
ScreenplayArtifact
  screenplay_id
  version

  adaptation_branch_ref
  content_basis

  scenes[]
  characters[]
  source_mapping_refs[]

  approval_status
  locked_for_direction: boolean
```

Only an approved/locked screenplay enters the formal cinematic Director path.

---

# 10. ContentBasis

ContentBasis is mandatory at the boundary into production.

```text
ContentBasis
  basis_type:
    FACTUAL
    NARRATIVE
    ADAPTATION

  basis_version
  refs[]
```

## FACTUAL refs
May include:
- ResearchPack version;
- Claim IDs/versions;
- Evidence IDs;
- Source IDs where required.

## NARRATIVE refs
May include:
- Canon branch;
- Canon version;
- Fact/Event/Entity refs;
- NarrativePlan refs.

## ADAPTATION refs
May include:
- parent Canon branch/version;
- AdaptationBranch/version;
- AdaptationMap refs.

---

# 11. ScriptArtifact

```text
ScriptArtifact
  script_id
  version

  content_basis

  sections[]
  participants[]
  timing_intent

  creative_constraints[]
  approval_status
```

For factual content, sections may carry `claim_refs[]`.

---

# 12. ScriptLikeArtifact

`ScriptLikeArtifact` is a logical interface/union:

```text
ScriptArtifact
OR
ScreenplayArtifact
```

Both expose:
- identity/version;
- ContentBasis;
- units/scenes;
- participants;
- timing intent;
- creative constraints.

R2.3 does not require a dedicated persisted ScriptLikeArtifact table.

---

# 13. SceneSpec

```text
SceneSpec
  scene_id
  version

  source_artifact_ref
  source_unit_refs[]

  content_basis

  purpose
  duration_target

  temporal_context?
  location_ref?
  entity_refs[]

  required_beats[]
  continuity_requirements[]

  allowed_methods[]

  approval_status
```

SceneSpec is production semantic intent.

---

# 14. ShotSpec

```text
ShotSpec
  shot_id
  version

  scene_id

  purpose
  target_duration

  framing
  camera

  entity_refs[]

  audio_intent?

  required_continuity[]
  required_reference_roles[]

  allowed_methods[]
  quality_tier

  approval_status
```

## Forbidden stable fields in ShotSpec

```text
provider
model
endpoint
API payload
provider job id
provider-specific request schema
```

Provider/model are execution concerns.

---

# 15. ProductionBinding

ProductionBinding is the unique semantic→production bridge.

```text
ProductionBinding
  binding_id
  version

  target_type:
    SCENE
    SHOT

  target_id

  semantic_ref
  production_ref

  role:
    CHARACTER
    LOCATION
    PROP
    WARDROBE
    VOICE
    STYLE
    SOURCE_FOOTAGE
    OPENING_FRAME
    ENDING_FRAME
    PREVIOUS_SHOT

  asset_refs[]

  variant_ref?
  state_ref?
```

Canon entity identity and production variant identity remain distinct.

---

# 16. VisualIdentityProfile

```text
VisualIdentityProfile
  visual_identity_id
  version

  semantic_character_ref

  face_master_ref?
  full_body_master_ref?
  side_profile_ref?

  hairstyle_lock?
  costume_locks[]
  accessory_locks[]

  state_variants[]
  approved_reference_refs[]
```

Visual identity does not redefine Canon identity.

---

# 17. ProductionReadiness

Readiness is not a boolean-only field.

```text
ProductionReadiness
  readiness_id

  target_id

  state:
    READY
    BLOCKED

  requirements[]:
    requirement_id
    role

    required
    status

    resolved_binding?
    reason?
```

Example:

```text
CHARACTER    READY
LOCATION     READY
WARDROBE     READY
ENDING_FRAME OPTIONAL
VOICE        BLOCKED

overall = BLOCKED
```

---

# 18. MethodDecision

```text
MethodDecision
  method_decision_id

  target_ref

  method:
    REUSE
    STOCK
    SCREEN_CAPTURE
    DETERMINISTIC
    GENERATED_IMAGE
    GENERATED_VIDEO
    COMPOSITE

  rationale

  capability_requirements[]

  cost_class
  quality_tier

  fallback_methods[]
```

MethodDecision is provider-neutral.

---

# 19. PromptPlan

PromptPlan is R2 semantic generation preparation.

```text
PromptPlan
  prompt_plan_id
  version

  target_ref

  semantic_instruction
  positive_prompt
  negative_prompt

  identity_tokens[]
  style_tokens[]

  reference_binding_ids[]
  exclusions[]

  compiler_version
```

Invariant:

```text
PromptPlan ≠ ProviderRequest
```

---

# 20. ProviderRequest

ProviderRequest is adapter/runtime-level.

```text
ProviderRequest
  provider_request_id

  method_decision_ref
  prompt_plan_ref?

  provider
  model
  endpoint

  payload
  execution_options

  adapter_version
```

ProviderRequest may change without staling the creative content artifact.

---

# 21. GenerationCandidate

```text
GenerationCandidate
  candidate_id

  target_ref

  content_fingerprint
  execution_fingerprint

  provider_execution_ref

  output_asset_ref

  quality_report_ref?

  lifecycle_state:
    GENERATED
    FAILED

  selection_state:
    UNREVIEWED
    REJECTED
    SELECTED
```

Runtime failure and selection state are separate concerns.

---

# 22. ApprovedMaster

Generic base:

```text
ApprovedMaster
  master_id

  target_ref
  selected_candidate_id

  approval_record

  selected_at
  selected_by
```

Typed specializations may include:

```text
ApprovedShotMaster
ApprovedSceneMaster
ApprovedAudioMaster
ApprovedImageMaster
```

Invariant:

```text
generation succeeded
≠
approved master
```

---

# 23. EditTimelineArtifact

```text
EditTimelineArtifact
  timeline_id
  version

  master_refs[]
  audio_refs[]
  music_refs[]

  composition_plan
  timing_map

  render_profile

  approval_status
```

Renderers do not own upstream truth.

---

# 24. QualityReport

```text
QualityReport
  quality_report_id

  target_ref

  checks[]
  score?
  blocking_findings[]
  advisory_findings[]

  reviewer_type
  created_at
```

---

# 25. State-machine separation

R2 freezes four independent state families.

## 25.1 Creative approval

```text
DRAFT
PROPOSED
REVIEW_REQUIRED
APPROVED
REJECTED
```

## 25.2 Artifact currency

```text
CURRENT
STALE
MISSING
BLOCKED
```

## 25.3 Runtime task

ArcReel native semantics:

```text
QUEUED
RUNNING
CANCELLING
SUCCEEDED
FAILED
CANCELLED
```

## 25.4 Candidate selection

```text
UNREVIEWED
REJECTED
SELECTED
```

Do not collapse these state machines.

Valid example:

```text
ShotSpec.approval          = APPROVED
ApprovedShotMaster.currency = CURRENT
new_generation_task.runtime = FAILED
```

No contradiction exists.

---

# 26. Content fingerprint

Content fingerprint tracks semantic dependencies that determine whether an artifact is CURRENT or STALE.

Typical inputs:

```text
ShotSpec version
ProductionBinding versions
VisualIdentity refs/versions
ContentBasis direct refs
relevant approved source assets
```

Provider/model/seed are excluded unless they themselves are an explicit creative requirement.

---

# 27. Execution fingerprint

Execution fingerprint supports reproducibility, cost history and candidate comparison.

Typical inputs:

```text
provider
model
endpoint
seed
resolution
generation settings
PromptCompiler version
ProviderAdapter version
```

Execution fingerprint does not determine artifact currency.

---

# 28. Dependency DAG

Narrative path:

```text
CanonVersion N
NarrativePlan P
      │
      ▼
NarrativeRevision R
      │
      ▼
ScreenplayArtifact S
      │
      ▼
SceneSpec SC
      │
      ▼
ShotSpec SH
      │
      ├── ProductionBinding PB
      ├── VisualIdentity VI
      │
      ▼
MethodDecision MD
      │
      ▼
PromptPlan PP
      │
      ▼
GenerationCandidate G
      │
      ▼
ApprovedMaster M
      │
      ▼
EditTimeline ET
      │
      ▼
FinalMaster
```

Factual path:

```text
Source/Evidence
→ Claim
→ ScriptArtifact
→ SceneSpec
→ ShotSpec
→ production path
```

Selective invalidation follows declared direct dependency edges.

---

# 29. Direct-edge invalidation rule

Do not globally invalidate all downstream objects from a broad project version.

Instead:

```text
changed direct dependency
→ recompute content fingerprint
→ affected artifact becomes STALE
```

Unrelated branches remain CURRENT.

---

# 30. Provenance

Cross-authority artifacts must support:

```text
Provenance
  created_by:
    HUMAN
    AGENT
    SYSTEM
    IMPORT

  source_refs[]

  tool_or_adapter?
  model?
  model_version?

  created_at

  operation_id?
  parent_revision_refs[]
```

Provider/model metadata is retained for audit but must not leak into stable provider-neutral contracts unless semantically required.

---

# 31. Authority ownership mapping

| Contract | Authority Plane / Owner |
|---|---|
| SourceRecord | Factual Authority |
| EvidenceRecord | Factual Authority |
| ResearchPack | Factual Authority |
| Claim / ClaimLedger | Factual Authority |
| CanonBranch / CanonVersion | Narrative Authority |
| Entity / Fact / Event | Narrative Authority |
| KnowledgeState | Narrative Authority / Epistemic Engine |
| StoryFrame / plans / SceneContract | Authorial Intent |
| CreativePolicy | Authorial Intent |
| NarrativeContextPack | Working projection |
| SimulationEvent | Candidate plane |
| DraftCandidate | Candidate plane |
| NarrativeChangeSet | Proposal plane |
| CanonDelta | Proposal to Canon authority |
| AdaptationBranch / Map | Adaptation Authority |
| ScriptArtifact / ScreenplayArtifact | Cross-authority creative artifact |
| SceneSpec / ShotSpec | Production semantic layer |
| ProductionBinding | Production preparation |
| VisualIdentityProfile | Production preparation |
| ProductionReadiness | Production preparation |
| MethodDecision | Method Router |
| PromptPlan | Generation preparation |
| ProviderRequest | Runtime adapter |
| GenerationCandidate | Production Authority |
| ApprovedMaster | Production Authority |
| EditTimelineArtifact | Production Authority |
| QualityReport | Review/QA plane |

---

# 32. Forbidden contract couplings

R2 explicitly forbids:

```text
ShotSpec.provider
ShotSpec.model
SceneSpec.provider
NarrativePlan.provider
CanonFact.production_asset_path
CanonCharacter.face_image_path
Claim.provider_job_id
ApprovedMaster == latest successful task
StoryBible == canonical database row
CanvasNode == production artifact
SimulationEvent == CanonEvent
```

All such couplings require an adapter/binding/reference instead.

---

# 33. Contract evolution rules

1. Additive fields may be introduced with compatible schema evolution.
2. Removing/renaming semantics requires a schema-version change and migration plan.
3. Provider/model-specific additions belong in adapter contracts, not stable core.
4. New cross-authority references require owner/permission review under R2.2.
5. Any new field that changes artifact currency must declare fingerprint participation.
6. Any new state enum must belong to one named state-machine family.
7. Any new authoritative contract must declare exactly one commit authority.

---

# 34. Machine-readable contract registry

R2 maintains a registry file:

```text
R2_03_CONTRACT_REGISTRY.json
```

The registry records:
- contract family;
- authority plane;
- commit authority;
- provider-neutral requirement;
- content-basis requirement;
- versioning requirements;
- forbidden fields where applicable.

This registry is intended to become input for future architecture tests/CI.

---

# 35. R2.3 frozen conditions

The following are frozen:

1. Stable logical ID + monotonic object version.
2. Schema version is independent from object version.
3. ContentBasis is mandatory at the boundary into production.
4. `NarrativeChangeSet ≠ CanonDelta`.
5. `PromptPlan ≠ ProviderRequest`.
6. SceneSpec/ShotSpec are provider-neutral.
7. Approval, currency, runtime and candidate-selection statuses are independent state machines.
8. Content fingerprint and execution fingerprint are different concepts with different responsibilities.
9. Dependency invalidation follows declared direct edges.
10. Domain contracts are frozen before SQL/ORM layout.
11. ProductionBinding is the semantic→production bridge.
12. ApprovedMaster requires explicit selection/approval.
13. KnowledgeState remains first-class.
14. Adaptation branch/overlay is distinct from source Canon.
15. New authoritative contracts must have one commit authority.

---

# 36. R2.3 exit criteria

R2.3 is complete when:
- Human Showrunner approves the contract boundaries;
- each durable contract maps to one authority or explicitly non-authoritative plane;
- forbidden provider coupling is documented;
- state-machine families are non-overlapping;
- registry is machine-readable;
- R2.4 can consolidate decisions without ambiguity.

**Status: COMPLETE / FROZEN v1**
