# R2-M5A Canon Authority and Transactions Design

**Status:** Proposed for written-spec review
**Date:** 2026-09-07
**Milestone:** R2-M5A, first slice of R2-M5 Canon & Narrative Kernel
**Decision:** [ADR-0075](../../adr/0075-canon-authority-append-only-deltas.md)
**Starting revision:** `9d5e6a3971cc88909e49b834974d763c06984491`

## 1. Goal

M5A implements the smallest durable Canon authority that can:

- create a main or narrative branch;
- append an explicit `CanonDelta` against an expected base version;
- produce an immutable `CanonVersion`;
- resolve a branch view deterministically;
- reject stale, invalid, unapproved, or conflicting commits without changing authoritative state;
- survive process restart and concurrent writers on PostgreSQL.

M5A prepares the authority and transaction boundary required by M5B and M5C. It does not implement the epistemic engine, narrative planning, writing workbench, donor adapters, adaptation, production generation, or user interface.

## 2. Authority

This design implements existing frozen decisions rather than reopening them:

- `R2-DEC-002`: one commit authority per authoritative state family;
- `R2-DEC-003`: Narrative Authority stays separate from Production and Runtime Authority;
- `R2-DEC-004`: candidate content is never Canon;
- `R2-DEC-008`: `NarrativeChangeSet` and `CanonDelta` are different artifacts;
- `R2-DEC-009`: branches use explicit parent/overlay lineage;
- `R2-OPEN-001`: physical SQL/ORM mapping for R2 authority contracts;
- `R2-OPEN-005`: physical representation of overlays and resolved Canon views.

Only `CanonTransactionService` may advance a Canon branch head. Repositories persist and retrieve rows for that service; they do not expose a public operation that bypasses base-version checks, validation, or approval.

## 3. Evidence and reuse

### Host seams retained

- Reuse the existing asynchronous SQLAlchemy database and `AsyncSession` boundary from ADR-0020.
- Reuse `Base`, `UserOwnedMixin`, timezone-aware timestamps, Alembic, and repository conventions in `lib/db/`.
- Reuse the PostgreSQL `SELECT ... FOR UPDATE` branch-lock pattern demonstrated by the C04 budget repository. SQLite-focused tests use the repository's existing serialized-write convention; PostgreSQL concurrency evidence remains the acceptance authority.
- Reuse `R2ContractModel`, `NonEmptyStr`, `JSONValue`, and deterministic canonical JSON hashing from `r2/contracts/`.
- Reuse the existing architecture tests that enforce one commit authority; extend their registry rather than creating another authority registry.

### Narrative donor lessons retained

- Novel Studio contributes the draft-isolation and explicit-acceptance workflow shape.
- Huohuo contributes causal `NarrativeChangeSet` concepts, consumed only in M5C.
- Shenbi contributes validator and truth-sync patterns, also consumed only through R2-owned proposal/validation seams.
- Donor SQLite stores, truth files, memory services, and direct state-settling writes do not become Canon persistence.

M5A therefore reuses Host infrastructure and donor patterns while keeping R2's Canon schema, transaction semantics, and authority local.

## 4. Scope decomposition

M5 is divided into independently reviewable slices:

| Slice | Owns | Excludes |
|---|---|---|
| M5A | branch/version lineage, Entity/Fact/Event core, delta replay, commit transaction, projection recovery | epistemic rules, authorial plan, extraction, donor execution |
| M5B | KnowledgeState, temporal/epistemic validation, NarrativePlan, SceneContract, context compilation | Canon storage redesign |
| M5C | NarrativeChangeSet, CanonDelta compilation, candidate validation pipeline, combined 30-scene fixture | direct donor authority |

M5A may model references needed by later slices, but it does not implement their behavior.

## 5. Domain model

### 5.1 CanonBranch

`CanonBranch` is stable identity and lineage metadata:

```text
branch_id
user_id
project_name
branch_type = MAIN | NARRATIVE_BRANCH
parent_branch_id?
parent_version_id?
head_version_id?
created_at
created_by
```

Rules:

- A project/user scope has at most one `MAIN` branch.
- A main branch has no parent branch or parent version.
- A narrative branch requires both a parent branch and an immutable parent version from that branch.
- A narrative branch remains pinned to that parent version. Parent advancement has no implicit effect.
- `head_version_id` is the concurrency boundary. It is the only mutable Canon authority pointer.
- Branch creation is idempotent by `branch_id`: an identical retry returns the existing branch; a different payload under the same ID fails closed.

### 5.2 CanonVersion

`CanonVersion` is an immutable commit receipt:

```text
canon_version_id
branch_id
version_number
parent_version_id?
committed_delta_id
committed_at
committed_by
content_hash
content_hash_algorithm
content_hash_version
content_schema_version
```

Rules:

- Version numbers are contiguous within a branch and start at `1`.
- Version 1 on a main branch is produced by a genesis delta against an empty view.
- Version 1 on a narrative branch applies its first local delta over the pinned parent view and sets `parent_version_id` to `CanonBranch.parent_version_id`.
- Every later version points to the previous local branch version.
- `parent_version_id` always identifies the semantic content base: `null` only for main genesis, the pinned parent version for narrative version 1, and the previous local version thereafter.
- A committed version, its delta reference, and its content hash never change.
- `content_hash` covers the canonical resolved view, not execution metadata or projection storage metadata.
- M5A writes `content_hash_algorithm = "sha256"`, `content_hash_version = "r2-canon-content-v1"`, and `content_schema_version = "r2-canon-schema-v1"`. Replay selects the recorded versions and fails closed on an unsupported value.

### 5.3 CanonDelta

M5A materializes the frozen `CanonDelta` contract as an immutable proposal accepted for one branch/base pair:

```text
canon_delta_id
target_branch_id
base_canon_version_id?
operations[]
source_change_set_refs[]
author_decision_refs[]
validation_report_refs[]
payload_hash
payload_hash_algorithm
payload_hash_version
content_schema_version
created_at
created_by
```

M5A supports these operations:

```text
ADD_ENTITY
UPDATE_ENTITY
ADD_FACT
RETIRE_FACT
ADD_EVENT
```

The remaining frozen operation kinds enter with the slice that owns their semantics. Unknown operations fail validation; they are not ignored or stored for speculative future interpretation.

An operation has a stable `operation_id`, a kind, a target ID, and a strictly validated payload. Ordering is significant and canonical. Two operations in one delta cannot claim the same `operation_id`.

`base_canon_version_id` is the expected semantic content base, not merely the current local head. It is `null` for main genesis, the pinned parent version for the first local narrative delta, and the previous local version thereafter. The service derives that expected base from the locked branch as `head_version_id` when present, otherwise `parent_version_id` for a narrative branch, otherwise `null`.

`payload_hash` covers the delta ID, content schema version, payload hash version, target branch, expected semantic base, ordered operations, and sorted source/author/validation references. M5A writes `payload_hash_algorithm = "sha256"` and `payload_hash_version = "r2-canon-delta-v1"`. Creation time and database row metadata are excluded. User/project scope and approval identity are checked separately, so an approval cannot be replayed across scopes or under a new delta ID. Replay fails closed on an unsupported hash or schema version.

### 5.4 Core atoms

M5A resolves three atom families:

- `Entity`: stable semantic identity, type, canonical name, sorted unique aliases;
- `Fact`: subject, predicate, object/value, optional effective interval, sorted unique source-event refs; retired facts remain in the view with a closed `effective_until`;
- `Event`: type, sorted unique participant refs, optional location, temporal anchor, sorted unique causal and state-effect refs.

Resolved atoms are immutable values inside a `ResolvedCanonView`. An update operation replaces one value in the newly resolved view; it does not update a prior version or delta.

### 5.5 ResolvedCanonView

`ResolvedCanonView` is a deterministic read model:

```text
canon_version_id
branch_id
content_hash
content_hash_algorithm
content_hash_version
content_schema_version
content:
  entities_by_id
  facts_by_id
  events_by_id
```

The view is derived in this order:

```text
main branch:
  empty view → local delta 1 → ... → local head

narrative branch:
  pinned parent resolved view → local delta 1 → ... → local head
```

`content_hash` covers only the canonical `content` object. It excludes `canon_version_id`, `branch_id`, the hash field itself, projection timestamps, and execution metadata. Map keys are sorted during canonical serialization. Set-like lists are normalized to sorted unique values. Timestamps use UTC-aware ISO 8601. Non-finite floats and non-string JSON object keys are rejected by the existing JSON contract helpers.

Fact validity uses half-open intervals `[effective_from, effective_until)`. A null start means negative infinity; a null end means positive infinity. Intervals that meet at the same timestamp do not overlap. `RETIRE_FACT` carries an explicit, non-null `effective_until` in its operation payload; replay never derives it from wall-clock time. The value must be later than a finite `effective_from`, and retiring a fact whose end is already finite fails validation.

## 6. Physical persistence

M5A adds one additive Alembic revision with four tables.

### `canon_branches`

- primary key: `branch_id`;
- ownership: `user_id`, `project_name`;
- lineage: nullable `parent_branch_id`, `parent_version_id`;
- mutable pointer: nullable `head_version_id`;
- metadata: `branch_type`, `created_at`, `created_by`;
- unique partial constraint for one main branch per `(user_id, project_name)`;
- check constraints enforce valid branch type and parent-field pairing.

### `canon_deltas`

- primary key: `canon_delta_id`;
- scope: `user_id`, `project_name`, `target_branch_id`;
- expected base: nullable `base_canon_version_id`;
- immutable payload: `operations_json`, source/author/validation reference arrays, `payload_hash`;
- hash metadata: `payload_hash_algorithm`, `payload_hash_version`, `content_schema_version`;
- authorization receipt: `approval_ref`, `approval_status`, `approved_by`, `approved_at`;
- metadata: `created_at`, `created_by`;
- foreign key to the target branch;
- unique `approval_ref`: one approval receipt authorizes exactly one accepted Canon delta identity;
- check constraint requires `approval_status = "APPROVED"`;
- `canon_delta_id` is the sole idempotency identity. Payload/base uniqueness is not an implicit retry mechanism.

### `canon_versions`

- primary key: `canon_version_id`;
- foreign keys: `branch_id`, nullable `parent_version_id`, unique `committed_delta_id`;
- immutable receipt: `version_number`, `content_hash`, `content_hash_algorithm`, `content_hash_version`, `content_schema_version`, `committed_at`, `committed_by`;
- unique `(branch_id, version_number)`;
- unique `(branch_id, content_hash, parent_version_id)` is not required: a no-op delta is rejected before persistence.

### `canon_resolved_projections`

- primary/foreign key: `canon_version_id`;
- `resolved_view_json`, `content_hash`, `content_hash_algorithm`, `content_hash_version`, `content_schema_version`, `built_at`;
- optional `replay_count` for diagnostics only;
- no branch head, approval state, or independent version number.

The projection table is not an authority table. Deleting all projection rows must leave every branch/version/delta intact and all views reconstructable. Projection persistence is an idempotent upsert keyed by version ID. It may replace a missing or invalid row only after replay produces the immutable version's exact hash and hash/schema versions. Concurrent rebuilders of the same version therefore converge on identical bytes; a duplicate projection writer is not a Canon conflict.

### Foreign-key cycle handling

`canon_branches.head_version_id`/`parent_version_id` and `canon_versions.branch_id` form a logical cycle. The database keeps the strong direction: versions reference branches, version parents reference versions, and child branches reference parent branches. The two version pointers on a branch are indexed IDs without physical foreign keys; `CanonTransactionService` validates their existence, branch membership, and scope while holding the branch lock. This avoids dialect-specific post-create constraints while keeping every authoritative version tied to a real branch. An executable integrity checker compensates for the omitted foreign keys: it verifies branch pointer existence/scope/membership, head/version contiguity, semantic parent lineage, committed delta linkage, and supported hash/schema versions. ORM relationships must avoid cascade paths that could delete history. Canon rows use restrictive deletion; project deletion follows the repository's explicit project lifecycle rather than database cascade from a branch.

## 7. Service boundaries

### CanonRepository

The repository provides persistence primitives for `CanonTransactionService`:

```python
async def get_branch(*, branch_id: str, project_name: str, user_id: str) -> CanonBranchSnapshot | None

async def lock_branch(*, branch_id: str, project_name: str, user_id: str) -> CanonBranchSnapshot

async def get_version(*, canon_version_id: str, project_name: str, user_id: str) -> CanonVersionSnapshot | None

async def get_delta(*, canon_delta_id: str, project_name: str, user_id: str) -> CanonDelta | None

async def load_projection(
    *, canon_version_id: str, project_name: str, user_id: str
) -> ResolvedCanonView | None
```

Append/head-update primitives remain module-private or transaction-service-private. No router, Agent tool, donor adapter, compiler, or worker receives them.

### CanonResolver

```python
async def resolve(
    *, branch_id: str, version_id: str | None, project_name: str, user_id: str
) -> ResolvedCanonView
```

Resolution behavior:

1. Load the requested version or branch head within the caller's scope.
2. Accept a projection only when its stored hash equals the immutable version hash and recomputed canonical view hash.
3. On missing or mismatched projection, replay the pinned lineage and local deltas.
4. Persist the rebuilt projection only through a projection-specific repository method.
5. Return an immutable domain snapshot.

A corrupt delta, broken lineage, missing parent, or final hash mismatch raises `CanonIntegrityError`. Resolution never guesses, skips an operation, or substitutes the current parent head.

`CanonResolver` does not own a session. It receives a transaction-bound `CanonRepository` for commit-time replay. A read-only application facade may open a unit-of-work and bind both repository and resolver to it; projection rebuild uses that same unit-of-work. No resolver or repository method opens a nested or independent session.

### CanonTransactionService

```python
async def create_branch(command: CreateCanonBranch) -> CanonBranchSnapshot

async def commit(
    *,
    delta: CanonDelta,
    approval: CanonCommitApproval,
    project_name: str,
    user_id: str,
    now: datetime,
) -> CanonCommitResult
```

`CanonCommitApproval` is the domain-specific receipt of the authenticated Human Showrunner action:

```python
class CanonCommitApproval(R2ContractModel):
    approval_ref: NonEmptyStr
    canon_delta_id: NonEmptyStr
    payload_hash: NonEmptyStr
    payload_hash_algorithm: Literal["sha256"]
    payload_hash_version: Literal["r2-canon-delta-v1"]
    content_schema_version: Literal["r2-canon-schema-v1"]
    project_name: NonEmptyStr
    user_id: NonEmptyStr
    approved_by: NonEmptyStr
    approved_at: datetime
    status: Literal["APPROVED"]
```

The authenticated application facade constructs this receipt only for an explicit approval action and calls `CanonTransactionService` in the same request. The service requires exact delta ID, payload hash and versions, content schema version, project, user, actor, status, and timestamp binding, then persists the complete receipt fields with the accepted delta. One `approval_ref` can authorize exactly one `(user_id, project_name, canon_delta_id, payload_hash, payload_hash_algorithm, payload_hash_version, content_schema_version)` tuple. This mirrors the existing explicit production-promotion receipt pattern while keeping approval domain-specific. M5A does not reuse `ProductionApprovalService` as Canon approval authority and does not create a general workflow engine.

`CanonTransactionService` receives an `async_sessionmaker` (or an equivalent `CanonUnitOfWork` factory), not a repository with an ambiguous lifecycle. Each `create_branch` or `commit` call opens exactly one fresh `AsyncSession` transaction, constructs one repository bound to that session, and passes that repository to every resolver and persistence operation on the authoritative path. Only the service commits or rolls back that unit-of-work.

## 8. Commit transaction

The commit path is one database transaction:

1. Validate the command, delta schema, approval receipt, timestamps, IDs, operation kinds, reference lists, and canonical payload hash before acquiring a lock.
2. Begin a fresh async session transaction.
3. Lock the scoped branch row with `SELECT ... FOR UPDATE` on PostgreSQL.
4. Look up `canon_delta_id` within the transaction before checking the current base.
   - Same scope, exact canonical payload bytes/hash metadata, semantic base, complete approval receipt identity, and committed version returns the original `CanonCommitResult` without replay or writes.
   - Any mismatch under the same ID raises `CanonIdentityConflictError`.
5. For a new delta, derive the locked semantic base: local head when present, otherwise the pinned parent version for a narrative branch, otherwise `null` for main genesis. Compare it with `delta.base_canon_version_id`; a mismatch raises `CanonBaseVersionConflict` with zero writes.
6. Resolve that locked semantic base view. A narrative branch with no local head starts from its pinned parent version.
7. Apply operations in declared order to a copy of the view.
8. Run M5A validators.
9. Reject an empty semantic change; a delta must alter the canonical resolved view.
10. Compute the resolved content hash with the existing canonical JSON rules.
11. Revalidate the approval receipt against the exact locked scope, delta ID, payload hash, hash/schema versions, actor, status, and approval timestamp. Verify that `approval_ref` has not authorized any other delta identity.
12. Insert the immutable delta and next version.
13. Update the branch head from the expected old value to the new version.
14. Insert the resolved projection with the same content hash.
15. Flush and commit.

Any exception rolls back delta, version, head, and projection together. The service never automatically rebases or retries a stale delta because doing so would change the meaning of an author-approved mutation.

## 9. Validation

M5A validators are deterministic and side-effect free.

### Structural validation

- IDs are non-empty and stable.
- Atom IDs are unique within the resolved view.
- Referenced entity/event/location IDs exist after applying earlier operations in the same delta.
- Effective intervals have an ordered start/end when both exist.
- Fact intervals use `[effective_from, effective_until)`; null bounds mean the corresponding infinity and equal adjacent endpoints do not overlap.
- Event participant and causal references contain no duplicates.
- An event cannot causally reference itself.
- A fact cannot be retired when absent or already retired in the resolved base.
- `RETIRE_FACT` supplies its deterministic `effective_until`; it cannot use transaction time as Canon content.
- `UPDATE_ENTITY` requires an existing entity and cannot change its ID or entity type.
- Adding an existing ID or updating a missing ID fails.

### M5A contradiction boundary

M5A rejects exact active fact collisions for the same `(subject_ref, predicate)` when their effective intervals overlap and their object/value differs. Rich world-rule, timeline, relationship, object-state, and epistemic contradictions belong to M5B. This boundary gives M5A a meaningful integrity gate without hiding later engines inside the storage slice.

### Validation report

The transaction produces a deterministic `CanonValidationReport` containing rule IDs, affected refs, and messages. Rejected reports may be persisted by a separate evidence path only if that path is explicitly non-authoritative. Rejection never appends a delta or advances the branch.

## 10. Concurrency and idempotency

### Concurrent commits

Two commits against the same base may validate concurrently before locking. After branch locking, exactly one may advance the head. The loser receives `CanonBaseVersionConflict` containing expected and current version IDs. It leaves no delta, version, projection, or approval-consumption side effect.

Commits to different branches may proceed independently. Creating two main branches concurrently is stopped by the database uniqueness constraint and translated into `CanonBranchConflict`.

### Retry behavior

- Retrying a successfully committed `canon_delta_id` with the exact same payload and approval returns the original result.
- Reusing that ID with different bytes, scope, base, or approval fails closed.
- Reusing an `approval_ref` for any other `(user_id, project_name, canon_delta_id, payload_hash, hash/schema versions)` fails closed. An exact retry of the original delta may reuse its recorded receipt.
- Retrying a transaction that failed before commit behaves like a fresh attempt.
- Callers decide how to create a new delta after a base conflict; the service does not mutate or rebase their proposal.

## 11. Recovery and integrity

M5A must prove these restart properties:

- Committed branch heads, deltas, and versions survive a new process/session.
- A missing projection is rebuilt to the recorded version hash.
- A corrupted projection is ignored, rebuilt, and replaced only when replay matches the version hash.
- A corrupted authoritative delta or broken lineage fails closed and remains observable; it is never repaired by changing history.
- Concurrent projection rebuilds converge through idempotent upsert and cannot create an authoritative conflict.
- A simulated failure after each flush point leaves either the old complete authority state or the new complete authority state.

The M5A integrity checker reports and fails its gate when any of these conditions is false:

- a branch head exists in the same scope and belongs to that branch;
- a null head has no local versions, while a non-null head is the highest contiguous local version;
- a narrative parent version exists in the same scope and belongs to `parent_branch_id`;
- main genesis has no semantic parent, narrative version 1 points to the pinned parent version, and every later version points to the previous local version;
- each version's committed delta belongs to the same scope/branch and names the same semantic base;
- every stored hash/schema version is supported and every authoritative payload verifies under its recorded version.

Backup/restore execution remains an M7 gate, but M5A records all authoritative Canon data in the existing PostgreSQL backup scope and defines a consistency checker suitable for the M7 restore drill.

## 12. Security and scope

Every branch, delta, version lookup, commit, and projection rebuild begins from `(user_id, project_name)`. Supplying a globally valid ID from another scope returns the same not-found result as an unknown ID. A parent branch/version must share the child branch's project/user scope.

`created_by`, `committed_by`, `approved_by`, and approval references are audit identities. They are not accepted as substitutes for request authentication. Canon payloads and validation reports must not contain provider credentials or runtime secrets.

## 13. Proposed module boundaries

```text
r2/contracts/narrative.py
  CanonBranch, CanonVersion, Entity, Fact, Event, CanonDelta,
  operation payloads, validation report/result contracts

r2/narrative/canon_state.py
  ResolvedCanonView and pure deterministic operation application

r2/narrative/validation.py
  M5A structural and exact-fact contradiction validators

r2/narrative/canon_resolver.py
  lineage replay, projection verification, projection rebuild

r2/narrative/canon_transaction.py
  CanonTransactionService and its authenticated-facade boundary

lib/db/models/canon.py
  four ORM tables

lib/db/repositories/canon_repo.py
  scoped reads, branch locking, transaction-private persistence primitives

alembic/versions/
  one generated revision whose filename ends in `_add_canon_authority.py`
```

The `r2/narrative` package may depend on stable contracts and an injected persistence port. `r2/contracts` cannot import ORM, server, provider, artifact-manifest, or donor modules. Host/runtime code cannot call transaction-private repository writes.

## 14. Acceptance strategy

### Contract tests

- strict extra-field rejection and timezone awareness;
- deterministic normalization and hashing;
- historical content/delta verification uses persisted algorithm, canonicalization, and schema versions; unsupported versions fail closed;
- each operation kind accepts only its typed payload;
- invalid atom references and duplicate operation IDs fail.

### Pure domain tests

- genesis, update, fact retirement, event creation, and ordered multi-operation delta;
- exact fact contradiction and overlapping effective intervals;
- half-open boundaries, null infinities, and deterministic fact retirement timestamps;
- deterministic replay gives identical bytes and hash;
- parent-pinned narrative branch stays unchanged after parent advances.

### Repository and migration tests

- upgrade creates exactly the four authority tables, constraints, indexes, and foreign keys;
- downgrade removes only M5A tables;
- scoped reads do not cross user/project boundaries;
- immutable history is not exposed through repository update/delete APIs;
- SQLite focused lifecycle tests pass;
- disposable PostgreSQL tests prove `FOR UPDATE` concurrency and uniqueness behavior.
- duplicate concurrent projection rebuilds converge on the same verified row.

### Transaction tests

- approved commit advances head exactly once;
- missing, rejected, wrong-scope, or wrong-payload approval produces zero authority writes;
- stale base produces zero writes;
- concurrent same-base commits produce one success and one base conflict;
- exact retry returns the original version;
- exact retry is checked before current-base conflict and performs no new writes;
- conflicting ID retry fails closed;
- approval-reference reuse across a different delta identity fails closed;
- injected failures before delta insert, after delta insert, after version insert, after head update, and during projection insert preserve the prior complete state;
- restart with a new engine/session resolves the same head and hash;
- deleted/corrupt projection rebuilds; corrupt delta fails closed.

### Architecture tests

- exactly one public Canon commit authority exists;
- donor, worker, router, Agent-tool, Canvas, production, and runtime modules cannot import transaction-private Canon persistence primitives;
- projection code cannot update branch heads, deltas, or versions;
- resolver/repository collaborators on the commit path cannot create sessions or commit transactions;
- `r2/contracts/narrative.py` stays provider/model/endpoint neutral;
- no second database, artifact registry, queue, or approval authority is introduced.

### M5A exit

M5A is complete only when:

1. the additive migration passes upgrade/downgrade on disposable SQLite and PostgreSQL;
2. all contract, domain, repository, transaction, restart, concurrency, and architecture tests pass;
3. the branch projection can be deleted and reproduced byte-for-byte;
4. every rejected or fault-injected commit leaves the prior branch head and history unchanged;
5. evidence records exact revision, migration head, commands, exit codes, and PostgreSQL container identity;
6. the executable integrity checker passes over the committed PostgreSQL fixture, including every logical branch version pointer;
7. the implementation diff contains no M5B/M5C, M6, provider, Canvas, or M7 activation.

## 15. Risks and controls

| Risk | Control |
|---|---|
| Delta replay grows with long history | benchmark the frozen 30-scene fixture; add checkpoint policy only with measured evidence |
| Projection is mistaken for authority | hash verification, deletion/rebuild test, architecture import boundary |
| Branch sees unapproved parent changes | pin exact `parent_version_id`; never resolve through parent head |
| Approval races with payload changes | bind approval lookup to delta ID, payload hash, scope, and actor |
| SQLite hides PostgreSQL locking behavior | require disposable PostgreSQL concurrent-writer evidence |
| Generic JSON operations become untyped | discriminated operation contracts and exact payload validators |
| M5A absorbs later narrative semantics | keep KnowledgeState, plans, extraction, rich timeline/epistemic rules in M5B/C |

## 16. Out of scope

- automatic Canon mutation from prose, Agent output, simulation, analytics, or donor state;
- KnowledgeState and epistemic filtering;
- NarrativePlan, SceneContract, context packs, drafting, and writer UX;
- NarrativeChangeSet extraction and CanonDelta compilation;
- adaptation branches and adaptation rebasing;
- production asset promotion or Artifact Manifest replacement;
- provider calls, paid side effects, Canvas promotion, learning, publishing, and production activation;
- destructive data migration or backfill of existing ArcReel project JSON.
