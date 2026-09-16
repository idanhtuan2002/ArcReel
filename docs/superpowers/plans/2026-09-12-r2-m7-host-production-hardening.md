# R2-M7 Host Production Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Use `superpowers:test-driven-development` for every behavior change.

**Goal:** Re-earn `RECOVERY_VERIFIED` and produce a reviewable
`PRODUCTION_CANDIDATE` dossier by closing H1-H8 on the existing ArcReel Host
without creating a second runtime or authority.

**Architecture:** Persist one immutable execution-attempt journal before every
paid asynchronous submit, make unknown remote outcomes explicit and reconcile
only through qualified provider capabilities. Prepare immutable candidate media
outside PostgreSQL, then atomically CAS one database master head with promotion,
usage and durable event evidence. Project SSE, backup/restore, telemetry and
upstream qualification consume those durable identities.

**Tech Stack:** Python 3.12+, Pydantic v2, SQLAlchemy async ORM, Alembic,
PostgreSQL 18, FastAPI/SSE, React/TypeScript, OpenTelemetry API/SDK + OTLP,
pytest/pytest-asyncio, Playwright/browser tests, ruff, basedpyright,
import-linter, deptry and pnpm.

**Spec:**
`docs/superpowers/specs/2026-09-12-r2-m7-host-production-hardening-design.md`

**ADR:**
`docs/adr/0078-durable-execution-evidence-and-recoverable-production-boundaries.md`

**Research:**
`docs/research/2026-09-12-r2-m7-host-production-hardening-research.md`

## Global Constraints

- Work only in a new M7 implementation worktree based on the final accepted,
  clean M6 handoff. The required Alembic head is `6c7c4a0e0002`.
- Task 0 must print `M7_PREREQUISITE_NOT_ACCEPTED` and exit 2 before code changes
  if M6 is not accepted, the tree is dirty, its evidence does not bind the exact
  HEAD, the migration head differs, or the ADR/spec/research hashes differ.
- ArcReel queue/task state, provider backends, Artifact Manifest, version
  history, usage accounting, recovery and export remain authoritative. Do not add
  a second queue, workflow engine, artifact registry, cost ledger or master
  selector.
- Every paid asynchronous submit is bound to a persisted `ExecutionAttempt`
  before network I/O. No legacy submit path may bypass the attempt service.
- `provider_job_id` is an observation, not local execution identity. Mutable
  provider defaults, trace IDs, process IDs and worker leases are never replay or
  idempotency identity.
- An ambiguous submit without proved native idempotency or exact lookup is never
  automatically retried. It ends at `NEEDS_OPERATOR` with a stable reason.
- All public reads/writes are scoped by `(user_id, project_name)`. Unknown and
  foreign IDs are indistinguishable. Global uniqueness errors disclose no owner.
- Attempt transitions, master promotion and event append use short
  `READ COMMITTED` transactions, explicit locks/CAS and exact expected versions.
  Automatic whole-command retries are forbidden; exact command replay returns
  the original receipt before stale-version checks.
- Candidate media is immutable after verification. Promotion and garbage
  collection never overwrite or delete current-master bytes.
- SSE and notifications are delivery projections. A durable PostgreSQL event row
  committed with the domain mutation is the replay authority; delivery is at
  least once.
- Tests use public ports and controllable fakes, no sleeps, private-symbol
  monkeypatches or mock-only provider qualification. Process recovery tests use a
  real subprocess boundary and PostgreSQL.
- Each behavior task runs RED, implements the minimum, runs GREEN and affected
  regression, runs `uv run python scripts/audit_tests.py --check` when tests
  change, inspects status, stages only owned paths and commits.
- Each checkpoint stops at a clean HEAD for independent Codex review. Claude Code
  may not cross a pending or rejected checkpoint.
- No task, test, review or commit authorizes live migrations, paid provider calls,
  credential use, infrastructure discovery, worker activation, deployment,
  cleanup, publication or production approval.

---

## Fixed File and Interface Map

| File | Responsibility |
|---|---|
| `r2/contracts/host_hardening.py` | Provider-neutral immutable contracts and enums from the spec |
| `r2/host_hardening/transitions.py` | Pure attempt transition table and monotonic observation fold |
| `r2/host_hardening/ports.py` | Repository, provider, candidate, event and promotion protocols |
| `r2/host_hardening/execution.py` | Attempt planning, submit result classification and reconciliation policy |
| `r2/host_hardening/promotion.py` | Sole new atomic promotion orchestration used by existing Production authority |
| `r2/host_hardening/backup.py` | Backup-set contracts, closure and clean-target verification rules |
| `r2/host_hardening/telemetry.py` | Attribute allowlist, HMAC job references and span-link helpers |
| `lib/db/models/host_hardening.py` | Attempt, observation, receipt, event, candidate, master and promotion ORM rows |
| `lib/db/repositories/host_hardening.py` | PostgreSQL-scoped repositories and unit of work |
| `lib/candidate_store.py` | Same-filesystem immutable candidate prepare/verify/quarantine adapter |
| `lib/video_backends/execution_adapter.py` | Existing backend bridge to the provider execution port |
| `server/services/execution_attempts.py` | Host wiring for submit/poll/cancel/reconcile and compatibility projections |
| `server/services/project_events.py` | Durable replay plus existing live wake-up integration |
| `server/services/backup_sets.py` | Write fence, DB/media inventory and verification orchestration |
| `server/telemetry.py` | OpenTelemetry bootstrap and source-side safe attributes |
| `scripts/r2/verify_m7_scope.py` | Scope, bypass, evidence and maturity verifier |
| `scripts/r2/verify_upstream_candidate.py` | Pinned upstream compatibility report verifier |

The exact public types and method signatures in spec sections 4-8 are normative.
If an accepted-base seam makes one impossible, stop with
`M7_BASE_SEAM_CHANGED`; do not rename or invent a parallel surface.

### Linear migration chain

```text
6c7c4a0e0002
  -> 7a7c4a0e0001  attempts, observations, receipts and project events
  -> 7b7c4a0e0001  candidates, master heads, promotion receipts and backup sets
```

No later task edits a migration frozen by an accepted checkpoint.
Task 0 hashes the complete ordered revision graph. A schema defect discovered
after checkpoint acceptance stops with `M7_ACCEPTED_SCHEMA_CHANGE_REQUIRED`; a
Codex design amendment must assign an additive revision after the then-current
head. Claude Code never edits an accepted migration or invents that revision.

### Execution packets

This document is the milestone dependency map. Claude Code executes one bounded
packet at a time and stops at its checkpoint:

| Checkpoint | Executable packet | Umbrella tasks |
|---|---|---|
| M7-A | `docs/superpowers/plans/2026-09-12-r2-m7a-execution-identity-idempotency.md` | 0-8 |
| M7-B | `docs/superpowers/plans/2026-09-12-r2-m7b-atomic-promotion.md` | 9-12 |
| M7-C | `docs/superpowers/plans/2026-09-12-r2-m7c-restart-event-recovery.md` | 13-16 |
| M7-D | `docs/superpowers/plans/2026-09-12-r2-m7d-backup-observability.md` | 17-19 |
| M7-E | `docs/superpowers/plans/2026-09-12-r2-m7e-production-candidate.md` | 20-22 |

### Stop codes

| Code | Meaning |
|---|---|
| `M7_PREREQUISITE_NOT_ACCEPTED` | M6 lineage, evidence, cleanliness or migration head is invalid |
| `M7_BASE_SEAM_CHANGED` | accepted implementation no longer matches a fixed consumed seam |
| `M7_SUBMIT_ROUTE_UNBOUND` | a paid asynchronous submit bypasses `ExecutionAttempt` |
| `M7_PROVIDER_CAPABILITY_UNQUALIFIED` | an enabled route lacks exact capability evidence |
| `M7_RECOVERY_AMBIGUOUS` | reconciliation found zero/multiple jobs or has no safe lookup |
| `M7_MASTER_DIVERGED` | database master head and compatibility projection disagree |
| `M7_BACKUP_SET_INCOMPLETE` | database/media/release closure cannot be proved |
| `M7_SECRET_EVIDENCE_LEAK` | canary secret appears in log/span/public event evidence |
| `M7_UPSTREAM_INCOMPATIBLE` | an upstream change lacks disposition or fails a required gate |
| `M7_ACCEPTED_SCHEMA_CHANGE_REQUIRED` | an accepted migration needs an additive design amendment |

---

### Task 0: Freeze the accepted starting boundary

**Files:**
- Create: `scripts/r2/verify_m7_scope.py`
- Create: `tests/unit/scripts/r2/test_verify_m7_scope.py`
- Create: `docs/r2/evidence/R2_M7_BASELINE.json`

**Interfaces:**
- Consumes: accepted M6 evidence, Git HEAD/parent, complete Alembic graph and
  hashes of the research, ADR, spec, umbrella plan and all five M7 packets.
- Produces: `verify_m7_scope(repo: Path, baseline: Mapping[str, object]) -> list[str]`
  and a digest of the complete ordered Alembic revision graph.

- [ ] Write tests proving rejection of a dirty tree, wrong ancestry, wrong
  migration head, missing M6 acceptance, mismatched document hash and a source
  change in every verified legacy seam.
- [ ] Run `uv run pytest tests/unit/scripts/r2/test_verify_m7_scope.py -q`.
  Expected RED: verifier import fails.
- [ ] Implement the verifier and a baseline fixture that names every file in the
  fixed interface map plus existing task/backend/resume/promotion/SSE/usage seams.
  Task 0 may create or modify only the three paths in its Files block.
- [ ] Run the focused test, `uv run python scripts/r2/verify_m7_scope.py --check`
  and `git diff --check`. Expected GREEN: all pass at the exact accepted base.
- [ ] Commit only Task 0 paths with `test(r2): freeze M7 accepted baseline`.

### Task 1: Add provider-neutral hardening contracts

**Files:**
- Create: `r2/contracts/host_hardening.py`
- Modify: `r2/contracts/__init__.py`
- Create: `tests/unit/r2/contracts/test_host_hardening.py`

**Interfaces:**
- Consumes: `ProviderRequest`, repository ID/timestamp/hash conventions.
- Produces: every enum/dataclass from spec section 4, including
  `ProviderTokenScope`, `ProviderNotFoundSemantics`, `AttemptLeaseFence`,
  `OperatorResolutionReceipt`, `ProviderObservation` and
  `PersistedProviderObservation`.

- [ ] Write construction, extra-field rejection, timezone, digest and enum
  round-trip tests. Include operator action/resolved-state compatibility,
  provider-sequence qualification and a counterexample proving trace/lease
  fields do not enter request digest identity.
- [ ] Run `uv run pytest tests/unit/r2/contracts/test_host_hardening.py -q`.
  Expected RED: module import fails.
- [ ] Implement frozen, extra-forbid contracts and canonical digest helpers;
  export only the public names required by the spec.
- [ ] Run focused tests and `uv run basedpyright r2/contracts`. Expected GREEN.
- [ ] Commit with `feat(r2): define host hardening contracts`.

### Task 2: Persist attempts, observations, receipts and project events

**Files:**
- Create: `lib/db/models/host_hardening.py`
- Modify: `lib/db/models/__init__.py`
- Create: `alembic/versions/7a7c4a0e0001_add_execution_attempts.py`
- Create: `tests/integration/lib/db/migrations/test_alembic_execution_attempts.py`
- Create: `tests/unit/lib/db/models/test_host_hardening_models.py`

**Interfaces:**
- Consumes: Task FK/user/project conventions and `6c7c4a0e0002`.
- Produces: ORM tables `execution_attempts`, `provider_observations`,
  `attempt_integrity_incidents`, `operator_resolution_receipts`,
  `command_receipts` and `project_events`;
  migration revision `7a7c4a0e0001`.

- [ ] Write model and upgrade/downgrade tests for unique `(task_id, attempt_no)`,
  scoped client token, scoped provider job ID, `(actor_scope, command_id)`,
  per-attempt `received_seq`, terminal-conflict incident uniqueness, non-null
  route snapshot/digest, increasing lease token, required timestamps, terminal
  timestamp checks and event dedupe key.
- [ ] Run the two test files. Expected RED: model and revision imports fail.
- [ ] Implement models and a reversible migration with
  `down_revision = "6c7c4a0e0002"`; PostgreSQL JSONB is authoritative and the
  SQLite test representation must preserve equivalent validation.
- [ ] Run focused SQLite mechanics plus the repository's real-PostgreSQL migration
  target selected by `CONTRIBUTING.md`. Expected GREEN with one linear head.
- [ ] Commit with `feat(db): add durable execution attempt evidence`.

### Task 3: Implement the pure attempt state machine and scoped repository

**Files:**
- Create: `r2/host_hardening/__init__.py`
- Create: `r2/host_hardening/transitions.py`
- Create: `r2/host_hardening/ports.py`
- Create: `lib/db/repositories/host_hardening.py`
- Create: `tests/unit/r2/host_hardening/test_transitions.py`
- Create: `tests/integration/lib/db/repositories/test_execution_attempt_repository.py`

**Interfaces:**
- Consumes: Task 1 contracts and Task 2 rows.
- Produces: `fold_observation(snapshot, observation) -> AttemptSnapshot`,
  `transition_worker(...)`, `apply_provider_observation(...)`,
  `resolve_operator_review(...)` and the remaining exact repository methods.

- [ ] Write table-driven tests for every allowed edge and every forbidden edge,
  terminal monotonicity, direct unknown-to-terminal observation, authoritative
  versus non-authoritative `NOT_FOUND`, equal-time conflicting terminals,
  duplicate observation no-op, operator-resolution edges, terminal incident
  closure without terminal-state replacement, exact retry before stale
  rejection, lease-token fencing and cross-project indistinguishability.
- [ ] Run both test files. Expected RED: transition/repository modules absent.
- [ ] Implement a pure transition fold and short `READ COMMITTED` repository
  operations using expected version in every update. Worker writes require an
  unexpired owner/token fence; provider observations and operator receipts use
  separate authority methods. Evidence, transition and `ProjectEvent` are one
  transaction.
- [ ] Run focused tests including concurrent PostgreSQL CAS. Expected GREEN: one
  winner, no partial observation and no leaked owner.
- [ ] Commit with `feat(r2): add fenced execution attempt state machine`.

### Task 4: Add versioned provider capability profiles

**Files:**
- Create: `r2/host_hardening/provider_capabilities.py`
- Create: `r2/provider_capabilities/registry.json`
- Create: `r2/provider_capabilities/schema.json`
- Create: `tests/unit/r2/host_hardening/test_provider_capabilities.py`
- Create: `tests/fixtures/r2/provider_capabilities/unqualified.json`

**Interfaces:**
- Consumes: `ProviderCapabilityProfile`.
- Produces: `load_capability_profile(ref: str) -> ProviderCapabilityProfile` and
  `require_enabled_capability(ref, release_mode) -> ProviderCapabilityProfile`.

- [ ] Write tests for digest verification, exact provider/API/adapter match,
  unknown fields, token scope/value consistency, `NOT_FOUND` settling semantics,
  mandatory `supports_webhook=false`, expired/missing evidence and rejection of
  `UNQUALIFIED` in production-candidate mode.
- [ ] Run the focused file. Expected RED: loader missing.
- [ ] Implement schema-validated immutable registry loading. Seed only an
  `UNQUALIFIED` fixture; do not claim real provider support from interfaces.
- [ ] Run focused tests and JSON/schema checks. Expected GREEN.
- [ ] Commit with `feat(r2): register provider execution capabilities`.

### Task 5: Make command and task creation idempotent

**Files:**
- Modify: `lib/db/repositories/task_repo.py`
- Modify: `lib/generation_queue.py`
- Modify: `server/routers/generate.py`
- Create: `tests/integration/server/routers/test_generation_command_idempotency.py`

**Interfaces:**
- Consumes: `command_receipts` and existing task deduplication.
- Produces: actor-scoped `command_id`; exact `CommandReceiptRepository.get_exact`
  and `add`; task creation and canonical immutable receipt commit atomically
  before an attempt can be planned.

- [ ] Write concurrent duplicate, restart replay, same-key/different-command-
  digest and canonical result-envelope tests. Assert exact replay returns the
  original task receipt without creating another task.
- [ ] Run focused tests. Expected RED: command ID is ignored.
- [ ] Insert/read the immutable receipt in the task-creation transaction and hash
  exactly the spec's version-1 command result envelope. Attempt correlation later
  follows the task relation; the receipt is never backfilled.
- [ ] Run focused tests plus existing queue/batch/router dedup regressions.
  Expected GREEN: one task and one receipt.
- [ ] Commit with `feat(host): make generation commands idempotent`.

### Task 6: Implement attempt planning, submit classification and adapters

**Files:**
- Create: `r2/host_hardening/execution.py`
- Create: `lib/video_backends/execution_adapter.py`
- Create: `server/services/execution_attempts.py`
- Modify: `lib/video_backends/base.py`
- Modify: `lib/reference_video/execution_checkpoint.py`
- Create: `tests/unit/r2/host_hardening/test_execution_service.py`
- Create: `tests/integration/server/services/test_execution_attempt_service.py`

**Interfaces:**
- Consumes: attempt repository, command receipt, capability registry, existing
  backend submit/poll/cancel functions and `VideoSubmissionCheckpoint`.
- Produces: exact `ExecutionAttemptService.plan_and_submit(...) ->
  AttemptSnapshot` and `reconcile(...) -> ReconcileResult` signatures from the
  spec. Adapters return observations and never mutate attempt state.

- [ ] Write failures for pre-send transport error, ambiguous post-send timeout,
  accepted receipt, native-token replay, exact lookup with zero/one/multiple
  matches, both `NOT_FOUND` semantics and mode `NONE`.
- [ ] Run focused tests. Expected RED: service/adapter absent.
- [ ] Persist `PLANNED`, acquire a token fence, CAS `SUBMITTING`, call the adapter
  once and ingest its observation
  through the repository. Unknown outcome follows qualified reconciliation or
  operator review; no webhook path is introduced.
- [ ] Run focused tests plus existing backend/checkpoint/resume suites. Expected
  GREEN and no changed legacy success payload.
- [ ] Commit with `feat(host): bind provider submit to durable attempt`.

### Task 7: Bind every paid route and make result/usage ingestion idempotent

**Files:**
- Modify: each concrete asynchronous video backend reported by the refreshed
  `ProviderJobIdPersistenceMixin._persist_provider_job_id` inbound trace
- Modify: `server/services/generation_tasks.py`
- Modify: `lib/generation_worker.py`
- Modify: `lib/db/repositories/usage_repo.py`
- Modify: `scripts/r2/verify_m7_scope.py`
- Create: `tests/architecture/test_m7_execution_attempt_boundary.py`
- Create: `tests/integration/lib/test_generation_worker_attempts.py`
- Create: `tests/integration/lib/db/repositories/test_attempt_usage_idempotency.py`

**Interfaces:**
- Consumes: Task 6 service, existing task/backend paths and `api_call_id` usage.
- Produces: exactly one attempt-bound entry for every paid asynchronous route and
  one idempotent result/candidate/usage ingestion per execution.

- [ ] Refresh inbound traces, coverage-check every candidate path and freeze the
  route inventory. Write failures for direct submit, unknown-outcome resubmit,
  default-route mutation, duplicate terminal result and duplicate usage finality.
- [ ] Run focused architecture/integration tests. Expected RED with
  `M7_SUBMIT_ROUTE_UNBOUND` or duplicate evidence.
- [ ] Route every inventoried submit through Task 6 without changing public
  backend results. Make result, candidate and usage ingestion idempotent by exact
  execution/evidence keys; legacy job fields are projection-only.
- [ ] Run all affected backend, worker, queue, checkpoint and usage suites.
  Expected GREEN: one task, attempt, remote submit, candidate and usage record.
- [ ] Commit with `refactor(host): enforce attempt-bound generation effects`.

### Task 8: Freeze and review checkpoint M7-A

**Files:**
- Create: `docs/r2/evidence/R2_M7_A_IDENTITY_IDEMPOTENCY.json`

**Interfaces:**
- Consumes: Tasks 0-7 exact HEAD and test outputs.
- Produces: machine verdict `EXECUTION_RECOVERY_VERIFIED | REJECTED`.

- [ ] Run H1/H2 focused suites, real-PostgreSQL concurrency, all provider backend
  regressions, scope verifier, static gates and test audit.
- [ ] Record exact SHA/parent, clean state, migration head, graph generation and
  coverage, route inventory, commands/exits/test counts and evidence hashes.
- [ ] Stop for independent Codex review. Commit accepted evidence with
  `docs(r2): record M7-A identity acceptance`; do not start Task 9 while pending.

### Task 9: Prepare immutable verified candidate media

**Files:**
- Create: `lib/candidate_store.py`
- Create: `r2/host_hardening/retention.py`
- Create: `tests/unit/lib/test_candidate_store.py`
- Create: `tests/integration/lib/test_candidate_store_faults.py`

**Interfaces:**
- Consumes: `VerifiedCandidateObject` and project-root safety helpers.
- Produces: `prepare_candidate(source: Path, identity: CandidateIdentity) ->
  VerifiedCandidateObject`, `verify_candidate(candidate) -> None`, and
  `quarantine(candidate_id, reason_code) -> None`; exact
  `CandidateRetentionPolicy.can_delete(...) -> bool` from the spec.

- [ ] Write tests for temp write, fsync, digest/probe mismatch, disk full,
  cross-filesystem rename rejection, symlink/path escape, duplicate same bytes,
  duplicate different bytes and kill after final rename. Unit-test the injected
  retention policy against master, active-attempt, retained-receipt and
  incomplete-backup references using repository fakes.
- [ ] Run focused tests. Expected RED: store absent.
- [ ] Implement same-filesystem temp/flush/fsync/verify/atomic immutable rename;
  never overwrite a final candidate or current master. The shared retention
  policy refuses master, active-attempt, retained-receipt and incomplete-backup
  references; existing deletion routes are wired after Task 10 creates the
  backup-set relation. M7 adds no cleanup scheduler.
- [ ] Run focused tests and existing project-path security tests. Expected GREEN;
  failure leaves old master untouched and at most a quarantined orphan.
- [ ] Commit with `feat(host): add immutable candidate object store`.

### Task 10: Persist master heads and promotion evidence

**Files:**
- Extend: `lib/db/models/host_hardening.py`
- Create: `alembic/versions/7b7c4a0e0001_add_atomic_master_promotion.py`
- Extend: `lib/db/repositories/host_hardening.py`
- Modify: existing candidate/media deletion routes returned by refreshed graph
  discovery and recorded in `scripts/r2/verify_m7_scope.py`
- Create: `tests/integration/lib/db/migrations/test_alembic_master_promotion.py`
- Create: `tests/integration/lib/db/repositories/test_master_head_repository.py`
- Create: `tests/architecture/test_m7_candidate_retention_boundary.py`

**Interfaces:**
- Consumes: `VerifiedCandidateObject` and `7a7c4a0e0001`.
- Produces: `candidate_objects`, `master_heads`, `master_head_versions`,
  `promotion_receipts` and `backup_sets`; migration `7b7c4a0e0001`.
  `project_events` already exists from Task 2.

- [ ] Write migration/repository tests for immutable candidate digest, one scoped
  head per artifact, expected-version CAS, exact command replay, conflicting
  command mismatch, approval/candidate/usage refs, append-only history and
  backup-set state/reference constraints required by retention.
- [ ] Run focused tests. Expected RED: tables/repository methods absent.
- [ ] Implement reversible migration with
  `down_revision = "7a7c4a0e0001"` and repository transactions that never mutate
  historical head versions. Inventory and route every existing candidate/media
  deletion path through the shared retention policy now that every referenced
  table exists; the architecture test rejects future bypasses.
- [ ] Run SQLite mechanics and real-PostgreSQL concurrency. Expected GREEN: one
  CAS winner and complete old/new state.
- [ ] Commit with `feat(db): add atomic master head persistence`.

### Task 11: Make the existing Production authority perform atomic promotion

**Files:**
- Create: `r2/host_hardening/promotion.py`
- Modify: `r2/production/approval_service.py`
- Modify: `r2/production/artifact_bridge.py`
- Create: `r2/host_hardening/master_resolver.py`
- Create: `tests/unit/r2/host_hardening/test_atomic_promotion.py`
- Extend: `tests/integration/r2/production/test_master_promotion_integration.py`
- Create: `tests/architecture/test_m7_master_reader_boundary.py`

**Interfaces:**
- Consumes: `AtomicPromotionService.promote(...)` signature from the spec,
  candidate/master repository port and existing approval validation.
- Produces: one authoritative DB head plus idempotent manifest/version projection;
  `MasterResolver.get_exact(...) -> MasterHeadSnapshot`; no second public
  approval entrypoint or direct legacy authoritative reader.

- [ ] Write tests for every failure cut: before candidate verify, before lock,
  before/after DB commit, manifest projection failure, crash before projection,
  duplicate projection and concurrent promotion. Freeze a graph-derived,
  coverage-checked inventory of every master/current-version reader and fail if
  an authoritative route bypasses `MasterResolver`.
- [ ] Run focused tests. Expected RED: DB head and manifest can diverge without a
  typed recovery state.
- [ ] Extend `ProductionApprovalService` to validate once and delegate authority
  commit to `AtomicPromotionService`; project manifest/version after commit and
  route authoritative reads through `MasterResolver`, which compares DB and
  compatibility projection and fails with `M7_MASTER_DIVERGED` until repaired.
- [ ] Run all M4/M7 production tests. Expected GREEN: readers observe complete old
  or complete new authority; exact replay is unchanged.
- [ ] Commit with `feat(r2): make master promotion transactionally authoritative`.

### Task 12: Freeze and review checkpoint M7-B

**Files:**
- Create: `docs/r2/evidence/R2_M7_B_ATOMIC_PROMOTION.json`

- [ ] Run H3/H4 fault matrix, real-PostgreSQL CAS, candidate-store security,
  legacy manifest/version tests, scope verifier and static gates.
- [ ] Record fault cut, pre/post head version, candidate/master digests, projection
  state, commands/exits and exact clean HEAD.
- [ ] Stop for Codex review. Commit accepted evidence with
  `docs(r2): record M7-B promotion acceptance`.

### Task 13: Expose durable project-event replay

**Files:**
- Extend: `lib/db/repositories/host_hardening.py`
- Modify: `server/services/project_events.py`
- Modify: `server/routers/project_events.py`
- Modify: `server/sse_channel.py`
- Create: `tests/integration/server/services/test_durable_project_events.py`
- Extend: `tests/unit/server/routers/test_project_events_router.py`

**Interfaces:**
- Consumes: `DurableProjectEvent` and `ProjectEventRepository` from the spec.
- Produces: repository access to Task 2 `project_events`; SSE replay by opaque
  integer event cursor and typed `EVENT_CURSOR_EXPIRED` resync response.

- [ ] Write stream tests for commit-before-publish, crash after
  commit, duplicate wakeup, reconnect cursor, subscribe/catch-up race, cursor
  expiry, cross-project cursor and server restart.
- [ ] Run focused tests. Expected RED: memory channel cannot replay.
- [ ] Implement durable replay over Task 2 rows; all domain UoWs already append
  those events. Subscribe before reading high watermark, drain DB, then use the existing channel as a
  wake-up hint.
- [ ] Run focused tests and all existing SSE/project-event tests. Expected GREEN:
  no gaps, duplicates tolerated, authorization preserved.
- [ ] Commit with `feat(host): make project event streams durable`.

### Task 14: Make frontend event replay and resync deterministic

**Files:**
- Modify: `frontend/src/utils/sse-stream.ts`
- Modify: `frontend/src/hooks/useProjectEventsSSE.ts`
- Modify: `frontend/src/api.ts`
- Modify: all supported locale files under `frontend/src/i18n/`
- Extend: `frontend/src/utils/sse-stream.test.ts`
- Extend: `frontend/src/hooks/useProjectEventsSSE.test.tsx`

**Interfaces:**
- Consumes: durable event ID and `EVENT_CURSOR_EXPIRED` response.
- Produces: event-ID dedupe, snapshot replacement and cursor reset/reconnect.

- [ ] Write tests for duplicate event, reconnect after visibility change, expired
  cursor, snapshot failure, project switch, stale response and localized resync
  error.
- [ ] Run selected pnpm tests. Expected RED: expired cursor is a generic stream
  error or stale events double-apply.
- [ ] Implement per-project cursor/dedupe state; on expiry fetch authoritative
  snapshot, replace projection atomically and reconnect from its watermark.
- [ ] Run focused tests, i18n consistency and `(cd frontend && pnpm check)`.
  Expected GREEN.
- [ ] Commit with `feat(frontend): recover project events from durable cursor`.

### Task 15: Prove restart, cancellation and remote-completion recovery

**Files:**
- Modify: `lib/generation_worker.py`
- Modify: `server/services/resume_executor.py`
- Modify: `server/services/execution_attempts.py`
- Create: `tests/integration/r2/host_hardening/test_process_recovery.py`
- Create: `tests/integration/r2/host_hardening/test_cancel_reconciliation.py`
- Create: `tests/fixtures/r2/host_hardening/provider_process.py`

**Interfaces:**
- Consumes: attempt lease/version, exact-route adapters and durable events.
- Produces: expired-attempt scanner and deterministic resume/reconcile/cancel
  behavior from spec section 7.

- [ ] Add subprocess tests that SIGKILL at pre-submit, post-provider-accept,
  post-local-accept, mid-poll, post-download and pending-cancel barriers. Simulate
  provider completion while the application process is absent.
- [ ] Run focused tests. Expected RED at unknown acceptance and stale-worker
  fencing cases.
- [ ] Implement scanner and fenced writes: remote ID resumes exact poll/download;
  unknown follows qualified reconciliation; cancel intent persists before call;
  late terminal truth wins. `NEEDS_OPERATOR` can leave only through an exact
  `OperatorResolutionReceipt`; no webhook receiver is added.
- [ ] Run focused tests plus existing worker/orphan/checkpoint/cancel regressions.
  Expected GREEN with one remote submit/candidate/usage.
- [ ] Commit with `feat(host): recover attempts across real process restart`.

### Task 16: Freeze and review checkpoint M7-C

**Files:**
- Create: `docs/r2/evidence/R2_M7_C_RESTART_STREAM_RECOVERY.json`

- [ ] Run H5 subprocess matrix, durable SSE tests, backend/resume/cancel
  regressions, frontend checks, scope verifier and static gates.
- [ ] Record process PIDs/barriers, attempt/event ranges, provider submit counts,
  exact clean HEAD and evidence hashes.
- [ ] Stop for Codex review. Commit accepted evidence with
  `docs(r2): record M7-C recovery acceptance`.

### Task 17: Implement backup-set creation and clean-target verification

**Files:**
- Create: `r2/host_hardening/backup.py`
- Create: `server/services/backup_sets.py`
- Create: `scripts/r2/create_backup_set.py`
- Create: `scripts/r2/verify_restored_backup_set.py`
- Create: `tests/unit/r2/host_hardening/test_backup_manifest.py`
- Create: `tests/integration/r2/host_hardening/test_backup_set_service.py`

**Interfaces:**
- Consumes: `BackupSetManifest`, DB master/candidate reads, manifest/version reads
  and media probes.
- Produces: deterministic JSON manifest, `create_backup_set(...)` in explicitly
  provided roots, and `verify_restored_backup_set(...) -> BackupVerdict`.

- [ ] Write tests for missing DB ref, missing/corrupt media, changed release/schema,
  incomplete copy, GC race, secret/path leakage, non-empty restore target and 100%
  master closure.
- [ ] Run focused tests. Expected RED: backup modules absent.
- [ ] Implement explicit-path-only scripts, write/GC fence, exact recovery target,
  sorted media inventory and checksum closure. The verifier refuses source and
  target aliases and never infers production paths.
- [ ] Run focused disposable PostgreSQL/media integration without touching live
  data. Expected GREEN and deterministic manifest bytes.
- [ ] Commit with `feat(host): define consistent database media backup sets`.

### Task 18: Add secret-safe OpenTelemetry correlation

**Files:**
- Create: `r2/host_hardening/telemetry.py`
- Create: `server/telemetry.py`
- Modify: attempt, provider, candidate, promotion, usage and event service seams
  enumerated by `scripts/r2/verify_m7_scope.py`
- Create: `tests/unit/r2/host_hardening/test_telemetry_policy.py`
- Create: `tests/integration/server/test_m7_telemetry_correlation.py`

**Interfaces:**
- Consumes: durable request/method/task/execution/candidate/master/usage IDs.
- Produces: allowlisted span/log attributes,
  `public_provider_job_ref(raw_id: str, key: bytes, key_version: str) -> str`, and
  async span links across restart.

- [ ] Write a unique canary into credentials, prompt, signed URL, headers,
  provider body and path. Assert it is absent from structured logs, in-memory OTLP
  export and public event rows while the durable ID join remains complete.
- [ ] Run focused tests. Expected RED: no common policy or leaked canary.
- [ ] Implement source-side minimization, HMAC refs, baggage clearing and
  collector-independent attribute allowlist; metric labels exclude high-cardinality
  IDs.
- [ ] Run focused tests and dependency/static gates. Expected GREEN with zero
  canary occurrences and complete join.
- [ ] Commit with `feat(host): correlate generation without leaking secrets`.

### Task 19: Execute disposable clean-target restore and review M7-D

**Files:**
- Create: `tests/integration/r2/host_hardening/test_clean_target_restore.py`
- Create: `docs/r2/runbooks/m7-backup-restore.md`
- Create: `docs/r2/evidence/R2_M7_D_RECOVERY_VERIFIED.json`

- [ ] In a disposable test root and PostgreSQL instance only, seed Golden A/B
  master/candidate/version/event/usage refs, create a fenced backup set, destroy
  the disposable source, restore to empty targets and run 100% closure plus
  no-provider review/export smoke.
- [ ] Measure recovery point, RPO and RTO. Record measured values without claiming
  they are approved business objectives.
- [ ] Run all H1-H7 suites, migration round trip, full affected backend gates,
  frontend checks, test audit and scope verifier.
- [ ] Record exact clean HEAD, image/tool/PostgreSQL versions, commands/exits,
  counts, timings and evidence hashes. Stop for Codex review.
- [ ] Commit accepted evidence with `docs(r2): record M7-D recovery verification`.

### Task 20: Build upstream compatibility and provider qualification gates

**Files:**
- Create: `r2/host_hardening/compatibility.py`
- Create: `scripts/r2/verify_upstream_candidate.py`
- Create: `scripts/r2/verify_provider_qualification.py`
- Create: `docs/r2/schemas/m7-upstream-candidate.schema.json`
- Create: `docs/r2/schemas/m7-provider-qualification.schema.json`
- Create: `tests/unit/scripts/r2/test_verify_upstream_candidate.py`
- Create: `tests/unit/scripts/r2/test_verify_provider_qualification.py`

**Interfaces:**
- Consumes: pinned SHAs, migration/test/Golden/browser evidence and provider
  capability profile.
- Produces: deterministic verdicts `COMPATIBLE | INCOMPATIBLE` and
  `UNQUALIFIED | OFFLINE_VERIFIED | SANDBOX_VERIFIED | QUALIFIED`.

- [ ] Write tests for missing provenance, unsigned/unpinned input, incomplete
  range inventory, absent change disposition, migration failure, required skip,
  dirty evidence SHA, mock-only provider evidence, expired capability version and
  missing rollback target.
- [ ] Run focused tests. Expected RED: verifiers absent.
- [ ] Implement schema-first offline verifiers. `git range-diff` may be stored for
  review but never acts as the only machine gate. Enabled production-candidate
  routes must resolve to `QUALIFIED` exact-version evidence.
- [ ] Run focused tests, JSON/schema validation and scope verifier. Expected GREEN
  for fixtures and fail-closed for incomplete reports.
- [ ] Commit with `feat(r2): gate upstream and provider compatibility`.

### Task 21: Add near-production Golden A/B, browser and operator evidence

**Files:**
- Create: `tests/e2e/test_m7_production_candidate_workflow.py`
- Create: `scripts/r2/run_m7_golden.py`
- Create: `docs/r2/runbooks/m7-provider-reconciliation.md`
- Create: `docs/r2/runbooks/m7-incident-and-rollback.md`
- Create: `docs/r2/runbooks/m7-production-candidate.md`
- Create: `docs/r2/evidence/R2_M7_E_PRODUCTION_CANDIDATE.json`

**Interfaces:**
- Consumes: accepted M7-A through M7-D, M6 dual-profile Golden B, compatibility
  and provider qualification reports.
- Produces: machine-readable M7-E dossier bound to exact release/config/provider
  evidence; it never grants `PRODUCTION_APPROVED`.

- [ ] Write an offline browser flow for create -> generate fixture -> review ->
  failed regeneration -> old master intact -> approve -> reconnect/resync ->
  export, plus foreign project/user denial. Golden B runs the shared Canon through
  Western generic and CN short-drama branches and selects neither implicitly.
- [ ] Run no-provider workflow against a restore-derived disposable environment.
  Expected GREEN before any paid canary is considered.
- [ ] Add explicit CLI flags that require pre-existing approved qualification and
  bounded budget evidence for a real provider canary. Tests prove the command
  refuses absent approval; do not run the canary during implementation.
- [ ] Complete deploy/config/secrets/reconcile/cancel/backup/restore/incident/
  rollback/cost-cap runbooks and verify every command uses explicit targets.
- [ ] Run browser, Golden, H1-H8, frontend/website and backend gates; create the
  dossier only if all required evidence is current, clean and unskipped.
- [ ] Commit with `test(r2): prove M7 production candidate workflow`.

### Task 22: Run final gates and create the M7 handoff

**Files:**
- Modify: `docs/r2/evidence/R2_M7_E_PRODUCTION_CANDIDATE.json` only to add final
  immutable command/evidence hashes.

- [ ] Run `uv run ruff check .`, `uv run ruff format .`,
  `uv run basedpyright --warnings`, `uv run lint-imports`,
  `uv run deptry lib server alembic scripts tests r2`, full pytest per
  `CONTRIBUTING.md`, test audit, `(cd frontend && pnpm check)`,
  `(cd website && pnpm check)`, all migration round trips and both M7 verifiers.
- [ ] Confirm selected tests are non-zero, required skips are zero, one Alembic
  head equals `7b7c4a0e0001`, worktree is clean and the evidence SHA equals HEAD.
- [ ] Re-run Codebase Memory coverage for every touched and claimed path; read any
  reported missed ranges before a completeness claim.
- [ ] Set dossier status to `PRODUCTION_CANDIDATE` only when M7-A through M7-E are
  independently accepted and every H1-H8 evidence hash resolves. Otherwise set
  `REJECTED` with exact stop codes.
- [ ] Commit final evidence with `docs(r2): finalize M7 production candidate` and
  stop. Do not push, deploy, migrate, activate workers, call providers, restore
  live systems, clean data or claim `PRODUCTION_APPROVED`.

---

## Plan Self-Review Checklist

- H1 maps to Tasks 1-7 and checkpoint M7-A.
- H2 maps to Tasks 2-7 and checkpoint M7-A.
- H3-H4 map to Tasks 9-11 and checkpoint M7-B.
- H5 maps to Tasks 13-15 and checkpoint M7-C.
- H6 maps to Tasks 17 and 19 and checkpoint M7-D.
- H7 maps to Task 18 and checkpoint M7-D.
- H8 maps to Tasks 20-22 and checkpoint M7-E.
- Migration chain is exactly `6c7c4a0e0002 -> 7a7c4a0e0001 ->
  7b7c4a0e0001`.
- Exact public types/signatures originate in the spec and have one producing task.
- Every task contains a RED observation, minimal GREEN implementation, affected
  regression and an isolated commit or explicit checkpoint stop.
- Paid provider activity and production operations remain approval-gated and are
  not implementation steps.

## Claude Code Handoff

Claude Code must read the research, ADR, spec, this umbrella plan and the current
checkpoint packet in that order. Initially it executes M7-A Task A0 only, whose
write allowlist is exactly `scripts/r2/verify_m7_scope.py`,
`tests/unit/scripts/r2/test_verify_m7_scope.py` and
`docs/r2/evidence/R2_M7_BASELINE.json`. It stops after every checkpoint for
independent Codex review. It must not ask the user to choose architecture: fixed
decisions are already recorded. If a frozen prerequisite or seam differs, it
returns the exact stop code and evidence instead of improvising.
