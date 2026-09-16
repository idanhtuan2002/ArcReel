# R2-M7A Execution Identity and Idempotency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close H1-H2 by binding every paid asynchronous submission to durable,
fenced and recoverable execution evidence.

**Architecture:** Command receipt and task commit first; an immutable attempt is
then persisted before network I/O. Worker commands, provider observations and
operator resolutions use three separate write authorities, while every mutation
appends a durable project event in the same PostgreSQL transaction.

**Tech Stack:** Python 3.12+, Pydantic v2, SQLAlchemy async, Alembic, PostgreSQL
18, pytest, ruff, basedpyright and Codebase Memory.

**Spec:** `docs/superpowers/specs/2026-09-12-r2-m7-host-production-hardening-design.md`

## Global Constraints

- Read the research, ADR, spec and umbrella M7 plan before this packet.
- Execute umbrella Tasks 0-8 only. Start from accepted clean M6 at Alembic head
  `6c7c4a0e0002`; stop with `M7_PREREQUISITE_NOT_ACCEPTED` otherwise.
- Migration `7a7c4a0e0001` creates attempts, observations, operator resolutions,
  command receipts and project events together.
- No paid route bypasses the attempt service; no webhook receiver is introduced.
- `NEEDS_OPERATOR` is non-terminal and only an exact operator receipt can leave it.
- Stop at a clean M7-A evidence HEAD for Codex review; do not start M7-B.

---

### Task A0: Freeze lineage and complete migration graph

**Files:** `scripts/r2/verify_m7_scope.py`, its unit test, and
`docs/r2/evidence/R2_M7_BASELINE.json` only.

**Interfaces:** Produce `verify_m7_scope(repo, baseline) -> list[str]`, the digest
of every ordered `(revision, down_revision)` pair and hashes of the research,
ADR, spec, umbrella plan and all five execution packets.

- [ ] Add failing fixtures for dirty state, wrong SHA/ancestor, missing M6
  acceptance, changed document/seam hash, altered revision edge and multiple head.
- [ ] Run `uv run pytest tests/unit/scripts/r2/test_verify_m7_scope.py -q`;
  expected RED is an import failure.
- [ ] Implement exact checks and emit `M7_PREREQUISITE_NOT_ACCEPTED` with exit 2
  before any implementation path is created.
- [ ] Run the focused test, verifier and `git diff --check`; expected GREEN is
  zero errors at the exact accepted base.
- [ ] Commit `test(r2): freeze M7 accepted baseline` and stage only A0 files.

### Task A1: Define contracts and transition fold

**Files:** `r2/contracts/host_hardening.py`, `r2/contracts/__init__.py`,
`r2/host_hardening/{__init__,transitions,ports}.py` and their unit tests.

**Interfaces:** Produce all spec section-4 types including incoming/persisted
observations and `AttemptIntegrityIncident`; `fold_observation`,
`transition_worker`, `apply_provider_observation` and
`resolve_operator_review` use the exact signatures in the spec.

- [ ] Write table-driven failures for all legal/illegal edges, direct
  unknown-to-terminal facts, both NOT_FOUND policies, conflicting terminal facts,
  duplicate observation, operator action/resolved-state compatibility, terminal
  incident closure without state replacement and opaque-ID/hash validation.
- [ ] Run `uv run pytest tests/unit/r2/contracts/test_host_hardening.py tests/unit/r2/host_hardening/test_transitions.py -q`; expected RED is missing modules.
- [ ] Implement frozen extra-forbid contracts, canonical hashes and a pure fold;
  timestamp or UUID order must never choose between conflicting terminal facts.
- [ ] Rerun focused tests and `uv run basedpyright r2/contracts r2/host_hardening`;
  expected GREEN includes every transition row.
- [ ] Commit `feat(r2): define hardened execution semantics`.

### Task A2: Add the M7-A persistence boundary

**Files:** `lib/db/models/host_hardening.py`, model exports,
`alembic/versions/7a7c4a0e0001_add_execution_attempts.py`, migration/model tests.

**Interfaces:** Create `execution_attempts`, `provider_observations`,
`attempt_integrity_incidents`, `operator_resolution_receipts`, `command_receipts`
and `project_events` with
`down_revision = "6c7c4a0e0002"`.

- [ ] Write migration failures for unique scoped attempt/token/job/command/event
  keys, received sequence, lease token, timestamps and terminal constraints.
- [ ] Run the migration/model tests; expected RED is missing revision/model.
- [ ] Implement reversible SQLite-compatible mechanics and PostgreSQL-authoritative
  JSONB/constraints with one linear head.
- [ ] Run focused SQLite and real-PostgreSQL migration gates; expected GREEN is
  exact upgrade/downgrade and one head.
- [ ] Commit `feat(db): add M7 execution and event evidence`.

### Task A3: Implement scoped repository and lease-token fencing

**Files:** `lib/db/repositories/host_hardening.py` and repository integration tests.

**Interfaces:** Implement spec `ExecutionAttemptRepository`; `acquire_lease`
increments a token, worker updates compare owner/token/expiry/version, observation
and operator writes use their own evidence authority.

- [ ] Write failing PostgreSQL tests for stale owner, reacquired same owner with
  old token, expired lease, concurrent CAS, provider fact while worker lease is
  dead, exact retry and foreign-scope access.
- [ ] Run the repository test; expected RED is a missing repository.
- [ ] Implement short READ COMMITTED operations. Each evidence/state/event group
  commits together or writes nothing.
- [ ] Rerun focused/concurrency tests; expected GREEN is one CAS winner and no
  partial evidence.
- [ ] Commit `feat(db): fence execution attempt mutations`.

### Task A4: Qualify provider capabilities fail-closed

**Files:** `r2/host_hardening/provider_capabilities.py`, registry/schema,
unqualified fixture and unit tests.

**Interfaces:** Produce `load_capability_profile(ref)` and
`require_enabled_capability(ref, release_mode)`.

- [ ] Write failures for token scope/value mismatch, non-authoritative NOT_FOUND,
  missing settling window, `supports_webhook=true`, expired evidence and enabled
  unqualified route.
- [ ] Run the focused test; expected RED is a missing loader.
- [ ] Implement schema/digest verification and seed only unqualified profiles.
- [ ] Rerun tests/schema check; expected GREEN is fail-closed for every unproved
  capability.
- [ ] Commit `feat(r2): register qualified provider capabilities`.

### Task A5: Make command and task creation idempotent

**Files:** existing task repository, generation queue, generate router and
`tests/integration/server/routers/test_generation_command_idempotency.py`.

**Interfaces:** Actor-scoped `command_id` returns the exact original task receipt;
implement exact `CommandReceiptRepository.get_exact` and `add`; receipt result
digest uses the spec's version-1 canonical envelope.

- [ ] Write concurrent duplicate, restart replay and same-key/different-digest
  failures.
- [ ] Run the focused router test; expected RED is duplicate tasks or ignored key.
- [ ] Stage task and immutable receipt through repositories sharing one session
  and transaction; correlate later attempts through task ID without mutating the
  receipt.
- [ ] Run queue/batch/router regressions; expected GREEN is one task/receipt.
- [ ] Commit `feat(host): make generation commands idempotent`.

### Task A6: Submit and reconcile through one attempt service

**Files:** `r2/host_hardening/execution.py`, backend execution adapter,
`server/services/execution_attempts.py`, backend base/checkpoint seams and tests.

**Interfaces:** Implement exact `plan_and_submit` and `reconcile` signatures;
adapters return observations and never persist state.

- [ ] Write failures for definite pre-send error, ambiguous timeout, native-token
  replay, lookup zero/one/many, both NOT_FOUND policies and mode NONE.
- [ ] Run focused tests; expected RED is missing service/adapter.
- [ ] Persist attempt, acquire fence, submit once and ingest the
  returned fact. Unknown goes through qualified lookup or operator pause.
- [ ] Run backend/checkpoint/resume regressions; expected GREEN preserves legacy
  success results and never blind-resubmits.
- [ ] Commit `feat(host): bind provider submit to durable attempt`.

### Task A7: Bind all routes and terminal effects

**Files:** graph-discovered async backends, generation worker/tasks, usage
repository, scope verifier, boundary/integration tests.

**Interfaces:** Every paid async route enters A6; execution ID deduplicates
terminal result, candidate and authoritative usage finalization.

- [ ] Refresh graph traces and coverage, freeze route inventory, then add failures
  for direct submit, new unlisted route, changed default after acceptance and
  duplicate terminal/usage ingestion.
- [ ] Run architecture/integration selection; expected RED includes
  `M7_SUBMIT_ROUTE_UNBOUND`.
- [ ] Route the inventory through A6 and retain legacy job columns as projections.
- [ ] Run all affected provider/worker/queue/checkpoint/usage suites; expected
  GREEN is one task, attempt, submit, result and usage record.
- [ ] Commit `refactor(host): enforce attempt-bound generation effects`.

### Task A8: Produce M7-A acceptance evidence

**Files:** `docs/r2/evidence/R2_M7_A_IDENTITY_IDEMPOTENCY.json`.

- [ ] Run H1/H2, PostgreSQL concurrency, provider regressions, scope verifier,
  static gates and test audit on the final clean candidate HEAD.
- [ ] Record SHA/parent, migration-graph digest, graph generation/coverage, route
  inventory, commands/exits/counts and evidence hashes.
- [ ] Set only `EXECUTION_RECOVERY_VERIFIED` or `REJECTED`, commit accepted
  evidence as `docs(r2): record M7-A identity acceptance`, and stop for Codex.
