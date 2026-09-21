# R2-M7C Poll/Cancel/Download Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**STATUS 2026-09-21: D1-D5 all complete.** The sponsor explicitly lifted the
"do not touch live worker startup" constraint below (`git log`: `8a70ebf7`
through `76e68479`). What actually closed H5, in the end, was *not* the
`ACCEPTED`/`RUNNING` poller this plan originally scoped for D3 -- see
`docs/research/2026-09-20-r2-m7c-poll-download-cancel-design.md` §6: mirroring
every task-finalization outcome into `execution_attempts`
(`GenerationQueue.mark_task_succeeded/failed/cancelled`, `bfa4770d`) makes that
table truthful within a bounded number of restarts without touching any
backend at all, since the legacy orphan handler (ADR 0007) already makes
every real recovery decision and just never told `execution_attempts` about
it. D4 wires `reconcile_expired`/`realize_pending_cancels` into a live
periodic scan (`41019f5a`); D5 proves the whole thing survives a real SIGKILL,
not a simulated one (`76e68479`). Read §6 of the design doc before touching
this area again -- the original D3 "poll/download recovery" framing below is
historical context for how the investigation got here, not the final design.

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

### Task D1: Add the cancel-intent write authority -- DONE (`8a70ebf7`)

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

- [x] Write failing tests: reject from every state except `ACCEPTED`/`RUNNING`;
  exact replay of the same `command_id` is a no-op returning the same result,
  never a second transition; two different `command_id`s racing for the same
  attempt have exactly one winner (real PostgreSQL concurrent test, same
  pattern as `test_concurrent_promotion_has_exactly_one_winner`); no lease is
  required (a `RUNNING` attempt with no lease at all still accepts the cancel).
- [x] Run focused tests; expected RED is the missing method.
- [x] Implement `request_cancel`. It writes intent only -- it must not call
  any adapter or provider; that is Task D3's job when the poller later
  observes `CANCEL_REQUESTED` on a dead-lease attempt (matches spec §4.1:
  "cancel ghi intent trước, gọi provider sau").
- [x] Run the full repository test file plus `tests/unit/r2/host_hardening/`;
  expected GREEN.
- [x] Run the file through real PostgreSQL (`DATABASE_URL=postgresql+asyncpg://...`
  Docker container, `-m "uses_db and not sqlite_only"`), matching the M7-B/M7-C
  precedent for anything with a concurrency claim.
- [x] Full static/test gates (ruff, basedpyright, lint-imports, deptry,
  `scripts/audit_tests.py --check`, full pytest).
- [x] Commit `feat(r2): add the cancel-intent write authority`.

### Task D2: Build the route-to-adapter registry (structural proof, one real backend) -- translation layer DONE (`b53da35a`), dispatch deferred to D3

**Files:** new module (suggest `r2/host_hardening/adapter_registry.py`), one
real video backend's translation layer (Kling -- its submit route now
disambiguates by subpath, `cecd2cff`), tests.

**Interfaces:** `resolve_backend_execution_functions(route: ProviderRouteSnapshot)
-> BackendExecutionFunctions`, keyed by `(route.provider_id, route.adapter_version)`
matching the same key `route_inventory.py::require_submit_route` already uses
for submit. This directly answers the `NotImplementedError` comment left at
`r2/host_hardening/host_submit.py:112` ("polling is owned by the backend
adapter registered for this route").

**Research completed 2026-09-21 -- findings that shape the implementation:**

- **The registry must be async and resolver-dependent, not a pure lookup.**
  Backends are built by `lib/backend_assembly/assembler.py::assemble_backend`
  (`provider_id`, `media_type`, `model_id`, `resolver`) which loads credentials
  from current config. Credentials *should* be current (secrets rotate); only
  the route *identity* is pinned. So the registry signature needs a resolver
  (or a small port wrapping it), not just the route.
- **`assemble_backend` cannot pin `submitted_base_url`.** It builds base_url
  from current config with no override parameter. Built-in backends also do
  **not** read `VideoGenerationRequest.submitted_base_url` (only
  `lib/custom_provider/declarative_backend.py:332` honors it: `request.submitted_base_url
  or self._base_url`). Pinning the submitted base URL therefore needs either an
  explicit `base_url=` at construction (every built-in backend constructor
  already accepts one, e.g. `KlingVideoBackend(..., base_url=...)`, so prefer
  `lib/video_backends/registry.py::create_backend` with an explicit
  `base_url=route.submitted_base_url`) or a new override parameter on
  `assemble_backend`. Do not mutate a constructed backend's private `_base_url`.
- **Wrap the single-shot poll, not the poll-until-terminal loop.** `PollFn` is
  one call -> one `ProviderObservation`; the caller owns the loop. Kling's
  `_poll_until_terminal` (`lib/kling_backend_base.py:160`) loops *and*
  `KlingVideoBackend._poll_and_build` also downloads in the same call. The right
  seam is `KlingBackendBase._poll_query(client, f"videos/{subpath}/{task_id}")`
  -- one GET, raw dict -- translated via the existing
  `lib/kling_shared.py` predicates (`is_kling_task_terminal`,
  `kling_task_status`, `kling_task_failure_reason`) into a `ProviderObservation`.
  Do not re-implement those predicates.
- **Kling has no provider-side cancel.** Confirmed in code (no cancel endpoint
  anywhere in `lib/kling_backend_base.py` / `lib/video_backends/kling.py`) and
  in its registry profile (`supports_cancel: false`). Leave `cancel=None`.
- **`generate_audio` is not recoverable from the attempt.** Kling's legacy
  resume path needs it for correct pricing and reads it from its own encoded
  legacy job id (`subpath:task_id:audio`, `_encode_job_id`), but the
  host-hardening attempt stores only the raw `task_id`
  (`accepted_submit_receipt(task_id, provider_job_id=task_id)`). Task D3's ledger
  finalization must therefore source it from the legacy `tasks` row for the same
  `task_id`, not from `AttemptSnapshot`. Decide in D3 whether that bridge is
  acceptable or whether the attempt should carry it.

**Prerequisite found and fixed while researching (`cecd2cff`):** every Kling
submit recorded the same `endpoint_id` `"videos.create"` even though Kling
polls three different URLs by request shape, so the persisted route could not
say which URL to poll. `endpoint_id` now derives from the real endpoint path
and the inventory registers the three families. Agnes/OpenAI poll one fixed
endpoint regardless of request shape, so their single identity stays correct.

**Scope correction:** a dispatch registry with one entry and no caller is
speculative generality. The translation layer D3 actually needs is built here;
dispatch arrives with D3, its first real consumer, which will also know whether
it needs the resolver-dependent construction seam described above.

- [x] Write failing tests: the wrapped poll produces one `ProviderObservation`
  per call for every Kling task status; a 404 reports `NOT_FOUND` rather than
  raising; a hard error body without a failed status is still `FAILED`; an
  attempt with no provider job id cannot be polled; a backend configured for a
  drifted domain still queries the submitted one on the accepted subpath.
- [x] Run focused tests; expected RED is the missing wrapper.
- [x] Implement `KlingVideoBackend.poll_attempt` (`b53da35a`), wrapping the
  single-shot `_poll_query` (not the poll-until-terminal-and-download loop) and
  reusing `lib/kling_shared.py`'s status predicates. `_poll_query` gained an
  optional `base_url` override so the query goes to the submitted domain.
  No cancel wrapper: Kling has no provider-side cancel (`supports_cancel: false`).
- [x] Run focused + `tests/integration/lib/video_backends/`; GREEN (83 passed).
- [x] Full static/test gates (14085 passed).
- [x] Commit `feat(r2): add Kling's exact-route attempt poll`.
- [ ] Deferred to D3: the dispatch seam (`route -> BackendExecutionFunctions`),
  including how the backend instance is constructed with a pinned
  `submitted_base_url` and current credentials.

### Task D3: Build the recovery poller -- SCOPE CUT to cancel-intent realization only

**Research completed 2026-09-21 -- this changes D3 from what was originally
planned:**

- **`ACCEPTED`/`RUNNING` poll/download recovery is not safely buildable yet.**
  Confirmed by grep: nothing renews or even touches `execution_attempts`'
  lease fields between the `apply_provider_observation` call that lands
  `ACCEPTED` and any later state change -- `plan_and_submit`'s fence is never
  renewed, and no heartbeat exists (`lib.generation_queue`'s
  `acquire_or_renew_lease` is the *legacy* `tasks`-table lease, a separate
  mechanism). So every `ACCEPTED`/`RUNNING` attempt's lease looks "expired" to
  `list_lease_expired`-style querying almost immediately, including ones a
  live worker is legitimately still handling via the untouched legacy
  `generate`/`resume_video` path. A scanner keyed on lease expiry cannot tell
  "orphaned" from "alive and running fine" for these two states without the
  happy path first renewing a live lease while it works -- which is exactly
  the happy-path migration (option (a)) the original M7 research rejected.
  **This is blocked on a real architecture decision (how the happy path would
  renew a lease without becoming a full migration), not an implementation
  detail** -- do not attempt it by reusing `list_lease_expired` on these states
  as originally suggested here; that would misfire constantly.
- **No backend supports provider-side cancel.** Checked
  `r2/provider_capabilities/registry.json`: `supports_cancel: false` on all 11
  profiles. A poller that calls `adapter.cancel()` has zero real destinations
  to prove itself against today; every real call would raise
  `BackendCapabilityUnsupportedError` immediately. It is still worth building
  (fakes prove the mechanism, and Task D1's `request_cancel` already writes
  `CANCEL_REQUESTED` rows that nothing currently ever revisits -- see the
  `16abd4d6` fix this same research produced), but do not expect or claim any
  real end-to-end cancel proof from it.
- **Found and fixed in the course of this research (`16abd4d6`):**
  `reconcile_expired`'s `RECOVERABLE_EXPIRED_STATES` used to include
  `CANCEL_REQUESTED -> CANCEL_OUTCOME_UNKNOWN`, written for a worker that
  `transition_worker`'d into `CANCEL_REQUESTED` under its own live lease and
  died before calling the provider. That scenario has zero production callers
  (`transition_worker` is never invoked with that target) -- the only real
  writer is D1's unfenced `request_cancel`, whose lease is stale by
  construction. Left in place, the first scan after any cancel request would
  have folded it to `CANCEL_OUTCOME_UNKNOWN` (then `NEEDS_OPERATOR` for a
  `NONE`-idempotency provider) without ever attempting the provider call.
  Removed from the map before this task began.

**Files:** `lib/db/repositories/host_hardening.py` (new
`list_pending_cancels`), `r2/host_hardening/ports.py`,
`r2/host_hardening/execution.py` (new `realize_pending_cancels` on
`ExecutionAttemptServiceImpl`), tests.

**Interfaces:** `ExecutionAttemptRepository.list_pending_cancels(*, limit=100)
-> list[tuple[str, str, AttemptSnapshot]]` -- every `CANCEL_REQUESTED` attempt,
unscoped, **no lease-liveness filter** (unlike `list_lease_expired`: nothing
ever holds a live lease on this state under the current design, so every row
is immediately realizable, not just the "expired" ones).
`ExecutionAttemptServiceImpl.realize_pending_cancels(*, limit=100) ->
list[ReconcileResult]`: for each candidate, acquire a fresh fence, call
`adapter.cancel(leased)`; `BackendCapabilityUnsupportedError` releases the
fence and leaves the attempt `CANCEL_REQUESTED` (never silently `CANCELLED`);
any other exception transitions to `CANCEL_OUTCOME_UNKNOWN` and hands off to
the existing `reconcile()` path (mirrors `plan_and_submit`'s
ambiguous-vs-definite exception split, reusing the state that already exists
for "maybe reached the provider" rather than inventing a new one); a clean
`ProviderObservation` applies via `apply_provider_observation` as usual.

**Extra finding while implementing:** the fence needed `acquire_lease`'s new
`force=True` (`lib/db/repositories/host_hardening.py`) -- `request_cancel`
never touches the lease, so a fresh, realistic cancel request (users cancel
within minutes of submitting) can land while the submission-phase lease's
300s TTL has not yet elapsed, even though nothing is using it. Without
`force`, that fencing call would fail and silently defer a legitimate cancel
for no correctness reason. `force` skips only the ownership/liveness OR-clause
-- the `state_version` CAS underneath still gives two racing callers exactly
one winner (proven against real PostgreSQL). Also had to add `force: bool =
False` to the fake `_FakeRepository.acquire_lease` in
`tests/unit/r2/host_hardening/test_execution_service.py` to keep it matching
the `ExecutionAttemptRepository` Protocol.

- [x] Write failing tests (fakes only -- no real backend has anything to
  prove): a fake adapter whose `cancel` raises `BackendCapabilityUnsupportedError`
  leaves the attempt `CANCEL_REQUESTED` with the fence released; a fake adapter
  whose `cancel` raises any other exception moves it to `CANCEL_OUTCOME_UNKNOWN`
  and reconciles to `NEEDS_OPERATOR`; a fake adapter whose `cancel` returns a
  `CANCELLED` observation lands the attempt `CANCELLED`; two concurrent calls
  to `realize_pending_cancels` racing the same attempt have exactly one winner
  (real PostgreSQL); an `ACCEPTED` attempt with no `CANCEL_REQUESTED` sibling
  is never touched. Also added at the repository level: `acquire_lease` with
  `force=True` seizes a live lease while the `state_version` CAS still rejects
  a stale version; `list_pending_cancels` finds a `CANCEL_REQUESTED` row
  regardless of lease state and excludes every other state.
- [x] Run focused tests; expected RED is the missing method -- confirmed, then
  a second RED round when the naive fence (no `force`) rejected a
  still-nominally-live submission-phase lease in the success/ambiguous tests.
- [x] Implement `list_pending_cancels` and `realize_pending_cancels`.
- [x] Run focused + `tests/unit/r2/host_hardening/` +
  `tests/integration/server/services/test_execution_recovery_scan.py`
  (unchanged, still passing); GREEN (14094 passed full suite).
- [x] Run the concurrency race through real PostgreSQL via Docker (39 passed).
- [x] Full static/test gates.
- [x] Commit `feat(r2): realize pending cancel intents against the provider (M7-C Task D3)` (`dffbd892`).
- [x] **Stopped for a sponsor decision.** `ACCEPTED`/`RUNNING` exact-route
  poll/download recovery (the other half of the original H5 ask) remains
  blocked on the happy-path lease-renewal architecture question above.
  What D1-D3 prove: mechanism correctness (state transitions, fencing,
  idempotent replay, concurrent-race safety) against fakes and real
  PostgreSQL CAS. What they do not prove: `realize_pending_cancels` has never
  run against a real backend's real HTTP API (none support cancel today), and
  nothing in D1-D3 has ever been invoked from any live process -- D4 (live
  wiring) and D5 (real SIGKILL tests) remain explicitly blocked pending a
  separate go-ahead, as they were before this task.

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
