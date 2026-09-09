# R2 M5C persistence and state-machine validation

Date: 2026-09-09

Status: research complete; design constraints validated with two items that the
M5C design must make explicit

Decision gate: `DESIGN_SPEC_READY_WITH_EXPLICIT_HANDOFF_SEMANTICS`

## 1. Question and evidence discipline

This note validates the proposed M5C persistence topology and state machines
before the design specification freezes them. It is not a design specification,
implementation plan, migration authorization, or production authorization.

Terms used below are deliberate:

- **Observed** means behavior stated by an ArcReel source or an external primary
  source.
- **Inference** means a design lesson supported by observations but not dictated
  by the donor system.
- **ArcReel requirement** means a constraint already imposed by frozen R2
  documents or accepted ADR-0076, including its 2026-09-09 amendment.

The local baseline is the main checkout at
`558db83ef5c08c46c3645f507a5733cb25a6ee58` plus the uncommitted ADR-0076
amendment, and the live M5B implementation at
`a2dc1c141c77ce1365eea8360a3593b55567c5af`. The required M5B source was read
directly because its graph coverage is stale or absent. The external systems
below are pattern evidence only; this note does not propose adding KurrentDB,
Temporal, or a generic workflow/event-sourcing framework.

## 2. Controlling ArcReel constraints

The following are requirements, not options:

1. Immutable candidates, revisions, extraction/compilation attempts and
   results, and change sets are evidence. The three append-only Human decision
   families are Narrative workflow authority; heads are rebuildable projections
   (`docs/adr/0076-narrative-lifecycle-evidence-and-acceptance-authority.md:7-18,103-131`).
2. Revision and change-set heads have different logical keys and cardinalities.
   Many non-overlapping change-set lineage heads may coexist for one accepted
   revision (`ADR-0076:133-156`).
3. New downstream work must name exact decision IDs and prove that they are
   currently effective. Historical replay may resolve superseded evidence but
   may not use it as current authority (`ADR-0076:158-183`).
4. Exact retry lookup precedes stale-predecessor rejection. A decision ID is
   opaque and is idempotent only for its complete canonical identity tuple
   (`ADR-0076:185-203`).
5. The compiler is a pure proposal transformation surrounded by durable
   attempt/result evidence. It cannot approve, select latest, or commit Canon
   (`ADR-0076:39-69`; frozen responsibility matrix
   `docs/r2/R2_02_FROZEN_RESPONSIBILITY_MATRIX.md:167-230`).
6. M5C ends at a `CanonDelta` proposal. The existing `CanonCommitApproval` and
   `CanonTransactionService` remain the approval receipt and sole Canon commit
   path (`docs/r2/R2_01_FROZEN_ARCHITECTURE.md:832-877`).

The live M5B source supports these choices:

- `NarrativePlanService.commit_revision()` resolves an existing
  `plan_revision_id` before locking/checking the plan head, then appends the
  immutable version and advances the head in one commit
  (`/home/anhtuan/content-production-os-m5b/r2/narrative_plan/service.py:49-140,179-210`).
- `CanonTransactionService.commit()` locks the branch, resolves an existing
  exact delta retry, and only then rejects a stale Canon base; delta, version,
  head, and projection are written in one transaction
  (`/home/anhtuan/content-production-os-m5b/r2/narrative/canon_transaction.py:167-262,279-380`).
- `NarrativeContextCompiler` receives exact read-only ports and no repository,
  UoW, provider, or latest-state read. It verifies returned identities after
  every exact lookup (`/home/anhtuan/content-production-os-m5b/r2/narrative_context/ports.py:1-79`;
  `compiler.py:134-268`).
- `CanonDeltaPayload` already carries plural exact change-set and author-decision
  refs, while `CanonCommitApproval` binds exact delta identity/hash/schema and
  tenant scope (`/home/anhtuan/content-production-os-m5b/r2/contracts/narrative.py:340-389`).

The Production approval donor validates generated state, rejection, target and
content fingerprint, and returns a no-change result for the same selected
candidate/version (`r2/production/approval_service.py:35-77`). That is a useful
validation/idempotency pattern, but its mutable Production metadata is not a
donor for append-only Narrative authority.

## 3. External primary-source findings

### 3.1 PostgreSQL 18

**Observed.** A transaction makes multiple steps all-or-nothing and exposes
committed changes together. `SELECT ... FOR UPDATE` prevents other writers and
lockers from changing a selected row until transaction end. PostgreSQL warns
that long transactions and inconsistent multi-row lock order create blocking
and deadlock risks. [PostgreSQL 18 transactions](https://www.postgresql.org/docs/18/tutorial-transactions.html),
[explicit locking](https://www.postgresql.org/docs/18/explicit-locking.html).

**Observed.** `UNIQUE` applies to a column group, nullable values are distinct by
default unless `NULLS NOT DISTINCT` is requested, and a foreign key enforces a
reference to an existing primary/unique key. PostgreSQL explicitly warns that a
`CHECK` constraint is not a sound cross-row/cross-table invariant; it recommends
`UNIQUE`, `EXCLUDE`, or `FOREIGN KEY` where applicable.
[PostgreSQL 18 constraints](https://www.postgresql.org/docs/18/ddl-constraints.html).

**Inference for M5C.** Each authority transition should be one short transaction
that locks concrete logical-head rows, validates the expected predecessor,
appends the decision, and advances the projection. Provider/compiler execution
must occur outside that transaction. Exact ID, scope, receipt, and lineage
uniqueness belongs in database constraints, while overlap/applicability across
multiple rows needs locked transaction logic and an integrity checker rather
than a cross-row `CHECK`.

**Important first-head caveat.** `FOR UPDATE` only locks a row that exists. The
first decision for a scope therefore needs one explicit strategy: pre-create the
head row, atomically insert it under a unique stable-scope key and retry/reread
on conflict, or use a transaction-scoped advisory lock. This is an ArcReel
design choice, not a PostgreSQL mandate. The existing M5B Plan path provides the
closest local precedent: genesis inserts the scoped head in the same authority
transaction and relies on primary-key uniqueness.

### 3.2 KurrentDB/EventStoreDB

**Observed.** KurrentDB appends with an expected stream state/revision and
returns a wrong-version error when the stream has advanced. A successful append
retried with the same consistency check and event IDs is accepted without
duplicating events. Event IDs are not globally unique and are specifically retry
detectors, not substitutes for semantic equality.
[KurrentDB Python client 1.3 append documentation](https://docs.kurrent.io/clients/python/v1.3/appending-events),
[KurrentDB v25.1.4 protocol at `3b4cc113`](https://github.com/kurrent-io/KurrentDB/blob/3b4cc1133f2fdffbd2aff34f61615c8d883d108f/src/Protos/Grpc/streams.proto#L184-L242).

**Observed.** KurrentDB projections store checkpoints/results and can rebuild
from the event stream; projection-owned output must not be independently
appended by applications because that destroys predictability.
[projection streams at commit `22ebf50a`](https://github.com/kurrent-io/KurrentDB/blob/22ebf50ad042bc60d9644ddc957fac0197a1e714/docs/server/features/streams.md#L45-L55),
[projection ownership/recovery at the same commit](https://github.com/kurrent-io/KurrentDB/blob/22ebf50ad042bc60d9644ddc957fac0197a1e714/docs/server/features/projections/README.md#L76-L88).

**Inference for M5C.** Expected revision is a strong analogue for
expected-predecessor OCC, and projection recovery supports keeping decision
history authoritative while heads remain disposable. KurrentDB's event-ID
dedupe is deliberately weaker than ADR-0076: M5C must compare the entire
canonical retry tuple and fail closed on any mismatch.

### 3.3 Temporal

**Observed.** Temporal Activities should be idempotent; failures normally create
new Activity Task executions. Inputs and returned result are recorded in
workflow history. The API records an attempt number, and an Activity task token
is attempt-scoped: completion fails with `NotFound` when the token is stale due
to timeout, prior completion, or nonexistence.
[Temporal documentation at `5fece287`](https://github.com/temporalio/documentation/blob/5fece287fbc8cde4a6e4ac890d2ba963092dbd40/docs/develop/java/activities/execution.mdx#L17-L27),
[retry policy at `5fece287`](https://github.com/temporalio/documentation/blob/5fece287fbc8cde4a6e4ac890d2ba963092dbd40/docs/encyclopedia/retry-policies.mdx#L126-L138),
[Temporal API at `46ee8b82`](https://github.com/temporalio/api/blob/46ee8b820cff353e92fa8c9d052414d4e573feb7/temporal/api/workflowservice/v1/service.proto#L292-L298).

**Observed caveat.** Temporal does not necessarily persist every intermediate
started attempt as a separate permanent history event; its server can defer
the started/final pair until the Activity finishes.
[Temporal API at `46ee8b82`](https://github.com/temporalio/api/blob/46ee8b820cff353e92fa8c9d052414d4e573feb7/temporal/api/workflowservice/v1/service.proto#L211-L226).

**Inference for M5C.** Attempt identity plus an attempt generation/token is a
useful model for rejecting a late result after a timeout or replacement attempt.
However, ArcReel's rule to persist an attempt before work and append a separate
immutable result afterward is a stronger local requirement, not a behavior
proven or imposed by Temporal.

## 4. Decision table

| Topic | Evidence | Select | Reject | Principal failure window | Required design constraint |
|---|---|---|---|---|---|
| Authority storage | ADR-0076; M5A/M5B append/head patterns; PostgreSQL transactions | Typed append-only decision families with logical head projections | Boolean acceptance on revision/change-set; head-only authority | Decision lands without head, or head moves without decision | Decision append and head advance share one transaction; history rebuilds and verifies every head |
| Physical decision schema | Three materially different identities/cardinalities in amendment | Three typed decision tables backed by one internal authority kernel/UoW | One nullable polymorphic table unless it proves equivalent constraints | Null combinations bypass identity/FK rules; one family collides with another | Database-enforced family-specific PK/FK/unique/check constraints; common code is not a common weak schema |
| Effective heads | ADR-0076 has revision and per-lineage multiplicity | Distinct logical revision and change-set head keys | One generic key/cardinality | Replacing one lineage invalidates unrelated accepted partitions | Shared physical table is allowed only with disjoint subject namespace and family-specific uniqueness |
| Conflict-resolution head | Amendment allows replacement but does not give the replacement chain a key | Add explicit `resolution_lineage_id` or deterministic conflict-set identity | Infer replacement from overlap bytes or "latest resolution" | Two resolutions race or an unrelated conflict supersedes another | Design must freeze a stable resolution logical-head key and expected predecessor |
| Exact retry/OCC | ADR-0076; Plan and Canon live source; Kurrent expected revision | Resolve exact retry before predecessor/base rejection | OCC first; content hash as decision ID | Response is lost, head later advances, exact retry is falsely rejected or resurrects authority | Same ID/same full tuple returns original immutable receipt with no writes; mismatch writes nothing; retry never makes an old decision current again |
| First head | PostgreSQL locks only existing rows; M5B Plan genesis | Unique genesis insertion plus reread/retry, unless pre-created heads are justified | Blind `SELECT FOR UPDATE` on an absent row | Two genesis decisions both observe no head | Freeze one executable genesis serialization strategy per head family |
| Evidence attempt/result | ADR-0076; Temporal attempt/result and token patterns | Immutable attempt row followed by at most one immutable terminal result for that attempt generation | Mutable attempt status as sole history; provider call inside transaction | Crash after admission, late result from timed-out generation, duplicate completion | Unique `(attempt_id, generation)`; result FK to exact attempt; late/inapplicable result remains evidence but cannot advance workflow |
| Pure compilation | M5B exact-read compiler; frozen role matrix | Run pure compiler outside transaction over snapshotted exact IDs | Hold head locks during compile; compiler reads latest or writes authority | Long lock/deadlock; mixed versions; hidden rebase | Admission records all exact semantic inputs; output identity is deterministic; no UoW/provider/write port in compiler |
| Historical replay | ADR-0076; Kurrent projection rebuild | Explicit audit/replay capability resolving exact historical IDs and bases | Reuse normal "current" port with a flag defaulting to latest | Superseded decision returns to live pipeline | Historical resolver cannot emit a current-authority token or invoke downstream handoff |
| M5A handoff | ADR-0076; existing `CanonCommitApproval`; live Canon service | Atomic Narrative handoff admission after current-effective revalidation, then existing M5A approval/commit | Best-effort read immediately before approval; lock Narrative rows across provider/Human waits | Supersession races between validation and authority crossing | Design must define the exact crossing instant and durable admission evidence; no second Canon approval service |

## 5. Recommended persistence constraints

### 5.1 Evidence

Use separate logical persistence for:

- draft candidates and narrative revisions, with normalized prose inline and
  frozen content-hash metadata;
- extraction attempts and exactly linked terminal extraction results;
- immutable `NarrativeChangeSet` proposals with declared lineage, source-span
  coverage, semantic-effect keys, extractor/policy provenance, and exact source
  revision acceptance;
- compilation attempts and exactly linked terminal compilation results.

Every evidence row has an opaque primary identity, tenant scope, immutable exact
basis refs, schema/hash versions, provenance, and restrictive deletion. Result
tables have a unique FK to `(attempt_id, generation)`. An attempt may have no
result after a crash; absence is recoverable evidence, not permission to invent
success or acceptance.

Use terminal result vocabulary rather than one cross-domain mutable state
machine:

```text
ExtractionResult = SUCCEEDED | ABSTAINED | CONFLICT | FAILED | OUTCOME_UNKNOWN
CompilationResult = SUCCEEDED | ABSTAINED | CONFLICT | FAILED
```

`outcome_unknown` is justified only around an external nondeterministic effect
whose response may be lost. The pure local compiler either has a durable result
or leaves an admitted attempt without a result; a crash does not semantically
turn deterministic compilation into a provider ambiguity. If future compiler
execution crosses an external boundary, that adapter may add its own
`outcome_unknown` evidence without changing acceptance authority.

### 5.2 Decisions and heads

Prefer three typed append-only tables:

```text
revision_acceptance_decisions
change_set_review_decisions
change_set_conflict_resolution_decisions
```

They may share serializers, retry comparison, transaction helpers, and one UoW,
but should not share a nullable catch-all row whose constraints cannot express
each family's complete identity. Each decision ID is unique and each Human
approval receipt is unique to its complete authority tuple.

The design must distinguish **decision-chain head** from **eligible selection**.
A head identifies the latest authoritative decision for its logical subject;
eligibility additionally requires the correct action (`ACCEPT`/resolved), exact
scope, and current applicability. A rejected head is never compilation input.
The design must explicitly decide whether rejecting a non-current proposal
advances a lineage head or is a review record outside the effective chain; it
must not accidentally clear an unrelated accepted revision/lineage.

For conflict resolution, add a stable replacement/OCC identity. Recommended:

```text
ConflictResolutionHead key =
  (revision_acceptance_decision_id, conflict_resolution_lineage_id)
```

The decision still names all competing review decisions and exact overlap
coverage. The lineage ID is workflow identity, not a hash-derived inference.

### 5.3 Authority transaction order

For each of the three decision commands:

1. Validate shape, canonical tuple, exact scope, hash metadata, and receipt
   before the authority lock where possible.
2. Begin one fresh short transaction.
3. Serialize the logical head, including the explicit genesis strategy.
4. Look up the opaque decision ID and resolve exact retry **before** any stale
   predecessor rejection. Same ID/different tuple is an identity conflict.
5. For a new decision, compare the locked head with the expected predecessor.
6. Resolve every referenced evidence/decision by exact ID and verify tenant,
   basis, current-effectiveness, action, and mutual applicability.
7. Append the immutable decision and advance only the relevant logical head.
8. Flush and commit once.

An exact retry returns the original immutable decision receipt and does not
advance a head. Mutable `currently_effective` status should be a separate query,
not embedded in the original idempotent result, because later supersession would
make that result time-dependent.

When one command locks multiple change-set/resolution heads, sort keys by one
canonical total order before locking. This follows PostgreSQL's deadlock
avoidance guidance and must be tested with reverse-order competing requests.

## 6. State machines and historical use

### 6.1 Decision authority

```text
immutable evidence
  -> Human decision request
  -> exact retry OR identity conflict
  -> expected-predecessor/current-input validation
  -> appended decision + advanced logical head
  -> currently effective selection
  -> superseded/rejected historical decision
```

No transition updates or deletes the earlier decision. Superseding one
change-set lineage cannot advance another lineage. Replacing a revision does not
inherit the prior revision's change-set or conflict-resolution heads.

A conflict resolution is applicable only while every named review decision is
current and accepted. Superseding any named review decision makes the old
resolution inapplicable without modifying it. New compilation must either name
a new applicable resolution or fail closed.

### 6.2 Durable execution

```text
ATTEMPT_RECORDED(generation, exact inputs)
  -> work outside authority transaction
  -> one terminal RESULT_RECORDED for that generation
  -> current-input revalidation
  -> eligible handoff OR historical-only evidence
```

Retries create a new generation/attempt link unless they are resolving the
already-durable result for the exact same attempt. A late terminal result may be
stored for audit, but only the designated non-superseded generation with exact
semantic output identity may be selected. Pure compilation reruns must produce
the same delta semantic identity for the same exact input fingerprint; mismatch
is an integrity failure, not another valid candidate.

Historical replay uses exact revisions, decisions, Canon/Plan/Scene/Context
bases, and compiler/policy versions. It may reproduce an old change set or delta
for audit. It cannot acquire current-authority capability, update a head, create
a current acceptance, or invoke M5A handoff.

## 7. M5A handoff race that the design must freeze

"Revalidate immediately before M5A" is not by itself a concurrency guarantee.
If revalidation is a read, a supersession can commit between that read and
creation of `CanonCommitApproval`. Holding Narrative head locks across Human
approval or `CanonTransactionService.commit()` would create a long cross-authority
transaction/coupling and conflicts with the existing fresh-UoW M5A boundary.

The recommended narrow solution is a durable **handoff-admission receipt** owned
by Narrative workflow authority:

1. In one short transaction, lock all named revision/change-set/resolution heads
   in canonical order, prove the compilation result and all inputs current, and
   append an admission receipt containing the exact decision IDs, observed head
   identities/generations, compilation result ID, CanonDelta ID/hash, and actor.
2. The existing authenticated facade constructs `CanonCommitApproval` and calls
   `CanonTransactionService`; it does not create a second Canon approval service.
3. The `CanonDelta` continues to hash-bind exact source change-set and author
   decision refs. The admission receipt is workflow evidence that the M5A
   boundary was crossed while inputs were current; it is not Canon approval.

The design/Human review must freeze one semantic point: does supersession after
admission invalidate an already-admitted but not-yet-committed M5A action, or is
currentness required only at the atomic handoff-admission instant? The latter is
recommended because it preserves short independent transactions. Requiring
currentness through Canon commit needs a new cross-authority fence/lease or
shared transaction and cannot be smuggled in as "revalidate once."

## 8. Failure-window and adversarial-test matrix

| Window/mutation | Required result |
|---|---|
| Two first acceptances see no head row | Database uniqueness/genesis serialization admits one; loser retries/rereads and receives predecessor conflict |
| Response lost after decision commit; head later superseded | Exact same decision ID/tuple returns original receipt, does not become current, and performs no writes |
| Same decision ID with changed actor, receipt, scope, evidence, predecessor, or exact bases | Identity conflict with zero writes |
| Crash after decision insert but before head advance | Whole transaction rolls back; no orphan authoritative decision |
| Crash after attempt record but before work/result | Durable unresolved attempt remains; recovery can create a new generation or exact deterministic rerun |
| Provider returns after its generation timed out/replaced | Late result is fenced from acceptance; `outcome_unknown` remains evidence only |
| Pure compiler produces two different semantic outputs for the same exact input fingerprint | Integrity failure; neither output proceeds automatically |
| One named review decision is superseded during compilation | Result persists as historical evidence; handoff admission fails current-effectiveness revalidation |
| One conflict resolution names a rejected/superseded review decision | Resolution is inapplicable; compilation fails closed |
| Two commands lock the same lineage set in reverse caller order | Repository canonicalizes lock order; no unbounded deadlock; aborted transaction is safely retryable |
| Head row points to a missing/wrong-scope/wrong-family decision | Integrity gate fails; reader does not choose another/latest decision |
| Head tables are deleted and rebuilt | Rebuild from append-only decisions produces identical logical heads/cardinalities |
| Historical replay of D1 after D2 supersedes it | Exact historical output can be reproduced but no current handoff token/receipt can be issued |
| Supersession commits after handoff validation but before admission receipt | Admission transaction detects it under lock and fails/retries; a naked read is insufficient |
| Supersession commits after admitted receipt but before Canon commit | Behavior matches the explicitly frozen admission-vs-commit semantic; never silently varies by timing |

## 9. Conclusion and open design items

The proposed hybrid topology is validated:

- semantic command interfaces for revision acceptance, change-set review, and
  conflict resolution;
- one internal authority kernel/UoW for canonical retry comparison, OCC, append,
  and projection advance;
- separate immutable evidence capability;
- a pure compiler wrapped by durable attempt/result recording;
- existing M5A Canon approval/commit authority unchanged.

The M5C design may proceed, but it must answer these items explicitly:

1. What is the stable `conflict_resolution_lineage_id`/head key and replacement
   rule?
2. Does a rejection advance a decision-family head, and how is "latest decision"
   separated from "currently eligible accepted selection"?
3. Which concrete first-head serialization strategy is used for each logical
   head family?
4. Is current-effectiveness frozen at atomic Narrative handoff admission, or
   must a new fence remain valid through M5A Canon commit? The recommended answer
   is admission-time currentness plus a durable admission receipt.

No generic framework, cross-authority shared transaction, provider call,
migration, worker, or production operation is justified by this research.

## 10. Coverage and limitations

Codebase Memory Tier 2 for the main project was a full generation at
`2026-09-08T15:15:51Z`; every relied-on main-checkout path reported
`metadata_match` with no recorded issue. That signal is best effort, not proof
of completeness. The M5B graph generation was the older fast index at
`2026-09-08T10:51:56Z`: `narrative_plan/service.py`,
`narrative_context/compiler.py`, and `ports.py` were `not_tracked`, while
`canon_transaction.py` and `contracts/narrative.py` were `metadata_changed`.
All five were therefore read directly from live HEAD `a2dc1c14`; no negative
claim relies on that graph.

External research inspected documentation and pinned source; it did not run
KurrentDB or Temporal, benchmark PostgreSQL lock strategies, or test a migration.
Those systems validate patterns, not ArcReel's domain semantics.
