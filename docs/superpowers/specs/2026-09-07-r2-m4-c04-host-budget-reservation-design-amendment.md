# R2-M4 C04 Host Budget Reservation — Design Amendment

**Project:** Content & Narrative Production OS  
**Milestone:** R2-M4 — Production Intelligence  
**Amendment:** C04 Host-owned budget reservation/claim capability  
**Date:** 2026-09-07  
**Status:** APPROVED / AUTHORITATIVE  
**Starting repository HEAD:** `1985b815d70dd600519839973b1da20472012d8f`  
**Parent design:** `2026-09-06-r2-m4-production-intelligence-design-APPROVED.md`

---

## 1. Why this amendment exists

Approved C04 requires a Host-owned concurrency-safe authorization for paid execution:

```text
reserve atomically
→ Generation Admission may become ADMITTED
→ claim/revalidate immediately before paid submission
→ submit
→ reconcile actual cost in Host
```

Read-only seam discovery proved that the current Host has cost estimation and actual usage accounting, but no durable atomic reservation/claim seam.

Classification:

```text
C04_BLOCKER_NO_SAFE_SEAM
```

The Human Showrunner selected **Path A — bounded Host extension**.

This amendment defines the smallest durable Host capability needed to remove that blocker without creating a parallel cost system.

**Approval record:** Human Showrunner approved this amendment on 2026-09-07 (+07:00), including the bounded Host runtime change and additive migration described herein.

---

## 2. Scope

### In scope

```text
Host-owned admission-budget scope
durable budget reservations
atomic reserve under concurrency
claim/revalidate before paid submission
release/expire before submission
attempt-correlated reconciliation
restart-safe reservation state
M4 integration port
migration required for the new durable Host state
```

### Explicitly out of scope

```text
general finance/accounting system
provider account-balance synchronization
new billing UI
cross-tenant quotas
global ArcReel budget rewrite
retroactive budgeting of all pre-M4 calls
H1 submission-identity closure
M5 Canon/Narrative authority
second cost ledger
```

---

## 3. Authority split

The extension creates a **budget authorization plane**, not another actual-cost truth plane.

```text
Existing Usage/Spend record
= authoritative evidence of actual provider call/cost

BudgetScope + BudgetReservation
= Host authorization state used to decide whether a new paid M4 attempt may proceed
```

A reconciliation row/reference may materialize authorization counters for concurrency, but it MUST point back to the existing Host usage/cost record when actual cost exists.

It MUST NOT become an independent source for provider billing truth.

---

## 4. Budget scope semantics

M4 does not attempt to budget every legacy ArcReel action.

A `BudgetScope` is an explicit Host authorization envelope for one R2/M4 production scope.

Minimum identity:

```text
budget_scope_ref
currency
authorized_limit
reserved_total
committed_total
version
created_at
updated_at
```

Rules:

1. `budget_scope_ref` is stable and unique.
2. One scope has exactly one currency in M4.
3. `authorized_limit >= 0`.
4. `reserved_total >= 0`.
5. `committed_total >= 0`.
6. `reserved_total + committed_total` may exceed `authorized_limit` only after a real provider charge exceeds its reservation; no new reservations are then permitted.
7. The scope row is the serialization anchor for concurrent reserve/claim/reconcile operations.
8. Scope counters are authorization materializations, not replacement usage/cost evidence.

No automatic currency conversion is introduced in M4.

---

## 5. Reservation semantics

Minimum durable object:

```text
BudgetReservation
├─ reservation_ref
├─ budget_scope_ref
├─ execution_decision_ref
├─ reserved_amount
├─ currency
├─ state: ACTIVE | CLAIMED | RELEASED | EXPIRED
├─ created_at
├─ expires_at?
├─ claimed_at?
├─ released_at?
├─ reconciled_at?
├─ cost_record_ref?
├─ version
└─ provenance_json
```

Additional invariant:

```text
execution_decision_ref is unique
```

One immutable `ExecutionDecision` cannot silently reuse two independent reservations.

### ACTIVE

Budget is held but provider submission is not yet authorized.

### CLAIMED

The reservation passed the immediate pre-submit atomic check. Provider submission may now occur for that attempt.

A CLAIMED reservation is not released merely because the caller times out; provider side effects may already exist.

### RELEASED

Confirmed pre-submit abandonment/cancellation returned the hold to the scope.

### EXPIRED

An ACTIVE reservation exceeded its expiration policy before claim.

Only ACTIVE reservations may transition to RELEASED or EXPIRED.

---

## 6. Atomic reserve algorithm

The authoritative transaction is Host-owned.

Pseudo-flow:

```text
BEGIN

lock/update BudgetScope serialization row

expire any ACTIVE reservations for this scope whose expires_at <= now

available =
    authorized_limit
    - committed_total
    - reserved_total

if requested_amount > available:
    ROLLBACK / return DENIED_BUDGET

insert BudgetReservation(state=ACTIVE)

BudgetScope.reserved_total += requested_amount
BudgetScope.version += 1

COMMIT
```

Concurrency requirement:

```text
Two concurrent reserve requests against the same scope
must serialize on the same BudgetScope row.
```

PostgreSQL implementation should use the repository's SQLAlchemy transaction plus row locking / equivalent atomic update semantics.

SQLite tests must prove no double reservation under concurrent writers; SQLite serializes writes, but the implementation must still use one transaction for the scope mutation plus reservation insert.

No process-local mutex is sufficient or authoritative.

---

## 7. Claim/revalidation algorithm

Immediately before the first paid provider side effect:

```text
BEGIN

lock/update BudgetScope serialization row
load reservation

require:
  reservation.state == ACTIVE
  reservation not expired
  reservation.execution_decision_ref == current immutable ED
  reservation.currency == scope.currency
  reservation remains represented in scope.reserved_total

transition ACTIVE → CLAIMED
set claimed_at
increment reservation.version and scope.version

COMMIT
```

Only after commit may the Host cross the paid provider submission boundary.

If claim fails:

```text
no provider submission
→ return to Generation Admission
→ DENIED_BUDGET or new admission cycle
```

`PromptCompiler` cannot claim a reservation.

The claim belongs at the Host execution/submission seam.

---

## 8. Release and expiration

### Explicit release

Allowed only while ACTIVE and only when the Host can prove no paid provider side effect occurred.

```text
ACTIVE → RELEASED
scope.reserved_total -= reserved_amount
```

Examples:

```text
enqueue failure after reservation
pre-submit cancellation
compiler failure before Host submission
capability/preflight invalidation before submission
```

### Expiration

Allowed only while ACTIVE:

```text
ACTIVE → EXPIRED
scope.reserved_total -= reserved_amount
```

Expiration is evaluated transactionally during reserve/claim and may also be serviced by a maintenance path later. M4 does not require a background scheduler.

No timer converts CLAIMED to RELEASED/EXPIRED.

---

## 9. Reconciliation

After a CLAIMED attempt has an authoritative Host usage/cost record:

```text
BEGIN

lock/update BudgetScope
load CLAIMED reservation
load/verify referenced existing Host cost record

require:
  cost_record_ref belongs to the same execution/attempt correlation
  cost currency == scope currency

scope.reserved_total -= reserved_amount
scope.committed_total += actual_cost

reservation.cost_record_ref = authoritative Host cost record ref
reservation.reconciled_at = now
increment versions

COMMIT
```

The reservation remains `CLAIMED`; `reconciled_at != null` marks that the authorization hold has been converted to committed budget consumption.

This avoids introducing a fifth state beyond the approved C04 state machine.

If actual cost is greater than the reservation:

```text
record the real actual cost
allow committed_total to exceed the limit
deny later reservations until policy/limit changes
```

Never falsify or clamp actual cost to preserve the budget.

If a provider attempt is conclusively known to have incurred zero cost, reconciliation may use the authoritative zero-cost Host record and free the full reserved amount.

---

## 10. Restart/recovery

Both scope and reservation state are durable DB state.

After restart:

```text
ACTIVE + not expired
→ still held

ACTIVE + expired
→ released only by transactional expiration

CLAIMED + unreconciled
→ remains held
→ never auto-resubmit solely because of budget state

CLAIMED + reconciled_at
→ already converted to committed_total
```

Budget recovery MUST NOT infer remote submission identity.

H1 remains separate.

---

## 11. Required persistence

This extension requires durable Host DB state.

Approved amendment will therefore authorize **one bounded Alembic migration family** creating:

```text
budget_scopes
budget_reservations
```

No R2-specific parallel database is introduced.

### `budget_scopes`

Conceptual columns:

```text
budget_scope_ref        primary key
currency                non-null
authorized_limit        numeric, non-negative
reserved_total          numeric, non-negative, default 0
committed_total         numeric, non-negative, default 0
version                 integer, non-negative
created_at              timezone-aware timestamp
updated_at              timezone-aware timestamp
```

### `budget_reservations`

Conceptual columns:

```text
reservation_ref         primary key
budget_scope_ref        foreign key / indexed
execution_decision_ref  unique / indexed
reserved_amount         numeric, positive
currency                non-null
state                   non-null
created_at              timezone-aware timestamp
expires_at              nullable timezone-aware timestamp
claimed_at              nullable timezone-aware timestamp
released_at             nullable timezone-aware timestamp
reconciled_at            nullable timezone-aware timestamp
cost_record_ref          nullable / indexed
version                  integer, non-negative
provenance_json          JSON-compatible
```

DB constraints must reject invalid negative totals/amounts and invalid state strings.

No migration may alter existing usage/cost semantics.

---

## 12. Repository placement

The implementation plan should follow existing Host patterns and use these bounded responsibilities:

```text
lib/db/models/budget_reservation.py
    BudgetScopeModel
    BudgetReservationModel

lib/db/repositories/budget_reservation_repo.py
    BudgetReservationRepository

lib/budget_reservation.py
    typed Host-facing service/domain values

server/services/budget_reservation_service.py
    async orchestration over repository + existing usage/cost verification

r2/production/budget_port.py
    narrow R2-facing port/adaptor only; no storage ownership
```

Existing authoritative cost path remains:

```text
lib/db/repositories/usage_repo
server/services/cost_estimation.py
```

Existing queue/runtime remains:

```text
lib/generation_queue.py
server/services/generation_tasks.py
```

The implementation plan must re-read exact local symbols before changing these files. It must not rename/restructure existing subsystems merely to fit this amendment.

---

## 13. Submission boundary integration

For M4 paid tasks, `budget_reservation_ref` travels as execution metadata to the Host.

Before the first paid provider submission:

```text
Host task execution
→ verify current immutable ExecutionDecision correlation
→ BudgetReservationService.claim_or_revalidate(...)
→ only on success cross provider submit boundary
```

Existing tests already identify a reference-video submit/checkpoint boundary. The M4 plan must choose the narrowest equivalent real seam during Task 0 and keep H1's submission-identity concerns separate.

No change is required for legacy Host tasks that do not carry an M4 budget reservation.

---

## 14. Admission integration

Generation Admission flow becomes:

```text
Gate 1 READY
→ MethodDecision
→ CapabilityResolution
→ PromptPlan
→ approval/policy/availability checks
→ Host budget reserve
→ ADMITTED
→ immutable ExecutionDecision includes budget_reservation_ref
```

If reserve fails:

```text
GenerationAdmission = DENIED_BUDGET
ExecutionDecision = absent
provider submission = zero
```

Reservation must be created before constructing the final admitted `ExecutionDecision` reference graph, or the two must be bound in one deterministic service sequence so no admitted ED can exist without its required reservation.

---

## 15. Failure semantics

Required mappings:

```text
insufficient available budget
→ DENIED_BUDGET / NOT_RETRYABLE until budget changes

reservation expired before claim
→ DENIED_BUDGET / NEW_EXECUTION_DECISION_REQUIRED as policy dictates

reservation missing/corrupted
→ INTEGRITY/CONTRACT failure
→ fail closed

DB serialization conflict/transient DB lock
→ recoverable Host execution/admission failure
→ bounded retry may be allowed before any provider side effect

claimed reservation + ambiguous provider timeout
→ do NOT release automatically
→ preserve attempt history
```

---

## 16. Observability

Every reservation operation emits a non-authoritative correlated event:

```text
budget.scope.created
budget.reservation.active
budget.reservation.claimed
budget.reservation.released
budget.reservation.expired
budget.reservation.reconciled
budget.reservation.denied
```

Required correlation:

```text
budget_scope_ref
reservation_ref
execution_decision_ref
attempt_ref when known
cost_record_ref when reconciled
trace_id/span_id when present
```

Metric dimensions must not include high-cardinality refs.

---

## 17. Test strategy

### Contract/unit

Prove:

```text
invalid state transitions rejected
negative amounts rejected
execution_decision_ref uniqueness
release only from ACTIVE
expire only from ACTIVE
CLAIMED never auto-released
reconciled reservation references an authoritative Host cost record
```

### Repository concurrency

Required real-DB tests:

```text
two concurrent reservations cannot both spend the same remaining budget
reserve + release restores availability
reserve + claim retains hold
reconcile converts reserved_total to committed_total
restart/reopen preserves states
expired ACTIVE reservation cannot be claimed
```

At least PostgreSQL integration evidence is required for the production DB path.

SQLite regression must preserve supported local/test semantics.

### Submission integration

Controlled provider double:

```text
claim succeeds → submission_count == 1
claim denied/expired → submission_count == 0
pre-submit cancellation → release
post-claim timeout → no auto-release
```

### Existing frozen regressions

The extension must not change the frozen M1/M2/M3/Host results except for explicitly approved new tests.

---

## 18. Architecture fitness additions

Extend existing `import-linter` / AST checks to reject:

```text
r2.* importing DB models/repositories directly
PromptCompiler importing budget repository/service
MethodRouter importing provider/cost runtime modules
budget reservation code writing Usage cost truth directly
new parallel queue/runtime
new parallel artifact registry
M5 Canon/Narrative imports
```

No new architecture-audit dependency is required.

---

## 19. Migration and rollback rules

This approved amendment explicitly authorizes the bounded DB migration described in section 11.

Migration rules:

```text
additive only
no destructive rewrite of existing usage/task tables
downgrade drops only the two new budget tables after FK-safe order
migration tests required
SQLite + PostgreSQL compatibility required by repository baseline
```

Rollback of application code does not falsify provider usage/cost records.

If budget tables exist but code is rolled back, they remain inert until migration downgrade is explicitly performed.

---

## 20. Acceptance criteria for this amendment

The C04 blocker is closed only when:

```text
1. durable BudgetScope exists
2. durable BudgetReservation exists
3. concurrent reserve is atomic
4. hard-budget paid admission cannot ADMIT without ACTIVE reservation
5. immediate pre-submit claim/revalidation is enforced
6. denied/expired claim produces zero provider submissions
7. pre-submit release is proven
8. CLAIMED ambiguous attempts are never silently released
9. reconciliation points to existing Host cost evidence
10. restart preserves reservation truth
11. no second cost ledger exists
12. no process-local mutex is budget authority
13. H1 remains OPEN
14. architecture audit = 0 blocking violations
15. required regressions pass
```

---

## 21. Approved design decision

Approval of this amendment grants explicit approval for:

```text
bounded Host runtime change for C04
new Host-owned budget authorization subsystem
one additive DB migration family:
  budget_scopes
  budget_reservations
narrow M4 integration hooks
```

It does NOT authorize implementation yet; implementation still requires approved implementation plans.

Approved sequencing:

```text
1. C04 Host Budget Reservation Implementation Plan
2. R2-M4 Production Intelligence Implementation Plan
3. self-review of both plans
4. Human approval
5. only then TDD implementation
```

---

## 22. Research basis

The concurrency design uses database transaction serialization rather than process-local locking.

- SQLAlchemy 2.0 supports `SELECT ... FOR UPDATE` / `with_for_update()` for row-locking capable databases.
- PostgreSQL row locks acquired with `FOR UPDATE` block competing writers/lockers on the same row until transaction end.
- SQLite serializes writes and provides transactional atomicity; repository tests must still prove the exact implementation's behavior under concurrent writers.

Primary references:

- https://docs.sqlalchemy.org/en/20/core/selectable.html
- https://www.postgresql.org/docs/17/explicit-locking.html
- https://sqlite.org/isolation.html
- https://www.sqlite.org/transactional.html
