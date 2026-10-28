# M10 A5 Run Closure Implementation Plan

> Execute serially with superpowers:executing-plans and TDD. Spec:
> [2026-10-28-r2-m10-a5-run-closure-design.md](../specs/2026-10-28-r2-m10-a5-run-closure-design.md).

**Goal:** seal re-verified multi-assessor runs and project their validity, fail-closed for unadmitted evidence.

**Constraints:** no A1–A4 contract/digest/error/table change; PostgreSQL is the only authority; tests list
explicit paths (sponsor rule); `/tmp` is tmpfs — use `-o tmp_path_retention_policy=failed`.

### Task 1: Pure closure and validity — `r2/quality/runs.py`

- [ ] RED unit tests: missing slot evidence, duplicate binding, wrong kind/class, mixed subject/profile,
  rule/config mismatch, N-of-M and distinct independence, Human slot refusing MODEL evidence,
  disagreement with/without escalation, INAPPLICABLE only when policy-authorized technical,
  INDETERMINATE, FACTUAL/unadmitted kinds fail closed, recomputed digests, FAILED slots still seal.
- [ ] RED validity tests: precedence INVALIDATED > STALE > SUPERSEDED > EXPIRED > CURRENT.
- [ ] Implement; commit.

### Task 2: Persistence — models, migration, repository

- [ ] RED migration test (singleton head, upgrade/downgrade/upgrade, ORM parity, triggers, JSON ceilings).
- [ ] Implement four tables, `QualityRunRepository` (lock, replay, append human observation, append run,
  CAS head, load observations); repository tests on PostgreSQL; commit.

### Task 3: Services — Human observation and run completion

- [ ] RED PostgreSQL integration: auth failures, missing/foreign grant, unqualified slot, replay/conflict,
  closure over real A4 receipts + Human observation, stale root/dependency, head race both orders,
  validity transitions with historical read preserved.
- [ ] Implement `HumanObservationService` and `QualityRunService`; commit.

### Task 4: Qualification and candidate

- [ ] Affected-domain static gates and related suites (PostgreSQL, zero required skips).
- [ ] One independent read-only review; adjudicate and fix; seal `R2_M10_A5_CANDIDATE.json`; checkpoint.
