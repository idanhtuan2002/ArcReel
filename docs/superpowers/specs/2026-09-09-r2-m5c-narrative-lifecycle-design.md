# R2-M5C Narrative Lifecycle, Acceptance Authority, and Canon Delta Compilation Design

**Date:** 2026-09-09

**Status:** approved 2026-09-09 by the operator (Human Showrunner); see
`docs/r2/evidence/R2_M5C_DOCUMENT_APPROVAL.json`. Implementation plan:
`docs/superpowers/plans/2026-09-09-r2-m5c-narrative-lifecycle.md`. F9 and
review-closure semantics incorporated.

**Prerequisites:** accepted M5A Canon Authority handoff; accepted M5B Epistemic State,
Narrative Plan, and Context Compilation handoff

**Authoritative decision:** `docs/adr/0076-narrative-lifecycle-evidence-and-acceptance-authority.md`

**Research:**

- `docs/research/2026-09-08-r2-m5c-narrative-production-lifecycle-research.md`
- `docs/research/2026-09-08-r2-m5c-adr-decision-validation.md`
- `docs/research/2026-09-09-r2-m5c-persistence-state-machine-validation.md`
- `docs/research/2026-09-08-r2-m5b-author-draft-omniscient-gate.md`
- `docs/research/2026-09-08-r2-m5b-validate-scene-plan-commit-rules.md`
- `docs/r2/evidence/PROJECT_STATUS_REVIEW_2026-09-09.md` finding F9

## 1. Goal

M5C adds the smallest complete Narrative workflow above M5A and M5B:

- immutable draft, revision, extraction, change-set, compilation, and handoff evidence;
- one narrow Narrative authority boundary for Human revision selection, per-lineage
  change-set review, and explicit conflict resolution;
- a pure deterministic `CanonDeltaCompiler` over exact accepted inputs;
- a durable handoff-admission receipt proving that all Narrative inputs were current at
  the instant the existing M5A approval/commit path was entered;
- a narrow versioned compatibility extension that closes the frozen M5 relationship/thread
  exit-fixture gap without rewriting accepted M5B history; and
- executable evidence that prose, extraction, compilation, orchestration, providers,
  and projections cannot acquire Narrative or Canon authority.

The intended flow is:

```text
DraftCandidate
  -> NarrativeRevision
  -> Human revision decision
  -> extraction attempt/result
  -> NarrativeChangeSet proposals
  -> Human per-lineage review decisions
  -> explicit Human conflict resolutions where required
  -> compilation attempt/result
     -> NO_CANON_MUTATION for valid outcome-only effects; stop without M5A
     -> SUCCEEDED with exact CanonDelta
        -> explicit existing M5A CanonCommitApproval
        -> NarrativeHandoffAdmission with exact durable approval copy
        -> existing M5A CanonTransactionService
```

`NarrativeChangeSet` describes what accepted prose appears to change.
`CanonDelta` describes the exact Canon operations proposed for M5A validation and
commit. They never become the same contract or authority.

## 2. Authority model and frozen decisions

### 2.1 State ownership

| State | Classification | Owning write boundary | What it cannot do |
|---|---|---|---|
| `DraftCandidate`, `NarrativeRevision` | immutable workflow evidence | `NarrativeLifecycleEvidenceService` | select prose or authorize extraction |
| extraction attempt/result, `NarrativeChangeSet` | immutable proposal evidence | `NarrativeLifecycleEvidenceService` | accept its own output |
| revision acceptance decision | Narrative workflow authority | `NarrativeAcceptanceService` | mutate prose or Canon |
| change-set review decision | Narrative workflow authority | `NarrativeAcceptanceService` | compile or commit Canon |
| conflict-resolution decision | Narrative workflow authority | `NarrativeAcceptanceService` | infer a Human choice |
| compilation attempt/result and exact `CompiledCanonDeltaEvidence` | immutable deterministic-execution evidence | `NarrativeLifecycleEvidenceService` around `CanonDeltaCompiler` | make its inputs current |
| `NarrativeHandoffAdmission` plus exact immutable approval copy | immutable Narrative boundary-crossing evidence | `NarrativeAcceptanceService` | approve, replace, or commit the copied M5A approval |
| `CanonCommitApproval`, accepted `CanonDelta`, `CanonVersion` | Canon authority | existing M5A boundary | derive Narrative acceptance |

`NarrativeLifecycleEvidenceService` and `NarrativeAcceptanceService` are separate
capabilities. They may share a database and internal UoW implementation, but no public
interface exposes a combined unrestricted repository.

### 2.2 Human-approved M5C decisions

This design freezes the following reviewed choices:

1. `NarrativeAcceptanceService` owns three typed decision families: revision
   acceptance, change-set review, and change-set conflict resolution.
2. Revision and change-set heads have different logical keys and multiplicity.
3. New downstream work requires exact currently effective decision references;
   historical replay cannot create a current capability.
4. Opaque decision IDs use full semantic-tuple equality for exact retry; prose and
   payload hashes are never decision identities.
5. Authority uses a hybrid topology: three semantic command surfaces backed by one
   internal authority kernel/UoW, with separate evidence recording and a pure compiler.
6. `REJECT` advances the latest decision chain but never changes the effective
   selection. M5C v1 has no implicit revoke.
7. First-head concurrency uses unique genesis insertion followed by lock/reread.
8. Conflict resolution uses a stable opaque lineage within one accepted revision.
9. Currentness is frozen at atomic handoff admission. Later Narrative supersession
   does not retroactively invalidate an admitted M5A action.
10. Successful extraction and compilation evidence are atomic bundles; compilation owns
    the exact durable `CanonDelta` payload.
11. Conflict-lineage genesis belongs only to `resolve_change_set_conflict()` and one
    revision plus canonical conflict subject maps to one lineage.
12. M5C v1 decision authority is Human Showrunner only. Generic administrator state,
    authorship, Agents, providers, extractors, compilers, and orchestration confer none.
13. Exact reads hide cross-scope IDs as not-found; database-global create collisions use
    a generic non-disclosing identity conflict.
14. `OUTCOME_UNKNOWN` is terminal and M5C v1 does not ingest late provider success.
15. A handoff admission is bound to one exact persisted delta and one exact M5A approval
    tuple/retry lineage.
16. Every donor-derived M5C surface must pass the project-wide `R2-DEC-031` gate.
17. M5C owns the narrow F9 closure as a forward SceneContract/NarrativePlan v2
    compatibility extension. Accepted v1 bytes and M5B evidence remain immutable.
18. Relationship constraints are typed read-only selectors over Canon Facts. Thread
    lifecycle validation is a plan-level cross-scene pass, not a per-scene rule.
19. A thread payoff requires exact accepted Narrative evidence after the acceptance layer
    exists. A tag, payoff ref, or prose string cannot prove fulfillment.
20. The SceneContract half of the deferred omniscient-authoring gate rides the same v2
    transition. The typed CreativePolicy half remains explicitly deferred.
21. F9 validators are clean-room R2 implementations informed by donor patterns only; F9
    itself does not activate the four `R2-DEC-031` donor-port gates.
22. Handoff admission durably owns a lossless immutable copy of the exact existing M5A
    approval tuple so restart recovery never reconstructs or replaces it.
23. Original decision authorization and fresh retry authentication are distinct
    capabilities. Only the former is immutable decision identity.
24. Narrative effect keys form a typed union of Canon-mutation and Narrative-outcome
    effects. A valid outcome-only selection returns `NO_CANON_MUTATION`, never an empty
    `CanonDelta`.
25. Scene-level omniscient permission can pass only its necessary SceneContract gate.
    Overall no-POV `AUTHOR_DRAFT` remains blocked until typed CreativePolicy authority
    supplies the second conjunct.

### 2.3 No new Canon authority

M5C ends at a `CanonDelta` proposal and a Narrative handoff-admission receipt. The
authenticated application facade constructs or receives the existing M5A
`CanonCommitApproval`, binds its exact tuple during Narrative admission, and then calls
the existing `CanonTransactionService.commit()` with that same approval.

The admission receipt is not a Canon approval, cannot waive M5A validation, and cannot
override M5A branch/base OCC. M5C adds no Canon repository, Canon approval service,
Canon transaction, or direct Canon table write.

### 2.4 Evidence and reuse boundaries

The design reuses these verified Host seams:

- M5A `CanonDelta`, canonical payload hashing, `CanonCommitApproval`, branch/base OCC,
  and `CanonTransactionService` without changing their authority;
- M5B exact Canon/Plan/Scene/Context identities, prose normalization, immutable source
  descriptors, and read-only `AcceptedNarrativeReader` seam;
- M5B's append-only plan service as a transaction/idempotency pattern, not as Narrative
  acceptance storage; and
- the Host async database/UoW conventions as the persistence substrate.

The current filesystem-backed `DraftWorkflow` quarantine may remain a UI/workbench
transport during migration, but its file lock, revision counter, status fields, and prose
files are not M5C authority or durable decision history.

External and donor evidence is deliberately narrower than adoption:

| Source | Pattern retained | Explicit exclusion |
|---|---|---|
| PostgreSQL | short transactions, row locks, unique/FK/check constraints, canonical lock order | absent-row locking by `FOR UPDATE`; long cross-authority transactions |
| KurrentDB/EventStoreDB | expected predecessor, append-only history, rebuildable projections | framework/database dependency; weaker event-ID-only dedupe |
| Temporal | durable attempt identity and late-completion fencing | workflow-engine dependency; loss of intermediate attempt history |
| Novel Studio | exact bounded context and deterministic selection shapes | donor memory/truth store |
| Shenbi | evidence-oriented extraction and Human review workflow | donor authority or direct Canon writes |
| Huohuo | causal change-record normalization | treating a donor change record as `CanonDelta` |
| StoryBox | character-local narrative context | simulator output as acceptance or Canon truth |

These sources support failure-window analysis. ArcReel-specific scope, authority,
identity, and handoff semantics come only from ADR-0076 and the Human decisions recorded
for this design.

`R2-DEC-031` governs every donor-derived M5C surface. M5C v1 selects exactly two Python
ports:

- Huohuo `workbench-server/src/common/novel/novel-change-record.ts` at
  `appolloqin/huohuo-drama@f104b853b3563e124d9cde25f9331d323fb483b9`, source
  SHA-256 `dd3a310e1d83f80fca132a6ea64380c3d953c780054d0ea93e9f865c09fb5088`,
  for pure change-record parsing/normalization into proposal evidence; and
- Novel Studio `src/lib/continuity/hardRules.ts` at
  `YfengJ/novel-studio-ai@9b690ae2e2f6921f9bd2782b42cef53c1662ad3b`, source
  SHA-256 `7756c4093b52e11e3f591c58af1719887428fd5e437f4ade0828533ac3663954`,
  for deterministic continuity findings and stable report merging.

Neither port receives an authority or persistence interface. Shenbi state-settling and
Novel Studio memory extraction remain reference-only; they are not called a parity-tested
port. Any later concrete donor-derived behavior expands the `R2-DEC-031` baseline and must
pass its gates before acceptance.

The F9 relationship and thread validators are a separate clean-room surface. Novel
Studio relation triples and Huohuo unclosed-causal records inform only terminology and
edge-case checklists. No donor source is copied, translated, imported, or executed for
F9, so F9 does not activate `R2-DEC-031` baseline, coverage, same-fixture parity, or
exact-HEAD donor completion. The selected Huohuo and Novel Studio ports below remain
independently subject to all four gates.

Both selected sources are executable TypeScript, so corpus assertions alone cannot
establish parity. M5C verification must compile/run each unmodified exact pinned donor
source through a small test-only Node harness and run its Python port against the same
canonical fixtures. Huohuo runs in its pinned source-tree context so its relative
`novel-memory-parser.js` dependency resolves without altering the baseline. Each harness
verifies the manifest revision and source hash before execution. These harnesses are
development evidence only: they are not shipped, imported, or started by the ArcReel/M5C
runtime and do not weaken the no-separate-TypeScript-service decision.

## 3. Scope decomposition

M5C is delivered through four sequential checkpoints:

```text
M5C-1  Versioned M5 compatibility + immutable Narrative lifecycle evidence
       M5C-1A: SceneContract/NarrativePlan v2 + F9/R9/R10
                + scene-side omniscient gate + donor compatibility/parity
                -> clean verified HEAD + independent review
       M5C-1B: draft/revision + extraction attempt/result
                + NarrativeChangeSet
                -> final M5C-1 checkpoint
              |
              v
M5C-2  Narrative acceptance authority
       typed decisions + logical heads + conflict-resolution lineage
              |
              v
M5C-3  CanonDelta compilation
       compilation attempt/result + pure exact-input compiler
       + exact accepted thread-payoff proof binding
              |
              v
M5C-4  M5A handoff admission and acceptance corpus
       atomic currentness receipt + authenticated existing M5A path
       + combined M5 v2 exit fixture
```

`M5C-1A` and `M5C-1B` are mandatory internal subgates, not new externally numbered
milestones. The compatibility/hash/validator blast radius is frozen and independently
reviewed before lifecycle persistence is added. Donor ports and the same-fixture Node
parity harness land in `M5C-1A`; `M5C-1B` integrates their proposal output only through
the immutable evidence contracts. `M5C-1` is not complete until both subgates pass.

Each checkpoint must be independently reviewable and green. Later checkpoints may read
earlier immutable artifacts through exact ports; they cannot bypass the owning service.

## 4. Stable scope and exact bases

### 4.1 NarrativeWorkScope

```text
NarrativeWorkScope
  user_id
  project_name
  plan_id
  scene_contract_id
  canon_branch_id
```

The tuple above is the stable workflow scope. Every repository operation additionally
takes `user_id` and `project_name`, even when an opaque ID is expected to be globally
unique. Cross-scope and unknown identifiers return the same public not-found behavior.

The following are immutable bindings, not stable-scope fields:

```text
canon_version_id
plan_version
scene_contract_version
context_pack_id
creative_policy_ref + creative_policy_version
compiler_version
extractor/version/provenance identifiers
```

No service may replace any exact binding with a current or latest value. Equal prose
under different bindings remains different workflow evidence.

### 4.2 Normalized prose identity

Draft and revision prose uses the frozen M5B normalization and canonical byte rules.

```text
content_hash = sha256(normalized UTF-8 prose bytes)
```

`content_hash` proves prose bytes only. A separate semantic fingerprint covers the
artifact kind, opaque artifact ID, stable scope, exact bases, provenance, and relevant
schema/policy versions. Neither hash selects an artifact or grants authority.

### 4.3 M5 relationship/thread compatibility extension (F9)

M5C closes finding F9 as a forward, versioned compatibility extension over the accepted
M5B base. It does not amend the meaning of an accepted M5B commit, rewrite a persisted
v1 SceneContract or NarrativePlan, or create a new Canon authority. Relationship truth
continues to be represented by Canon Facts and every mutation continues through the
existing M5A approval and transaction boundary. Plot-thread declarations remain
authorial plan state; accepted prose and change sets provide outcome evidence but do not
become Canon merely by being accepted.

#### 4.3.1 Versioned SceneContract and NarrativePlan

The extension adds these selectors:

```text
r2-scene-contract-content-v2
r2-narrative-plan-v2
r2-narrative-plan-content-v2
```

Persisted reads discriminate SceneContract values by `semantic_hash_version` and plan
values by their schema/content-hash selectors. The v1 serializers retain their exact
accepted field set and byte domain; they must not begin serializing empty/default v2
fields. A v2 NarrativePlan may contain an explicit union of v1 and v2 SceneContracts so
unaffected scene identities remain byte-stable.

V2-only SceneContract semantics are:

```text
SceneRelationshipConstraint
SceneThreadConstraint
omniscient_authoring_allowed_by_scene = true
```

The current content determines the minimum legal selector, while immutable lineage
determines whether a downgrade would occur:

```text
genesis -> v1       legal when no v2-only semantics are present
genesis -> v2       legal
v1 -> v1            legal when no v2-only semantics are present
v1 -> v2            legal
v2 -> v2            legal, including after v2-only lists later become empty
v2 -> v1            illegal
```

Thus a new or still-v1 scene containing only Fact/Knowledge constraints remains v1. A
scene using any v2-only semantic must select v2. Once one logical scene lineage reaches
v2, every later version remains v2 even if its current v2-only lists are empty. The plan
aggregate follows the same ratchet: a plan containing a v2 scene must be v2, and a plan
lineage cannot downgrade after reaching v2.

The migration is append-only. A v1 scene that acquires v2 semantics receives the exact
next scene version and a v2 semantic hash. Unchanged v1 scenes retain their existing
versions and hashes inside the new plan version. The plan revision/version advances
under the existing approval and OCC rules. Version-dispatched hash functions reject an
unknown selector, a selector below the content's minimum, a v2-to-v1 downgrade, and any
supplied hash that does not match the exact selected byte domain.

#### 4.3.2 Relationship constraint and Canon Fact profile

```text
SceneRelationshipConstraint
  constraint_id
  constraint_kind = RELATIONSHIP
  source_character_ref
  target_character_ref
  relationship_key          # for example trust_level
  comparison:
    PRESENT | ABSENT | EQUALS | NOT_EQUALS
  expected_state?           # non-empty string; for example TRUSTED
```

Both character refs must resolve to distinct `CHARACTER` entities in the exact Canon
basis. Relationships are directional. Symmetry is never inferred: a reciprocal
relationship requires a second Fact and, when required by the scene, a second explicit
constraint.

The only legal mapping to the existing Fact contract is the shared versioned function:

```text
relationship_fact_predicate(
  target_character_ref,
  relationship_key,
  mapping_version = r2-relationship-fact-key-v1,
) =
  "r2rel:" + sha256(canonical_json({
    "schema": "r2-relationship-fact-key-v1",
    "target_character_ref": target_character_ref,
    "relationship_key": relationship_key,
  }))

Fact.subject_ref = source_character_ref
Fact.predicate   = relationship_fact_predicate(...)
Fact.value       = relationship state string
```

This yields a distinct existing M5A `(subject_ref, predicate)` collision key for every
directional `(source, target, relationship_key)`. The validator, change-set effect-key
normalizer, and CanonDelta compiler call the same pure function. No extractor, compiler,
provider, orchestration layer, or caller may concatenate or otherwise invent a
relationship predicate.

An active Fact selected by this profile whose value is not a non-empty string is
malformed relationship state and produces the relationship-integrity finding; it is not
coerced, stringified, or treated as absence.

Relationship truth is evaluated at the list-defined exact instant using active Facts:

| Comparison | `expected_state` | Match semantics |
|---|---|---|
| `PRESENT` | forbidden | exactly one active Fact exists for the exact relationship key; its state is ignored |
| `ABSENT` | forbidden | no active Fact exists for the exact relationship key |
| `EQUALS` | required | exactly one active Fact exists and its canonical state equals `expected_state` |
| `NOT_EQUALS` | required | exactly one active Fact exists and its canonical state differs; absence is not inequality |

More than one active Fact for the exact relationship key is an integrity error, even
when the values are equal; the selector never chooses one. Entry failures use
`SCENE_ENTRY_RELATIONSHIP_UNMET`, exit failures use
`SCENE_EXIT_RELATIONSHIP_UNMET`, and ambiguous/malformed Canon state uses a distinct
relationship-integrity finding.

#### 4.3.3 Thread constraint and cross-scene lifecycle

```text
SceneThreadConstraint
  constraint_id
  constraint_kind = THREAD
  thread_ref
  required_state:
    OPEN | RESOLVED
  payoff_ref?               # forbidden for OPEN; required for RESOLVED

SceneStateConstraint =
  SceneFactConstraint
  | SceneKnowledgeConstraint
  | SceneRelationshipConstraint
  | SceneThreadConstraint
```

The containing `entry_state_constraints` or `exit_state_targets` list supplies the
evaluation phase. `active_threads` describes thread context active at scene entry/during
the scene, consistent with the M5B pre-scene ContextPack. `promise_payoff_refs` is an
authorial reference list, not proof that a payoff occurred.

Thread structure is validated once over the whole plan by the pure function:

```text
validate_plan_thread_lifecycle(plan_content)
```

It lives beside, but is not folded into, `validate_plan_hierarchy()`. NarrativePlanService
runs both plan-wide passes before its existing per-scene validation loop. The lifecycle
pass sorts by the already unique `sequence_index`; presentation order, not story-time
order, defines thread progression. It applies these rules:

1. The first appearance in `active_threads` establishes the thread as open at that scene
   entry. Later omissions do not implicitly resolve it.
2. An entry `OPEN` constraint requires the thread to be open and present in that scene's
   `active_threads`. An entry `RESOLVED` constraint requires an earlier resolution and the
   thread to be absent from `active_threads`; its `payoff_ref` must equal the payoff that
   performed that earlier resolution.
3. An exit `OPEN` target requires the thread to remain open with no resolution in that
   scene.
4. An exit `RESOLVED` target requires the thread to be open at entry, requires its exact
   `payoff_ref` in that scene's `promise_payoff_refs`, and marks it resolved after that
   scene.
5. Resolution without a prior/open thread, orphan payoff binding, two resolutions, and
   any later reappearance/re-open of the same resolved `thread_ref` fail closed.
6. No per-scene call to `validate_scene()` may claim these cross-scene invariants.

Structural failures use `SCENE_THREAD_LIFECYCLE_*`. These findings prove that the plan is
internally consistent; they do not prove that accepted prose actually delivered a
payoff.

#### 4.3.4 Accepted thread-payoff outcome proof

After M5C-2 supplies Narrative authority, M5C-3 may validate a planned resolution against
an exact immutable proof value assembled from existing evidence and decisions:

```text
AcceptedThreadPayoffProof
  thread_ref
  payoff_ref
  revision_id
  revision_acceptance_decision_id
  change_set_id
  review_decision_id
  conflict_resolution_decision_ids[]
  source_spans[]
```

This value is a typed read view, not a new write authority or a mutable payoff row. The
named `NarrativeChangeSet` must contain the exact typed
`THREAD_PAYOFF(thread_ref, payoff_ref)` effect key, every source span must be covered by
that immutable change set, and all named revision/review/resolution decisions must be
applicable and currently effective when new outcome work is admitted. Historical replay
may resolve the same exact proof without treating it as current authority.

`validate_thread_payoff_outcome()` is a pure exact-input validator introduced only after
the M5C-2 decision layer exists. A `promise_payoff_refs` entry, active-thread tag, model
claim, or prose substring without this accepted proof yields `SCENE_EXIT_THREAD_UNMET`.
Extraction of relationship/thread changes remains part of the general M5C
`NarrativeChangeSet` proposal flow; F9 does not create a second extractor or acceptance
path.

#### 4.3.5 Scene-side omniscient-authoring gate

The same v2 transition adds:

```text
omniscient_authoring_allowed_by_scene: bool = false
```

A v1 scene is treated as `false`. An `AUTHOR_DRAFT` request with no POV passes only the
SceneContract half when the selected scene has `pov is None` and the v2 field is `true`;
otherwise that scene gate fails before reading author-only material. Passing this half is
not overall admission. A `CHARACTER_SIMULATION` request still always requires its exact
POV subject.

This field records only scene-level authorial permission. It is a necessary condition,
not the full future authorization promised by M5B's “SceneContract and policy” wording.
The CreativePolicy read seam remains opaque prose and cannot grant a capability. The
typed CreativePolicy conjunct stays explicitly deferred until its owning contract and
authority exist; no compiler may infer it from policy text. Until that capability exists,
every no-POV `AUTHOR_DRAFT` request that passes the scene half terminates with the stable
`AUTHOR_DRAFT_POLICY_CAPABILITY_UNAVAILABLE` finding and remains blocked overall. M5C has
no fully permitted no-POV authoring case.

#### 4.3.6 R9 and R10 closure

M5C-1 closes the adjacent M5B validation gaps while the same contracts and validators are
already under change:

- R9: every Fact/Knowledge/Relationship entity or proposition reference that describes
  present Canon state must resolve against the exact plan Canon basis. A future exact
  `event_ref` may be absent at plan commit and remains an obligation, but it must resolve
  to that exact Event during post-scene outcome validation; an existing incompatible ref
  fails at plan commit.
- R10: every `constraint_id` is unique within one SceneContract, and two normalized
  semantically identical constraints in the same list are rejected even when their IDs
  differ. Required/forbidden or entry/exit collisions continue to use their dedicated
  semantic findings rather than being hidden as duplicate-ID errors.

These checks add no field and therefore are not independent hash-version triggers. They
run as current new-work eligibility validation on v1 and v2 scenes. They do not
retroactively redefine historical persisted-v1 integrity: an old accepted v1 artifact is
verified and replayed against its committed schema/hash and the rules in force at its
decision time. Failing a newly introduced R9/R10 eligibility rule blocks that artifact
from a new downstream workflow step; it does not make the immutable row corrupt, rewrite
its acceptance evidence, or change its historical hash.

## 5. Immutable evidence contracts

All public contracts are frozen, reject extra fields, use timezone-aware UTC timestamps,
and use explicitly versioned canonical hash domains.

### 5.1 DraftCandidate

```text
DraftCandidate
  candidate_id
  work_scope
  base_canon_version_id
  plan_version
  scene_contract_version
  context_pack_id
  normalized_content
  content_hash
  writer_kind
  writer_version
  provenance
  created_at
  created_by
  semantic_fingerprint
```

Writer output is evidence only. `writer_kind` may identify a Human, local tool, Agent,
or provider-backed adapter, but it never implies acceptance.

### 5.2 NarrativeRevision

```text
NarrativeRevision
  revision_id
  work_scope
  base_candidate_id
  predecessor_revision_id?
  base_canon_version_id
  plan_version
  scene_contract_version
  context_pack_id
  normalized_content
  content_hash
  review_refs[]
  provenance
  created_at
  created_by
  semantic_fingerprint
```

`predecessor_revision_id` expresses immutable evidence lineage, not effective acceptance.
The service verifies that candidate, predecessor, scope, and exact bases agree. A cycle,
cross-scope reference, missing predecessor, or ID reuse with different bytes fails before
any insert.

There is no `accepted` boolean on the revision. Acceptance exists only in the decision
stream described in Section 6.

### 5.3 ExtractionAttempt and ExtractionResult

```text
ExtractionAttempt
  attempt_id
  generation
  work_scope
  revision_id
  revision_acceptance_decision_id
  observed_revision_effective_generation
  base_canon_version_id
  plan_version
  scene_contract_version
  context_pack_id
  extractor_kind
  extractor_version
  policy_ref + policy_version
  admitted_at
  admitted_by
  input_fingerprint

ExtractionResult
  result_id
  attempt_id
  generation
  outcome: SUCCEEDED | ABSTAINED | CONFLICT | FAILED | OUTCOME_UNKNOWN
  change_set_ids[]
  diagnostics[]
  provider_receipt?
  completed_at
  output_fingerprint
```

The attempt is persisted before external extraction begins. There is at most one result
for `(attempt_id, generation)`. Same result identity and full tuple is an exact retry;
any mismatch is an identity conflict. A late result for a superseded generation remains
evidence but cannot advance workflow.

A `SUCCEEDED` result and every `NarrativeChangeSet` named by its ordered
`change_set_ids` land as one atomic evidence bundle. The bundle must contain at least one
change set, and the declared IDs must equal the supplied change-set identities exactly.
No successful result is observable before all of its proposal evidence exists. A
non-success result has an empty `change_set_ids` list and may be appended alone.

`OUTCOME_UNKNOWN` is legal only when an external nondeterministic effect may have
completed but its response was lost. It never means accepted, never advances a head,
and is terminal for that exact attempt generation. M5C v1 does not ingest a later
provider success, payload, or change set into that generation and does not define a core
`ExtractionReconciliation` record. A provider adapter may retain a late observation in
its own non-authoritative audit log outside the M5C lifecycle, but that observation cannot
authorize workflow advancement. Continuing the workflow requires a newly admitted
generation that references the prior `OUTCOME_UNKNOWN` result. A local deterministic
extractor that crashes leaves an attempt without a result or records `FAILED`; it does
not manufacture ambiguity.

### 5.4 NarrativeChangeSet

The frozen `NarrativeChangeSet` semantic shape remains intact and gains explicit M5C
workflow identity and coverage metadata:

```text
NarrativeChangeSet
  change_set_id
  change_set_lineage_id
  source_revision_id
  extraction_attempt_id + extraction_generation
  base_canon_version_id
  source_spans[]
  semantic_effect_keys[]
  changes[]
  confidence
  extractor_version
  policy_ref + policy_version
  created_at
  output_fingerprint
```

`source_spans` use one normalized coordinate system and canonical sort order.
`semantic_effect_keys` are not free-form labels. They use this closed, versioned algebra:

```text
NarrativeSemanticEffectKey =
    CanonMutationEffectKey
  | NarrativeOutcomeEffectKey

CanonMutationEffectKey
  -> identifies an affected Canon subject/effect
  -> may map to one or more existing M5A Canon operations

NarrativeOutcomeEffectKey
  -> identifies accepted Narrative outcome coverage/conflict semantics
  -> maps to zero Canon operations

THREAD_PAYOFF(thread_ref, payoff_ref) is a NarrativeOutcomeEffectKey
```

Both `source_spans` and `semantic_effect_keys` are non-empty when the change set proposes
an effect. Both key families participate in canonical ordering, coverage, collision, and
Human conflict-resolution rules. Each change's evidence span must be contained by
declared coverage. A Narrative outcome key never implies that PlotThread is Canon state
and cannot be coerced into a Canon mutation.

`change_set_lineage_id` is opaque workflow identity. It partitions alternative proposals
for the same semantic change. It is not inferred from prose, overlap, or hash equality.
One successful extraction result may produce multiple non-overlapping lineages.

An extractor can append a proposal but receives no review or decision write port.

### 5.5 CompilationAttempt and CompilationResult

```text
CompilationAttempt
  attempt_id
  generation
  work_scope
  revision_id
  revision_acceptance_decision_id
  selected_change_sets[]:
    change_set_id
    review_decision_id
  conflict_resolution_decision_ids[]
  observed_effective_heads[]
  base_canon_version_id
  plan_version
  scene_contract_version
  context_pack_id
  creative_policy_ref + creative_policy_version
  compiler_version
  requested_canon_delta_id
  delta_created_at
  delta_created_by
  admitted_at
  admitted_by
  input_fingerprint

CompilationResult
  result_id
  attempt_id
  generation
  outcome: SUCCEEDED | NO_CANON_MUTATION | ABSTAINED | CONFLICT | FAILED
  canon_delta_id?
  canon_delta_payload_hash?
  diagnostics[]
  completed_at
  output_fingerprint

CompiledCanonDeltaEvidence
  compilation_result_id
  compilation_attempt_id + generation
  canon_delta: exact immutable M5A CanonDelta payload
  canon_delta_payload_hash
  stored_at
```

The attempt is admitted and persisted while all named decisions are currently effective.
Compilation then runs outside the authority transaction over exact immutable inputs.

The pure local compiler has no `OUTCOME_UNKNOWN` result. A crash before result recording
leaves a durable attempt with no result; the same exact generation may be recomputed and
recorded idempotently. A nondeterministic external adapter introduced later must own a
separate execution attempt/result boundary rather than weakening compiler semantics.

A `SUCCEEDED` compilation result and its exact `CompiledCanonDeltaEvidence` land in one
transaction. The evidence owns the complete immutable `CanonDelta`, not only its ID/hash,
and is keyed one-to-one by `compilation_result_id`. The service recomputes the existing
M5A payload hash before insert and requires exact equality with both the result and the
embedded delta. Non-success results have null delta fields and no compiled-delta row.
Handoff and recovery reload this persisted payload; rerunning the compiler is an integrity
check, not the normative recovery path for obtaining the proposal.

`NO_CANON_MUTATION` also has null delta fields and no compiled-delta row, but is a valid
deterministic terminal result rather than an abstention or failure. It means that the
complete valid selected effect set contains zero `CanonMutationEffectKey` values after
explicit conflict resolution. It cannot create a handoff admission or enter M5A.

A selection containing a `CanonMutationEffectKey` that is unsupported, underspecified,
or fails to generate its required operation returns `ABSTAINED` or `FAILED`; it may not be
mislabeled `NO_CANON_MUTATION`. M5C never fabricates a no-op or empty `CanonDelta`.

The compiled-delta row stores the lossless canonical M5A payload inline with its payload-
hash algorithm/version and content-schema version. JSONB is acceptable only when a strict
contract round trip reproduces the same canonical M5A bytes and hash. An ephemeral cache,
caller resubmission, or external object reference is not the owning durable copy.

## 6. Narrative decision authority

### 6.1 Typed decision families

The public service exposes three narrow commands:

```text
decide_revision(command)                 -> NarrativeDecisionReceipt
review_change_set(command)               -> NarrativeDecisionReceipt
resolve_change_set_conflict(command)     -> NarrativeDecisionReceipt
```

The commands share one internal authority kernel for canonical identity, exact retry,
locking, OCC, append, and commit. The contracts and database tables remain typed so
family-specific foreign keys and cardinalities are enforceable.

`resolve_change_set_conflict()` is also the only conflict-lineage creation interface. Its
genesis form atomically creates the lineage, creates its zero-generation head, appends the
first `RESOLVE` or `REJECT` decision, and advances that head as required. There is no
public `open_change_set_conflict()` or evidence/compiler path that can allocate a lineage.

Family actions are:

```text
RevisionDecisionAction = ACCEPT | REJECT | SUPERSEDE
ChangeSetReviewAction = ACCEPT | REJECT | SUPERSEDE
ConflictResolutionAction = RESOLVE | REJECT | SUPERSEDE
```

`SUPERSEDE` always names the old effective decision and a new selected artifact or
resolution. It does not mutate the old decision. M5C v1 has no implicit or standalone
revoke. A future ability to clear a selection without replacement requires a new ADR
amendment because it changes downstream cardinality.

### 6.2 Human authority capability policy

M5C v1 authorizes only an authenticated Human Showrunner to invoke Narrative decision
commands:

| Actor/capability | Decide revision | Review change set | Resolve conflict |
|---|---:|---:|---:|
| authenticated Human Showrunner capability | ALLOW | ALLOW | ALLOW |
| delegated Narrative Reviewer | DENY in v1 | DENY in v1 | DENY in v1 |
| Human author without Showrunner capability | DENY | DENY | DENY |
| extractor, compiler, Agent, provider, or orchestrator | DENY | DENY | DENY |
| generic host administrator role alone | DENY | DENY | DENY |

The authenticated facade uses one injected `NarrativeShowrunnerAuthorityPort`. Its sole
source of truth is an explicit project-scoped `HUMAN_SHOWRUNNER` grant issued by the
frozen Governance/Showrunner approval authority:

```text
NarrativeShowrunnerAuthorityPort
  authorize_initial_decision(authenticated_principal, canonical_command)
    -> NarrativeDecisionAuthorization
  authenticate_exact_retry(authenticated_principal, decision_id, exact_scope)
    -> NarrativeDecisionRetryAuthentication
```

M5C may read and verify that grant but receives no capability to create, amend, revoke,
or infer it. A generic Host administrator role, API-key possession, `user_id`, authorship,
or single-operator deployment mode is not the grant. The current Governance/Showrunner
boundary is manual/fixture-only; therefore M5C may use an explicit test fake for
acceptance evidence, but every production adapter must deny by default and production
activation is a STOP condition until that authority source exists. M5C does not silently
expand scope by implementing a replacement governance service.

The initial explicit Human action produces:

```text
NarrativeDecisionAuthorization
  authorization_ref
  user_id + project_name
  actor_id
  authority_role: HUMAN_SHOWRUNNER
  decision_family + action
  decision_id
  stable_subject_fingerprint
  decision_command_fingerprint
  authenticated_at
  authenticated_via
```

The authorization is the original Human approval/review evidence. It is immutable,
scoped to one exact canonical command, persisted with the typed decision, and included
in stored decision identity. Reuse for another family, action, scope, decision ID, or
command fingerprint fails closed.

A later request that may be an exact retry supplies fresh authentication, not a new
decision authorization:

```text
NarrativeDecisionRetryAuthentication
  retry_authentication_ref
  user_id + project_name
  actor_id
  authority_role: HUMAN_SHOWRUNNER
  decision_id
  authenticated_at
  authenticated_via
```

This value proves only that the same original `actor_id` is currently authenticated and
may request replay in the exact scope. It is never persisted as the original Human
decision, is not part of decision identity, and cannot authorize a new decision or
different command.

M5C v1 does not require four-eyes separation. The same Human may author source prose or
proposal evidence and later decide it only if that person separately performs the
explicit authenticated Showrunner action. Authorship, extraction, possession of an ID,
or a prior decision never implies authorization. Adding delegated reviewer roles or
family-limited delegation requires a later explicit policy decision and receipt shape.

### 6.3 Decision identity and exact retry

Every command carries:

```text
decision_id
decision_family
action
stable subject key
selected evidence IDs
expected_latest_decision_id: decision ID | null
expected_effective_decision_id: decision ID | null
exact Canon/Plan/Scene/Context bindings
Human actor identity
family-specific semantic inputs
```

For a new `decision_id`, the facade obtains exactly one
`NarrativeDecisionAuthorization`; the authority service verifies its binding and stores
it atomically with the decision. For an already-stored same-scope ID, the service first
validates `NarrativeDecisionRetryAuthentication`, reloads the original stored
authorization, verifies its immutable binding to the stored decision, and compares the
canonical business command without substituting the fresh authentication value.

`decision_id` is an opaque idempotency identity. A shared identity registry enforces
global uniqueness across all three physical decision tables:

```text
narrative_decision_identities
  decision_id PRIMARY KEY
  user_id
  project_name
  decision_family
  canonical_identity_hash
```

The registry row and typed decision row land in the same transaction. Decision identity
is globally unique before any typed authority write; `user_id` and `project_name` remain
part of the canonical tuple and every lookup predicate. Reusing an ID in another scope,
family, or with any different canonical tuple is an identity conflict and writes nothing.
This create-path collision returns one generic identity-conflict shape and never exposes
the owning scope, family, subject, actor, or content.

Stored decision identity includes all fields above plus the exact original
`NarrativeDecisionAuthorization`, including its receipt time. Exact retry comparison
includes expected pointers, selected IDs, bases, original actor, conflict coverage, and
chosen resolution. Fresh `NarrativeDecisionRetryAuthentication` is deliberately excluded
from identity. The service records `stored_at` as audit metadata after validation; it is
not command or retry identity.

After fresh retry authentication and stored tuple verification, exact retry is resolved
before either predecessor is judged stale. It returns the original immutable decision
and original authorization without changing a head. `currently_effective` is deliberately
absent from that receipt because currentness can change later.

### 6.4 Why two expected predecessors are required

`REJECT` advances the append-only decision chain but does not change the effective
selection. Therefore one predecessor field cannot express both concurrency facts:

```text
expected_latest_decision_id
  -> serializes every Human decision for the logical subject

expected_effective_decision_id
  -> proves which accepted selection the command expects to preserve or replace
```

Both are part of retry identity. Genesis expects both to be null. `ACCEPT` requires no
existing effective selection. `SUPERSEDE` requires the exact current effective decision.
`REJECT` names a candidate and preserves the effective pointer after verifying the
caller's expected view.

### 6.5 Logical heads

```text
RevisionAcceptanceHead
  key = (user_id, project_name, plan_id, scene_contract_id, canon_branch_id)

ChangeSetReviewHead
  key = (revision_acceptance_decision_id, change_set_lineage_id)

ConflictResolutionHead
  key = (revision_acceptance_decision_id, conflict_resolution_lineage_id)
```

Every logical head contains:

```text
latest_decision_id?
decision_generation
effective_decision_id?
effective_generation
```

`decision_generation` increases for every new decision. `effective_generation` increases
only when the effective selection changes. A rejection of an unrelated proposal must not
invalidate a compilation that consumes the unchanged effective decision.

A revision head has no effective decision before its first acceptance and exactly one
after acceptance. A change-set or conflict head has at most one. Many non-overlapping
change-set heads and independent conflict heads may coexist under one revision acceptance.

Heads are rebuildable lock/index projections. The typed append-only decisions and their
validated predecessor chains remain authoritative.

A current-selection guard never trusts a head pointer alone. Under the head lock it loads
the referenced typed decisions, validates subject/action/predecessor consistency, and
proves that the latest pointer and folded effective pointer agree with the authoritative
chain. Any mismatch is `NarrativeAuthorityIntegrityError`, not an accepted selection.

### 6.6 REJECT semantics

`REJECT` records a Human judgment about the exact named candidate or proposed resolution:

- it appends a typed decision;
- advances `latest_decision_id` and `decision_generation`;
- leaves `effective_decision_id` and `effective_generation` unchanged;
- cannot clear or replace an unrelated effective selection; and
- cannot be consumed by extraction, compilation, or handoff as an accepted selection.

If an effective selection must change, the caller submits `SUPERSEDE` with the exact old
effective decision and the exact new evidence. A rejection after acceptance is not a
hidden revocation.

### 6.7 ConflictResolutionLineage

```text
ConflictResolutionLineage
  conflict_resolution_lineage_id
  revision_acceptance_decision_id
  conflict_subject:
    canonical source-span coverage[]
    canonical semantic-effect keys[]
  conflict_subject_fingerprint
  created_at
  created_by
```

The opaque lineage is allocated by the genesis form of
`resolve_change_set_conflict()` when a conflict thread is first identified. Its revision
and conflict subject are immutable. The caller proposes an opaque lineage ID, but the
service derives the versioned `conflict_subject_fingerprint` from the minimal canonical
intersection of the exact currently effective competing reviewed change sets. Caller-
supplied widened, partial, reordered, or free-form coverage is rejected.

The database enforces:

```text
UNIQUE (revision_acceptance_decision_id, conflict_subject_fingerprint)
```

Therefore the same accepted revision plus the same canonical conflict subject denotes
one lineage. Materially different conflict coverage creates another lineage. Reuse of a
lineage ID for another subject is an identity conflict. If concurrent genesis commands
propose different opaque IDs for the same subject, one lineage wins and the other command
receives `NarrativeConflictLineageConflict` with no writes; within the already authorized
scope it may resolve and retry against the winning lineage. The compiler never performs
this resolution.

A resolution decision names:

```text
competing change_set_ids[]
competing review_decision_ids[]
exact overlapping spans/effect keys
chosen resolution
Human actor + approval receipt
expected latest/effective predecessors
```

The chosen resolution is a typed semantic instruction that the compiler version
understands; it is not unrestricted prose. A resolution is currently applicable only
while it is the effective resolution for its head and every named review decision remains
effective. Replacing a reviewed change set makes any resolution naming it inapplicable,
even before a replacement resolution is authored.

The compiler cannot create a lineage, merge lineages, widen conflict coverage, infer a
choice, or choose the latest resolution.

## 7. Persistence and transaction semantics

### 7.1 Logical tables

The preferred physical schema uses typed tables:

```text
narrative_draft_candidates
narrative_revisions
narrative_extraction_attempts
narrative_extraction_results
narrative_change_sets
narrative_compilation_attempts
narrative_compilation_results
narrative_compiled_canon_deltas
narrative_handoff_admissions

narrative_decision_identities
revision_acceptance_decisions
change_set_review_decisions
conflict_resolution_lineages
conflict_resolution_decisions

revision_acceptance_heads
change_set_review_heads
conflict_resolution_heads
```

A different physical layout is acceptable only if it proves equivalent typed FKs,
uniqueness, check constraints, logical keys, cardinalities, identity isolation, and
rebuild behavior. A nullable polymorphic decision table without those proofs is rejected.

All authoritative references use restrictive deletion. Immutable evidence and decisions
are never updated in place. Head rows are the only mutable Narrative acceptance rows.

Minimum database constraints are:

- primary keys for every evidence, attempt, result, lineage, and admission identity, and
  database-global Narrative decision identity through the shared registry;
- unique `(attempt_id, generation)` attempts and a unique FK from one result to that
  exact pair;
- a successful extraction result and all change sets it declares are inserted in one
  transaction, with ordered association rows proving exact result membership; non-success
  results declare no change sets;
- a successful compilation result has exactly one one-to-one compiled-delta row inserted
  in the same transaction; `NO_CANON_MUTATION` and non-success results have none;
- every typed decision durably owns its exact original
  `NarrativeDecisionAuthorization`; fresh retry authentication is never stored as or
  compared with that original authority evidence;
- every handoff admission durably owns the exact M5A `CanonCommitApproval` payload and
  its recomputable fingerprint in the same immutable row/aggregate;
- composite scope/basis FKs where a bare opaque-ID FK could otherwise join tenants or
  incompatible revisions;
- `UNIQUE (decision_id, decision_family)` in the identity registry plus a composite FK
  from every typed decision row and a family `CHECK` on that row;
- composite self-FKs from expected latest/effective decisions to the same typed logical
  subject where applicable;
- one unique complete stable key per logical head family, with composite FKs from head
  pointers back to decisions for that same subject;
- unique `(revision_acceptance_decision_id, conflict_subject_fingerprint)` lineage
  subjects, plus immutable full-subject equality for lineage-ID retry;
- non-negative generations and null-pointer/zero-generation genesis checks;
- unique ordered association rows for competing reviews, selected change sets,
  resolutions, and admission head observations; and
- no cascading delete from authority or handoff evidence.

Repository methods update a head with its expected pointer/generation in the predicate
and must affect exactly one row. An unexpected zero or multi-row update is a deterministic
predecessor or integrity failure. The service state machine increments
`effective_generation` only in the same update that changes `effective_decision_id`.

### 7.2 First-head serialization

Every authority kernel transaction runs at `READ COMMITTED`. The two-phase retry check
below (an early lookup, then a second lookup after the head row is locked) is correct
only because `READ COMMITTED` takes a fresh snapshot per statement: the second lookup
observes a concurrent decision that committed in between. A stricter isolation level
(`REPEATABLE READ`, `SERIALIZABLE`) would keep the transaction's original snapshot across
both lookups, so the second lookup could miss that concurrent decision and the identity-
registry `INSERT` would instead fail on the raw unique constraint (or, under
`SERIALIZABLE`, abort the whole transaction with a `40001 serialization_failure` outside
the §13 error taxonomy) rather than resolving cleanly into exact retry or
`NarrativeDecisionIdentityConflictError`. `READ COMMITTED` is therefore a correctness
precondition of this section, not an incidental default, and no session, pool, or ORM
configuration may raise it for authority kernel transactions.

`SELECT FOR UPDATE` cannot serialize an absent row. Revision/change-set heads and commands
for an already-existing conflict lineage therefore use the Human-approved genesis
strategy:

1. begin one fresh short authority transaction;
2. look up `decision_id`; if it exists in the exact scope, require fresh
   `NarrativeDecisionRetryAuthentication`, reload and verify the original stored
   authorization, compare the full canonical business tuple, and return the immutable
   exact-retry receipt without creating or mutating a head;
3. for a new ID, `INSERT ... ON CONFLICT DO NOTHING` the typed head using its complete stable key,
   null pointers, and zero generations;
4. select that head by full key `FOR UPDATE`;
5. verify that the returned row exactly matches the requested scope/subject;
6. look up `decision_id` again under the serialized transaction and resolve a concurrent
   exact retry before stale predecessor rejection;
7. for a new decision, compare both expected pointers;
8. for a new ID, verify the one original `NarrativeDecisionAuthorization` plus all exact
   evidence, authority, scope, basis, and applicability inputs;
9. insert identity registry and typed decision rows;
10. update latest pointer and, when applicable, effective pointer;
11. flush once and commit once.

Concurrent genesis commands converge on one unique head row. One wins the locked
transition; the other becomes an exact retry or receives a deterministic predecessor
conflict. No advisory lock or pre-created global head inventory is used.

Conflict-resolution genesis uses the same exact-retry and OCC rules but orders the new
objects explicitly:

1. begin one fresh short authority transaction and resolve an existing `decision_id`
   exact retry only after fresh retry authentication and verification of the original
   stored authorization;
2. lock the required revision and competing change-set review heads in canonical order
   and verify they are current/effective;
3. derive the minimal canonical conflict subject and versioned fingerprint from those
   exact reviewed change sets;
4. insert the immutable lineage with its proposed opaque ID using the subject-unique
   constraint and `ON CONFLICT DO NOTHING`;
5. read the unique subject row; a different stored opaque ID produces
   `NarrativeConflictLineageConflict` with no writes from the losing transaction;
6. insert its zero-generation conflict head with `ON CONFLICT DO NOTHING`, then lock and
   validate that head;
7. resolve a concurrently landed exact decision retry before predecessor checks;
8. verify null genesis predecessors and the exact original authorization/decision tuple;
9. insert the identity and first typed decision and advance latest/effective pointers
   according to `REJECT` or `RESOLVE`; and
10. flush once and commit once.

Thus lineage, head, and first decision become visible together. A subject collision is
not permission to create a duplicate conflict thread.

### 7.3 Multi-head locking

Commands that validate or lock multiple heads use one canonical order:

```text
(head_family_rank, user_id, project_name, serialized_logical_key)
```

Family rank is revision, change-set, then conflict-resolution. IDs and keys use canonical
UTF-8 byte ordering. Every repository adapter must accept the already-sorted keys or
apply the same function. Reverse-order competing requests must not create a deadlock.

### 7.4 Atomicity and failure points

Decision append and head advancement share one transaction. A fault before commit leaves
neither visible. A commit whose response is lost is reconciled by exact decision ID and
full tuple, never by reading the latest head and inventing success.

Evidence recording is append-only and may commit independently of acceptance. Orphaned
unaccepted evidence is expected and harmless, but a successful extraction result may not
be orphaned from any declared change set. Provider calls, Human waits, compilation, and
M5A commit never occur while a Narrative authority transaction is open.

## 8. Workflow services and ports

### 8.1 NarrativeLifecycleEvidenceService

The evidence service is the only public append capability for non-authority lifecycle
evidence other than the separately governed handoff-admission receipt:

```text
record_draft_candidate(candidate)
record_revision(revision)
admit_extraction(command) -> ExtractionAttempt
record_successful_extraction(result, change_sets)
record_non_successful_extraction(result)
admit_compilation(command) -> CompilationAttempt
record_successful_compilation(result, canon_delta)
record_compilation_without_delta(result)
get_exact_*(scope, exact_id)
```

`record_successful_extraction()` verifies the exact attempt/generation, requires
`SUCCEEDED`, compares the complete ordered ID set, inserts the result and every declared
change set, flushes, and commits once. Exact retry compares the result and all change-set
tuples and performs no write. Any partial or mismatched retry fails with no write.
`record_non_successful_extraction()` rejects `SUCCEEDED` and any non-empty
`change_set_ids`. There is no public result-then-change-set append sequence.

`record_successful_compilation()` requires `SUCCEEDED`, recomputes the existing M5A
payload hash, inserts the result and exact compiled-delta payload atomically, and returns
an immutable deep copy. Exact retry compares both complete tuples.
`record_compilation_without_delta()` accepts exactly `NO_CANON_MUTATION`, `ABSTAINED`,
`CONFLICT`, or `FAILED` and rejects populated delta fields or any compiled-delta payload.
No public interface can record `SUCCEEDED` without its exact durable proposal or attach a
delta to an outcome-only result.

Attempt admission uses a narrow transaction-bound selection guard backed by the same
Narrative UoW: it locks the required heads in canonical order, verifies their effective
pointers, and inserts the immutable attempt before commit. This makes the attempt's
admission instant atomic with its currentness proof. The evidence service can lock/read
through that guard but receives no method that can create a decision or update a head.

### 8.2 NarrativeAcceptanceService

The acceptance service exposes only:

```text
decide_revision(...)
review_change_set(...)
resolve_change_set_conflict(...)
admit_canon_handoff(..., canon_commit_approval) -> AdmittedNarrativeHandoff
get_current_revision_selection(exact_scope)
get_current_change_set_selection(exact_revision_decision, exact_lineage)
get_current_conflict_resolution(exact_revision_decision, exact_resolution_lineage)
verify_exact_current_selection(exact_decision_refs)
```

Read results name exact decisions and generations. They are observations, not durable
authority tokens. Only a decision transaction can change a selection, and only
`admit_canon_handoff` creates the durable boundary-crossing receipt.

No generic `save_decision`, `set_head`, `approve`, `latest`, or raw repository method is
public.

### 8.3 Extractor boundary

An extractor receives one admitted attempt plus exact revision/context/Canon inputs and
returns typed proposal evidence or an explicit non-success result. It receives:

- no Narrative acceptance write port;
- no Canon or plan write port;
- no latest-state reader;
- no mutable head or repository; and
- no capability to author a Human receipt.

Provider-backed adapters own provider submission, polling, response normalization, and
provider audit outside the M5C lifecycle. Core evidence does not adopt a generic provider
state machine in M5C.

`OUTCOME_UNKNOWN` is terminal for its exact attempt generation. A late provider success
is rejected by the M5C evidence interface and cannot attach change sets to that
generation. If another extraction execution is needed, the service admits a new
generation that names the ambiguous predecessor; it never rewrites or supplements the
unknown result into success. A future requirement to ingest late success requires a new
typed evidence contract and state-machine amendment.

### 8.4 M5B accepted-narrative read adapter

M5C supplies the concrete exact reader behind M5B's existing
`AcceptedNarrativeReader`. An `accepted_narrative_ref` is a revision-acceptance decision
ID, not a revision ID, prose hash, or mutable head ID.

For a normal M5B context compilation, the adapter resolves the exact decision and
revision, verifies the decision is the current effective acceptance for its stable work
scope, and returns prose plus an authority descriptor binding the exact Canon, Plan,
SceneContract, and ContextPack bases. Missing, rejected, superseded, corrupt, or
cross-scope references return the existing indistinguishable not-found result, which
M5B raises as `NarrativeSourceMetadataError`. An exact current record with a descriptor
incompatible with the requested Canon/Plan/visibility basis reaches M5B's existing
visibility filter and is recorded as an omission. Neither path emits `RECENT_ACCEPTED`
content.

Historical audit uses the separate replay port from Section 10.2. It is not injectable
as M5B's live accepted-narrative reader.

## 9. Pure CanonDeltaCompiler

### 9.1 Interface

```text
CanonDeltaCompiler.compile(
  output_identity,
  revision,
  reviewed_change_sets,
  conflict_resolutions,
  exact_canon_base,
  compiler_policy,
) -> CanonDeltaCompilation

CanonDeltaCompilation =
  SUCCEEDED(CanonDelta)
  | NO_CANON_MUTATION(findings)
  | ABSTAINED(findings)
  | CONFLICT(findings)
  | FAILED(findings)
```

The compiler object has no async dependency, clock, random source, provider, database,
repository, UoW, writer, acceptance service, or Canon transaction service. Exact immutable
inputs are loaded before invocation. `output_identity` carries the attempt-bound
`canon_delta_id`, `created_at`, and `created_by`; the compiler never reads a clock or
generates an opaque ID during transformation.

### 9.2 Input validation order

The compiler validates in this stable order:

1. supported compiler, policy, change-set, and Canon schema versions;
2. exact work scope and revision identity equality;
3. exact Canon base and branch equality;
4. accepted decision/evidence pair equality from the admitted attempt;
5. lineage uniqueness and canonical ordering;
6. source-span and both semantic-effect-key-family coverage validity;
7. pairwise overlap analysis across Canon-mutation and Narrative-outcome keys;
8. complete applicable Human resolution coverage for every overlap;
9. deterministic mapping of `CanonMutationEffectKey` values only to existing M5A Canon
   operation contracts;
10. `NO_CANON_MUTATION` when the complete valid resolved selection is outcome-only;
11. recomputed M5A `CanonDelta.payload_hash` for a non-empty mapped operation set.

The compiler does not query whether decisions are current. Currentness belongs to
attempt admission and final handoff admission; the compiler consumes the exact immutable
snapshot named by its attempt.

### 9.3 Selection and conflict rules

The attempt must name every selected change set and its effective review decision. There
is no list-latest or auto-selection behavior.

Two selected change sets conflict when their normalized source spans overlap or either
typed semantic-effect-key family collides under the selected compiler policy. Non-overlap
is computed deterministically after canonical ordering. A conflict without one exact
applicable resolution returns `CONFLICT` and no delta.

A resolution may choose one input, combine typed non-conflicting effects, or provide a
typed replacement effect supported by the compiler policy. Unknown resolution kinds,
partial conflict coverage, references outside the selection, or two applicable
resolutions for the same conflict fail closed.

### 9.4 CanonDelta construction

The compiler emits only operation variants legal for the exact M5A Canon schema. Every
operation is derived from a selected `CanonMutationEffectKey` and an explicit compiler-
policy rule. `NarrativeOutcomeEffectKey` values, including `THREAD_PAYOFF`, participate
in coverage, conflict, resolution, and outcome-proof validation but emit zero Canon
operations.

If at least one Canon-mutation key exists, every such key must map to its required
operation set; unsupported, underspecified, or semantically ambiguous mutation effects
abstain, fail, or conflict and are never converted by best effort. If none exists after
complete validation and resolution, the compiler returns `NO_CANON_MUTATION`. It never
constructs an empty M5A `CanonDelta`.

The resulting existing M5A contract contains:

```text
target_branch_id = NarrativeWorkScope.canon_branch_id
base_canon_version_id = exact compilation base
source_change_set_refs = canonical selected change_set_ids
author_decision_refs = canonical revision/review/resolution decision IDs
validation_report_refs = exact compiler finding/report refs
created_by = admitted Human/workflow actor
```

`canon_delta_id` is opaque workflow identity. `payload_hash` is recomputed with the
existing M5A canonical hash function and covers the complete payload. A caller-supplied
hash mismatch fails.

### 9.5 Determinism

Given the same exact input bytes and version selectors, compilation must produce the same:

- terminal outcome;
- ordered findings;
- ordered operations and operation IDs;
- source and author decision refs; and
- Canon delta payload hash.

Opaque output IDs and output timestamps are supplied in the admitted attempt. Purely
content-addressed subordinate IDs may be derived only under an explicit versioned rule.
Wall-clock time, database order, locale, process hash seed, provider output, or latest
state cannot influence compilation.

## 10. Current authority and historical replay

### 10.1 New downstream work

Extraction admission requires the named revision decision to be the exact current
effective revision selection.

Compilation admission requires:

- the exact current revision acceptance;
- every named review decision to be current and effective for its lineage;
- every selected change set to match that review decision;
- every required conflict-resolution decision to be current, effective, and applicable;
- no unresolved overlap; and
- exact mutual scope and basis equality.

The attempt records effective decision IDs and effective generations observed during the
admission transaction. A later supersession does not delete the attempt or result, but it
blocks a new handoff unless currentness was already frozen by Section 11.

### 10.2 Historical replay

An explicit audit/replay capability may resolve immutable historical evidence and
decisions by exact IDs and exact bases. It may reproduce an old extraction or compilation
result for integrity comparison.

Historical replay cannot:

- call a current-selection API with a historical override;
- update a decision or head;
- emit a current-authority token;
- admit new extraction or compilation work;
- create a `NarrativeHandoffAdmission`; or
- invoke the authenticated M5A handoff.

Normal workflow ports have no `latest=true`, `allow_historical`, or fallback flag.

## 11. Atomic M5A handoff admission

### 11.1 Contract

```text
NarrativeHandoffAdmission
  admission_id
  work_scope
  compilation_attempt_id + generation
  compilation_result_id
  canon_delta_id
  canon_delta_payload_hash
  canon_commit_approval_ref
  canon_commit_approval: exact immutable CanonCommitApproval payload
  canon_commit_approval_fingerprint
  canon_commit_approval_fingerprint_algorithm: sha256
  canon_commit_approval_fingerprint_version: r2-m5c-canon-approval-binding-v1
  revision_acceptance_decision_id
  review_decision_ids[]
  conflict_resolution_decision_ids[]
  observed_heads[]:
    head_family
    logical_key
    effective_decision_id
    effective_generation
    decision_generation
  base_canon_version_id
  actor_id
  admitted_at
  canonical_identity_hash
```

The admission ID is opaque and idempotent. Same ID/full tuple returns the original
receipt, including after a later Narrative supersession. Same ID/different tuple is an
identity conflict.

The admission owns a lossless immutable inline copy of the exact existing M5A
`CanonCommitApproval`. JSONB is acceptable only when strict M5A contract round-trip
reproduces the same canonical approval bytes and fingerprint. An ephemeral cache,
caller resubmission, approval reconstruction, or an external reference without a durable
exact reader is not the owning recovery copy.

`canon_commit_approval_fingerprint` uses the declared versioned canonical hash, with aware
timestamps normalized to UTC, over every existing M5A approval field: `approval_ref`,
`canon_delta_id`, `payload_hash`, payload-hash
algorithm/version, content-schema version, `project_name`, `user_id`, `approved_by`,
`approved_at`, and `status`. The approval remains M5A authority. Its M5C copy can prove
and recover the admitted tuple but cannot approve, replace, validate, or commit Canon.

### 11.2 Admission transaction

`NarrativeAcceptanceService.admit_canon_handoff()`:

1. validates and deep-copies the exact existing M5A `CanonCommitApproval` input;
2. begins one fresh short Narrative transaction;
3. resolves exact admission retry before testing currentness;
4. locks the revision, selected change-set, and required conflict heads in canonical
   order;
5. loads the exact persisted `CompiledCanonDeltaEvidence` and verifies it against the
   successful compilation result, attempt, scope, exact bases, and all effective decisions;
6. recomputes the delta payload hash and the complete approval fingerprint and requires
   the approval to bind that exact delta, scope, hash/schema versions, actor, status, and
   timestamp;
7. verifies each locked projection against its typed authoritative chain, proves every
   recorded effective pointer still equals the named decision, and proves every
   resolution remains applicable;
8. appends the immutable admission receipt and exact approval payload atomically; and
9. commits once.

No Canon row is locked or written in this transaction.

The application result `AdmittedNarrativeHandoff` contains the immutable admission
receipt plus exact deep copies of the persisted `CanonDelta` and persisted
`CanonCommitApproval`. It is a convenience result, not another durable authority
contract. The facade never substitutes a caller-held, recompiled, reconstructed, or
freshly issued tuple after admission.

### 11.3 Frozen currentness semantics

Currentness is required at the atomic admission instant. A Narrative decision that
commits before receipt insertion is observed under the locked heads and blocks admission.
A Narrative supersession that commits after the admission transaction does not
retroactively invalidate the receipt or an already-admitted M5A action.

This is intentionally not currentness-through-Canon-commit. The design does not hold
Narrative locks across Human approval or M5A work and adds no cross-authority fence,
lease, or distributed transaction.

An admission is reusable only for the exact bound `CanonDelta` and the exact existing
M5A approval/retry lineage identified by the persisted approval payload, its
`canon_commit_approval_ref`, and complete approval fingerprint. It cannot authorize
another delta, recompilation result, Canon base, M5A approval tuple, or fresh approval
action. A response-lost M5A call may retry only with the exact persisted
`AdmittedNarrativeHandoff` delta and approval tuple.

### 11.4 Existing M5A handoff

The authenticated facade requires:

- an authenticated principal with an exact project-scoped Human Showrunner
  capability proven through `NarrativeShowrunnerAuthorityPort`;
- the exact caller-supplied `NarrativeWorkScope`, used for a scoped admission
  lookup rather than a global ID-only lookup;
- one exact `NarrativeHandoffAdmission`;
- the exact `CanonDelta` bound by that receipt; and
- the exact persisted `CanonCommitApproval` whose complete payload, reference, and
  fingerprint are bound by that receipt.

It then calls existing `CanonTransactionService.commit()`. M5A independently verifies
the approval, recomputes the delta hash, locks the Canon branch, resolves exact Canon
retry, checks the base, validates the candidate Canon view, appends the accepted delta
and version, advances the branch head, and updates its projection atomically.

The facade constructs the M5A approval before Narrative admission and passes it to the
admission transaction. On the initial request or after process restart, it reloads the
exact durable delta and approval from that committed admission before calling or retrying
M5A. Narrative admission proves only currentness, tuple binding, and restart-safe custody;
M5A remains the sole authority that judges and persists Canon approval.

If Canon advances before commit, M5A returns its existing base conflict. The Narrative
admission remains immutable evidence but cannot change its delta/base; a new delta and
admission are required. Narrative supersession after admission is not substituted for
M5A base OCC.

## 12. Integrity checking and projection rebuild

`NarrativeLifecycleIntegrityChecker` verifies without mutating authority:

- each evidence ID maps to one full immutable tuple;
- prose and semantic hashes recompute;
- attempt/result generation and unique-result constraints hold;
- every change set belongs to its exact successful extraction result;
- identity registry rows match exactly one typed decision family;
- typed decision predecessor chains are acyclic and scope-consistent;
- latest pointers and decision generations rebuild from all decisions;
- effective pointers and generations rebuild under action semantics;
- change-set and conflict head keys match their revision/lineage decisions;
- every historical conflict-resolution decision validates against the immutable evidence,
  decision predecessors, and effective reviewed inputs that existed at its append point;
- only current resolution applicability additionally requires the resolution to be the
  effective conflict head and every named review decision to be currently effective;
- every successful compilation result owns one exact durable compiled-delta payload and
  every non-success result owns none;
- compilation results recompute from their exact attempts and compiler version, with the
  recomputed output compared to—not substituted for—the persisted delta;
- `NO_CANON_MUTATION` results prove a complete valid outcome-only effect set and own no
  compiled-delta row;
- each original decision authorization still binds the stored actor, scope, family,
  action, decision ID, subject, and command fingerprint; retry-authentication timestamps
  are not historical decision evidence;
- handoff admissions bind successful results, exact persisted delta hashes, and the exact
  lossless M5A approval payload/reference/fingerprint; and
- no head or receipt points to missing or cross-scope evidence.

Rebuild computes candidate head rows into a separate projection and compares before
replacement. A mismatch is an integrity failure, not permission to trust the mutable
head. Repair requires an explicit offline procedure and evidence; M5C implementation
does not authorize running it in production.

## 13. Stable failure behavior

| Error | Meaning |
|---|---|
| `NarrativePlanSchemaVersionError` | unknown, below-minimum, or illegal SceneContract/NarrativePlan v1/v2 transition |
| `NarrativeRelationshipIntegrityError` | relationship refs/profile are malformed or exact active state is ambiguous |
| `NarrativeThreadLifecycleError` | plan-wide presentation-order thread invariants fail |
| `NarrativeThreadPayoffApplicabilityError` | payoff proof is absent, stale, rejected, mismatched, or incompletely resolved |
| `NarrativeEvidenceNotFoundError` | exact evidence absent or outside scope |
| `NarrativeEvidenceIdentityConflictError` | evidence ID reused with a different full tuple |
| `NarrativeEvidenceIntegrityError` | hash, lineage, attempt/result, or reference corruption |
| `NarrativeDecisionNotFoundError` | exact decision absent or outside scope |
| `NarrativeDecisionAuthorizationError` | authenticated actor lacks the explicit project-scoped Human Showrunner grant, original command authorization, or exact-retry authentication |
| `NarrativeDecisionIdentityConflictError` | caller-supplied global decision/admission ID collides with a different tuple; public detail reveals no owner or scope |
| `NarrativeDecisionPredecessorConflict` | expected latest or effective predecessor is stale |
| `NarrativeDecisionApplicabilityError` | selected evidence/decision is rejected, superseded, mismatched, or mutually invalid |
| `NarrativeAuthorityIntegrityError` | authoritative decision chain and mutable projection disagree or contain an invalid link |
| `NarrativeConflictCoverageError` | overlap is unresolved, partially resolved, multiply resolved, or outside its lineage subject |
| `NarrativeConflictLineageConflict` | the canonical conflict subject already belongs to another opaque lineage |
| `NarrativeAttemptGenerationConflict` | stale/duplicate attempt generation or mismatched completion |
| `CanonDeltaCompilationError` | unsupported/invalid exact compiler input; no partial delta |
| `NarrativeHandoffConflict` | compilation inputs are no longer current at admission |
| existing M5A errors | Canon approval, schema, base, validation, identity, or integrity failure |

Validation and identity errors write nothing. Decision failure leaves both history and
head unchanged. Compilation failure returns no partial `CanonDelta`. Handoff failure
creates no admission receipt and no Canon write.

## 14. Security and scope

- Every read and write carries `user_id` and `project_name` through repository predicates.
- For exact reads and reference resolution, an unknown opaque ID and an ID owned by
  another scope both return the same public not-found result.
- For creation with a caller-supplied database-global decision or admission ID, a
  collision in any scope returns the same generic identity-conflict result. That result
  exposes no owning scope, family, subject, actor, or content. Global uniqueness is not
  weakened to pretend that the ID was absent.
- Original Human decision authorizations are immutable authenticated evidence;
  model/provider text cannot synthesize them, and fresh retry authentication cannot
  replace them.
- Only the explicit `HUMAN_SHOWRUNNER` capability may authorize any M5C v1 decision
  family. Generic administrator roles, authorship, and possession of evidence IDs confer
  no authority.
- That capability resolves only from a project-scoped grant issued by the
  Governance/Showrunner authority. Missing or unavailable authority adapters deny by
  default; test fakes cannot be wired into production.
- Prose and provider payloads are not copied into decision heads, logs, or error messages.
- Conflict diagnostics reveal only IDs and authorized coverage metadata unless the caller
  already has access to the underlying revision.
- Orchestration receives command ports, not repositories, sessions, or mutable ORM rows.
- Values crossing an `await` or transaction boundary are deep immutable contract copies;
  approval-bound bytes are revalidated before persistence.
- The compiler and integrity checker receive no secret credentials or provider clients.

## 15. Proposed module boundaries

```text
r2/contracts/narrative_plan.py            # v1/v2 SceneContract and NarrativePlan unions
r2/narrative_plan/hashing.py              # selector-dispatched byte-stable v1/v2 hashes
r2/narrative_plan/schema_upgrade.py        # legal SceneContract/plan schema-transition ratchets
r2/narrative_plan/validation.py            # hierarchy + pure cross-scene thread lifecycle
r2/narrative/relationship_facts.py         # sole versioned relationship Fact-key mapping
r2/narrative/validation.py                 # exact-point relationship and R9/R10 validation
r2/narrative_context/compiler.py           # Scene-side omniscient AUTHOR_DRAFT gate

r2/contracts/narrative_lifecycle.py       # immutable evidence, decisions, heads, receipts
r2/narrative_lifecycle/hashing.py         # versioned prose/evidence/decision hash domains
r2/narrative_lifecycle/errors.py          # stable public failure taxonomy
r2/narrative_lifecycle/coverage.py        # pure span/effect normalization and overlap rules
r2/narrative_lifecycle/changeset_parser.py# Huohuo-derived pure parser; proposal output only
r2/narrative_lifecycle/continuity_rules.py# Novel Studio-derived pure deterministic findings
r2/narrative_lifecycle/ports.py           # exact evidence, authority, UoW, and M5A facade ports
r2/narrative_lifecycle/evidence.py        # one deep immutable evidence append service
r2/narrative_lifecycle/acceptance.py      # three commands + handoff admission; sole head writer
r2/narrative_lifecycle/compiler.py        # pure CanonDeltaCompiler
r2/narrative_lifecycle/integrity.py       # decision/head/result/receipt verification and rebuild

lib/db/models/narrative_lifecycle.py      # typed immutable rows and logical heads
lib/db/repositories/narrative_lifecycle.py# scoped transaction-bound adapter
lib/db/narrative_lifecycle_uow.py         # Narrative transaction lifecycle
server/services/narrative_canon_handoff.py# authenticated admission -> existing M5A facade

tests/fixtures/r2/m5c_narrative_corpus.py          # combined M5 v2 successor fixture
tests/donor_parity/huohuo_change_record_runner.mjs  # test-only exact-source Node runner
tests/donor_parity/test_huohuo_change_record.py     # same-fixture TS/Python comparison
tests/donor_parity/fixtures/huohuo_change_record/   # canonical shared JSON/JSONL corpus
tests/donor_parity/novel_hard_rules_runner.mjs      # test-only exact-source Node runner
tests/donor_parity/test_novel_hard_rules.py         # same-fixture TS/Python comparison
tests/donor_parity/fixtures/novel_hard_rules/       # canonical shared JSON/JSONL corpus
```

Public exports include frozen contracts, pure coverage/compiler functions, evidence
commands, `NarrativeAcceptanceService`, and integrity reports. ORM models, raw repository
writes, head mutation, identity-registry insertion, transaction sessions, and repair
methods remain internal.

Architecture fitness rules enforce:

- contracts and pure modules do not import `lib.db`, `server`, providers, Agent runtime,
  or production runtime;
- relationship Fact predicates are produced only by the shared versioned mapping helper;
- cross-scene thread lifecycle is implemented only in the plan-wide pure validator, not
  duplicated in `validate_scene()` or the context compiler;
- F9 modules import no donor code and are absent from donor-parity runtime paths;
- compiler imports no authority write port, repository, UoW, clock, random, or provider;
- evidence service cannot import or call head mutation methods;
- only `NarrativeAcceptanceService` can append Narrative decisions or mutate Narrative
  heads;
- extractor/provider/orchestration modules cannot import acceptance repositories;
- M5C repositories cannot import or write M5A Canon ORM models;
- only the authenticated handoff facade connects a valid M5C admission to existing M5A
  approval/commit; and
- M5C adds no Production Authority, Canvas, worker activation, or provider routing.

## 16. Acceptance strategy

### 16.1 Contract and hashing tests

- strict extra-field rejection and aware UTC timestamps;
- v1 SceneContract and NarrativePlan golden bytes/hashes remain exact;
- a v1-only scene remains under the v1 selector, while Relationship, Thread, or enabled
  scene-side omniscient semantics require v2;
- legal genesis/v1-to-v2/v2-to-v2 transitions pass and v2-to-v1 fails;
- a v2 plan may retain unchanged v1 scenes byte-for-byte and must itself remain v2 after
  the last v2-only scene semantic is removed;
- each v2 executable-field mutation changes the scene semantic hash, while commit-only
  metadata does not;
- relationship-key mapping is deterministic, direction-sensitive, target-sensitive, and
  shared by validation, effect-key normalization, and compilation;
- `PRESENT`/`ABSENT` forbid `expected_state`; `EQUALS`/`NOT_EQUALS` require it;
- stable prose normalization and hash under Unicode/line-ending fixtures;
- equal prose with different scope/bases produces distinct semantic identity;
- canonical list ordering and duplicate rejection;
- duplicate constraint IDs and normalized semantic duplicates are rejected on both v1
  and v2 scenes;
- change-set lineage and typed effect-key validation;
- Canon delta uses the existing M5A payload hash implementation;
- opaque evidence/decision/admission ID reuse with one changed tuple field fails.

### 16.2 F9 compatibility and outcome tests

- relationship `PRESENT`, `ABSENT`, `EQUALS`, and `NOT_EQUALS` pass/fail matrices cover
  exact effective instants, direction, target, key, state, absence, expiry, and malformed
  or multiply active Fact state;
- relationship source/target missing, non-character, equal, reversed, or cross-basis refs
  fail closed;
- one plan-wide pass detects orphan resolution, orphan payoff binding, double resolution,
  post-resolution reappearance, missing active membership, and presentation-order versus
  story-time confusion;
- a thread may be omitted from an intermediate scene without being implicitly resolved;
- an exit resolution requires an open thread and the exact payoff ref; an entry
  `RESOLVED` constraint requires a prior resolution;
- the per-scene validator cannot independently claim cross-scene thread validity;
- a structural payoff declaration without exact effective revision/change-set decisions
  fails `validate_thread_payoff_outcome()`;
- superseded, rejected, wrong-thread, wrong-payoff, uncovered-span, or incomplete conflict
  proof fails closed, while historical replay remains non-authoritative;
- `AUTHOR_DRAFT` without POV fails for v1, v2 false, or a scene with a fixed POV and passes
  the SceneContract half only for v2 `omniscient_authoring_allowed_by_scene=true` with
  `scene.pov is None`;
- no policy prose can enable omniscient authoring;
- present-state proposition/entity refs resolve exactly at plan commit; a future absent
  exact Event remains an obligation but must resolve at outcome; and
- the F9 test/import manifest proves no donor source or Node harness is used by the F9
  implementation.

### 16.3 Evidence tests

- draft/revision immutable lineage and cross-scope rejection;
- attempt persisted before execution and result uniquely bound to generation;
- crash after attempt leaves recoverable no-result evidence;
- exact result retry returns original; mismatched retry writes nothing;
- a late terminal result for a superseded generation that has no prior result is retained
  but fenced from workflow advancement;
- a late provider success after `OUTCOME_UNKNOWN` is rejected, attaches no change set,
  and continuation requires a newly admitted generation;
- `OUTCOME_UNKNOWN` exists for external extraction only and never creates a change set;
- fault injection before the successful extraction bundle commit leaves neither result
  nor change set visible;
- a `SUCCEEDED` result cannot commit with a missing, extra, reordered, foreign-scope, or
  wrong-generation change set; and
- non-success results reject non-empty `change_set_ids`.

### 16.4 Decision authority tests

- all three decision families require an exact Human actor/receipt, exact
  `NarrativeDecisionAuthorization`, and exact bases;
- generic administrator, delegated reviewer, Human-author-only, Agent, extractor,
  compiler, provider, and orchestrator identities are denied for all decision commands;
- one authorization cannot be replayed for another family, action, scope, decision ID,
  or command fingerprint;
- a Human Showrunner who authored an input must still perform a separate explicit
  authenticated decision action;
- global decision identity cannot collide across typed tables;
- exact retry is returned after later head movement without making the old decision
  effective again;
- same ID/different family or tuple is an identity conflict with zero writes;
- a cross-scope exact read is indistinguishable from unknown, while a cross-scope global
  create collision returns only the generic identity-conflict shape;
- `REJECT` advances latest generation and preserves effective pointer/generation;
- `ACCEPT` with an existing effective selection fails; `SUPERSEDE` replaces only its
  exact expected effective predecessor;
- one lineage supersession does not alter another non-overlapping lineage;
- a new revision acceptance does not inherit prior revision change-set heads;
- conflict resolution requires all named reviews effective and exact overlap coverage;
- conflict genesis creates lineage, head, and first decision in one transaction;
- the same revision plus canonical conflict subject cannot create two lineages, including
  under concurrent genesis with different opaque IDs;
- widened, partial, reordered, or caller-invented conflict subjects fail before writes;
- extractor, compiler, provider, and orchestration cannot invoke decision writes.

### 16.5 Transaction and concurrency tests

- two concurrent genesis decisions on each head family yield one accepted transition and
  one deterministic retry/conflict;
- fault after identity insert, decision insert, or head update but before commit rolls
  back all authority writes;
- response loss after commit reconciles through exact ID/full tuple;
- reverse-order multi-lineage requests follow canonical locks and do not deadlock;
- stale latest predecessor fails even when effective pointer is unchanged;
- stale effective predecessor fails even when latest pointer matches;
- corrupted or missing head target is an integrity error, not treated as genesis;
- rebuild reproduces latest/effective pointers and both generations exactly;
- superseding a reviewed input makes an old resolution inapplicable to new work but does
  not make its historically valid decision evidence corrupt.

### 16.6 Compiler tests

- input permutation produces identical output and payload hash;
- process hash seed, locale, and wall-clock changes do not affect output;
- exact accepted selection compiles without any latest read;
- unsupported effect or policy version abstains/fails deterministically;
- overlapping spans and each semantic-effect-key family conflict without resolution;
- partial, stale, foreign, duplicate, or unknown resolution fails closed;
- non-overlapping accepted lineages coexist and compile in canonical order;
- compiler crash leaves attempt without `OUTCOME_UNKNOWN`;
- repeated exact computation records one identical result;
- fault before the successful compilation bundle commit leaves neither result nor
  compiled-delta payload visible;
- process restart reloads the exact persisted delta without relying on recomputation;
- a successful result without exactly one matching compiled-delta row is an integrity
  failure; and
- `NarrativeChangeSet` never serializes as or bypasses `CanonDelta` construction.

### 16.7 Handoff tests

- supersession before admission is observed under lock and blocks receipt creation;
- supersession concurrent with validation cannot land invisibly between a naked read and
  receipt insertion;
- supersession after committed admission does not retroactively invalidate the receipt;
- exact admission retry after supersession returns the original immutable receipt;
- same admission ID with another delta/decision tuple fails;
- same admission ID or receipt with another M5A approval ref or any changed approval
  field fails;
- changing the approval-binding hash algorithm/version fails closed;
- an admission cannot authorize another delta, recompilation result, Canon base, or fresh
  approval tuple;
- stale or failed compilation result cannot be admitted;
- Canon delta hash mismatch blocks admission;
- Canon head movement after admission is rejected by existing M5A base OCC;
- Narrative admission cannot replace or fabricate `CanonCommitApproval`;
- M5A exact retry remains governed by its existing delta/approval identity.

### 16.8 Required adversarial mutations

| Mutation | Required result |
|---|---|
| Serialize empty/default v2 fields into a v1 scene or recompute a v1 golden hash | byte/hash compatibility gate fails |
| Keep selector v1 after adding Relationship, Thread, or enabled omniscient semantics | schema-transition validation fails |
| Downgrade a v2 scene/plan after removing its last v2-only semantic | schema-transition validation fails |
| Reverse a relationship direction, target, key, state, or effective interval | `SCENE_ENTRY_RELATIONSHIP_UNMET` or `SCENE_EXIT_RELATIONSHIP_UNMET` |
| Construct a relationship Fact predicate outside the shared versioned helper | architecture/mapping-vector test fails |
| Resolve a thread before it opens, resolve it twice, or reintroduce it later | `SCENE_THREAD_LIFECYCLE_*` |
| Treat story-time order as thread lifecycle order | presentation-order mutation fails deterministically |
| Treat `promise_payoff_refs` or prose as payoff proof without effective decisions | `SCENE_EXIT_THREAD_UNMET` |
| Omit POV in `AUTHOR_DRAFT` without the v2 SceneContract permission | context compilation fails before author-only reads |
| Reuse a constraint ID or normalized semantic constraint under another ID | R10 validation fails |
| Treat an unresolved present-state ref as a normal unmet constraint | R9 exact-reference validation fails |
| Put `accepted=true` on revision/change set and bypass decision lookup | architecture/contract test fails |
| Let extractor invoke `review_change_set` | import/port fitness fails |
| Compare OCC before exact decision retry | response-loss retry test fails |
| Reuse decision ID with changed Human receipt or exact basis | identity conflict; zero writes |
| Use one generic head key for revision and change-set | uniqueness/cardinality test fails |
| Advance effective pointer on `REJECT` | decision state-machine test fails |
| Lock an absent row without unique genesis insertion | concurrent-genesis test exposes double acceptance |
| Compile a superseded decision by ID | compilation admission fails |
| Resolve overlap from model prose without Human decision | conflict remains unresolved |
| Create two lineages for the same revision/subject | subject uniqueness admits one and rejects the other with zero losing writes |
| Treat compiler crash as `OUTCOME_UNKNOWN` | result-vocabulary test fails |
| Commit `SUCCEEDED` extraction before its declared change sets | atomic bundle fault test leaves neither visible |
| Persist only a successful compilation ID/hash | exact-payload cardinality/integrity test fails |
| Read currentness, release it, then write handoff receipt | supersession-race test fails |
| Require Narrative currentness through M5A commit implicitly | boundary/transaction fitness fails |
| Call Canon repository directly from M5C | import/architecture test fails |
| Remove `source_change_set_refs` or `author_decision_refs` from delta hash domain | hash mutation test fails |
| Treat an admission receipt as Canon approval | M5A approval validation fails |
| Reuse an admission with another M5A approval tuple | admission fingerprint check fails before Canon commit |

### 16.9 Acceptance corpus and hard exit

The existing combined M5 narrative corpus is extended with at least:

- the accepted M5B v1 corpus replayed byte-for-byte under its original selectors;
- one v2 NarrativePlan containing both unchanged v1 scenes and upgraded v2 scenes;
- one directional relationship Fact and entry/exit relationship constraints over exact
  effective instants;
- one thread opened in presentation order, omitted from an intermediate unrelated scene,
  carried across a story-time jump, and resolved once by an exact payoff ref;
- one exact accepted revision/change-set proof for that payoff and one structurally valid
  but unaccepted payoff that fails outcome validation;
- one no-POV `AUTHOR_DRAFT` scene that passes only the SceneContract half of the gate
  and remains blocked overall pending typed CreativePolicy authority, and one otherwise
  identical scene denied by that SceneContract half;
- R9 exact-reference and R10 normalized-duplicate regression cases;
- one accepted revision producing multiple non-overlapping change-set lineages;
- one rejected alternative that leaves an existing effective selection intact;
- one overlap resolved explicitly by a Human resolution lineage;
- one unresolved ambiguity producing no delta;
- one historical replay of a superseded revision and decision;
- one extraction `OUTCOME_UNKNOWN` case proving late success rejection and continuation
  only through a new generation;
- one compilation crash/recompute case;
- one supersession-before-admission race and one supersession-after-admission case; and
- one Canon-base race rejected by M5A.

M5C is acceptable only when fresh evidence at the exact clean verified HEAD shows:

```text
v1 Scene/Plan hash regressions           0
relationship constraint violations       0
thread lifecycle violations              0
unproven thread payoff acceptance        0
unauthorized omniscient authoring         0
unauthorized Narrative decisions       0
stale decision consumption             0
unresolved overlap compilation         0
compiler nondeterminism                0
Narrative-to-Canon authority bypass    0
failed transaction corruption          0
cross-scope evidence leakage           0
donor parity regressions                0
unverified material donor behavior      0
required skips                         0
```

Evidence includes exact base/head lineage, migration head, v1/v2 schema/hash selectors
and golden vectors, mixed-version plan fixtures, scope allowlist, graph generation and
coverage, focused and affected M5B/M5C regression commands, PostgreSQL identity,
concurrency/fault evidence, per-mutation outcomes, and a clean verified-head to
evidence-only handoff.

M5C donor acceptance additionally requires a `R2-DEC-031` evidence bundle at that exact
HEAD:

- baseline manifest entries reproduce the exact repository revisions, paths, and source
  hashes named in Section 2.4, plus an inventory of every selected and explicitly excluded
  donor behavior;
- the Huohuo port has approximately 25–35 branch/error cases and at least 10 prose
  fixtures covering every selected pure parser/normalizer branch, including malformed
  headers, orphan blocks, empty input, and prose shaped like a false structured record;
- the Novel Studio port has approximately 8–10 cases covering rule hit/miss behavior and
  empty, hard-only, soft-only, combined, severity, and stable rule-ID merge ordering; its
  test-only Node harness runs the exact pinned TypeScript source on those same fixtures
  and compares normalized output/error records with the Python port;
- a test-only Node harness compiles/runs the unmodified exact pinned Huohuo module in its
  source-tree context after verifying revision and SHA-256. It exercises the seven selected
  pure exports—header canonicalization, structured/trailing split, structured detection,
  orphan peeling, artifact normalization, prose/change-record split, and length-adjust
  echo removal—on every applicable corpus case;
- the Node baseline and Python port consume the same canonical JSON/JSONL fixture records
  and emit normalized per-case output/error records. Verification compares exact
  structured/string output, error versus success behavior, deterministic repeat output,
  and every other applicable `R2-DEC-031` dimension. Any intentional improvement is
  recorded and backed by an explicit regression fixture; and
- parity alone is insufficient: the ports also pass M5C proposal-only, determinism,
  failure-safety, provider-neutrality, and no-authority-import fitness tests.

The case counts are minimum planning estimates, not a substitute for branch-complete
coverage. A Python-only corpus pass is insufficient for either executable TypeScript
source. Missing Node baseline execution, uncovered material behavior, unexplained
mismatched output, or evidence not bound to the verified HEAD blocks M5C acceptance.

## 17. Review gates and execution handoff

1. Human review must approve this complete design before an implementation plan is
   written.
2. M5B must have a clean accepted implementation/evidence handoff. A documentation
   branch state or self-review is not a substitute for that prerequisite.
3. After design and plan approval, their exact hashes and the accepted integration base
   are recorded in a document-approval manifest.
4. The implementation branch materializes only approved documents and manifest over the
   exact accepted base before implementation begins.
5. M5C-1 through M5C-4 each freeze a clean verified implementation HEAD, run relevant
   gates there, receive independent Codex review, and add only evidence/handoff material
   before the next checkpoint.
6. M5C-1 reruns the complete affected M5B contract, hashing, schema-transition,
   NarrativePlan, scene/outcome validation, and NarrativeContextCompiler suites. M5C-4
   reruns the combined M5 v1/v2 corpus through real public interfaces. Historical M5B
   acceptance evidence is referenced, never edited into proof for the new HEAD.
7. Final evidence is regenerated from the exact clean final implementation HEAD. Required
   skips are zero. `R2-DEC-031` material behavior/parity gaps have no waiver within this
   design; any unrelated waiver requires separate narrow Human approval.
8. No design, implementation, test, or review result authorizes an operating migration,
   production discovery, production repair, worker activation, provider spending, push,
   publish, or deployment without separate explicit Human approval.

## 18. Risks and controls

| Risk | Control |
|---|---|
| Evidence becomes authority through a boolean or convenience query | No accepted boolean; exact typed decisions and authoritative chains only |
| One generic head loses revision/change-set multiplicity | Distinct logical keys, typed constraints, and rebuild tests |
| Rejection accidentally removes accepted work | Separate latest/effective pointers; `REJECT` preserves effective state |
| Two first decisions both observe no head | Unique genesis insertion followed by lock/reread |
| Exact retry is rejected after supersession | Retry lookup/full-tuple equality precedes predecessor checks |
| Stale accepted inputs return after supersession | Admission at extraction, compilation, and M5A boundary checks current effective refs |
| Handoff revalidation races with supersession | Atomic receipt under locked Narrative heads |
| Locks span Human/provider/M5A waits | Short independent transactions; admission-time currentness |
| Compiler invents meaning for overlap | Exact applicable Human resolution or fail closed |
| Compiler becomes an orchestration/service god object | Pure transformation with exact preloaded inputs and one output algebra |
| Provider ambiguity contaminates authority | `OUTCOME_UNKNOWN` is terminal; late success stays in adapter audit and new workflow work requires a new generation |
| Narrative service becomes another Canon writer | Existing authenticated M5A approval/commit is the only Canon path |
| Historical replay creates live capability | Dedicated exact audit port cannot admit downstream work |
| Head corruption silently authorizes work | Append-only chain remains authority; integrity checker/rebuild fails closed |
| V2 silently changes accepted v1 bytes | Separate selector-dispatched serializers, committed v1 golden vectors, and no in-place migration |
| A scene/plan downgrades after v2 semantics disappear | Predecessor-aware v1/v2 transition ratchet rejects v2-to-v1 |
| Relationship callers invent incompatible Fact predicates | One shared versioned content-addressed relationship-key mapping and architecture fitness test |
| Per-scene validation mistakes local tags for a valid thread history | One pure plan-wide presentation-order lifecycle pass with adversarial cross-scene mutations |
| A declared payoff is mistaken for accepted fulfillment | Exact effective revision/change-set proof and `SCENE_EXIT_THREAD_UNMET` on tag/prose-only input |
| Scene permission is mistaken for complete omniscient policy authorization | Scene field is explicitly one necessary conjunct; typed CreativePolicy conjunct remains deferred and prose cannot grant it |
| Donor port silently loses source behavior | `R2-DEC-031` exact-source differential corpus and exact-HEAD evidence block acceptance |

## 19. Out of scope

- M5A Canon schema, approval, repository, transaction, or projection redesign;
- M5B Canon/plan/context authority redesign beyond the narrow versioned F9 compatibility,
  Scene-side omniscient, and R9/R10 closures in Section 4.3;
- typed CreativePolicy authority and the policy-side omniscient-authoring permission;
- a new RelationshipState or PlotThreadTruth Canon authority family; F9 uses existing
  Canon Facts plus authorial plan/Narrative evidence only;
- a second relationship/thread extractor or acceptance path; the general M5C
  NarrativeChangeSet flow remains the only proposal path;
- automatic acceptance, automatic conflict resolution, or model-authored Human receipts;
- clearing an effective selection without replacement;
- generic event-sourcing/workflow-framework adoption, KurrentDB, or Temporal dependency;
- provider routing, retry policy, worker activation, or live provider integration beyond an
  adapter-owned extraction seam;
- ingestion of a late provider success after an extraction generation recorded
  `OUTCOME_UNKNOWN`;
- adaptation branches and Golden B production behavior (M6);
- Production Authority, `SceneSpec`, `ShotSpec`, media generation, Canvas, or UI;
- operating migrations, production data repair, deployment, push, or publish; and
- an implementation plan before explicit Human approval of this design.
