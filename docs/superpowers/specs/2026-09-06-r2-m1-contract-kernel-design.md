# R2-M1 Contract Kernel Design

**Project:** Content & Narrative Production OS  
**Milestone:** R2-M1 — Contract Kernel  
**Date:** 2026-09-06  
**Status:** DESIGN APPROVED / SPEC REVIEW REQUIRED  
**Architecture baseline:** R2.1–R2.7 frozen  
**Depends on:** R2-M0 Host Fork Foundation — COMPLETE

---

## 1. Goal

Implement the provider-neutral R2 production contract kernel as pure Python/Pydantic domain models and deterministic fingerprint utilities.

R2-M1 establishes stable domain semantics before persistence, ArcReel Artifact Manifest integration, Director integration, provider execution, Canon, or UI work.

The central invariant is:

```text
Domain Contract
≠ Database Row
≠ Provider Request
≠ Runtime Task
```

---

## 2. Selected approach

R2-M1 uses **Pydantic v2 models independent of ArcReel persistence/runtime internals**.

Why:

1. ArcReel already uses Pydantic, so this follows the host ecosystem.
2. Pydantic provides validation, serialization, JSON-schema support, and deterministic testable boundaries.
3. It preserves the R2.3 domain-first rule: contracts are designed before SQL/ORM mapping.
4. It avoids manually reimplementing validation/serialization with raw dataclasses.
5. It keeps provider/runtime-specific fields isolated to adapter-level models.

Rejected for M1:

- SQLAlchemy-first domain design;
- ORM entities as domain contracts;
- raw `dataclass` as the primary model system;
- direct ArcReel manifest schema mutation;
- provider/model-specific production semantics.

---

## 3. Scope

R2-M1 implements only the provider-neutral production contract kernel plus adapter-level `ProviderRequest`.

Target package:

```text
r2/contracts/
├── __init__.py
├── common.py
├── enums.py
├── content_basis.py
├── provenance.py
├── production.py
├── preparation.py
├── execution.py
├── results.py
└── fingerprints.py
```

Tests mirror source paths under ArcReel's required test taxonomy:

```text
tests/unit/r2/contracts/
```

Do not create unused future directories such as:

```text
r2/authority/
r2/adapters/
r2/governance/
```

during M1.

---

## 4. Out of scope

R2-M1 explicitly does **not** implement:

```text
database migrations
SQLAlchemy persistence mapping
ArcReel Artifact Manifest extension
direct dependency DAG persistence
ApprovedMaster persistence
Canon / Epistemic Engine
NarrativePlan
DirectorAdapter
OpenMontage
take
Jellyfish
DramaClaw
Butterfly integration
Method Router business logic
CapabilityRegistry business logic
provider execution
runtime task submission
UI changes
cloud-provider qualification
```

These remain later milestones.

---

## 5. Contract base and identity

R2-M1 must not create one giant base class carrying every possible metadata field.

Use a small identity/version base:

```text
ContractIdentity
  id
  schema_version
  version
```

Semantics:

```text
id
= stable logical identity

version
= monotonic object revision
= integer >= 1

schema_version
= semantic contract schema version
= independent from object version
```

Example:

```text
id = "SH042"
version = 7
schema_version = "2.1"
```

Forbidden identity pattern:

```text
id = "SH042_v7"
```

when `SH042` is the actual stable logical identity.

### 5.1 Version validation

M1 validates:

```text
version >= 1
schema_version is non-empty
id is non-empty
```

M1 does **not** implement persistence-backed monotonicity enforcement across commits. That belongs to services/persistence in later milestones.

---

## 6. Common configuration

All R2 Pydantic models should use an explicit shared configuration appropriate for stable contracts.

Required behavior:

- reject unknown fields unless a model explicitly needs an extension envelope;
- use string-valued enums in serialized output;
- preserve provider-neutral boundaries;
- avoid hidden mutation during validation;
- provide deterministic `model_dump(mode="json")` behavior for fingerprint inputs.

Recommended Pydantic configuration:

```text
extra = "forbid"
validate_assignment = True
use_enum_values = False
```

Exact configuration may follow ArcReel/Pydantic conventions where equivalent, but must preserve these semantics.

---

## 7. Enum families

R2-M1 defines independent enum families.

### 7.1 Creative approval

```text
DRAFT
PROPOSED
REVIEW_REQUIRED
APPROVED
REJECTED
```

### 7.2 Artifact currency

```text
CURRENT
STALE
MISSING
BLOCKED
```

### 7.3 Runtime task

```text
QUEUED
RUNNING
CANCELLING
SUCCEEDED
FAILED
CANCELLED
```

This enum mirrors frozen ArcReel runtime semantics but is not a replacement for ArcReel runtime state.

### 7.4 Candidate selection

```text
UNREVIEWED
REJECTED
SELECTED
```

### 7.5 Generation lifecycle

For R2-M1:

```text
GENERATED
FAILED
```

### 7.6 Readiness

```text
READY
BLOCKED
```

### 7.7 Content basis

```text
FACTUAL
NARRATIVE
ADAPTATION
```

### 7.8 Production method

```text
REUSE
STOCK
SCREEN_CAPTURE
DETERMINISTIC
GENERATED_IMAGE
GENERATED_VIDEO
COMPOSITE
```

### 7.9 Production binding target

```text
SCENE
SHOT
```

### 7.10 Production binding role

```text
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
```

These enum families must remain separate types even if labels overlap conceptually.

---

## 8. ContentBasis

`ContentBasis` is mandatory at production-boundary contracts.

```text
ContentBasis
  basis_type
  basis_version
  refs[]
```

Requirements:

- `basis_type` is `FACTUAL | NARRATIVE | ADAPTATION`;
- `basis_version` is non-empty;
- `refs` is non-empty;
- duplicate refs are rejected or normalized deterministically;
- refs are opaque stable references at M1;
- no database lookup occurs in the model.

Production-boundary contracts that require ContentBasis in M1:

```text
SceneSpec
ScriptArtifact if introduced later
ScreenplayArtifact if introduced later
```

For M1, `SceneSpec` directly requires `content_basis`.

`ShotSpec` inherits production lineage through its `scene_id`; M1 may also carry a direct `content_basis` only if R2.3 registry/spec requires it at the production boundary. To avoid duplicating lineage and creating divergence, the selected M1 design is:

```text
SceneSpec.content_basis = REQUIRED
ShotSpec.content_basis = REQUIRED
```

This keeps every production-semantic artifact independently lineage-addressable and matches the frozen registry requirement for both `SceneSpec` and `ShotSpec`.

---

## 9. Provenance

Define:

```text
Provenance
  created_by
  source_refs[]
  tool_or_adapter?
  model?
  model_version?
  created_at
  operation_id?
  parent_revision_refs[]
```

`created_by` enum:

```text
HUMAN
AGENT
SYSTEM
IMPORT
```

Provider/model metadata is audit information here. It does not make a stable production-semantic contract provider-specific.

Requirements:

- `created_at` is timezone-aware;
- reference lists serialize deterministically;
- no secret/provider credentials can be stored.

---

## 10. SceneSpec

```text
SceneSpec
  id
  schema_version
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

### 10.1 Constraints

- `duration_target > 0`;
- `source_artifact_ref` non-empty;
- `purpose` non-empty;
- `content_basis` required;
- `approval_status` uses CreativeApprovalStatus;
- `allowed_methods` contains ProductionMethod values;
- no provider/runtime fields.

Forbidden stable fields include at minimum:

```text
provider
model
endpoint
payload
provider_job_id
```

Unknown fields are rejected, so injecting one of these fields must fail validation.

---

## 11. ShotSpec

```text
ShotSpec
  id
  schema_version
  version

  scene_id
  content_basis

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

### 11.1 Constraints

- `scene_id` non-empty;
- `purpose`, `framing`, and `camera` non-empty;
- `target_duration > 0`;
- `quality_tier >= 0`;
- `content_basis` required;
- `required_reference_roles` uses ProductionBindingRole;
- stable ShotSpec remains provider-neutral.

Forbidden:

```text
provider
model
endpoint
payload
provider_job_id
provider_request
execution_options
```

---

## 12. ProductionBinding

`ProductionBinding` is the semantic-to-production bridge.

```text
ProductionBinding
  id
  schema_version
  version

  target_type
  target_id

  semantic_ref
  production_ref

  role
  asset_refs[]

  variant_ref?
  state_ref?
```

Requirements:

- `target_id`, `semantic_ref`, `production_ref` non-empty;
- role uses ProductionBindingRole;
- `asset_refs` may be empty only for binding types where production_ref itself is sufficient; M1 does not infer role-specific requirements;
- Canon/entity semantic identity remains distinct from production identity.

No database relationship object is embedded.

---

## 13. VisualIdentityProfile

```text
VisualIdentityProfile
  id
  schema_version
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

Requirements:

- `semantic_character_ref` non-empty;
- at least one usable reference or lock is required only if the profile is being used for production readiness; M1 does not force that business rule at construction time;
- production-readiness validation remains a separate concern.

This prevents model construction from becoming a hidden Method Router/readiness engine.

---

## 14. ProductionReadiness

Do not use:

```text
ready: bool
```

Use explicit requirements.

```text
ReadinessRequirement
  requirement_id
  role
  required
  status
  resolved_binding?
  reason?

ProductionReadiness
  id
  target_id
  state
  requirements[]
```

### 14.1 Derived-state invariant

M1 must make contradictory readiness impossible.

Selected rule:

```text
if any required requirement is not READY
→ overall state must be BLOCKED

if all required requirements are READY
→ overall state may only be READY
```

To avoid two sources of truth, preferred implementation is:

```text
state is computed/validated from requirements
```

rather than trusting arbitrary caller input.

An optional requirement may be unresolved without blocking readiness.

---

## 15. MethodDecision

```text
MethodDecision
  id
  target_ref

  method

  rationale

  capability_requirements[]

  cost_class
  quality_tier

  fallback_methods[]
```

Constraints:

- provider-neutral;
- provider/model/endpoint are forbidden;
- `quality_tier >= 0`;
- fallback methods are ProductionMethod values;
- no provider ranking logic in M1.

`MethodDecision` is a contract only. The Method Router service belongs to M4.

---

## 16. PromptPlan

```text
PromptPlan
  id
  schema_version
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

Constraints:

- `target_ref` non-empty;
- `semantic_instruction` non-empty;
- `compiler_version` non-empty;
- provider-neutral;
- no endpoint/model/API payload.

`PromptPlan` describes semantic generation intent.

---

## 17. ProviderRequest

`ProviderRequest` is the explicit adapter/runtime boundary.

```text
ProviderRequest
  id

  method_decision_ref
  prompt_plan_ref?

  provider
  model
  endpoint

  payload
  execution_options

  adapter_version
```

Unlike SceneSpec/ShotSpec/MethodDecision/PromptPlan, ProviderRequest **is allowed** to contain provider-specific execution details.

Requirements:

- provider/model/endpoint non-empty;
- payload/execution_options are JSON-compatible mappings;
- adapter_version non-empty;
- credentials/secrets are forbidden by policy and must never be embedded.

`ProviderRequest` is not used for artifact currency.

---

## 18. GenerationCandidate

```text
GenerationCandidate
  id

  target_ref

  content_fingerprint
  execution_fingerprint

  provider_execution_ref

  output_asset_ref

  quality_report_ref?

  lifecycle_state
  selection_state
```

Required separation:

```text
lifecycle_state:
  GENERATED | FAILED

selection_state:
  UNREVIEWED | REJECTED | SELECTED
```

Do not overload one `state`.

### 18.1 Cross-field validation

Selected M1 invariants:

- `FAILED` candidate cannot be `SELECTED`;
- `SELECTED` candidate must have lifecycle `GENERATED`;
- successful generation does not automatically set `SELECTED`.

---

## 19. ApprovedMaster

```text
ApprovedMaster
  id

  target_ref
  selected_candidate_id

  approval_record

  selected_at
  selected_by
```

M1 models the contract only.

Requirements:

- `selected_candidate_id` non-empty;
- `selected_at` timezone-aware;
- selected master cannot be inferred from “latest successful generation”;
- M1 does not persist master pointers.

Typed specializations such as ApprovedShotMaster may be added only if immediately required by tests/consumers. YAGNI default: keep one generic ApprovedMaster in M1.

---

## 20. QualityReport

```text
QualityFinding
  code
  message
  blocking

QualityReport
  id
  target_ref

  checks[]
  score?
  blocking_findings[]
  advisory_findings[]

  reviewer_type
  created_at
```

M1 does not implement actual QA algorithms.

Requirements:

- `created_at` timezone-aware;
- score, if present, has a defined numeric range selected by implementation and documented in tests;
- blocking/advisory findings remain explicitly separate.

Recommended score range:

```text
0.0 <= score <= 1.0
```

---

## 21. Fingerprint semantics

R2-M1 exposes exactly two deterministic fingerprint APIs.

Recommended public API:

```python
compute_content_fingerprint(
    *,
    shot_spec: ShotSpec,
    bindings: Sequence[ProductionBinding],
    visual_identity_refs: Sequence[str],
    approved_source_asset_refs: Sequence[str],
) -> str

compute_execution_fingerprint(
    *,
    provider: str,
    model: str,
    endpoint: str,
    seed: int | None,
    resolution: str | None,
    generation_settings: Mapping[str, JSONValue],
    prompt_compiler_version: str,
    provider_adapter_version: str,
) -> str
```

### 21.1 Canonical serialization

Fingerprinting must use deterministic canonical JSON semantics:

- UTF-8;
- sorted mapping keys;
- stable enum serialization;
- stable list policy;
- no timestamp/non-semantic runtime fields unless explicitly part of the fingerprint input;
- cryptographic hash: SHA-256.

The result is lowercase hexadecimal SHA-256.

### 21.2 Content fingerprint inputs

Content fingerprint uses semantic dependencies only:

```text
ShotSpec content
ProductionBinding versions/content
VisualIdentity refs
ContentBasis direct refs via ShotSpec
approved source asset refs
```

### 21.3 Execution fingerprint inputs

Execution fingerprint uses:

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

### 21.4 Required invariant

Changing only:

```text
provider
model
endpoint
seed
resolution
execution settings
```

may change `execution_fingerprint` but must not change `content_fingerprint`.

Changing semantic ShotSpec/binding/content-basis inputs must change `content_fingerprint`.

---

## 22. Deterministic collection policy

Fingerprint correctness depends on list semantics.

M1 freezes:

### Order-sensitive lists

Preserve order for:

```text
required_beats
continuity_requirements
fallback_methods
prompt token lists when prompt order is semantically meaningful
```

### Set-like references

Canonicalize by sorting unique values for:

```text
entity_refs
source_unit_refs
asset refs when ordering has no semantic meaning
approved source asset refs
visual identity refs
```

Where ambiguity exists, default to preserving order unless the contract explicitly declares set semantics.

Normalization must be explicit per field/function; no global “sort all lists” behavior.

---

## 23. JSON-compatible execution values

ProviderRequest payload and fingerprint generation settings require a JSON-compatible recursive type.

M1 should define a type alias conceptually equivalent to:

```text
JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]
```

Pydantic must reject arbitrary Python objects in provider payload/execution settings.

This improves reproducibility and serialization safety.

---

## 24. Forbidden coupling enforcement

M1 must have both model-level and registry-level tests.

### 24.1 Model validation tests

These must fail:

```python
ShotSpec(..., provider="seedance")
ShotSpec(..., model="h3")
SceneSpec(..., endpoint="...")
MethodDecision(..., provider="...")
PromptPlan(..., payload={...})
```

because unknown fields are forbidden.

### 24.2 Reflection tests

Architecture tests inspect `model_fields` for provider-neutral models and assert the forbidden field names are absent.

Required forbidden set:

```text
provider
model
endpoint
payload
provider_job_id
provider_request
execution_options
```

Applicable at minimum to:

```text
SceneSpec
ShotSpec
MethodDecision
PromptPlan
```

### 24.3 Frozen-registry alignment

Existing `R2_03_CONTRACT_REGISTRY.json` remains authoritative for registry-declared forbidden fields.

Implementation tests must not silently weaken the registry.

---

## 25. Serialization and round-trip

For every M1 durable model:

```text
construct
→ model_dump(mode="json")
→ JSON encode/decode
→ model_validate
→ semantic equality
```

must pass.

M1 must test:
- enum round-trip;
- timezone-aware datetime round-trip;
- nested ContentBasis;
- nested readiness requirements;
- ProviderRequest JSON payload;
- GenerationCandidate states.

---

## 26. Error semantics

Domain validation errors use standard Pydantic `ValidationError`.

M1 does not invent custom service exceptions for ordinary field validation.

Custom errors are appropriate only inside deterministic fingerprint utilities for non-JSON-compatible values or impossible canonicalization inputs.

Error messages must identify:
- contract/field;
- violated invariant;
- invalid state combination where relevant.

---

## 27. ArcReel integration boundary

M1 may depend on general Python/Pydantic libraries already present in ArcReel.

M1 must not import runtime/application modules from:

```text
server.*
lib.* task/queue/provider runtime
```

except purely shared value types if an architecture test demonstrates that dependency is stable and provider-neutral.

Preferred rule:

```text
r2/contracts/*
→ Python stdlib + Pydantic + r2/contracts/*
```

Architecture tests should enforce this dependency boundary using import inspection or the repository's existing import-linter mechanisms if practical.

No ArcReel runtime source file should be modified in M1.

---

## 28. Test layout

ArcReel requires directory-based test classification.

Use:

```text
tests/unit/r2/contracts/
  test_common.py
  test_content_basis.py
  test_production.py
  test_preparation.py
  test_execution.py
  test_results.py
  test_fingerprints.py
  test_architecture_boundaries.py
```

Do not use:

```text
tests/architecture/
```

M1 tests are unit tests.

---

## 29. TDD order

Recommended implementation order:

```text
1. enums/common identity
2. ContentBasis + Provenance
3. SceneSpec + ShotSpec
4. ProductionBinding + VisualIdentityProfile
5. ProductionReadiness derived-state validation
6. MethodDecision + PromptPlan + ProviderRequest
7. GenerationCandidate + ApprovedMaster + QualityReport
8. canonical serializer
9. content fingerprint
10. execution fingerprint
11. architecture reflection/import-boundary tests
12. round-trip regression suite
```

Every unit follows:

```text
RED
→ minimal GREEN
→ focused regression
→ commit
```

---

## 30. Acceptance criteria

R2-M1 is complete only when all are true:

1. All M1 contract models validate and serialize.
2. JSON round-trip tests pass.
3. Stable logical identity and independent object/schema versions are represented correctly.
4. `SceneSpec.content_basis` is required.
5. `ShotSpec.content_basis` is required.
6. SceneSpec/ShotSpec/MethodDecision/PromptPlan reject provider/runtime fields.
7. Four frozen status families remain independent enum types.
8. Generation lifecycle and candidate selection are independent.
9. Failed generation cannot be selected.
10. ProductionReadiness cannot represent contradictory overall/requirement state.
11. Content fingerprint is deterministic.
12. Execution fingerprint is deterministic.
13. Provider/model/execution-only change does not change content fingerprint.
14. Semantic content change changes content fingerprint.
15. ProviderRequest accepts provider-specific execution details and rejects non-JSON-compatible payload values.
16. R2 contracts do not import ArcReel runtime/provider/task/application layers.
17. Existing frozen-registry verifier passes.
18. Existing R2-M0 baseline verifier passes.
19. Existing M0 R2 tests pass.
20. ArcReel focused Host regression remains green.
21. No database migration is introduced.
22. No ArcReel runtime implementation file is modified.

---

## 31. Planned commits

M1 implementation should remain reviewable.

Suggested commit sequence:

```text
feat(r2): add contract identity and enums
feat(r2): add content basis and provenance contracts
feat(r2): add production semantic contracts
feat(r2): add production preparation contracts
feat(r2): add execution and result contracts
feat(r2): add deterministic contract fingerprints
test(r2): enforce contract architecture boundaries
test(r2): record M1 contract kernel verification
```

Exact grouping may be reduced if neighboring files are too small to justify separate review gates, but unrelated responsibilities must not be combined.

---

## 32. M1 exit artifact

On completion, create:

```text
docs/r2/evidence/R2_M1_VERIFICATION_<timestamp>.json
docs/r2/evidence/R2_M1_VERIFICATION_<timestamp>.md
```

Minimum evidence:

```text
M1 unit test count
frozen-registry verifier
baseline verifier
ArcReel focused regression
changed-file scope
no DB migration
no ArcReel runtime modification
content-vs-execution fingerprint invariant
known R2-HOST-001 status unchanged
```

---

## 33. Next milestone boundary

Only after R2-M1 passes may R2-M2 begin.

R2-M2 owns:
- Artifact Manifest integration;
- persistence mapping where required;
- dependency edges;
- selective invalidation;
- ApprovedMaster semantic integration over ArcReel versions.

M1 must not pre-implement these features.

---

# Design conclusion

R2-M1 creates a small, pure, provider-neutral contract kernel whose semantics can be tested independently of persistence and execution.

Its most important protections are:

```text
domain-first
provider-neutral stable production semantics
orthogonal state machines
explicit ContentBasis
semantic-to-production binding
readiness without boolean ambiguity
explicit candidate/master separation
content fingerprint ≠ execution fingerprint
no runtime coupling
```

**Status: APPROVED DESIGN / WRITTEN SPEC AWAITING USER REVIEW**
