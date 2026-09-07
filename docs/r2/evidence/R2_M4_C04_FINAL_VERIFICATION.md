# R2-M4 C04 Host Budget Reservation — Final Verification

**Status:** `C04_HOST_BUDGET_STATUS = READY`
**Branch:** `feat/r2-m4-c04-budget`
**C04 starting head:** `521aad2f83a19bdb03219923b6bd2268a338f617` (remediation clean handoff)
**C04 verified head:** `ef47f99c620029023a9f866bc8c505f13ccf0db8`
**Original R2 baseline:** `1985b815d70dd600519839973b1da20472012d8f`
**Remediation verified head:** `e72cce2272e1e496a7c8a52df2d3513fd20e815d` (ancestor of the starting head)
**H1 / R2-HOST-001:** OPEN / PRODUCTION_BLOCKER — unchanged by C04.

## Task commits (`521aad2f`..`ef47f99c`)

| Task | Commit | Subject |
|---|---|---|
| 0–1 | `c829ff79` | pin approved M4 C04 design and seams |
| 2 | `93882344` | add durable budget reservation tables |
| 3 | `bf03242d` | reserve production budget atomically |
| 4 | `bd920dbf` | manage budget reservation lifecycle |
| 5 | `9d8ab281` | reconcile budget with usage cost evidence |
| 6 | `36cd828f` | project C04 budget authorization events |
| 7 | `5f324f3e` | expose host budget authorization port |
| 8 | `e33db8fd` | guard paid submission with budget claim |
| 9 | `eba3934a` | enforce C04 budget architecture boundaries |
| 9 | `ef47f99c` | scope M2 artifact-bridge boundary diff to the M2 tip |

## Step 1 — C04 focused suite

```bash
uv run python -m pytest -q \
  tests/unit/lib/test_budget_reservation.py \
  tests/integration/lib/db/migrations/test_alembic_budget_reservations.py \
  tests/integration/lib/db/repositories/test_budget_reservation_repo.py \
  tests/integration/server/services/test_budget_reservation_service.py \
  tests/unit/server/services/test_budget_reservation_events.py \
  tests/unit/server/services/test_paid_submission_guard.py \
  tests/unit/r2/production/test_budget_port.py \
  tests/unit/r2/production/test_c04_budget_architecture_boundaries.py
```

Result: **49 passed**, 0 skipped, 0 failed.

Plan deviation (recorded in the Task 5 commit): the plan places the budget service
tests at `tests/unit/server/services/test_budget_reservation_service.py`, but
`scripts/audit_tests.py` forbids real-DB access from the `unit` tier. The
DB-backed service tests (reserve / claim / release / expire / reconcile / events)
live at `tests/integration/server/services/test_budget_reservation_service.py`;
`tests/unit/server/services/test_budget_reservation_events.py` and
`tests/unit/server/services/test_paid_submission_guard.py` are pure unit.

## Step 2 — Frozen R2 regressions

Baseline for "no C04 regression" is the C04 starting head `521aad2f` (the
post-remediation clean handoff), not the M3 tip. The CI remediation lineage
(`b345a16b`..`521aad2f`) had already shifted two of the M3-era frozen counts
before C04 began: `tests/unit/r2/ tests/integration/r2/` = 125 (M3 doc records
122) and `tests/unit/r2/contracts/` = 50 (M3 doc records 41). C04 introduces
**zero** regressions against `521aad2f`.

| Selection | at `521aad2f` | at `ef47f99c` | C04 effect |
|---|---|---|---|
| `tests/integration/lib/test_artifact_manifest_storage.py tests/integration/lib/test_speech_artifact_provenance_integration.py tests/integration/lib/test_visual_artifact_provenance.py tests/integration/lib/test_workflow_plan_adapters.py tests/integration/lib/test_workflow_state.py tests/integration/server/services/test_video_artifact_currency.py tests/integration/server/services/test_workflow_planner.py tests/unit/lib/test_artifact_manifest.py tests/unit/lib/test_artifact_provenance.py tests/unit/lib/test_speech_artifact_provenance.py tests/unit/lib/test_workflow_plan.py tests/unit/server/services/test_video_batch_admission.py` | 349 PASS | **349 PASS** | none |
| `tests/unit/r2/test_bootstrap.py tests/unit/scripts/r2/test_verify_frozen_registries.py tests/unit/scripts/r2/test_known_blockers.py tests/unit/scripts/r2/test_verify_baseline.py tests/unit/scripts/r2/test_verify_postgres_baseline_script.py` | 15 PASS | **15 PASS** | none |
| `tests/unit/r2/production/ tests/integration/r2/production/` — frozen subset (deselect `test_budget_port.py`, `test_c04_budget_architecture_boundaries.py`) | 53 PASS | **53 PASS** | 0 regressions |
| `tests/unit/r2/production/ tests/integration/r2/production/` — full | 53 PASS | **64 PASS** | +11 approved C04 tests |
| `tests/unit/r2/contracts/` | 50 PASS | **50 PASS** | 0 regressions |
| `tests/unit/r2/ tests/integration/r2/` — frozen subset (deselect the two C04 files) | 125 PASS | **125 PASS** | 0 regressions |
| `tests/unit/r2/ tests/integration/r2/` — full | 125 PASS | **136 PASS** | +11 approved C04 tests |

Frozen ArcReel Host focused regression: **exactly 349 PASS**, unchanged.

## Step 3 — PostgreSQL concurrency evidence

Engine: PostgreSQL **16.15** (`r18-arcreel-postgres`, `postgres:16-alpine`),
`DATABASE_URL=postgresql+asyncpg://arcreel:***@127.0.0.1:55432/arcreel_r18`
(per-test schema, `DROP SCHEMA … CASCADE` on teardown).

```bash
DATABASE_URL=postgresql+asyncpg://arcreel:***@127.0.0.1:55432/arcreel_r18 \
uv run python -m pytest -q \
  tests/integration/lib/db/repositories/test_budget_reservation_repo.py \
  tests/integration/server/services/test_budget_reservation_service.py \
  tests/integration/lib/db/migrations/test_alembic_budget_reservations.py
```

Result: **24 passed** on PostgreSQL — includes
`test_concurrent_reserve_allows_exactly_one_writer` (real `SELECT … FOR UPDATE`
row lock, exactly one writer wins),
`test_reopen_preserves_reservation_state_and_counters` (state survives a new
session), and the alembic upgrade/downgrade migration tests.

## Step 4 — Repo-wide Python CI quality gates

| Gate | Result |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 1653 files already formatted |
| `uv run basedpyright --warnings` | 0 errors, 0 warnings, 0 notes |
| `uv run deptry lib server alembic scripts tests r2` | Success! No dependency issues found |

## Step 5 — Architecture audit

| Gate | Result |
|---|---|
| `uv run lint-imports` | Contracts: 3 kept, 0 broken (incl. new "C04 R2 预算端口不直连 Host DB 层") |
| `uv run python scripts/audit_tests.py` | 闸门通过：0 处违规 |

`tests/unit/r2/production/test_c04_budget_architecture_boundaries.py` (7 tests)
asserts: `budget_port` imports no `lib.db.*` / `server`; `budget_port` writes no
usage/cost truth; budget modules import no artifact-manifest/currency/master or
canon/narrative modules; the event projection reaches no repository/session; any
future `prompt_compiler` module cannot import the budget repo/service; the
import-linter contract is present with no ignores.

## Step 6 — Repository scope

`git merge-base --is-ancestor 521aad2f HEAD` → exit 0.
`git diff --name-status 521aad2f...HEAD`:

- Host runtime changes: only approved C04 files
  (`lib/budget_reservation.py`, `lib/db/models/budget_reservation.py`,
  `lib/db/repositories/budget_reservation_repo.py`,
  `server/services/budget_reservation_service.py`,
  `server/services/budget_reservation_events.py`,
  `server/services/paid_submission_guard.py`,
  `r2/production/budget_port.py`, plus `lib/db/models/__init__.py` /
  `lib/db/repositories/__init__.py` registration and `pyproject.toml` import-linter).
- `lib/db/repositories/usage_repo.py`: **not modified** — reconciliation reuses
  `UsageRepository.get_calls(call_id=…)` unchanged (Task 0 decision).
- DB migrations: **exactly 1** approved additive migration —
  `alembic/versions/c04b7d93e5a1_add_budget_reservations.py`, chained after
  `9f3c7a52d1b4`.
- `test_m2_artifact_bridge_architecture_boundaries.py`: user-approved re-anchor of
  the `M1_HEAD..HEAD` diff to the pinned M2 tip `9cc04edd`, so the two "nothing
  changed since M1" checks keep asserting M2's own scope instead of re-scanning
  every later milestone. Count unchanged at 7 PASS.
- H1: **OPEN**.
- Second cost ledger: **none**. Second queue: **none**. Parallel artifact
  registry: **none**. M4-local shadow balance: **none**. Process-local budget
  mutex: **none**.
- `git status --short`: clean.

## Decision

R2-M4 C04 satisfies its acceptance gate: durable budget authorization
(`budget_scopes` / `budget_reservations`), atomic reserve, restart-safe
claim / release / expire, idempotent reconciliation against existing Usage/Spend
truth, a non-authoritative event projection, an R2 delegation port that never
touches Host storage, and a paid-submission guard that claims before the first
side effect. Existing Usage/Spend remains the actual-cost authority. H1 remains
open. Do **not** push — the main M4 plan reads the clean C04 worktree HEAD as
`M4_STARTING_HEAD`.
