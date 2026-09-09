# R2-M5B Epistemic State, Narrative Plan, and Context Compilation Design

**Date:** 2026-09-08

**Status:** proposed for Human review

**Prerequisite:** accepted M5A Canon Authority handoff
**Research:** `docs/research/2026-09-08-r2-m5b-reuse-and-boundary-research.md`

## 1. Goal

M5B adds the smallest complete narrative slice above M5A:

- first-class, temporally valid `KnowledgeState` inside Canon;
- deterministic temporal and epistemic validation;
- a separately versioned `NarrativePlan` aggregate containing `SceneContract` authorial intent;
- an R2-owned `NarrativeContextCompiler` that produces version-pinned, visibility-safe context;
- executable evidence that secrets, false beliefs, future plan intent, rejected candidates, and failed transactions do not contaminate an authority they do not own.

M5B does not redesign M5A Canon persistence. It evolves Canon content through the selectors and append-only transaction seam M5A already provides.

## 2. Authority and prior decisions

This design instantiates frozen decisions rather than creating a new authority model:

| State | Authority | Sole commit interface | M5B behavior |
|---|---|---|---|
| Entity, Fact, Event, KnowledgeState, TemporalRelation | Narrative Authority | `CanonTransactionService` | Extend the M5A Canon schema and operation vocabulary. |
| NarrativePlan and SceneContract | Authorial Intent | `NarrativePlanService` | Add a separate append-only plan aggregate and transaction. |
| NarrativeContextPack | Non-authoritative working projection | none | Rebuild from exact authoritative versions and immutable retrieval inputs. |
| Draft, simulation, review, extraction | Candidate/proposal planes | none | Read context and produce proposals only. |

The following boundaries are fixed:

1. `NarrativePlan` and `SceneContract` describe future intent; neither is a Canon fact or event.
2. `KnowledgeState` is Canon content and may be committed only through an approved `CanonDelta`.
3. A proposition describes belief content. A `Fact` asserts truth. They are not interchangeable.
4. `SceneContract` is upstream authorial intent; production `SceneSpec` is a downstream production-semantic contract.
5. Context selection, temporal filtering, and epistemic visibility belong to the R2 compiler, not to donor retrieval or memory stores.
6. Canon and Authorial Intent use separate transactions. Neither service opens or participates in the other's unit of work.

No new ADR is required for this baseline. R2-DEC-003, R2-DEC-005, R2-DEC-006, and R2-DEC-007 already fix the durable boundaries. A separately writable proposition store, a Canon/plan cross-authority transaction, or another visibility authority would require a new decision and is excluded.

## 3. Evidence and reuse

### Host seams retained

- `R2ContractModel`, `ContractIdentity`, `NonEmptyStr`, and strict JSON guards remain the public-contract base.
- M5A `CanonDelta`, `ResolvedCanonView`, `CanonResolver`, validation report, repository ports, and authority/projection unit-of-work ownership remain intact.
- M5A canonical JSON and recorded hash/schema selectors remain the compatibility mechanism.
- `ContentBasis` carries exact Canon and plan dependencies into later screenplay, `SceneSpec`, and `ShotSpec` artifacts.
- The existing async database and migration chain remain the only Host persistence substrate.

### Donor semantics retained

- Novel Studio contributes bounded recent context, hybrid retrieval candidates, and deterministic hard-rule shapes.
- Shenbi contributes layered context priority, hook debt, evidence-oriented state extraction, and human-reviewed proposal workflow.
- Huohuo contributes causal sidecar and normalization patterns for later `NarrativeChangeSet` work.
- StoryBox contributes character-local perception and bounded-attention simulation inputs.

Donor truth stores, SQLite layouts, provider calls, skill runtimes, persona memory, and direct truth-file writes remain excluded. Donor outputs enter M5B only as typed retrieval candidates or later proposals.

## 4. Scope decomposition

M5B is one architecture slice delivered through three sequential checkpoints:

```text
M5B-1  Canon schema v2
       EpistemicProposition + KnowledgeState + TemporalRelation
       deterministic epistemic/temporal validation
              │
              ▼
M5B-2  Authorial Intent authority
       NarrativePlan aggregate + SceneContract
       append-only NarrativePlanService
              │
              ▼
M5B-3  NarrativeContextCompiler
       exact-version reads + visibility filter + deterministic budget
       30-scene acceptance corpus
```

Each checkpoint must be independently reviewable and green. M5B-2 may use M5B-1 contracts but cannot write Canon. M5B-3 receives read interfaces from both authorities but cannot write either.

## 5. Canon schema evolution

### 5.1 Selector behavior

M5A writes `content_schema_version = "r2-canon-schema-v1"`. M5B introduces `r2-canon-schema-v2`.

Schema v2 adds:

```text
epistemic_propositions_by_ref
knowledge_states_by_id
temporal_relations_by_id
```

The canonical JSON algorithm and byte-domain rules do not change, so M5B retains:

```text
content_hash_algorithm = "sha256"
content_hash_version = "r2-canon-content-v1"
payload_hash_algorithm = "sha256"
payload_hash_version = "r2-canon-delta-v1"
```

The schema selector, not the hash selector, determines which content and operations are legal. Replay supports v1 and v2 explicitly. An unknown selector fails closed.

The first v2 delta over a v1 base performs a pure deterministic upgrade:

```text
v1 content
+ empty epistemic proposition map
+ empty knowledge state map
+ empty temporal relation map
→ v2 content
```

The upgrade has no wall-clock input and cannot change existing Entity, Fact, or Event bytes. A v1 version remains verifiable under v1; it is not rewritten in place.

### 5.2 EpistemicProposition

`EpistemicProposition` is an immutable value inside the KnowledgeState family:

```text
EpistemicProposition
  proposition_ref
  subject_ref
  predicate
  object_or_value
```

`subject_ref` is the Canon entity the proposition is about. It differs from `KnowledgeState.subject_entity_id`, which identifies the character who holds the epistemic state.

`proposition_ref` is content-addressed:

```text
"ep:" + sha256(canonical_json({
  "schema": "r2-epistemic-proposition-v1",
  "subject_ref": ...,
  "predicate": ...,
  "object_or_value": ...
}))
```

Normalization uses the existing strict JSON rules. A supplied reference that does not match the normalized value fails validation. Reusing a reference with different content is an identity conflict.

The value expresses the content of a belief; it does not assert that the content is true. It has no repository, head, commit interface, approval state, or independently writable lifecycle. The resolved v2 view deduplicates proposition values by reference only to make `KnowledgeState.proposition_ref` resolvable.

### 5.3 KnowledgeState

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

Times are timezone-aware UTC story instants. Intervals are half-open `[effective_from, effective_until)`. `effective_from` is required. Null `effective_until` means positive infinity.

Absence of a KnowledgeState does not imply explicit `UNKNOWN`. Explicit unknown is useful when a scene or transition must prove that a tracked proposition is not known; the ledger is not a closed-world inventory of everything a character could know.

### 5.4 UPDATE_KNOWLEDGE

Canon schema v2 adds exactly two operation kinds: `UPDATE_KNOWLEDGE`, defined here, and
`ADD_TEMPORAL_RELATION`, defined in Section 5.6. All M5A v1 operation kinds remain legal in a v2 delta.

```text
UpdateKnowledgeOperation
  operation_id
  kind = UPDATE_KNOWLEDGE
  target_id                    # new KnowledgeState ID
  subject_entity_id
  proposition                  # complete EpistemicProposition value
  epistemic_state
  effective_from
  effective_until?
  evidence_event_refs[]
  bootstrap_author_decision_ref?
  supersedes_knowledge_state_id?
```

Application rules:

1. The subject, proposition subject, and every evidence event must exist in the candidate Canon view.
2. A new tracked `(subject_entity_id, proposition_ref)` may omit `supersedes_knowledge_state_id` only when no active prior state exists at `effective_from`.
3. A transition from an active prior state names its exact ID. The reducer closes that prior interval at the new `effective_from` and appends the new state.
4. A missing, inactive, differently keyed, or already closed superseded state fails.
5. The operation cannot derive transition time from transaction time or evidence-event time.
6. Exact retries remain governed by the M5A delta identity. The reducer does not provide a second idempotency rule.
7. Overlapping incompatible states for the same subject/proposition fail; equal boundary handoffs are valid.
8. A delta that produces no semantic change fails under the existing M5A no-op rule.
9. `bootstrap_author_decision_ref`, when present, must identify exactly one reference already present in
   the enclosing delta's `author_decision_refs`. A validator never infers a transition-to-decision mapping
   from two unkeyed lists.
10. `KNOWN` and `FALSE_BELIEF` use either non-empty `evidence_event_refs` or one
    `bootstrap_author_decision_ref`, but not both. `SUSPECTED` requires event evidence and forbids the
    bootstrap field. `UNKNOWN` permits optional event evidence and forbids the bootstrap field.

This explicit supersession prevents “latest row wins” behavior and makes backdated transitions auditable.

### 5.5 Epistemic truth and evidence rules

A KnowledgeState classifies a proposition relative to Canon truth over its entire half-open active interval,
not only at `effective_from`:

- `KNOWN(P)` requires active Canon Facts whose exact
  `(subject_ref, predicate, object_or_value)` equals P and whose interval union covers the complete
  KnowledgeState interval without a gap.
- `FALSE_BELIEF(P)` requires active Canon Facts with the same `(subject_ref, predicate)` and a different
  value whose interval union covers the complete KnowledgeState interval without a gap. Mere absence of P
  is unresolved, not proof that P is false.
- `SUSPECTED(P)` permits true, contradicted, or unresolved P, but requires at least one admissible evidence
  event.
- `UNKNOWN(P)` cannot overlap any other active state for the same subject/proposition and does not require
  a truth judgment.

Coverage includes `effective_from` and every instant before the excluded `effective_until`. An open-ended KnowledgeState therefore requires
open-ended supporting truth or contradiction. Adjacent, equal-valued Facts may jointly provide coverage;
an uncovered instant fails validation. Any Canon operation that would invalidate an existing `KNOWN` or
`FALSE_BELIEF` interval must close or supersede that KnowledgeState at the invalidating boundary in the
same CanonDelta. Otherwise the complete candidate fails before persistence. This rule applies equally to
forward and backdated Fact changes.

`KNOWN` and `FALSE_BELIEF` require at least one admissible evidence event unless their operation contains
`bootstrap_author_decision_ref`. Bootstrap decisions are author evidence, not synthetic events. The named
reference must be present in the enclosing delta's `author_decision_refs`. Because the operation-local
mapping and that list are inside the delta payload hash, the existing scope-bound `CanonCommitApproval`
approves their exact association; M5B does not invent a second decision-approval authority.

`KnowledgeState.evidence_event_refs` is the authoritative evidence link. An existing historical Event is
not mutated merely to add a backlink. `Event.state_effect_refs` is optional corroboration for historical
Events; when it names a KnowledgeState, that state must reciprocally name the Event. A newly added Event
and KnowledgeState in the same ordered delta may use this reciprocal binding, validated over the final
candidate view. No relation operation or second Event authority is introduced.

Participation in an Event is not evidence of perception. Every event-backed transition must explicitly
name its evidence Event, and that Event must not be provably later than `effective_from`. It is provably
later when:

- its direct `temporal_anchor` is later than `effective_from`;
- it is simultaneous with an anchored Event later than `effective_from`; or
- a reachable anchored predecessor occurs at or after `effective_from`, so the strict `BEFORE` path places
  the evidence Event later.

An unanchored, temporally incomparable Event is admissible rather than assigned an invented order. The
validator records which anchor or relation path proved a chronology rejection.

### 5.6 TemporalRelation

M5B adds a minimal relative-time value:

```text
TemporalRelation
  temporal_relation_id
  left_event_ref
  relation:
    BEFORE
    SIMULTANEOUS
  right_event_ref
  evidence_event_refs[]
```

`AFTER` is represented by swapping endpoints of `BEFORE`. This keeps one canonical direction. `SIMULTANEOUS` canonicalizes endpoint order by event ID.

`ADD_TEMPORAL_RELATION` inserts one immutable relation into Canon schema v2. The validator:

- rejects self-relations and missing event references;
- rejects both `BEFORE(A, B)` and `BEFORE(B, A)` directly or transitively;
- collapses simultaneous events into an equivalence class before checking the `BEFORE` DAG;
- rejects `BEFORE` within one simultaneous class;
- checks that anchored event datetimes respect every reachable `BEFORE` edge;
- derives a normalized relation key as `BEFORE(left, right)` or
  `SIMULTANEOUS(min(left, right), max(left, right))` and rejects the same key under another relation ID;
- returns a stable incomparable result for unanchored events that have no relation path, rather than inventing order.

M5B uses timezone-aware datetimes for knowledge intervals and context queries, matching M5A. A narrative time jump is a difference between authorial scene order and story-time order; it does not require an ordinal/calendar authority in this slice.

## 6. Pure narrative validation

`NarrativeInvariantValidator` is a deep pure module:

```python
class NarrativeInvariantValidator:
    def validate_canon(
        self,
        *,
        base: ResolvedCanonView,
        delta: CanonDelta,
        candidate: ResolvedCanonView,
    ) -> NarrativeValidationReport: ...

    def validate_scene(
        self,
        *,
        canon: ResolvedCanonView,
        plan: NarrativePlan,
        scene: SceneContract,
    ) -> NarrativeValidationReport: ...

    def validate_scene_outcome(
        self,
        *,
        before: ResolvedCanonView,
        after: ResolvedCanonView,
        plan: NarrativePlan,
        scene: SceneContract,
        audience_reveal_evidence: tuple[AudienceRevealEvidence, ...],
    ) -> NarrativeValidationReport: ...
```

It receives immutable values and returns a deterministic report. The Canon method retains base, delta, and
candidate so it can validate supersession, operation-local bootstrap binding, and same-delta repairs rather
than attempting to reconstruct them from the final view. It has no repository, session, provider,
retrieval client, clock, or mutation method.

Findings contain:

```text
rule_id
severity: ERROR | WARNING
affected_refs[]
story_time?
message
evidence_refs[]
```

Ordering is `(severity, rule_id, affected_refs, story_time)`. Commit gates treat every `ERROR` as blocking. A required `SceneContract` constraint cannot be downgraded to warning by a caller.

Initial rule families:

| Family | Blocking examples |
|---|---|
| `EPI_IDENTITY_*` | proposition hash mismatch, reused ID with different content, missing subject |
| `EPI_INTERVAL_*` | invalid interval, incompatible overlap, invalid supersession |
| `EPI_TRUTH_*` | incomplete interval coverage for KNOWN or FALSE_BELIEF; Fact mutation leaves an invalid state |
| `EPI_EVIDENCE_*` | missing evidence, ambiguous bootstrap binding, participation treated as observation, provably future evidence |
| `TIME_GRAPH_*` | temporal cycle, simultaneous/before conflict, anchor violation, duplicate normalized relation |
| `SCENE_ENTRY_*` | typed Fact/Knowledge entry constraint fails at the exact entry instant |
| `SCENE_KNOWLEDGE_*` | forbidden interval overlap, reveal precondition, false-belief mismatch |
| `SCENE_EVENT_*` | unsatisfiable selector, required/forbidden collision, indeterminate forbidden Event time |
| `SCENE_EXIT_*` | post-scene Fact/Knowledge target or reveal outcome is not satisfied |

Donor hard rules and model reviews may be converted into additional findings, but only R2 rule implementations can emit blocking results for these families.

## 7. EpistemicViewResolver

```python
class EpistemicViewResolver:
    def resolve(
        self,
        *,
        canon: ResolvedCanonView,
        subject_entity_id: str,
        at: datetime,
    ) -> EpistemicView: ...
```

For each tracked proposition at the supplied UTC story instant, the resolver applies this cardinality rule:

```text
0 active KnowledgeStates -> proposition absent from the view
1 active KnowledgeState  -> select that state
>1 active KnowledgeStates -> raise EpistemicIntegrityError
```

It never selects the latest row to conceal corrupt overlapping state. A valid resolution returns:

```text
EpistemicView
  canon_version_id
  subject_entity_id
  story_time
  known[]
  suspected[]
  false_beliefs[]
  explicit_unknown[]
  evidence_event_refs[]
  view_hash
```

Each item retains its proposition and KnowledgeState source ID. Lists are sorted by proposition reference. The view hash covers the exact version, subject, time, and selected state values. It is a rebuildable projection and receives no persistence interface.

## 8. NarrativePlan aggregate

### 8.1 Aggregate shape

`NarrativePlan` is the versioned Authorial Intent aggregate:

```text
NarrativePlan
  plan_id
  version
  schema_version = r2-narrative-plan-v1
  parent_version?
  canon_basis:
    branch_id
    canon_version_id
  story_frame
  volume_plans[]
  episode_plans[]
  arc_plans[]
  chapter_plans[]
  scene_contracts[]
  content_hash
  content_hash_algorithm = sha256
  content_hash_version = r2-narrative-plan-content-v1
  committed_at
  committed_by
  approval_ref
```

Every plan node has a stable logical ID, object version, intent, expected progression, child refs, constraints, and approval metadata. Medium-specific hierarchies may omit Volume, Episode, or Chapter layers, but every child declares exactly one aggregate-local parent except the StoryFrame root.

`canon_basis` says which immutable world state the plan was approved against. It is a cross-authority read dependency, not permission for `NarrativePlanService` to modify Canon.

### 8.2 SceneContract

```text
SceneContract
  scene_contract_id
  version
  semantic_hash
  semantic_hash_algorithm = sha256
  semantic_hash_version = r2-scene-contract-content-v1
  sequence_index
  purpose
  pov?
  location_ref?
  temporal_window
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

`sequence_index` is authorial presentation order. `temporal_window` is typed story time:

```text
SceneTemporalWindow
  effective_from
  effective_until
```

Both values are required timezone-aware UTC instants and define a non-empty half-open interval
`[effective_from, effective_until)`. Entry is evaluated at `effective_from`; exit is evaluated at
`effective_until`. A time jump is legal when presentation order differs from story-time order and all
entry, exit, and temporal-relation constraints remain valid.

All executable constraints have stable `constraint_id` values and strict typed payloads:

```text
SceneFactConstraint
  constraint_id
  constraint_kind = FACT
  subject_ref
  predicate
  comparison:
    PRESENT | ABSENT | EQUALS | NOT_EQUALS
  expected_value?              # required only for EQUALS/NOT_EQUALS

SceneKnowledgeConstraint
  constraint_id
  constraint_kind = KNOWLEDGE
  subject_entity_id
  proposition_ref
  states[]                     # non-empty EpistemicState set
  include_absent = false

SceneEventConstraint
  constraint_id
  event_ref?                   # exact Event selector
  event_type?                  # pattern selector when event_ref is absent
  participant_refs_all[]
  location_ref?

CharacterRevealRecipient
  recipient_kind = CHARACTER
  subject_entity_id
  resulting_state:
    KNOWN | SUSPECTED | FALSE_BELIEF

AudienceRevealRecipient
  recipient_kind = AUDIENCE
  audience_scope = STORY_AUDIENCE

SceneRevealConstraint
  constraint_id
  proposition_ref
  recipients[]                 # discriminated Character/Audience union; non-empty

AudienceRevealEvidence
  reveal_constraint_id
  accepted_narrative_ref
  source_descriptor_ref
  audience_scope = STORY_AUDIENCE
  content_hash

SceneStateConstraint = SceneFactConstraint | SceneKnowledgeConstraint
```

The list containing a constraint supplies its polarity and evaluation semantics:

- every `entry_state_constraints` item must match the exact Canon basis at entry;
- every `exit_state_targets` item is a required post-scene target evaluated at exit by outcome validation;
- a `forbidden_knowledge` item is violated if its state set, or absence when `include_absent=true`,
  matches at any instant in the scene window;
- every `required_events` selector must match at least one Event in a post-scene candidate; every
  `forbidden_events` selector must match none;
- an exact `event_ref` must resolve to that Event. A pattern requires `event_type`; all named participants
  must be present and a named location must equal the Event location. Outcome matching requires the Event's
  direct temporal anchor to fall inside the scene window; an unanchored candidate cannot satisfy a required
  selector and cannot be silently treated as outside a forbidden selector;
- `PRESENT`/`ABSENT` inspect active Facts for `(subject_ref, predicate)`. `EQUALS`/`NOT_EQUALS` compare
  canonical JSON values. `NOT_EQUALS` requires at least one active Fact and does not treat absence as
  inequality. The value field is required for `EQUALS`/`NOT_EQUALS` and forbidden for
  `PRESENT`/`ABSENT`;
- a Knowledge constraint matches one active state in `states`; zero active states match only when
  `include_absent=true`; multiple active states are an integrity error;
- the same normalized constraint cannot appear in both a required and forbidden list.

For a Character reveal, the recipient must not already have the requested resulting state at entry and
must have it at exit in a post-scene candidate. An Audience reveal is presentation intent for
`STORY_AUDIENCE`; it never creates a Canon entity or KnowledgeState. Accepted narrative metadata, rather
than prose inference, records fulfillment for that target. Its `AudienceRevealEvidence` must resolve an
`ACCEPTED_NARRATIVE` descriptor on the exact plan/Canon bases, name the same reveal constraint, include the
revealed proposition in `proposition_refs`, bind `STORY_AUDIENCE`, and match the accepted prose hash.

A reveal and every required Event or exit target remain authorial obligations until an accepted narrative
revision produces the separately approved Canon delta or accepted-narrative evidence needed to validate
the outcome. Compiling or approving a SceneContract cannot create an Event, Fact, or KnowledgeState.

Plan commit validation checks exact references, entry conditions, typed shapes, normalized duplicates,
and static satisfiability against `canon_basis`. It does not claim that future exit obligations are already
fulfilled. Pure post-scene outcome validation checks the required/forbidden Event selectors, reveal
recipients, and exit targets against explicit exact pre-scene and post-scene inputs.

Scene identity is deterministic across aggregate revisions:

1. A new `scene_contract_id` starts at version 1.
2. Its semantic hash covers every normalized semantic field except ID, version, and the hash fields themselves.
3. Unchanged semantic bytes retain the prior version; changed semantic bytes increment it by exactly one.
4. A scene removed from a plan version is absent from that version but remains in immutable history.
5. Reintroducing the same logical ID continues from its greatest historical version and increments by one.
6. Reusing `(scene_contract_id, version)` with a different semantic hash, decreasing a version, skipping a
   version, or assigning version 1 to a previously used ID is `NarrativePlanIdentityConflictError`.

The proposal supplies scene versions and hashes; they are part of the approved plan content bytes.
`NarrativePlanService` validates them against immutable plan history and never silently renumbers approved
content.

### 8.3 Revision proposal and approval

```text
NarrativePlanRevisionProposal
  plan_revision_id
  plan_id
  expected_version?
  proposed_content
  content_hash
  created_at
  created_by

NarrativePlanApproval
  approval_ref
  plan_revision_id
  plan_id
  expected_version?
  content_hash
  project_name
  user_id
  approved_by
  approved_at
  status = APPROVED
```

`plan_revision_id` is the idempotency identity. Exact retry returns the original committed version. Same ID with different bytes, scope, expected version, or approval receipt fails as an identity conflict. A stale expected version fails without writes; M5B never automatically rebases approved authorial intent.

One `approval_ref` may approve exactly one accepted identity tuple:

```text
(user_id, project_name, plan_id, plan_revision_id, expected_version, content_hash)
```

Reusing it for any different tuple fails before a write. Conversely, one `plan_revision_id` cannot be
committed under a different approval receipt. Exact retries require the same complete tuple and return the
original version.

The plan content hash covers `canon_basis`, StoryFrame, ordered hierarchy nodes, SceneContracts, and schema version. It excludes plan/version identity, approval, actor, and commit time. Proposal identity and approval bind those excluded fields separately.

### 8.4 Persistence

M5B adds one additive migration for two tables:

```text
narrative_plans
  plan_id PK
  user_id
  project_name
  head_version
  created_at
  created_by

narrative_plan_versions
  plan_id + version PK
  plan_revision_id UNIQUE
  approval_ref UNIQUE
  parent_version
  canon_branch_id
  canon_version_id
  schema_version
  content_json
  content_hash
  hash_algorithm
  hash_version
  approval receipt fields
  committed_at
  committed_by
```

The aggregate snapshot is authoritative Authorial Intent. Scene contracts are embedded in the immutable version payload; M5B does not add a separately writable SceneContract table. This preserves one transaction and one plan interface while retaining stable scene IDs/versions.

The mutable plan row only identifies the current head. Historical reads address `(plan_id, version)` exactly. Deletion is restrictive and follows explicit project lifecycle code.

The physical/logical reference topology is fixed:

- `narrative_plan_versions.plan_id` has a physical `RESTRICT` foreign key to `narrative_plans.plan_id`;
- `(plan_id, parent_version)` has a nullable composite self-foreign key to
  `(narrative_plan_versions.plan_id, narrative_plan_versions.version)` with `RESTRICT`;
- `narrative_plans.head_version` is a logical pointer rather than a physical foreign key, avoiding a
  create-time table cycle and preserving the existing SQLite migration path;
- repository reads and `NarrativePlanService` reject a head that is missing, belongs to another plan, or
  is not the greatest accepted local version. Integrity tests corrupt each logical-head case directly and
  require fail-closed detection; no reader selects another version as a fallback.

## 9. NarrativePlanService

```python
class NarrativePlanService:
    async def commit_revision(
        self,
        *,
        proposal: NarrativePlanRevisionProposal,
        approval: NarrativePlanApproval,
        project_name: str,
        user_id: str,
        now: datetime,
    ) -> NarrativePlanCommitResult: ...

    async def get_version(
        self,
        *,
        plan_id: str,
        version: int,
        project_name: str,
        user_id: str,
    ) -> NarrativePlan: ...

    async def get_scene_contract(
        self,
        *,
        plan_id: str,
        plan_version: int,
        scene_contract_id: str,
        scene_contract_version: int,
        project_name: str,
        user_id: str,
    ) -> SceneContract: ...
```

This is one deep module. A separate `SceneContractService` would be a shallow read-through interface and is not introduced.

`commit_revision` is the only plan authority path. `expected_version=None` is a genesis proposal and may
create the scoped `narrative_plans` head row only inside the same approved transaction that appends version
1. `expected_version=N` appends exactly version `N + 1`. A genesis proposal for an existing plan is a
version conflict; an append proposal for a missing plan is not found. Genesis and append use the same
`plan_revision_id` idempotency, approval tuple, exact Canon-basis validation, scene validation, fault
boundaries, and single commit. No unapproved empty plan can exist.

Each write call owns one fresh plan unit of work:

1. Validate proposal and approval bytes before lock.
2. Begin one async transaction.
3. Resolve the scoped plan row: lock the existing head for append; for genesis require it absent and rely on the `plan_id` primary key to serialize concurrent insertion.
4. Resolve exact retry before version conflict.
5. Compare the locked version with `expected_version`.
6. Resolve the exact scoped `canon_basis`; run `NarrativeInvariantValidator.validate_scene()` for every
   SceneContract and require zero blocking findings, then validate hierarchy, refs, scene identity/version
   rules, approval uniqueness, and content hash.
7. Append the immutable version and advance the head.
8. Flush and commit once.

The Canon read is exact and read-only. Plan approval cannot fall back to the Canon head. Outcome-only
obligations are checked for static satisfiability at commit and are not misreported as already fulfilled.

Repositories do not commit, roll back, open sessions, or expose plan-head update methods outside the authority adapter. PostgreSQL row locking is the concurrency authority; focused SQLite tests use the existing immediate-transaction convention.

## 10. NarrativeContextCompiler

### 10.1 Interface

```python
class NarrativeContextCompiler:
    async def compile(self, request: NarrativeContextRequest) -> NarrativeContextPack: ...
```

The small interface hides Canon resolution, plan reads, epistemic filtering, retrieval validation, ranking, de-duplication, budgeting, and provenance construction.

```text
NarrativeContextRequest
  user_id
  project_name
  canon_branch_id
  canon_version_id
  plan_id
  plan_version
  scene_contract_id
  scene_contract_version
  creative_policy_ref
  creative_policy_version
  mode:
    AUTHOR_DRAFT
    CHARACTER_SIMULATION
  pov_subject_entity_id?
  story_time
  recent_accepted_refs[]
  retrieval_snapshot_ref?
  token_budget
  compiler_version
```

All versions are exact. “Latest” is not accepted at the compiler seam. `CHARACTER_SIMULATION` requires a POV subject. `AUTHOR_DRAFT` may omit POV only for omniscient authoring explicitly permitted by the SceneContract and policy.

M5B compiles pre-scene context only, so request `story_time` must equal the selected
SceneContract's `temporal_window.effective_from`. Mid-scene and post-scene recompilation require a later
explicit workflow and cannot be used to expose planned exit knowledge early.

### 10.2 Read ports

The compiler receives only read interfaces:

```text
CanonVersionReader
NarrativePlanReader
CreativePolicyReader
AcceptedNarrativeReader
RetrievalSnapshotReader
TokenCounter
```

It receives no authority repository, write port, unit-of-work factory, provider client, runtime task client, or donor memory interface.

Opaque prose from retrieval, accepted narrative, or summaries must carry an immutable source descriptor
before its content is eligible for compilation:

```text
NarrativeSourceDescriptor
  descriptor_ref               # "nsd:" + sha256 of canonical fields below
  descriptor_hash_algorithm = sha256
  descriptor_hash_version = r2-narrative-source-descriptor-v1
  source_ref
  user_id
  project_name
  authority_class:
    ACCEPTED_NARRATIVE | RETRIEVED_REFERENCE | SUMMARY
  source_basis_refs[]
  canon_basis?                 # exact branch_id + canon_version_id
  plan_basis?                  # exact plan_id + plan_version
  effective_from               # required nullable field; null means negative infinity
  effective_until              # required nullable field; null means positive infinity
  visibility_policy:
    AUTHOR_ONLY | SUBJECTS
  proposition_refs[]
  visibility_subjects[]
  visibility_knowledge_state_refs[]
  content_hash
  content_hash_algorithm = sha256
  content_hash_version = r2-narrative-source-content-v1
```

`AUTHOR_ONLY` requires both visibility lists to be empty. `SUBJECTS` requires a non-empty subject list,
a non-empty proposition list, an exact `canon_basis`, and active KnowledgeState refs proving every named
subject has `KNOWN`, `SUSPECTED`, or `FALSE_BELIEF` for every named proposition at the requested story
time; `UNKNOWN` and an absent state do not grant visibility. Unannotated semantic content is not
eligible for `SUBJECTS`. `ACCEPTED_NARRATIVE` and `SUMMARY` additionally require exact `plan_basis` and
`canon_basis`. `source_basis_refs` is non-empty for every descriptor. A retrieval reference may omit
authority bases only when it is `AUTHOR_ONLY`; doing so never promotes it to Canon truth or Authorial
Intent.

Descriptor hashing uses the existing strict canonical JSON rules and excludes `descriptor_ref` itself.
`content_hash` is SHA-256 over the exact NFC-normalized UTF-8 prose bytes with LF line endings. A supplied
descriptor ref or content hash mismatch is invalid metadata. Descriptor intervals use the same half-open
comparison rules as Canon; both nullable fields must be present and any finite end must be after its finite
start. Set-like reference lists are sorted and duplicate-free.

Descriptor metadata is a claim, not a new authority. The compiler resolves its basis refs against exact
Canon/plan reads, checks the descriptor and prose hashes, and only then assigns an output visibility
channel. An input descriptor never supplies an `allowed_channel` field.

Retrieval input is an immutable candidate snapshot with a scope envelope and inline descriptor:

```text
RetrievalSnapshot
  snapshot_ref
  user_id
  project_name
  query_fingerprint
  candidates[]:
    candidate_id
    source_descriptor
    content
    score
  created_at
  retriever_version
```

The snapshot records what retrieval produced; it does not make candidates true or visible. A live vector search without a frozen candidate snapshot is not a reproducible compiler input. Accepted prose and summaries use the same descriptor contract even when supplied by their dedicated readers.

Metadata determines visibility; compiler code never infers scope, authority, time, or epistemic visibility
from prose. The compiler validates scope and descriptor shape before content is inspected, ranked, logged,
or returned. An optional item with missing, stale, unresolvable, or contradictory metadata is omitted with a
stable reason. Invalid metadata on a mandatory item fails compilation. Both paths are fail closed.

If one prose artifact mixes claims with different visibility, its upstream reader must supply separately
hashed and described segments. The compiler does not ask a retriever, donor model, or LLM to split secrets.

### 10.3 Visibility channels

Every packed segment has one channel:

```text
AUTHOR_TRUTH
POV_KNOWN
POV_SUSPECTED
POV_FALSE_BELIEF
EXPLICIT_UNKNOWN
AUTHORIAL_INTENT
CREATIVE_POLICY
RECENT_ACCEPTED
RETRIEVED_REFERENCE
SUMMARY
```

Each segment records its descriptor/basis refs, effective story interval, visibility subjects, priority,
token count, and content hash. Canon, SceneContract, and CreativePolicy segments are constructed directly
from their exact typed authority values; opaque prose segments require `NarrativeSourceDescriptor`.

`AUTHOR_DRAFT` may include `AUTHOR_TRUTH`, but POV-forbidden propositions are separately and explicitly labelled. Truth is never flattened into the POV-known lane. `CHARACTER_SIMULATION` cannot contain `AUTHOR_TRUTH`, explicit unknown content, or any segment not visible to the subject.

### 10.4 Compilation order

The compiler executes this fixed order:

1. Validate scope, exact identifiers, versions, UTC story time, mode, and budget.
2. Resolve the exact immutable Canon version.
3. Load the exact plan and SceneContract versions.
4. Require the plan's Canon basis to equal the requested Canon version for M5B. Rebase/revalidation belongs to a later explicit workflow.
5. Run Canon and SceneContract hard validation.
6. Resolve the POV epistemic view when required.
7. Load exact policy, recent accepted artifacts, and retrieval snapshot.
8. Resolve and validate every source descriptor and convert eligible candidates into typed source segments.
9. Apply authority, scope, effective-time, and epistemic filters to every segment, including accepted prose and summaries. Descriptor claims must be proven by the exact authority bases; prose is never a visibility input.
10. De-duplicate by semantic source/content identity.
11. Allocate the deterministic token budget.
12. Emit the pack and complete selection/omission trace.

Filtering precedes ranking and budgeting. Retrieval score cannot recover a segment rejected by authority, time, scope, or visibility.

### 10.5 Budget policy

Priority is fixed by compiler version:

1. SceneContract and hard forbidden constraints;
2. required Canon truth and POV knowledge/belief view;
3. CreativePolicy constraints;
4. active plan/thread/payoff context;
5. directly referenced recent accepted prose;
6. retrieval candidates;
7. optional summaries.

If mandatory layers exceed the token budget, compilation fails with `NarrativeContextBudgetError`. It never silently drops a hard constraint or truncates structured JSON into invalid content.

Optional items sort by `(priority, source_ref, content_hash)`. Token counting uses the injected deterministic counter identified by version. Equal inputs produce identical included items, ordering, omissions, and pack hash.

### 10.6 Output and trace

```text
NarrativeContextPack
  context_pack_id
  base_canon_version
  epistemic_view_ref?
  narrative_plan_refs[]
  creative_policy_ref
  scene_contract_ref
  pov?
  temporal_context
  segments[]
  recent_accepted_context[]
  retrieved_context[]
  token_budget
  tokens_used
  compiler_version
  retrieval_snapshot_ref?
  dependency_refs[]
  selection_trace[]
  content_hash
```

`context_pack_id` is derived from an input fingerprint covering exact dependency refs/versions, mode, POV, story time, retrieval snapshot, token budget, token-counter version, and compiler version. `content_hash` separately covers the emitted segments and selection trace; neither hash includes itself. The selection trace records each considered candidate as `INCLUDED` or an explicit omission reason such as `WRONG_SCOPE`, `MISSING_SOURCE_METADATA`, `UNRESOLVED_VISIBILITY_BASIS`, `OUT_OF_TIME`, `NOT_VISIBLE`, `DUPLICATE`, or `BUDGET`.

Omission trace data is visibility-sensitive. A source rejected by scope, authority, effective time, metadata,
or epistemic visibility records only `candidate_id`, a non-secret `source_ref`, status, and omission reason.
It carries no prose, `content_hash`, descriptor hash, token count derived from hidden prose, proposition refs,
or visibility proof refs. Only an `INCLUDED` item, or an item that passed every visibility gate and was then
omitted as `DUPLICATE` or `BUDGET`, may include its content hash and token count in the trace. Compiler logs
apply the same rule.

The pack may be persisted by a later working-artifact/cache adapter, but persistence does not grant authority and is not required by the M5B compiler interface.

## 11. Failure behavior

Stable errors distinguish caller correction from integrity failure:

| Error | Meaning |
|---|---|
| `NarrativeSchemaVersionError` | unsupported Canon, proposition, plan, or compiler schema/version |
| `EpistemicIdentityError` | proposition or KnowledgeState identity mismatch |
| `EpistemicIntegrityError` | resolved Canon contains more than one active state for a subject/proposition |
| `EpistemicValidationError` | invalid truth, evidence, interval, or transition |
| `TemporalValidationError` | cycle, anchor contradiction, duplicate normalized key, or invalid relation |
| `NarrativePlanNotFoundError` | unknown and cross-scope plan/version identifiers, deliberately collapsed |
| `NarrativePlanIdentityConflictError` | plan revision or SceneContract ID/version reused with different identity |
| `NarrativePlanVersionConflict` | expected plan head is stale |
| `NarrativePlanApprovalError` | incomplete or mismatched approval receipt |
| `NarrativeContextInputError` | inconsistent exact versions, mode, POV, time, or retrieval snapshot |
| `NarrativeSourceMetadataError` | mandatory source metadata is missing, contradictory, or cannot prove visibility |
| `NarrativeContextValidationError` | hard Canon/scene constraint blocks compilation |
| `NarrativeContextBudgetError` | mandatory context cannot fit |

Compile failure returns no partial pack. Canon commit failure leaves delta/version/head/projection unchanged. Plan commit failure leaves plan version/head unchanged.

## 12. Security and scope

- Every authority and compiler read includes `(user_id, project_name)`.
- Cross-scope identifiers are indistinguishable from unknown identifiers.
- Context packs and traces must not expose filtered segment content. Pre-visibility rejection records carry
  only the non-secret IDs/status/reason allowed by Section 10.6; post-visibility duplicate/budget records may
  additionally carry content hash and token count.
- A retrieval snapshot from another scope is rejected before content is inspected or returned.
- Compiler logs apply the same visibility-tiered trace rule; they never contain secret prose, hidden-content
  fingerprints/counts, or provider credentials.
- Donor adapters receive only the already-filtered pack appropriate to their mode.
- No Agent, writer, simulator, compiler, router, or donor adapter receives a Canon or plan write interface.

## 13. Proposed module boundaries

```text
r2/contracts/narrative.py             # extend M5A contracts with v2 epistemic/temporal values
r2/contracts/narrative_context.py     # source descriptors, requests, packs, and traces
r2/narrative/schema_upgrade.py         # pure v1 → v2 Canon content upgrade
r2/narrative/epistemic.py              # proposition identity and EpistemicViewResolver
r2/narrative/temporal.py               # relation normalization and DAG validation
r2/narrative/validation.py             # extend M5A validator with M5B rule families
r2/contracts/narrative_plan.py         # Authorial Intent aggregate and approval contracts
r2/narrative_plan/validation.py        # pure hierarchy/SceneContract validation
r2/narrative_plan/integrity.py         # logical head and immutable lineage integrity checks
r2/narrative_plan/ports.py             # plan authority/read/UoW protocols
r2/narrative_plan/service.py           # sole NarrativePlan commit interface
r2/narrative_context/ports.py          # read-only compiler dependencies
r2/narrative_context/compiler.py       # one deep compile interface
r2/narrative_context/errors.py         # stable compiler error taxonomy
lib/db/models/narrative_plan.py        # plan head and immutable plan versions
lib/db/repositories/narrative_plan.py  # scoped transaction-bound adapter
lib/db/narrative_plan_uow.py           # plan transaction lifecycle
```

Public package exports include contracts, pure result types, `NarrativePlanService`, `EpistemicViewResolver`, and `NarrativeContextCompiler`. ORM models, repositories, UoW implementations, hash helpers, reducers, and mutable write primitives remain internal.

Import fitness rules enforce:

- R2 contracts and pure narrative modules do not import `lib.db`, `server`, providers, or production runtime;
- context modules do not import authority write ports or UoW factories;
- `NarrativePlanService` cannot import Canon authority write ports;
- only `CanonTransactionService` reaches Canon authoritative writes;
- only `NarrativePlanService` reaches plan authoritative writes;
- production intelligence, provider execution, and Canvas do not enter M5B modules.

## 14. Acceptance strategy

### 14.1 Contract and schema tests

- strict extra-field rejection and UTC normalization;
- deterministic proposition reference and ID/content conflict;
- exactly two discriminated v2 operation additions while v1 replay remains supported;
- deterministic v1→v2 upgrade without v1 content drift;
- operation-local bootstrap decision binding and ambiguous/unlisted decision rejection;
- normalized TemporalRelation duplicate rejection under different IDs;
- stable plan/scene IDs, exact scene version transitions, removal/reintroduction, and hash behavior;
- provider/runtime fields rejected from stable narrative contracts.

### 14.2 Pure epistemic and temporal tests

- known, suspected, false-belief, and explicit-unknown truth matrices;
- exact boundary transitions under `[from, until)`;
- complete Fact coverage across finite and open-ended KnowledgeState intervals;
- Fact retirement/change without same-delta KnowledgeState closure fails; atomic closure/supersession passes;
- overlapping incompatible states rejected;
- resolver returns absent/one state and raises integrity error for more than one active state;
- backdated transition with explicit supersession;
- historical Event evidence succeeds without a backlink; a present inconsistent backlink fails;
- directly anchored and relation-proven future evidence fails while incomparable evidence remains admissible;
- participant without observation does not learn a proposition;
- temporal DAG, transitive cycle, simultaneous equivalence, anchored contradiction, and incomparable events;
- deterministic finding order and rule IDs.

### 14.3 Plan authority tests

- genesis and append through the sole `commit_revision` authority path;
- exact retry before version conflict;
- ID/approval/content mismatch and cross-revision `approval_ref` reuse rejection;
- stale version with zero writes;
- hierarchy cycles, missing children, illegal parent types, and duplicate sequence index;
- typed Fact, Knowledge, Event, Reveal, and temporal-window constraint matrices;
- Character and Story Audience reveal targets remain semantically distinct;
- SceneContract revision pinned inside aggregate version with exact +1 semantic versioning;
- exact Canon basis checked read-only by `validate_scene()` before append, with no head fallback;
- same-plan serialization and different-plan concurrency on PostgreSQL;
- rollback at every flush/commit fault window.

### 14.4 Compiler tests

- exact version pinning and no latest fallback;
- author and simulation modes produce different permitted channels;
- secret in Canon, recent prose, summary, and retrieval candidate is filtered consistently;
- optional opaque prose with missing, stale, wrong-scope, or unprovable descriptor metadata is omitted with
  a stable reason; the same fault on a mandatory source fails compilation;
- every pre-visibility rejection trace omits content/descriptor hashes, hidden-derived token counts,
  proposition refs, and visibility proof refs;
- descriptor content-hash mismatch and visibility claims unsupported by their exact KnowledgeState refs fail closed;
- mixed-visibility prose enters only as separately described segments; compiler text inspection is absent;
- false belief is visible without becoming Fact;
- future SceneContract event remains absent from Canon;
- mandatory-budget overflow fails without partial pack;
- deterministic optional ranking, de-duplication, omissions, token counts, and pack hash;
- Canon or plan advancement during compilation cannot create a mixed-version pack;
- compiler dependencies expose no write interface.

### 14.5 M5 fixture

The versioned acceptance fixture contains:

- 30 SceneContracts;
- 8 characters;
- 3 locations;
- 2 hidden identities;
- 2 false beliefs;
- an injury transition;
- an object ownership/state transition;
- a presentation-order time jump;
- relationship and plot-thread constraints;
- at least one unperceived reveal event;
- author-only secret text present in a retrieval candidate.

The fixture runs through real public M5B interfaces, not hand-built final reports. Mutations must alter inputs upstream of the same validation/compiler path.

### 14.6 Required adversarial mutations

The acceptance runner must inject each mutation before the same public validator/compiler path and prove
that it is detected:

| Mutation | Required result |
|---|---|
| Remove historical Event backlink while retaining authoritative KnowledgeState evidence | accepted |
| Add a non-reciprocal Event backlink | `EPI_EVIDENCE_*` error |
| Reuse one delta-level author decision without an operation-local binding | contract/validation error |
| Retire supporting Fact midway through an open KnowledgeState without superseding it | `EPI_TRUTH_*` error |
| Move evidence Event after transition directly or through a proven temporal path | `EPI_EVIDENCE_*` error |
| Duplicate a normalized temporal relation under another ID | `TIME_GRAPH_*` error |
| Remove or falsify a secret candidate's source descriptor | stable omission; no prose or hidden fingerprint in trace |
| Claim POV visibility with an inactive or wrong-subject KnowledgeState ref | stable omission/error by mandatory status |
| Reuse SceneContract ID/version with changed semantic bytes | `NarrativePlanIdentityConflictError` |
| Reuse `approval_ref` for another revision tuple | `NarrativePlanApprovalError` with zero writes |
| Make an entry constraint invalid only on the pinned Canon basis while head remains valid | plan commit rejected; no head fallback |
| Corrupt Canon with two active states for one subject/proposition | `EpistemicIntegrityError` |

### 14.7 Hard exit

M5B is acceptable only when fresh evidence at the exact clean verified HEAD shows:

```text
Canon contradiction             0
epistemic leakage               0
timeline violation              0
rejected candidate contamination 0
failed transaction corruption  0
required skips                  0
```

Evidence includes exact base/head, migration head, schema selectors, file allowlist, graph generation/coverage, focused and affected regression commands, PostgreSQL identity, per-rule fixture results, compiler omission traces, and verified-head→evidence-only-handoff proof.

## 15. Review gates and execution handoff

1. M5A must have an accepted clean handoff before M5B implementation starts.
2. After Human approval, Codex records the approved design and plan hashes in a separate document-approval
   manifest. The implementation branch materializes only those documents and that manifest over the exact
   accepted M5A integration head; Task 0 then records the observed materialization head in a starting-state-only commit.
3. M5B-1 freezes a clean implementation verified head, runs fresh gates there, receives independent
   contract/domain review, and adds the Codex verdict in an evidence-only handoff commit before M5B-2 begins.
4. M5B-2 repeats the verified-head → Codex authority/concurrency review → evidence-only handoff sequence before M5B-3 begins.
5. M5B-3 repeats the verified-head → Codex adversarial leakage/deterministic-budget review → evidence-only
   handoff sequence before the 30-scene acceptance corpus and final regression begin.
6. Final evidence is generated only from a clean final verified implementation HEAD; its commit is evidence-only.
7. No design or focused-test pass authorizes an operating migration, production activation, provider call, worker start, push, or publish action.

## 16. Risks and controls

| Risk | Control |
|---|---|
| False proposition becomes Canon truth | Separate proposition value from Fact; only explicit Fact supports truth. |
| Hidden truth leaks through accepted prose or retrieval | One post-retrieval visibility filter covers every segment source. |
| “Latest” mixes authority versions | Compiler accepts exact versions only and hashes every dependency. |
| Plan service becomes a second Canon writer | Separate ports/UoW/import fitness; Canon basis is read-only. |
| SceneContract and SceneSpec collapse | Separate contract modules, commit authorities, and explicit ContentBasis translation. |
| Plan aggregate becomes a shallow set of repositories | One deep service owns versioning, validation, approval, idempotency, and concurrency. |
| Context budget silently removes hard constraints | Mandatory overflow is an error; all omissions are traced. |
| New Canon semantics break old replay | Recorded schema dispatch and pure v1→v2 upgrade fixtures. |
| Temporal model grows into calendar ontology | Use aware UTC story instants plus minimal relations; expand only with executable blockers. |
| Donor validator is mistaken for authority | Donor output is advisory evidence; R2 deterministic rules own blocking verdicts. |

## 17. Out of scope

- M5A Canon storage redesign or a second Canon repository;
- normalized standalone proposition tables or proposition commit service;
- cross-authority Canon/plan atomic commits;
- NarrativeChangeSet extraction, CanonDelta compilation, drafting, revision, and candidate selection (M5C);
- adaptation branches and Golden B production (M6);
- CreativePolicy write authority;
- general calendar/era/timezone ontology or relative fictional calendars;
- production `SceneSpec`/`ShotSpec`, method routing, providers, workers, Canvas, UI, or operating migration;
- donor runtime integration and live provider/network evidence.
