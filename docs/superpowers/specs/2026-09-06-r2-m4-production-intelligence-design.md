# R2-M4 Production Intelligence — Design Specification

**Project:** Content & Narrative Production OS  
**Milestone:** R2-M4 — Production Intelligence  
**Document type:** APPROVED M4 Design Specification  
**Design status:** APPROVED — D01–D12 frozen; C01–C10 approved as authoritative clarifications  
**Target repository path:** `docs/superpowers/specs/2026-09-06-r2-m4-production-intelligence-design.md`  
**Prepared:** 2026-09-07 (+07:00)  
**Implementation status:** DESIGN APPROVED; IMPLEMENTATION PLAN NOT YET APPROVED  

---

## 0. Authority and source order

This specification operationalizes the frozen R2-M4 architecture. It does not reopen or weaken frozen R2 decisions.

Authority order for implementation:

```text
1. repository code + tests + current frozen specs/DEC records
2. frozen R2.1–R2.7 architecture decisions
3. R2_M4_D01-D12_FROZEN_2026-09-07.md
4. this written M4 design specification after Human Showrunner approval
5. implementation plan derived from this specification
6. implementation-agent output
```

If a lower-authority source contradicts a higher-authority source, implementation must stop and escalate with evidence rather than silently repair or reinterpret the architecture.

This document incorporates the recovered D05 semantics from the prior design session: **Scoped + Typed Visual Identity Model**, hierarchical scope inheritance, `LOCKED / PREFERRED / ADVISORY`, deterministic resolution, and `ResolvedVisualIdentity` as a computed view rather than a new authority.

This revision incorporates **clarification amendments C01–C10**, approved by the Human Showrunner on 2026-09-07 (+07:00). They are authoritative parts of this written M4 design.

---

## 1. Purpose

M4 turns the M3 Golden-A-specific preparation path into a reusable **Production Intelligence spine** that can prepare mixed-method shots safely before expensive execution.

M4 must answer, in an auditable and provider-neutral order:

```text
Which Director should interpret the ScriptLikeArtifact?
Is the Director result valid?
Are required production bindings ready?
What production identity/continuity constraints apply?
Which ProductionMethod should be used?
Which execution capabilities satisfy that method?
Is a specific execution attempt admissible now?
Which exact execution candidate is locked for this attempt?
How is semantic execution intent translated to the selected provider/tool?
How are failures, retries, fallbacks, costs and provenance observed without becoming truth?
How is the architecture itself continuously verified?
```

M4 is successful when the above questions are resolved through explicit contracts and gates without leaking provider configuration into stable semantic contracts and without creating duplicate Host subsystems.

---

## 2. Goals

M4 MUST provide:

```text
- reusable DirectorAdapter routing across OpenMontageDirector, TakeDirector and ArcReelNative
- explicit fallback/failure semantics
- normalized DirectorResult boundary
- reusable provider-neutral ProductionReadiness
- scoped typed VisualIdentity resolution
- Method Router with Method-before-Provider authority
- one normalized CapabilityRegistry with descriptor + observation separation
- provider-neutral PromptPlan
- Generation Admission before expensive execution
- immutable ExecutionDecision per admitted execution attempt
- provider-specific PromptCompiler translation below the semantic boundary
- correlated failure/attempt/cost observability without making telemetry authoritative
- canonical 12-shot mixed-method verification fixture
- layered contract/invariant/integration/evidence verification
- executable architecture fitness gate
```

---

## 3. Explicit non-goals

M4 MUST NOT implement or silently pull forward:

```text
Canon Kernel
Narrative Plan Store
CanonDelta
Novel Studio
Golden B
adaptation engine
Shenbi / Huohuo / StoryBox integration beyond interface awareness
H1–H8 Host hardening unless a verified M4 blocker requires escalation
new artifact registry
new runtime/media queue
new currency engine
new cost ledger
parallel ApprovedMaster store
provider/model-specific fields in SceneSpec or ShotSpec
hidden provider selection before MethodDecision
```

`R2-HOST-001 / H1` remains OPEN and is not an M4 closure requirement.

---

## 4. Frozen system invariants inherited by M4

M4 implementation MUST preserve:

```text
Human Showrunner authority
Candidate ≠ Canon
Shot ≠ Generation
Narrative truth ≠ production truth
Agent chat ≠ authoritative state
Method before model/provider
Reuse before generation
Deterministic QA/computation before generative
No provider/model-specific stable core fields
Provenance + version + dependencies
Selective invalidation
Failed regeneration preserves prior usable output
Analytics/learning may recommend but cannot silently mutate authority
Content fingerprint ≠ execution fingerprint
GenerationCandidate ≠ ApprovedMaster
Runtime State ≠ Artifact Truth
Observability ≠ Authoritative State
```

---

## 5. End-to-end M4 control flow

```text
Human Showrunner / Production Policy
        ↓
ScriptLikeArtifact
        ↓
DirectorRoutingPolicy + DirectorAdvisor + explicit Human override
        ↓
RoutingDecision
        ↓
DirectorAdapter
        ↓
DirectorResult
 ┌───────────────┴────────────────┐
DirectorSuccess             DirectorFailure
        ↓                         ↓
SceneSpec[] / ShotSpec[]      retry / fallback / fail-closed
        ↓
ProductionBinding
        ↓
Scoped VisualIdentity profiles
        ↓
VisualIdentityResolver
        ↓
ResolvedVisualIdentity
        ↓
GATE 1 — ProductionReadiness
        ↓ READY
MethodRoutingContext
        ↓
Hard Eligibility Filter
        ↓
Authoritative Method Policy
        ↓
Deterministic Rank
        ↓
MethodDecision
        ↓
CapabilityRequirementBuilder
        ↓
CapabilityRequirements
        ↓
CapabilityRegistry
  Descriptor Catalog
  + Observation Overlay
        ↓
CapabilityMatcher
        ↓
CapabilityResolution
        ↓
PromptPlan
        ↓
GATE 2 — Generation Admission
        ↓ ADMITTED
ExecutionDecision
        ↓
PromptCompiler
        ↓
ProviderRequest
        ↓
ArcReel Host execution/submission boundary
        ↓
Provider / Local Tool / Deterministic Tool
        ↓
Execution Attempt(s)
        ↓
GenerationCandidate(s)
        ↓ explicit review/promotion
ApprovedMaster
```

Provider/model/tool identity MUST first become authoritative for an attempt at `ExecutionDecision`; provider-specific request syntax begins only after that, at `PromptCompiler` / `ProviderRequest`.

---

## 6. Truth and authority boundaries

### 6.1 Semantic production contracts

`SceneSpec` and `ShotSpec` are provider-neutral production contracts. They may express semantic intent, production requirements, timing, references, continuity and composition intent, but MUST NOT embed provider/model/endpoint/API-specific fields.

### 6.2 Production provenance

`RoutingDecision`, `MethodDecision`, `CapabilityResolution`, `GenerationAdmission`, and `ExecutionDecision` are production-side decisions/results. They are auditable and versioned but are not Canon truth.

### 6.3 Operation envelopes

`DirectorResult` and `CapabilityResolution` are operation results, not truth layers and not new artifact registries.

### 6.4 Artifact truth

Artifact currency, lineage, candidates and `ApprovedMaster` remain owned by the existing ArcReel Artifact Manifest / Artifact Bridge semantics.

### 6.5 Runtime truth

Queue/task/runtime execution state remains Host-owned and separate from artifact currency and approval state.

### 6.6 Observability

Events, spans, logs, metrics and diagnostics project authoritative state. They MUST NOT become a second state engine or authority writer.

---

## 7. D01 — Director routing authority

### 7.1 Authority model

Director routing uses a hybrid authority model:

```text
explicit deterministic production policy = authoritative
heuristic/capability analysis = advisory only
Human Showrunner = explicit override authority
```

Exactly one final `RoutingDecision` drives execution.

### 7.2 Default routing policy

```text
GENERAL_CONTENT       → OpenMontageDirector
FICTION / CINEMATIC   → TakeDirector
eligible route failure → ArcReelNative
```

Automatic cross-routing is forbidden:

```text
OpenMontageDirector ↔ TakeDirector
```

unless a future explicit architecture decision authorizes it.

### 7.3 Minimum `RoutingDecision` semantics

```text
RoutingDecision
├─ routing_decision_id
├─ routing_policy_version
├─ input_profile_ref
├─ policy_selected_director
├─ advisory_recommendations[]
├─ advisory_reasons[]
├─ human_override?
├─ override_actor?
├─ override_reason?
├─ selected_director
├─ fallback_policy
├─ decided_at
└─ provenance
```

Implementation names may follow existing repository conventions, but these semantics are required.

### 7.4 Human override

Human override is explicit, auditable and **sticky**. If a human explicitly selects a Director, fallback defaults to disabled unless the same override explicitly permits fallback.

---

## 8. D02/D03 — Director execution, fallback and normalized output

### 8.1 Result type

```text
DirectorResult = DirectorSuccess | DirectorFailure
```

`DirectorResult` is an execution boundary envelope, not a persisted truth layer.

### 8.2 `DirectorSuccess`

Minimum semantics:

```text
DirectorSuccess
├─ routing_decision_ref
├─ actual_director
├─ scenes: SceneSpec[]
├─ shots: ShotSpec[]
├─ diagnostics[]
├─ validation_summary
└─ provenance
```

Success requires BOTH:

```text
contract validation PASS
+
semantic validation PASS
```

No partially valid or malformed output may masquerade as normalized production contracts.

### 8.3 `DirectorFailure`

Minimum semantics:

```text
DirectorFailure
├─ routing_decision_ref
├─ attempted_director
├─ failure_class
├─ retryable
├─ fallback_eligible          # normalized classification/evidence only
├─ error_code
├─ message
├─ diagnostic_refs[]
└─ partial_output_diagnostic_ref?
```

Invalid or partial output belongs only to diagnostic/quarantine paths. `fallback_eligible` is descriptive classification/evidence; the authoritative fallback decision remains the versioned routing/fallback policy plus Human override semantics.

### 8.4 Failure classes and handling

| Failure class | Examples | Required handling |
|---|---|---|
| `ROUTE_UNAVAILABLE` | unsupported input, donor unavailable, Director capability missing | fallback to ArcReelNative only if policy permits and no ambiguous side effect exists |
| `TRANSIENT_EXECUTION_FAILURE` | timeout, temporary connection/rate limit, temporary donor process failure | retry SAME Director first; fallback only after retry budget and policy allow |
| `CONTRACT_OR_SEMANTIC_FAILURE` | invalid SceneSpec/ShotSpec, schema violation, semantic validation failure | FAIL CLOSED; no silent fallback |
| `PARTIAL_OR_AMBIGUOUS_EXECUTION` | partial scenes/shots, crash after partial output, uncertain persisted effects | FAIL CLOSED; diagnostic/recovery; human decision if necessary |

Fallback MUST NOT merge ambiguous partial semantic output with fallback output.

---

## 9. D04 — Two-gate readiness model

### 9.1 Gate separation

```text
GATE 1 — ProductionReadiness
GATE 2 — Generation Admission

READY ≠ ADMITTED
```

### 9.2 Gate 1 — `ProductionReadiness`

Purpose: determine whether required provider-neutral production prerequisites are satisfied.

Minimum semantics:

```text
ProductionReadiness
├─ target_ref
├─ state: READY | BLOCKED
├─ requirements[]
│  ├─ requirement_id
│  ├─ role
│  ├─ required
│  ├─ status
│  ├─ resolved_binding?
│  ├─ resolution_source?
│  └─ reason?
├─ observed_target_version
├─ observed_binding_version / snapshot
├─ evaluation_policy_version
└─ provenance
```

Required unresolved requirements produce `BLOCKED`. Optional unresolved requirements may produce advisory warnings without blocking.

Gate 1 MUST NOT select provider/model/tool, generate missing assets, mutate Canon or become a workflow engine.

### 9.3 Readiness freshness

Persisted `READY` cannot be blindly trusted. If relevant content/binding versions have changed, readiness must be recomputed or synchronously revalidated before Gate 2.

```text
stale READY
≠ permission for expensive execution
```

### 9.4 Gate 2 overview

Gate 2 is downstream of MethodDecision, capability matching and PromptPlan. It is execution-aware and decides whether a specific execution attempt may proceed now.

---

## 10. D05 — Scoped + Typed Visual Identity Model

### 10.1 Purpose

VisualIdentity captures reusable **production identity, continuity and style constraints** without becoming Canon truth and without owning reference assets.

```text
VisualIdentity ≠ Canon truth
VisualIdentity ≠ provider configuration
VisualIdentity ≠ asset registry
```

`ProductionBinding` remains the owner of reference assets and semantic-to-production bindings.

### 10.2 Hierarchical scopes

Profiles may exist at these scopes:

```text
PROJECT
→ FORMAT / EPISODE
→ SEQUENCE
→ SCENE
→ SHOT
```

A target resolves all applicable profiles through deterministic inheritance from broadest to most specific scope.

### 10.3 Constraint strength

Each typed identity constraint has one of:

```text
LOCKED
PREFERRED
ADVISORY
```

Semantics:

```text
LOCKED     = hard production constraint; downstream routing/capability/compiler may not waive it
PREFERRED  = soft preference used after hard eligibility
ADVISORY   = guidance that may influence ranking/prompting but cannot override stronger constraints
```

### 10.4 Minimum semantic model

Physical class names are not frozen, but implementation MUST preserve the following concepts:

```text
VisualIdentityProfile
├─ profile_id
├─ version
├─ scope_type
├─ scope_ref
├─ constraints[]
│  ├─ semantic_key
│  ├─ strength: LOCKED | PREFERRED | ADVISORY
│  ├─ semantic_value / normalized intent
│  ├─ binding_role_ref?          # semantic reference to ProductionBinding role, not asset ownership
│  └─ provenance
└─ provenance
```

The resolver produces a computed view:

```text
ResolvedVisualIdentity
├─ target_ref
├─ status: RESOLVED | CONFLICTED
├─ contributing_profile_refs[]
├─ resolved_constraints[]
│  ├─ semantic_key
│  ├─ effective_strength
│  ├─ effective_value / intent
│  └─ source_scope_ref
├─ conflicts[]
├─ resolution_policy_version
├─ observed_profile_versions[]
└─ provenance
```

`ResolvedVisualIdentity` is a **computed operational view**, not a new authority store.

### 10.5 Deterministic inheritance rules

Resolver behavior is deterministic and versioned:

```text
1. collect applicable scopes from PROJECT → ... → SHOT
2. inherit broader constraints into narrower scopes
3. more-specific constraints may refine weaker inherited constraints
4. inherited LOCKED constraints cannot be silently weakened by a narrower PREFERRED/ADVISORY constraint
5. conflicting LOCKED constraints do not tie-break silently; they produce an explicit identity conflict
6. an authoritative human/source-profile update may change a LOCKED constraint, but the resolver itself may not “override” it
7. resolution order and policy version are persisted in provenance
```

### 10.6 Identity conflict authority and blocking semantics — C01 APPROVED

`VisualIdentityResolver` has **no authority to choose a winner** between incompatible effective `LOCKED` constraints.

When a conflict exists:

```text
ResolvedVisualIdentity.status = CONFLICTED
→ ProductionReadiness = BLOCKED
→ reason = IDENTITY_CONFLICT
→ no MethodDecision
→ no Generation Admission
→ no expensive execution
```

Resolution authority:

```text
Human Showrunner = final resolution authority
```

A conflict is resolved only by an explicit, versioned update to the authoritative `VisualIdentityProfile` source(s), or another explicitly approved production/architecture decision that changes those source profiles. A downstream method/provider/compiler override is forbidden.

Operational behavior:

```text
identity conflict
→ emit HUMAN_ACTION_REQUIRED failure/outcome
→ emit correlated production event / review signal
→ preserve current authoritative profiles and prior usable/ApprovedMaster artifacts
→ wait for explicit resolution
```

There is **no timeout-based default**, automatic downgrade, provider fallback, method fallback, or automatic weakening of a `LOCKED` constraint. If no Human Showrunner is available, the affected new production remains blocked. Unaffected shots may continue if their dependency graph does not include the conflicted identity state.

### 10.7 Typed capability compilation

VisualIdentity semantics compile to typed capability requirements downstream, for example:

```text
CHARACTER_REFERENCE
STYLE_REFERENCE
STRUCTURE_REFERENCE
OPENING_FRAME / ENDING_FRAME
MULTI_IMAGE_REFERENCE
```

Marketing/provider-specific feature names MUST NOT enter stable VisualIdentity semantics.

### 10.8 Invalidation

A semantic VisualIdentity change participates in normal content dependency/fingerprint rules and selectively invalidates dependent production artifacts.

A provider/model/capability availability change does NOT rewrite VisualIdentity and does NOT by itself change `content_fingerprint`.

---

## 11. D06 — Constrained Policy Method Router

### 11.1 Production methods

```text
REUSE
STOCK
SCREEN_CAPTURE
DETERMINISTIC
GENERATED_IMAGE
GENERATED_VIDEO
COMPOSITE
```

### 11.2 Routing algorithm

```text
HARD ELIGIBILITY FILTER
→ AUTHORITATIVE POLICY PRIORITY
→ DETERMINISTIC RANKING OF ELIGIBLE METHODS
→ MethodDecision
```

No provider/model/tool identity is an input to method authority.

### 11.3 Required policy rules

```text
- REUSE first only when CURRENT/approved/semantically compatible and all hard constraints are satisfied
- source authenticity wins when actual UI/person/event/evidence is required
- DETERMINISTIC before generation when it can satisfy the intent equivalently
- generation only when source/reuse/deterministic approaches cannot satisfy the semantic/creative requirement
- COMPOSITE is assembly, not a hidden fallback that re-labels a material treatment change
```

### 11.4 Quality Ladder

Quality Ladder is an **execution escalation policy**, not a ranking of ProductionMethods:

```text
Tier 0  REUSE
Tier 1  DETERMINISTIC
Tier 2  GENERATED_IMAGE/VIDEO via LOCAL
Tier 3  same generated method via CHEAP CLOUD
Tier 4  same generated method via PREMIUM CLOUD
Tier 5  HUMAN / MANUAL
```

`STOCK`, `SCREEN_CAPTURE` and `COMPOSITE` remain semantic production methods that may be correct regardless of tier.

### 11.5 `MethodDecision`

```text
MethodDecision
├─ id
├─ target_ref
├─ method_policy_version
├─ selected_method
├─ eligible_methods[]
├─ rejected_methods[]
│  ├─ method
│  └─ reason_codes[]
├─ decision_factors[]
├─ quality_policy_ref?
├─ budget_policy_ref?
├─ human_override?
├─ override_actor?
├─ override_reason?
└─ provenance
```

Material method changes MUST create a new MethodDecision.

---

## 12. D07 — Hybrid Normalized Capability Registry

### 12.1 Responsibility

Use one normalized execution capability subsystem:

```text
CapabilityDescriptor Catalog
+
CapabilityObservation Overlay
→ CapabilityMatcher
→ CapabilityResolution
```

It is an execution inventory/matcher, NOT an artifact registry.

### 12.2 Capability vs availability vs preference

```text
Capability   = what the adapter/model/tool can do
Availability = whether it can be used now
Preference   = which eligible candidate should be preferred
```

These axes MUST remain distinct.

### 12.3 Support state

```text
SUPPORTED
UNSUPPORTED
UNKNOWN
```

For a hard requirement:

```text
UNKNOWN → candidate ineligible
reason = CAPABILITY_UNKNOWN
```

`UNKNOWN` MUST NOT be rewritten as `UNSUPPORTED` or `SUPPORTED`.

### 12.4 `CapabilityDescriptor`

Minimum semantic declaration:

```text
CapabilityDescriptor
├─ capability_id
├─ adapter_id
├─ provider_id
├─ execution_type: LOCAL | LOCAL_GPU | API | HYBRID
├─ supported_methods[]
├─ input_modalities[]
├─ output_modalities[]
├─ typed_features[]
├─ limits
├─ resource_requirements
├─ stability
├─ descriptor_source
├─ descriptor_version
└─ provenance
```

Stable typed features describe semantics, not marketing names.

### 12.5 `CapabilityObservation`

Dynamic observation may include:

```text
availability
credentials readiness
endpoint/process health
runtime dependencies
resource fit / VRAM
quota/rate-limit observation
estimated cost
estimated latency
reliability observation
observed_at
observation version/snapshot
```

Changing dynamic availability MUST NOT rewrite stable capability declaration.

### 12.6 Observation freshness and revalidation — C03 APPROVED

Freshness is governed by a versioned `CapabilityFreshnessPolicy`; there is no implicit forever-valid observation and no single hard-coded TTL for all observation types.

Conceptual semantics:

```text
CapabilityFreshnessPolicy
├─ policy_version
├─ observation_class_rules[]
│  ├─ observation_class
│  ├─ max_age?
│  ├─ revalidate_on_admission
│  ├─ invalidation_triggers[]
│  └─ expiry_behavior: REVALIDATE | BECOME_UNKNOWN
└─ provenance
```

Observation classes:

```text
HARD_DYNAMIC
  availability
  credentials readiness
  endpoint/process health
  local resource fit / VRAM
  hard quota/rate-limit state when required for admission

SOFT_DYNAMIC
  estimated latency
  reliability estimate
  non-binding cost estimate
```

Rules:

1. Expired hard-dynamic evidence MUST NOT be treated as current `AVAILABLE`.
2. Gate 2 MUST synchronously revalidate the selected candidate's hard-dynamic predicates immediately before `ADMITTED`, or receive an equivalent Host/adapter freshness proof.
3. If a required hard-dynamic predicate cannot be revalidated and no still-valid proof exists, its effective state becomes `UNKNOWN` and admission is denied.
4. Soft-dynamic estimates may use policy-defined cache windows, but stale estimates may not satisfy hard budget/safety predicates.
5. Descriptor version change, credential rotation, known endpoint/process restart, relevant local resource-state change, or explicit provider health failure invalidates affected observations immediately when such events are observable.
6. Concrete cache durations are configuration policy, not provider code. They MUST be selected and documented in the implementation plan with deterministic tests; implementation agents may not choose them ad hoc.

This makes the safety boundary independent of an arbitrary cache TTL: cached observations may assist discovery/ranking, while the final expensive-execution gate requires current hard evidence.

### 12.7 Matching

```text
CapabilityRequirements
→ hard match
→ eligible candidates
→ current availability check
→ usable candidates
→ deterministic rank
→ CapabilityResolution
```

Hard constraints are filtered before ranking.

### 12.8 `CapabilityResolution`

```text
CapabilityResolution
├─ requirement_set_ref/hash
├─ registry_version
├─ observation_snapshot_ref
├─ matcher_policy_version
├─ eligible_candidates[]
├─ rejected_candidates[]
│  ├─ candidate
│  └─ reasons[]
├─ unknown_candidates[]
└─ diagnostics[]
```

CapabilityRegistry MUST NOT rewrite MethodDecision. Adding a conforming provider MUST NOT require MethodRouter changes.

---

## 13. D08 — PromptPlan, Generation Admission, ExecutionDecision and PromptCompiler

### 13.1 Provider-neutral PromptPlan

`PromptPlan` expresses **what execution must achieve**, not how a provider API expresses it.

```text
PromptPlan
├─ id
├─ target_ref
├─ method_decision_ref
├─ subject_intent
├─ environment_intent
├─ action_motion_intent?
├─ composition_intent
├─ camera_intent?
├─ timing_intent?
├─ reference_requirements[]
├─ visual_identity_constraints[]
├─ required_controls[]
├─ negative_constraints[]
├─ output_requirements
├─ plan_version
└─ provenance
```

Forbidden in PromptPlan:

```text
provider endpoint
provider API payload
provider-specific routing authority
provider-specific prompt syntax as stable semantic truth
```

### 13.2 Generation Admission

Gate 2 evaluates a **specific prospective execution attempt** using:

```text
current ProductionReadiness
MethodDecision
CapabilityResolution
PromptPlan
current availability snapshot
production policy
approval requirements
budget/resource preflight/reservation
safe compilability/submission prerequisites
```

Normalized outcomes:

```text
ADMITTED
APPROVAL_REQUIRED
DENIED_NOT_READY
DENIED_NO_CAPABILITY
DENIED_UNAVAILABLE
DENIED_BUDGET
DENIED_POLICY
```

Only `ADMITTED` may create an ExecutionDecision and continue toward expensive execution.

### 13.3 Budget ownership and reservation concurrency — C04 APPROVED

M4 MUST reuse Host cost governance. M4 does NOT create another cost engine or ledger.

For paid execution, a non-atomic "budget looks available" check is insufficient because concurrent admissions can consume the same remaining budget. Admission therefore requires a **Host-owned atomic reservation/claim contract** whenever budget policy is a hard gate.

Minimum Host-owned reservation semantics:

```text
BudgetReservation
├─ reservation_ref
├─ budget_scope_ref
├─ reserved_amount / authorized_limit
├─ currency / cost unit
├─ state: ACTIVE | CLAIMED | RELEASED | EXPIRED
├─ created_at
├─ expires_at?
├─ budget_version / concurrency token
└─ provenance
```

Required flow:

```text
Host atomic reserve
→ Generation Admission may become ADMITTED
→ before remote/paid submission: atomically claim/revalidate reservation
→ submit
→ reconcile actual cost in Host
```

Rules:

1. `ADMITTED` for a hard-budget paid attempt requires an `ACTIVE` reservation or an equivalent atomic Host authorization.
2. Immediately before paid submission, the reservation MUST be atomically claimed or revalidated against the same budget scope.
3. `EXPIRED`, already-consumed, insufficient, or invalid reservation means **no submission**; return to admission with `DENIED_BUDGET` or a new admission cycle.
4. Pre-submit abandonment/cancellation MUST release/unreserve the Host reservation when the Host contract supports reservation release.
5. M4 MUST NOT implement its own local mutex, shadow balance, or second cost ledger to solve this race.
6. Final cost reconciliation remains Host-owned and attempt-correlated.

If seam discovery finds that the existing Host cost capability cannot provide atomic reserve/claim (or an equivalent concurrency-safe authorization), this is a **verified Host capability blocker separate from H1**. It is a STOP/escalation condition. It does not silently weaken Gate 2. Paid-execution admission semantics cannot be declared complete until the Host seam is verified, explicitly extended with approval, or explicitly waived by the Human Showrunner.

### 13.4 Immutable `ExecutionDecision`

```text
ExecutionDecision
├─ id
├─ target_ref
├─ method_decision_ref
├─ prompt_plan_ref
├─ capability_resolution_ref
├─ adapter_id
├─ provider_id
├─ model_or_tool_id
├─ execution_type
├─ capability_descriptor_version
├─ observation_snapshot_ref
├─ execution_identity_stability: IMMUTABLE_REVISION | VERSIONED_ALIAS | MUTABLE_ALIAS | UNKNOWN
├─ resolved_model_or_tool_revision?
├─ request_semantics_hash
├─ selection_policy_version
├─ selection_reasons[]
├─ budget_reservation_ref?
├─ approval_ref?
└─ provenance
```

The decision is immutable for one execution attempt choice.

Same-method provider/tool change creates a **new ExecutionDecision**. Material method change creates a **new MethodDecision**.

### 13.5 PromptCompiler

```text
PromptPlan
+
ExecutionDecision
→ provider-specific PromptCompiler
→ ProviderRequest
```

PromptCompiler may translate:

```text
semantic intent → provider prompt syntax
semantic reference roles → provider reference slots
resolution/duration/control constraints → provider parameters
negative constraints → provider-compatible representation
```

PromptCompiler MUST NOT:

```text
choose ProductionMethod
silently select another provider
relax LOCKED VisualIdentity
mutate SceneSpec / ShotSpec / Canon
waive readiness / budget / approval
silently drop required semantics
```

If a required semantic cannot be represented for the selected execution candidate:

```text
COMPILATION_INCOMPATIBLE
→ fail closed
→ new execution decision or method decision only through the authoritative upstream path
```

### 13.6 Fingerprints

```text
provider/model/seed/compiler/execution configuration change
→ execution_fingerprint may change
→ content_fingerprint does not change solely for that reason
```

### 13.7 H1 boundary

`ExecutionDecision` expresses intended local execution selection. It does not replace H1's requirement to persist the actual submission identity safely at the Host remote-submission boundary.

```text
ExecutionDecision
→ PromptCompiler
→ ProviderRequest
→ Host submission boundary
→ H1 submission identity persistence/recovery
→ remote provider job/request id
```

M4-D08 MUST NOT claim H1 closure.

---

## 14. Execution attempt lifecycle and fallback

### 14.1 Attempt identity

Each actual execution attempt has a first-class attempt identity correlated with:

```text
shot/target
MethodDecision
ExecutionDecision
ProviderRequest/submission
runtime task
cost record
GenerationCandidate if produced
```

### 14.2 Same-execution retry guard — C02 APPROVED

Transient failure may retry under the same `ExecutionDecision` only after an explicit **Retry Identity Guard** passes.

Authority:

```text
ExecutionDecision / admission-side retry policy = retry authority
PromptCompiler = translator only
Host/adapter = supplies execution-side identity/idempotency evidence
```

The guard MUST verify at least:

```text
same ExecutionDecision id
same MethodDecision ref/version
same PromptPlan ref/version or semantic hash
same adapter/provider/model-or-tool selection
same resolved immutable revision when the provider exposes one
same compiler/adapter version relevant to request semantics
same request_semantics_hash
same required controls/references
no known ambiguous durable side effect from the previous attempt
provider/tool retry semantics are safe for this operation
```

The compiled provider request SHOULD expose a deterministic request fingerprint that excludes retry-variant transport metadata such as timestamp, trace id, or idempotency key.

Provider-side identity drift:

- If a provider exposes an immutable model/tool revision, retry must remain pinned to that revision.
- If only a mutable alias is available, the `ExecutionDecision` records `execution_identity_stability = MUTABLE_ALIAS`.
- A mutable alias may be retried under the same decision only when the versioned retry policy explicitly permits that stability class.
- If exact identity is required but cannot be verified, same-execution retry is forbidden; use a new admission/execution decision or fail closed.

Submission ambiguity:

```text
timeout/connection loss after remote submission may have occurred
≠ automatically safe retry
```

If the prior attempt may have produced a durable remote side effect, retry requires provider-supported idempotency/recovery evidence (for example a stable idempotency key or recoverable remote job identity). Otherwise the attempt is classified as ambiguous and must follow Host/H1 recovery semantics rather than blindly resubmitting.

### 14.3 Same-method provider fallback

If a new provider/model/tool must be selected while preserving the same ProductionMethod:

```text
old ExecutionDecision remains immutable
→ new Capability/Admission evaluation as required
→ new ExecutionDecision
→ new PromptCompiler translation
```

### 14.4 Method change

If fallback would materially change ProductionMethod:

```text
return to Method Router
→ create new MethodDecision
```

No downstream compiler/router may silently convert one method into another.

---

## 15. D10 — Failure semantics and observability

### 15.1 Domain outcomes vs telemetry

```text
Domain outcome ≠ telemetry signal
```

Expected outcomes such as `BLOCKED`, `DENIED`, `UNKNOWN`, `UNSUPPORTED`, `UNAVAILABLE`, `APPROVAL_REQUIRED` and normal `CANCELLED` are not automatically system errors.

### 15.2 Normalized failure classification

Failure domains include:

```text
DIRECTOR
READINESS
METHOD
CAPABILITY
ADMISSION
COMPILATION
EXECUTION
HOST
VALIDATION
INTEGRITY / ARCHITECTURE
```

Classifications include:

```text
EXPECTED_BLOCK
TRANSIENT
PERMANENT
CONTRACT
INTEGRITY
```

### 15.3 Retry disposition

Normalized failure semantics MUST carry explicit retry disposition:

```text
NOT_RETRYABLE
RETRY_SAME_EXECUTION
RETRY_WITH_BACKOFF
NEW_EXECUTION_DECISION_REQUIRED
NEW_METHOD_DECISION_REQUIRED
HUMAN_ACTION_REQUIRED
```

Retry policy must not be inferred ad hoc from arbitrary exception strings.

### 15.4 `FailureRecord`

Minimum semantic contract:

```text
FailureRecord
├─ failure_id
├─ occurred_at
├─ domain
├─ reason_code
├─ classification
├─ retry_disposition
├─ target_ref
├─ attempt_ref?
├─ decision_refs[]
├─ safe_message
├─ diagnostic_ref?
└─ provenance
```

`FailureRecord` is semantic failure information, not a raw stack trace dump.

### 15.5 `ProductionEvent`

Minimum event envelope:

```text
ProductionEvent
├─ event_id
├─ event_type
├─ timestamp
├─ production_run_id
├─ target_ref
├─ stage
├─ outcome?
├─ reason_code?
├─ decision refs...
├─ attempt_ref?
├─ trace_id?
├─ span_id?
└─ provenance
```

Events reference authoritative objects; they do not duplicate or replace them.

### 15.6 Correlation

Recommended hierarchy:

```text
production_run_id
└─ target_ref / shot_id
   ├─ director
   ├─ readiness
   ├─ method routing
   ├─ capability resolution
   ├─ admission
   └─ execution decision
      ├─ attempt 1
      └─ attempt 2
```

Telemetry trace/span IDs remain separate from stable domain IDs.

### 15.7 Parent/child success semantics

Example:

```text
Attempt A = FAILED
fallback
Attempt B = SUCCEEDED
Shot execution = SUCCEEDED
```

A handled child failure does not automatically make the successful parent operation failed.

### 15.8 Cost attribution

Every paid attempt must remain attributable even if:

```text
FAILED
TIMED_OUT
CANCELLED
DISCARDED
```

Attempt failure does not imply cost = 0.

Host cost governance remains authoritative; observability correlates attempt refs to Host cost record refs.

### 15.9 Sensitive diagnostics

Normal provenance/logs MUST NOT persist secrets such as API keys, authorization headers, signed URLs or secret provider payloads. Safe messages and restricted diagnostics must be separable.

---

## 16. Persistence and Host ownership

M4 MUST reuse existing Host/M2 mechanisms before adding persistence.

| Concern | Authoritative owner |
|---|---|
| artifact identity, lineage, currency, candidates, ApprovedMaster | ArcReel Artifact Manifest / Artifact Bridge |
| runtime tasks, queue, retries/cancellation mechanics | ArcReel Host runtime |
| cost governance / spend records | existing Host cost capability |
| stable semantic contracts | R2 contract kernel / M4 contracts where approved |
| Director routing provenance | M4 production decision integrated with existing provenance persistence |
| method/capability/admission/execution decisions | M4 production decision records integrated with existing Host/artifact provenance seams |
| logs/traces/metrics | observability infrastructure; non-authoritative |

M4 MUST NOT introduce persistence by creating a parallel registry merely because a new domain object exists. Implementation planning must discover and reuse existing repository persistence/provenance seams.

Unexpected need for a DB migration or Host runtime modification is a STOP condition requiring evidence and Human Showrunner approval.

---

## 17. D09 — Canonical 12-shot mixed-method fixture

### 17.1 Structure

Use **one positive Golden Baseline** plus controlled metamorphic fault overlays.

Three mini-sequences exercise all Director paths:

```text
Sequence A — GENERAL / FACTUAL       → OpenMontageDirector
Sequence B — FICTION / CINEMATIC     → TakeDirector
Sequence C — FALLBACK / MIXED EDGE   → ArcReelNative
```

### 17.2 Baseline shots

| Shot | Director | ProductionMethod | Primary architecture purpose |
|---|---|---|---|
| SH01 | OpenMontageDirector | REUSE | exact compatible approved asset is reused |
| SH02 | OpenMontageDirector | SCREEN_CAPTURE | source-authentic UI/footage wins over synthetic |
| SH03 | OpenMontageDirector | DETERMINISTIC | diagram/data representation before generation |
| SH04 | OpenMontageDirector | COMPOSITE | assembly is distinct from asset generation |
| SH05 | TakeDirector | GENERATED_IMAGE | cinematic identity/reference requirements |
| SH06 | TakeDirector | GENERATED_VIDEO | character + opening-frame continuity |
| SH07 | TakeDirector | GENERATED_VIDEO | Quality Ladder / execution escalation without method change |
| SH08 | TakeDirector | COMPOSITE | constituent asset methods remain distinct from assembly |
| SH09 | ArcReelNative | STOCK | fallback route plus source-fit method |
| SH10 | ArcReelNative | DETERMINISTIC | fallback Director still obeys Method Router |
| SH11 | ArcReelNative | GENERATED_IMAGE | provider-neutral PromptPlan boundary |
| SH12 | ArcReelNative | GENERATED_VIDEO | execution candidate/fallback semantics |

The baseline covers all seven ProductionMethods.

### 17.3 Quality/escalation examples

The fixture should exercise execution tier changes without changing generated method, for example:

```text
SH05 GENERATED_IMAGE → local tier
SH06 GENERATED_VIDEO → cheap-cloud-equivalent fixture candidate
SH07 GENERATED_VIDEO → premium-cloud-equivalent fixture candidate
```

Regression mode may use deterministic test doubles for external provider classes; evidence mode proves selected real seams.

#### 17.3.1 Quality Ladder execution-double contract — C05 APPROVED

The tier doubles do **not** pretend to simulate visual quality. They simulate only execution-policy characteristics needed to prove that Quality Ladder escalation is separate from `ProductionMethod`.

All candidates used in one escalation comparison MUST preserve the same generated method and the same hard semantic capability envelope.

Minimum normalized fixture dimensions:

```text
execution_type
cost_class
approval_class
latency_class
capability_features
availability
identity_stability
retry/idempotency behavior
```

Required fixture profiles:

| Fixture candidate | Required semantics |
|---|---|
| `LOCAL_TIER_DOUBLE` | `LOCAL`/`LOCAL_GPU`, no paid remote reservation, required generated-method capabilities present, local resource-fit observation |
| `CHEAP_CLOUD_TIER_DOUBLE` | `API`, low/normal cost class, same hard semantic capabilities, remote availability + retry semantics, budget path exercised |
| `PREMIUM_CLOUD_TIER_DOUBLE` | `API`, higher cost/approval class, same hard semantic capabilities, budget/approval escalation exercised |

Required assertions across tier changes:

```text
MethodDecision remains unchanged
hard semantic requirements remain unchanged
VisualIdentity LOCKED constraints remain unchanged
ExecutionDecision changes
execution_fingerprint changes
content_fingerprint does not change solely due to tier/provider change
budget/approval path may change
```

Evidence mode is responsible for proving selected real adapters/tools; the regression doubles are not accepted as evidence of real provider media quality.

### 17.4 Fault overlays

Required overlays:

```text
MUT-01 missing required binding
→ ProductionReadiness BLOCKED
→ zero expensive execution

MUT-02 hard capability becomes UNKNOWN
→ candidate ineligible
→ CAPABILITY_UNKNOWN
→ no method rewrite

MUT-03 Director UNSUPPORTED
→ ArcReelNative fallback only when policy permits

MUT-04 Director contract violation
→ FAIL CLOSED
→ no silent fallback

MUT-05 same-method provider/tool failure
→ old ExecutionDecision immutable
→ new admission/new ExecutionDecision
→ MethodDecision unchanged

MUT-06 execution-only configuration mutation
→ content_fingerprint unchanged
→ execution_fingerprint changed

MUT-07 paid attempt fails after charge
→ failure visible
→ cost still attributable

MUT-08 stale CapabilityObservation / observed-version mismatch
→ cannot silently admit execution
```

### 17.5 Regression mode

Uses real M4 policy/resolution/compiler code and controlled external execution boundary. Must be deterministic, CI-safe and not dependent on paid providers.

### 17.6 Evidence mode

Uses selected real local/tool/provider executions to prove adapter and execution seams. It is checkpoint/final evidence, not routine PR regression.

### 17.7 Stochastic oracle

Generated media is validated using:

```text
container/codec validity
duration/resolution/aspect constraints
required reference/control representation
semantic/quality floor rubric where appropriate
metamorphic invariants
```

Exact pixel equality is not required for stochastic output.

---

## 18. D11 — Layered verification strategy

### 18.1 Test layers

```text
L0 Contract / Schema
L1 Pure Policy / Decision
L2 Property + Stateful Invariants
L3 D09 12-Shot Golden + Fault Overlays
L4 Host Integration / Persistence
L5 Real Execution Evidence
L6 Frozen Regression + Architecture Audit
```

### 18.2 L0 — Contract tests

Fast, deterministic and network-free. Check provider-neutral schemas, discriminated result types, support-state semantics and illegal-field absence.

### 18.3 L1 — Policy tests

Directly test core authorities; do not mock them away:

```text
DirectorRoutingPolicy
fallback classifier/policy
ProductionReadiness
VisualIdentity resolution
Method Router
CapabilityMatcher
Generation Admission
PromptCompiler contract behavior
```

### 18.4 L2 — Property/stateful tests

Use property-based tests for broad pure invariants such as:

```text
MethodDecision never requires provider identity
all selected capability candidates satisfy hard requirements
BLOCKED implies attempt_count == 0
execution-only mutation preserves content_fingerprint
```

Use stateful tests for lifecycle invariants such as:

```text
ApprovedMaster B
→ attempt C fails
→ retry/fallback
→ candidate D succeeds but unapproved
→ restart
→ B remains master
→ explicit promotion of D changes master
```

### 18.5 L3 — Canonical integration fixture

D09 is the only canonical M4 integration fixture family. Fault scenarios mutate that fixture rather than creating parallel architectures.

### 18.6 L4 — Host integration

Test real M4-to-Host seams for persistence, reload/restart, Artifact Manifest, ApprovedMaster, currency, provenance and cost correlation.

Do not mock the Host API boundary that production M4 actually consumes.

### 18.7 Controlled execution double

A provider/tool test double may simulate:

```text
SUCCEED
TIMEOUT
RATE_LIMIT
UNAVAILABLE
MALFORMED_RESPONSE
CHARGE_THEN_FAIL
CANCEL
```

It must sit at the external execution boundary while real M4 consumer/compiler/adapter logic runs.

### 18.8 L5 — Real evidence

At milestone checkpoints/final gate, prove selected real seams including deterministic/composite tooling and at least representative real image/video generation execution where environment permits.

### 18.9 L6 — Frozen regressions

Mandatory final baseline:

```text
M3 focused regression PASS
M2 = 53 PASS
M1 = 41 PASS
ArcReel Host = exactly 349 PASS
Architecture audit = 0 BLOCKING violations
```

Exact M4 test count is recorded only at final evidence; it is not a design-time target.

### 18.10 Verification gates

```text
Gate A — Task/TDD
RED → minimal GREEN → focused regression

Gate B — Checkpoint
M4 affected suites + downstream contracts + relevant D09 mutations

Gate C — Pre-final
full M4 + M3 + M2 53 + M1 41 + Host 349 + architecture audit

Gate D — Final evidence
fresh Gate C + Evidence Mode + persistence/restart + evidence artifacts + clean worktree + exact HEAD
```

No push before Gate D.

### 18.11 Gate D evidence artifact format — C08 APPROVED

Gate D produces one canonical machine-readable evidence manifest plus a human-readable verification summary.

Canonical machine-readable artifact:

```text
r2_m4_evidence.json
```

Minimum schema:

```text
schema_version
milestone
design_spec_ref/hash
implementation_plan_ref/hash
starting_head
final_head
branch
worktree_clean

environment_summary
gate_results
suite_results[]
  suite_id
  expected_baseline?
  pass_count
  fail_count
  skip_count
  result

golden_baseline[]
  shot_id
  expected_method
  expected_director
  result

fault_overlays[]
  mutation_id
  expected_outcome
  observed_outcome
  result

real_execution_evidence[]
  seam_id
  execution_type
  artifact_refs[]
  attempt_refs[]
  cost_refs[]
  result

architecture_audit
  report_ref
  blocking_violation_count
  approved_exceptions[]

host_runtime_change_count
db_migration_count
h1_status
open_blockers[]
approved_waivers[]
generated_at
```

Human-readable companion:

```text
R2_M4_FINAL_VERIFICATION.md
```

It summarizes the JSON evidence and links/references the detailed artifacts. Evidence output MUST be deterministic in structure, redact secrets, and use stable reason/result codes. Physical repository/output directory is selected during seam discovery, but the evidence schema above is authoritative for M4.

---

## 19. D12 — Executable architecture fitness gate

### 19.1 Principle

```text
Functional PASS ≠ Architecture PASS
```

Every critical frozen architecture decision must map to one or more executable audit sensors.

### 19.2 Sensor families

```text
A — Dependency topology
B — Stable contract shape
C — Semantic authority leakage
D — Ownership / duplicate subsystem
E — Repository change scope
F — Runtime architecture invariants
```

### 19.3 Required blocking rules

BLOCKING violations include:

```text
provider/model field in SceneSpec/ShotSpec/stable PromptPlan/semantic identity contract
Method Router dependency on provider execution layer
CapabilityRegistry rewriting MethodDecision
PromptCompiler acting as router/content authority
observability writing authoritative production/artifact state
second artifact registry
second runtime/media queue
second currency engine
second cost ledger
parallel master store
M5 authority implementation in M4
unexpected Host runtime change
unexpected DB migration
unapproved architecture exception/ignore
```

### 19.4 Boundary matrix

| Frozen rule | Minimum sensor |
|---|---|
| SceneSpec/ShotSpec provider-neutral | contract-shape |
| Method before Provider | dependency + runtime-order |
| VisualIdentity provider-neutral / LOCKED hard constraints | contract + semantic + runtime |
| CapabilityRegistry not authority | dependency + semantic |
| PromptPlan ≠ ProviderRequest | contract-shape |
| PromptCompiler translator only | semantic + dependency |
| no second artifact registry | ownership + diff |
| no second queue | ownership + diff |
| no second currency engine | ownership + diff |
| no M5 authority | scope/diff |
| failed regeneration preserves master | runtime invariant |
| provider change ≠ content stale | runtime invariant |
| observability ≠ authority | dependency + semantic |

### 19.5 Tool neutrality and selection constraints — C10 APPROVED

Audit semantics are frozen; specific tools are not. Implementation planning must inspect existing repository tooling first. Import Linter/Semgrep/custom AST/pytest checks remain possible implementation choices only after seam discovery.

Any selected architecture-audit tool MUST satisfy:

```text
- runnable locally and in CI without external network/SaaS dependency
- version-pinned/reproducible
- compatible with the repository's Python/runtime environment, or runnable as an isolated compatible CLI
- deterministic exit status for BLOCKING violations
- capable of machine-readable or deterministically parseable output
- must not mutate production source/state as part of audit
- must not require secrets for normal architecture checks
- suitable for focused/checkpoint runs and final full runs
```

Tool choice MUST be resolved and recorded in the approved Implementation Plan **before** the corresponding architecture checks are implemented; it may not be postponed until the final milestone gate. If no third-party tool meets the constraints, targeted local AST/pytest/import-graph checks are preferred over adding a network-dependent service.

### 19.6 Architecture exceptions

Any exception requires:

```text
rule_id
exact scope
reason
supporting evidence
Human Showrunner approval
review/expiry condition where appropriate
```

M4 target is zero new exceptions.

Final gate requires:

```text
BLOCKING architecture violations = 0
```

---

## 20. Selective invalidation and fingerprint rules

M4 MUST preserve the established dependency semantics:

```text
semantic content / binding / VisualIdentity change
→ content_fingerprint may change
→ selectively invalidate direct semantic dependents

provider/model/tool/seed/resolution/compiler/execution change only
→ execution_fingerprint changes
→ content_fingerprint unchanged
→ semantic artifact currency unchanged solely for this reason
```

CapabilityRegistry descriptor/observation updates are execution-landscape changes and do not automatically make ShotSpec, VisualIdentity or ApprovedMaster stale.

Failed regeneration or failed execution must preserve prior usable/approved output.

---

## 21. Cancellation, recovery and partial-state rules

M4 does not redesign Host cancellation/recovery, but its production decisions must be compatible with Host semantics.

Required rules:

```text
- cancellation is runtime state, not artifact currency
- cancelled/failed attempts remain observable and cost-attributable
- partial/ambiguous Director semantic output fails closed
- failed new generation never deletes/replaces prior ApprovedMaster
- same-method fallback creates a new ExecutionDecision rather than mutating the old one
- restart/reload must recover authoritative persisted decisions/artifacts through existing Host seams
- H1 remote submission identity remains an independent open Host-hardening issue
```

---

## 22. Implementation boundaries and expected module responsibilities

Exact files/classes are NOT frozen until repository seam discovery. The implementation plan must map existing code to these responsibilities without creating unnecessary parallel modules.

Logical responsibilities:

```text
DirectorRoutingPolicy       deterministic route authority
DirectorAdvisor             advisory recommendation only
DirectorAdapter             donor normalization/execution boundary
DirectorValidator           contract + semantic normalization validation

VisualIdentityResolver      deterministic scoped identity resolution
ProductionReadinessEvaluator provider-neutral Gate 1

MethodRouter                ProductionMethod authority
CapabilityRequirementBuilder semantic method/identity → typed execution requirements
CapabilityRegistry          normalized descriptor + observation inventory
CapabilityMatcher           hard match + availability + deterministic rank

PromptPlanner               provider-neutral PromptPlan construction
GenerationAdmissionService  Gate 2 / preflight / approval / budget admission
ExecutionDecisionService    immutable attempt-level execution lock
PromptCompiler              provider-specific translation

FailureNormalizer           stable domain failure semantics
ProductionTelemetryProjector non-authoritative events/traces/metrics projection

M4 fixture/evidence helpers  canonical 12-shot verification only
ArchitectureAudit checks    development/verification tooling only
```

Implementation SHOULD adapt names to existing repository patterns when equivalent semantics already exist.

### 22.1 Authority / ownership matrix — C06 APPROVED

A component may reject only within its own authority domain. Earlier failed/blocked gates dominate downstream stages; no downstream component may convert an upstream invalid state into success.

| Responsibility | Owns / decides | May block/reject for | Must not decide |
|---|---|---|---|
| `DirectorRoutingPolicy` | selected Director policy | no valid route under policy | semantic output validity, method, provider |
| `DirectorValidator` | validity of Director normalized output | contract/semantic invalidity, partial/ambiguous Director output | readiness, method, provider |
| `VisualIdentityResolver` | deterministic identity resolution | unresolved LOCKED conflict | method/provider, asset ownership |
| `ProductionReadinessEvaluator` | Gate 1 provider-neutral readiness | missing required binding, identity conflict, stale required prep state | method/provider |
| `MethodRouter` | `ProductionMethod` | no method satisfies hard semantic policy | provider/model selection |
| `CapabilityMatcher` | candidate eligibility/ranking | no candidate satisfies hard requirements/current evidence | rewrite method, approve spend |
| `GenerationAdmissionService` | final pre-execution Gate 2 | stale/unready, no capability, unavailable, budget, approval, policy, unsafe compilation/submission | rewrite upstream semantics |
| `ExecutionDecisionService` | exact attempt candidate lock | cannot establish valid immutable execution choice | change ProductionMethod |
| `PromptCompiler` | provider/tool translation | required semantic cannot be represented | routing, authority override |
| Host runtime | actual task/submission/retry mechanics within approved decision | runtime/submission failure | semantic method/identity authority |
| Human Showrunner | final explicit authority change | may update/approve authoritative upstream decisions | may not be simulated by silent automated downgrade |

Conflict precedence:

```text
invalid DirectorResult
→ no valid ShotSpec enters readiness

VisualIdentity CONFLICTED / ProductionReadiness BLOCKED
→ MethodRouter is not authoritative to continue

MethodDecision with no eligible capability
→ CapabilityResolution NO_MATCH
→ Admission denied

Admission denied
→ no ExecutionDecision / no provider submission

PromptCompiler incompatible
→ fail closed
→ return upstream through explicit decision path
```

A Human Showrunner resolution changes the authoritative input/profile/policy/approval and causes reevaluation; it is not a downstream bypass flag.

---

## 23. Donor boundaries

M4 donor use remains adapter-oriented:

```text
OpenMontage
→ GENERAL_CONTENT Director patterns
→ deterministic composition ideas
→ tool/capability registry patterns
→ universal/provider-specific prompting separation

TakeDirector
→ FICTION/CINEMATIC Director behavior through adapter boundary

Jellyfish-derived concepts
→ production preparation/readiness semantics

ArcReelNative
→ deterministic fallback Director
→ Host runtime/task/queue/artifact/cost/provenance ownership

ai-short-film / related visual-production donors
→ continuity/visual-identity ideas only where they fit frozen D05
```

Donor-native internal objects must not leak past adapter boundaries into stable R2 contracts.

---

## 24. M4 acceptance criteria

M4 implementation is acceptable only if all of the following are true:

```text
1. all D01–D12 frozen semantics are implemented without silent redesign
2. all three Director paths work through one authoritative RoutingDecision
3. Director fallback follows failure-class + side-effect policy
4. every supported public DirectorAdapter success path constructs `DirectorSuccess` only after contract + semantic validation; malformed/partial payloads cannot be returned through that public success boundary
5. Gate 1 blocks unresolved required production bindings
6. scoped VisualIdentity resolves deterministically and LOCKED constraints remain hard
7. MethodDecision is made before provider selection
8. all seven ProductionMethods are represented by the canonical fixture
9. CapabilityRegistry separates capability/availability/preference and handles UNKNOWN correctly
10. PromptPlan remains provider-neutral
11. Gate 2 prevents unsafe/unapproved/unaffordable/unavailable expensive execution
12. each admitted execution choice gets immutable ExecutionDecision
13. PromptCompiler translates without routing or silent semantic weakening
14. same-method provider fallback creates a new ExecutionDecision
15. material method change creates a new MethodDecision
16. content vs execution fingerprint semantics remain correct
17. retries/fallbacks/costs remain observable at attempt level
18. runtime failure never silently mutates artifact truth or ApprovedMaster
19. D09 positive baseline passes **12/12 shots**, and **all required MUT-01..MUT-08** produce their exact expected outcomes; partial pass, silent skip or 11/12 is NOT acceptance
20. every Gate-D-required real execution evidence item is PASS; an unavailable required seam makes Gate D INCOMPLETE unless the Human Showrunner explicitly approves a scoped waiver
21. M3 focused regression passes
22. M2 frozen 53 passes
23. M1 frozen 41 passes
24. ArcReel Host frozen exactly 349 passes
25. architecture audit reports 0 BLOCKING violations
26. no unapproved Host runtime change
27. no unapproved DB migration
28. no M5 authority implementation pulled into M4
29. exact starting and final HEADs are recorded
30. worktree is clean at final evidence/push gate
```

### 24.1 Acceptance evidence semantics — C09 APPROVED

Acceptance criteria are engineering evidence requirements, not mathematical proofs of all possible Python executions.

For criteria stated as architectural "never" rules, M4 requires the strongest practical supported-boundary proof available:

```text
contract construction/validation invariant
+ negative contract tests
+ property/stateful tests where the state space is broad
+ integration fixture evidence
+ architecture fitness checks
```

A test result is binary at the milestone gate: required baseline/mutation/evidence items are PASS or the gate is not PASS. Skips are not silently counted as success.

---

## 25. Coding-readiness gate after this document

D01–D12 being frozen is not sufficient for coding.

After approval of this written spec:

```text
1. resolve exact repository HEAD and origin/r2/main
2. verify branch = r2/main
3. verify clean worktree
4. query codebase-memory-MCP first
5. inspect symbols/callers/callees/dependencies/blast radius
6. map existing repository seams to this specification
7. resolve concrete file/class reuse choices
8. create task-by-task implementation plan with TDD gates
9. review/approve implementation plan
10. only then begin implementation
```

If seam discovery reveals a contradiction with the approved design, STOP and return to Human Showrunner with evidence. Do not solve it by silently changing architecture.

---

## 26. Pre-implementation stop conditions

Stop before code modification if any of these appears necessary:

```text
provider/model fields in SceneSpec or ShotSpec
second artifact registry
second queue/runtime engine
second currency mechanism
second cost ledger
parallel ApprovedMaster store
Host runtime change not already approved
DB migration not already approved
M5 Canon/Narrative implementation
weakening a LOCKED VisualIdentity constraint
bypassing Gate 1 or Gate 2
moving provider selection before MethodDecision
letting PromptCompiler choose method/provider authority
closing H1 implicitly as part of M4
Host paid-budget admission without a concurrency-safe reservation/claim seam
```

### 26.1 Escalation and blocked-state behavior — C07 APPROVED

A pre-implementation STOP condition is not a retry timer and not permission for the agent to improvise.

Required behavior:

```text
STOP
→ cease further architecture-affecting code modification
→ preserve current worktree/artifacts/state
→ do not run destructive reset/clean/rollback commands
→ capture exact evidence, diff, tests and blocker reason
→ mark checkpoint BLOCKED_AWAITING_DECISION
→ create/update durable handoff/checkpoint record
→ escalate to Human Showrunner
```

There is **no timeout/default decision** in M4. If the Human Showrunner is unavailable, the work remains blocked until explicit resolution.

For a runtime production block, preserve prior authoritative state and prior usable/ApprovedMaster artifacts. Do not start new expensive execution for the affected dependency chain. Already-submitted remote work follows existing Host cancellation/recovery semantics; M4 does not erase or guess its state.

M4 does not define a human-response SLA. Lack of response never converts a STOP condition into an automatic fallback, waiver or architecture change.

---

## 27. Design-to-test traceability matrix

| Design decision | Primary proof |
|---|---|
| D01 routing authority | policy tests + D09 3-Director baseline + provenance assertions |
| D02 fallback semantics | failure-class tests + MUT-03/MUT-04 |
| D03 normalized DirectorResult | contract/semantic validation tests |
| D04 two-gate readiness | required-binding tests + stale-readiness test + admission tests |
| D05 scoped typed VisualIdentity | resolver inheritance/conflict tests + `IDENTITY_CONFLICT` fail-closed path + LOCKED capability tests |
| D06 constrained Method Router | hard-filter/policy/ranking tests + all-7-method D09 coverage |
| D07 capability registry | descriptor/observation/UNKNOWN/matching + freshness/revalidation tests |
| D08 admission/execution/compiler | PromptPlan neutrality + admission + atomic budget-reservation seam + retry-identity guard + immutable ExecutionDecision + compiler tests |
| D09 canonical fixture | baseline + MUT-01..MUT-08 |
| D10 observability | attempt/fallback/cost/correlation tests |
| D11 verification strategy | layered suites + evidence gates |
| D12 architecture fitness | dependency/contract/semantic/ownership/diff/runtime sensors |

---

## 28. Decision rationale log — explanatory, not a new authority layer

This log records why the frozen design shape exists so implementation agents can understand intent without reopening decisions. Frozen decisions/spec semantics remain authoritative over this explanatory rationale.

| Decision | Rationale | Rejected/avoided alternative |
|---|---|---|
| D01 Hybrid Director routing | deterministic auditability plus advisory intelligence and explicit Human override | fully heuristic routing; multiple competing routing authorities |
| D02 Side-effect-aware fallback | resilience without hiding semantic/contract defects | fallback on every failure; strict no-fallback for safe route-unavailable cases |
| D03 Discriminated DirectorResult | invalid/partial output cannot masquerade as production contracts | nullable/partially-valid success envelope |
| D04 Two gates | provider-neutral preparation is distinct from execution-time admission | one giant readiness boolean |
| D05 Scoped typed VisualIdentity | continuity must inherit deterministically without becoming Canon or asset ownership | provider-specific prompt/style blobs; silent LOCKED tie-break |
| D06 Constrained Method Router | semantic production method must precede provider optimization | global weighted score across methods; provider-first routing |
| D07 Descriptor + Observation registry | capability truth differs from live availability and preference | static boolean capability map; artifact-registry duplication |
| D08 Admission + immutable ExecutionDecision + compiler boundary | separate semantic intent, execution authorization and provider translation | compiler/router authority; mutable provider selection inside one attempt |
| D09 12-shot baseline + overlays | three 4-shot mini-sequences cover all 3 Directors, all 7 frozen ProductionMethods, repeated generated/composite cases for escalation/fallback/continuity, while remaining a coherent bounded fixture | unrelated case pile; failure-filled baseline; paid-provider-only E2E |
| D10 Domain failures + correlated observability | preserve audit/retry/cost visibility without making logs state authority | one `FAILED` enum; new event-sourced runtime |
| D11 Layered verification | fast deterministic proof plus realistic seam evidence | unit-only mocks; all-real-provider CI |
| D12 Multi-sensor fitness gate | tests passing does not prove boundary conformance | manual checklist only; import graph only |

Why **12 shots**: the number is not claimed to be mathematically minimal. It is the frozen fixture size that supports three Director-specific four-shot sequences while covering all seven ProductionMethods and providing intentional repetition for generated-tier escalation, composition, continuity and execution-fallback semantics.

Why **7 ProductionMethods**: D09 did not invent this taxonomy. `REUSE, STOCK, SCREEN_CAPTURE, DETERMINISTIC, GENERATED_IMAGE, GENERATED_VIDEO, COMPOSITE` are inherited frozen R2 production methods; the fixture is required to demonstrate each one.

---

## 29. Approved review clarifications

The following clarification amendments were approved by the Human Showrunner and are authoritative parts of this M4 design:

```text
C01 D05 identity-conflict authority / fail-closed behavior
C02 D08 same-execution retry identity guard
C03 D07 observation freshness / admission revalidation
C04 D08 Host-owned atomic budget reservation/claim semantics
C05 D09 Quality Ladder execution-double contract
C06 implementation authority / ownership matrix
C07 STOP escalation and blocked-state behavior
C08 Gate D evidence artifact schema
C09 acceptance evidence / exact pass semantics
C10 D12 architecture-audit tool constraints
```

These clarify implementation authority and safety boundaries; they do not authorize M5 work, a second Host subsystem, or H1 closure.

**Approval record:** Human Showrunner approved this revised M4 Design Spec and C01–C10 on 2026-09-07 (+07:00).

---

## 30. Final design state

```text
R2-M4 D01–D12: FROZEN
Review clarifications C01–C10: APPROVED / AUTHORITATIVE
Written M4 design spec v2: APPROVED / AUTHORITATIVE
Implementation plan: NOT YET CREATED
Implementation: NOT STARTED
H1 / R2-HOST-001: OPEN
Maturity baseline: INTEGRATION_READY
Coding readiness: NO
```

After approval of this document, the next artifact is the **M4 Implementation Plan**, but only after exact repository state and codebase seams are verified.
