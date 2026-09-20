# R2-M7C Poll/Cancel/Download Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remainder of Task C3
(`docs/superpowers/plans/2026-09-12-r2-m7c-restart-event-recovery.md`) --
exact-route poll, download and cancel for an attempt orphaned by a dead
worker -- using the narrow restart-scanner architecture the original M7
research already settled on, not a happy-path migration.

**Architecture:** A recovery-only poller extends the H5 lease scanner
(`reconcile_expired`, committed `df205ddf`) to `ACCEPTED`/`RUNNING`/
`CANCEL_REQUESTED` attempts whose lease is gone. It rebuilds a
`ProviderExecutionAdapter` from nothing but the persisted `ProviderRouteSnapshot`,
never from live config, and hands results to the existing candidate-store and
usage-ledger primitives. The live, non-crashed happy path
(`lib/media_generator.py` + `lib/video_backends/base.py`) is untouched --
every design decision here must justify why it does not need to touch that
path. A cancel-intent write authority is added because none exists today: the
three write authorities in `lib/db/repositories/host_hardening.py`
(worker/provider/operator) have no path for an external cancel request that
does not hold the current worker's lease.

**Tech Stack:** Python/FastAPI/PostgreSQL, pytest, subprocess SIGKILL tests
(Task D5 only).

**Spec:** `docs/superpowers/specs/2026-09-12-r2-m7-host-production-hardening-design.md`
**Design basis:** `docs/research/2026-09-20-r2-m7c-poll-download-cancel-design.md`
(current-state map + why (b) over (a), citing
`docs/research/2026-09-12-r2-m7-host-production-hardening-research.md` §2.4/§4.1
as the pre-existing architecture default) -- read this before starting D2/D3.

## Global Constraints

- Start only from the current M7-C head (`776231ab` at plan-writing time);
  adds no migration -- every table Task D1-D3 need already exists
  (`execution_attempts`, `command_receipts`, `api_calls.execution_id`).
- **Tasks D1-D3 build and test entirely against fakes and real PostgreSQL via
  Docker. They must not modify `server/app.py`'s lifespan,
  `lib/generation_worker.py`, or any live worker startup path.** This mirrors
  the constraint the sponsor set for the just-finished lease scanner
  (`df205ddf`): build and test the mechanism in isolation first.
- **Tasks D4 (wiring the poller into a live process) and D5 (real SIGKILL
  subprocess tests) are explicitly blocked pending a separate, later go-ahead.**
  Do not start them as part of executing D1-D3. Stop and report after D3's
  acceptance evidence instead of proceeding to D4.
- Reuse, do not reinvent: `lib/candidate_store.py::prepare_candidate` for
  download safety, `lib/db/repositories/usage_repo.py::UsageRepository` for
  the `execution_id` -> `api_call_id` reverse lookup and
  `lib/ledger.py`'s existing `resume_success`/`resume_failed` for
  no-double-charge finalization, `CommandReceiptRepository` for cancel-intent
  idempotency. A step that duplicates one of these instead of calling it is a
  design error, not a style preference.
- Every write path added here must commit its attempt row, its own evidence
  row and one `ProjectEvent` in the same transaction, matching the existing
  three authorities' contract (`lib/db/repositories/host_hardening.py`'s
  module docstring).

---

### Task D1: Add the cancel-intent write authority

**Files:** `lib/db/repositories/host_hardening.py`, `r2/host_hardening/ports.py`,
`r2/contracts/host_hardening.py` (if a dedicated receipt shape is needed --
prefer reusing `CommandReceipt` as-is before adding a new type),
`tests/integration/lib/db/repositories/test_execution_attempt_repository.py`.

**Interfaces:** `ExecutionAttemptRepository.request_cancel(*, user_id,
project_name, execution_id, expected_version, command_id, actor_scope) ->
AttemptSnapshot`. CASes `ACCEPTED`/`RUNNING` -> `CANCEL_REQUESTED`. No lease
fence required (matches `apply_provider_observation`/`resolve_operator_review`'s
precedent: intent and fact authorities never consult the worker lease). Dedupe
by `(user_id, project_name, actor_scope, command_id)` through
`CommandReceiptRepository`, reusing the exact pattern at
`lib/db/repositories/task_repo.py:221-334` (check receipt first, insert
attempt-row mutation and receipt in the same flush, catch `IntegrityError` on
the receipt as "someone else's identical command won, replay theirs").

- [ ] Write failing tests: reject from every state except `ACCEPTED`/`RUNNING`;
  exact replay of the same `command_id` is a no-op returning the same result,
  never a second transition; two different `command_id`s racing for the same
  attempt have exactly one winner (real PostgreSQL concurrent test, same
  pattern as `test_concurrent_promotion_has_exactly_one_winner`); no lease is
  required (a `RUNNING` attempt with no lease at all still accepts the cancel).
- [ ] Run focused tests; expected RED is the missing method.
- [ ] Implement `request_cancel`. It writes intent only -- it must not call
  any adapter or provider; that is Task D3's job when the poller later
  observes `CANCEL_REQUESTED` on a dead-lease attempt (matches spec §4.1:
  "cancel ghi intent trước, gọi provider sau").
- [ ] Run the full repository test file plus `tests/unit/r2/host_hardening/`;
  expected GREEN.
- [ ] Run the file through real PostgreSQL (`DATABASE_URL=postgresql+asyncpg://...`
  Docker container, `-m "uses_db and not sqlite_only"`), matching the M7-B/M7-C
  precedent for anything with a concurrency claim.
- [ ] Full static/test gates (ruff, basedpyright, lint-imports, deptry,
  `scripts/audit_tests.py --check`, full pytest).
- [ ] Commit `feat(r2): add the cancel-intent write authority`.

### Task D2: Build the route-to-adapter registry (structural proof, one real backend)

**Files:** new module (suggest `r2/host_hardening/adapter_registry.py`), one
real video backend's translation layer (pick the backend already used in
M7-A's attempt-bound submit tests to minimize new surface --
check `tests/integration/lib/video_backends/test_kling_video_backend.py`'s
fixtures first), tests.

**Interfaces:** `resolve_backend_execution_functions(route: ProviderRouteSnapshot)
-> BackendExecutionFunctions`, keyed by `(route.provider_id, route.adapter_version)`
matching the same key `route_inventory.py::require_submit_route` already uses
for submit. This directly answers the `NotImplementedError` comment left at
`r2/host_hardening/host_submit.py:112` ("polling is owned by the backend
adapter registered for this route").

- [ ] Research first: read the chosen backend's existing internal poll/cancel
  logic (inside its `generate`/`resume_video` implementation) to identify the
  exact function(s) to wrap -- do not write new HTTP polling logic, wrap the
  existing one, per `execution_adapter.py`'s own docstring ("wiring... is
  that translation layer's job, reused as-is rather than duplicated here").
- [ ] Write failing tests: registry resolves the expected `BackendExecutionFunctions`
  for a known route; an unregistered `(provider_id, adapter_version)` pair
  raises a typed error (never silently falls back to a different backend);
  the wrapped `poll` function, given a fake HTTP transport, produces the same
  `ProviderObservation` shape the existing submit-path adapter already
  produces (reuse `tests/fakes.py` fixtures where they exist).
- [ ] Run focused tests; expected RED is the missing registry/wrapper.
- [ ] Implement the registry and the one backend's poll wrapper. Cancel wrapper
  only if that backend has a real provider-side cancel endpoint -- confirm
  from that backend's own existing code before promising one; if it has none,
  leave `cancel=None` and let `BackendCapabilityUnsupportedError` stand
  (already the correct fail-closed behavior).
- [ ] Run focused + `tests/unit/r2/host_hardening/`, `tests/integration/lib/video_backends/`
  for the touched backend; expected GREEN.
- [ ] Full static/test gates.
- [ ] Commit `feat(r2): add a route-to-adapter registry for recovery polling`.

### Task D3: Build the recovery poller (poll, download, cancel handoff)

**Files:** new module (suggest `r2/host_hardening/recovery_poller.py`),
integration tests against real PostgreSQL.

**Interfaces:** `AttemptRecoveryPoller.scan(*, before=None, limit=100) ->
list[ReconcileResult]`, structurally parallel to
`ExecutionAttemptServiceImpl.reconcile_expired` but for
`ACCEPTED`/`RUNNING`/`CANCEL_REQUESTED` (extend
`ExecutionAttemptRepository.list_lease_expired` to accept these states --
already state-generic, no schema change needed).

- [ ] Write failing tests (fakes only, no real network): an `ACCEPTED` attempt
  with a dead lease and a fake adapter returning `RUNNING` is left `RUNNING`
  with a fresh fence and no double-poll; a fake adapter returning `SUCCEEDED`
  triggers a download-and-ingest call (fake `candidate_store.prepare_candidate`)
  and a ledger finalize call (fake `usage_repo`/`ledger`) using the `api_call_id`
  reverse-looked-up from `execution_id`, never a new one; a `CANCEL_REQUESTED`
  attempt with a dead lease calls the adapter's `cancel`, and
  `BackendCapabilityUnsupportedError` from an unsupported backend leaves the
  attempt `CANCEL_REQUESTED` (never silently marks it `CANCELLED`); a download
  failure after a `SUCCEEDED` observation retries the download for the same
  `provider_job_id` on the next scan, never resubmits (spec §7); the fence is
  released before handing off to `reconcile()`-equivalent finalization, exactly
  as `reconcile_expired`'s `release_lease` fix (`df205ddf`) already established
  -- write a test that would have caught that exact bug class here too.
- [ ] Run focused tests; expected RED is the missing poller.
- [ ] Implement, wiring Task D1's `request_cancel` observer path and Task D2's
  registry. No new download-safety or ledger logic -- call
  `candidate_store.prepare_candidate` and `usage_repo`/`ledger` as-is.
- [ ] Run focused + `tests/unit/r2/host_hardening/` +
  `tests/integration/server/services/test_execution_recovery_scan.py`
  (must still pass unchanged); expected GREEN.
- [ ] Run the concurrency-sensitive paths (two scans racing the same orphaned
  attempt) through real PostgreSQL via Docker, same pattern as D1.
- [ ] Full static/test gates.
- [ ] Commit `feat(r2): add the exact-route poll/download/cancel recovery poller`.
- [ ] **Stop here for a sponsor decision before D4.** Report: what D1-D3 prove
  (mechanism correctness against fakes + real PostgreSQL CAS), what they do
  not yet prove (the poller has never run against a real backend's real HTTP
  API, and has never been invoked from any live process).

---

## Blocked pending separate approval -- do not start without it

### Task D4: Wire the recovery poller into a live process

Requires its own scope decision (background task in `server/app.py`'s
lifespan? a separate process? on what interval?) and its own risk review --
this is the same category of decision the sponsor deferred for the lease
scanner and has not yet revisited.

### Task D5: Real SIGKILL subprocess barrier matrix

Only meaningful once D4 exists -- there is nothing to kill mid-poll/mid-download/
mid-cancel until a live process actually polls/downloads/cancels through this
path. Barriers per the original H5 test matrix: before submit, after provider
acceptance, after local acceptance, mid-poll, after download, after cancel
intent; complete the remote job while the application is absent.

### Task D6: Produce updated M7-C acceptance evidence

`docs/r2/evidence/R2_M7_C_RESTART_STREAM_RECOVERY.json`, after D4/D5, per the
original plan's Task C4 format.
