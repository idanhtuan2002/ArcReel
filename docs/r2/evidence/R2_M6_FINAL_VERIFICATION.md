# R2-M6 Final Verification (Checkpoint M6-FINAL, Task 17)

## Status: ACCEPTED BY HUMAN OVERRIDE — no Codex review

**This is not a Codex-approved verdict.** The plan
(`docs/superpowers/plans/2026-09-12-r2-m6-dual-profile-adaptation.md`, Task 17)
specifies that Codex reviews the whole M6 surface and, after an `APPROVED`
verdict, this file records that acceptance. That review was never requested or
run against this HEAD. The operator (Human Showrunner, `human:anhtuan`)
explicitly decided on 2026-09-16 to waive the Codex review requirement and
accept the evidence below — reproduced gate results at one exact clean HEAD,
including three real bugs found and fixed by the real-PostgreSQL run — as
sufficient to close M6-FINAL and unblock M7.

This mirrors the precedent already accepted for M5C-2, M5C-3 and M5C-4
(`R2_M5C_FINAL_VERIFICATION.md`), whose own Codex reviews never completed
(Codex hit its usage limit each time) and whose checkpoints were closed on the
operator's explicit decision to proceed anyway. That formal Codex sign-off
remains outstanding for M5C and now for M6 as well. If Codex capacity returns,
running the review this file describes is still valuable and may be done
retroactively.

## Frozen head and lineage

- `M6_FINAL_VERIFIED_HEAD`: `636c86d85c126000dee6ecda34e53460895f6e93`
- Worktree: `/home/anhtuan/content-production-os-m6`, branch `feat/r2-m6-dual-profile-adaptation`
- `M6` integration base (`m6_integration_base_intent` in `R2_M6_DOCUMENT_APPROVAL.json`):
  `8b1959e7ae882716a9d531f459d8289c83968fbb` (M5C's own `M5C_FINAL_VERIFIED_HEAD`,
  confirmed still current M5C acceptance via `R2_M5C_FINAL_VERIFICATION.md`)
- 21 commits since base (Tasks 0-17, full list: `e0e3b93d`..`636c86d8`), most recent:
  - `a084da0e` test(r2): add M6 adversarial mutations and cross-family PostgreSQL races (Task 16)
  - `82adf15c` fix(r2): write the admission decision before its FK-dependent
    projection row — a real FK-ordering bug in `admit_screenplay_for_direction`
    (production code, `r2/adaptation/authority.py`) plus two latent test-fixture
    bugs in `test_m6_postgres_concurrency.py`, all three only observable once the
    real-PostgreSQL suite actually ran (see "Bugs found and fixed" below)
  - `636c86d8` chore(r2): extend the M6 scope verifier with the M6-FINAL checkpoint
- Working tree: clean at `636c86d8` (confirmed via `git status --short`).

## Bugs found and fixed during this gate run

The M6-B/C/D per-checkpoint reviews (`R2_M6_B_REVIEW.md` / `R2_M6_C_REVIEW.md` /
`R2_M6_D_REVIEW.md`) were never produced — the operator explicitly deferred
per-checkpoint review to one combined pass at Task 17. A direct consequence: the
real-PostgreSQL concurrency suite (`test_m6_postgres_concurrency.py`,
`test_screenplay_admission.py`'s own race test, `test_adaptation_concurrency.py`)
had never actually been executed against real PostgreSQL before this session —
only structurally checked and always skipped under this sandbox's default SQLite
test engine. Provisioning a real isolated PostgreSQL 18 instance for this Task 17
run (mirroring M5C's own precedent) surfaced three real, previously-latent bugs:

1. **Production bug** (`r2/adaptation/authority.py`,
   `admit_screenplay_for_direction`): the `adaptation_screenplay_admissions`
   projection row was inserted *before* its own referenced `adaptation_decisions`
   row existed, violating `fk_adaptation_screenplay_admissions_decision` the
   instant the insert flushed under PostgreSQL's immediate (non-deferred) FK
   enforcement. SQLite's disabled FK checks let this pass silently in every prior
   run. Fixed by reordering: `append_decision_and_advance_head` now runs before
   `insert_screenplay_admission`.
2. **Test-fixture bug** (`test_m6_postgres_concurrency.py`, `_profile_ref`): used
   a fabricated `policy_pack_digest` (`"sha256:" + seed * 64`) that never matched
   a real profile pack's actual digest, so any code path that resolved the
   profile pack (`ProfilePackRegistry.resolve`) would fail closed. Fixed by
   computing the real digest from the pinned pack JSON, mirroring
   `test_screenplay_admission.py`'s own working pattern.
3. **Test-harness bug** (`test_m6_postgres_concurrency.py`,
   `_BarrierBeforeHeadLockRepository`): barriered *every*
   `prepare_or_lock_head` call, including the branch's `MAP_APPROVAL` lock
   inside `_verify_admission_applicability`. Once real Postgres row-level
   locking serialized the two racers at their shared `SCREENPLAY_ADMISSION`
   head, the loser could never reach the second barrier point until the
   winner's transaction completed — but the winner could not complete without a
   second party at that same barrier, deadlocking the test itself (observed as
   a 10s `TimeoutError`, not a false pass). Fixed by narrowing the barrier to
   the `SCREENPLAY_ADMISSION` lock only, mirroring
   `test_screenplay_admission.py`'s own working race harness.

All three fixes are commit `82adf15c`. Full pytest (13683 passed, 17 skipped)
and every real-PostgreSQL suite were re-run clean after the fix (below).

## PostgreSQL identity

- Docker container `m6-pg18-test` at `127.0.0.1:54330`, isolated (not the shared
  `pios2-postgres` dev container on `5433`)
- `SELECT version()`: `PostgreSQL 18.6 (Debian 18.6-1.pgdg13+2) on
  x86_64-pc-linux-gnu, compiled by gcc (Debian 14.2.0-19) 14.2.0, 64-bit`
- `current_database()` / `current_user`: `r2_m6_isolated` / `m6_test`
- Clean-ownership marker: `pg_tables` empty before the first `alembic upgrade`
  (fresh container, no prior schema)
- Migration lineage confirmed: `5c7c4a0e0004 -> 6a7c4a0e0001 -> 6b7c4a0e0001 ->
  6c7c4a0e0001 -> 6c7c4a0e0002` (matches the plan's own declared chain exactly)
- Round-trip: `alembic upgrade head` -> `alembic downgrade 6c7c4a0e0001` ->
  `alembic upgrade head` against `POSTGRES_TEST_URL` — clean, `alembic current`
  reports `6c7c4a0e0002 (head)`

## Gate results (re-run at `636c86d8`)

| Command | Result |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 1422 files already formatted |
| `uv run basedpyright --warnings` | 0 errors, 0 warnings, 0 notes |
| `uv run lint-imports` | 20 kept, 0 broken |
| `uv run deptry lib server alembic scripts tests r2` | No dependency issues found |
| `uv run python -m pytest -n 4 --dist loadfile` | 13683 passed, 17 skipped, 0 failed |
| `uv run python scripts/audit_tests.py --check` | 0 violations |
| `(cd frontend && pnpm check)` | typecheck + lint + knip + vitest: 183 test files / 2145 tests passed |
| `(cd website && pnpm check)` | typecheck + lint + format:check: all passed |
| `git diff --check` | clean |
| `git status --short` | empty |
| `uv run python scripts/r2/verify_frozen_registries.py` | PASS |
| `uv run python scripts/r2/verify_m6_scope.py --checkpoint M6-FINAL` | all 5 checks PASS (m5c_accepted, clean_tree, base_sha, document_hashes, scope: 101 changed paths) |
| `DATABASE_URL=$POSTGRES_TEST_URL uv run python -m pytest tests/integration/r2/adaptation/ tests/integration/r2/test_m5c_architecture_boundaries_db.py tests/integration/r2/narrative_lifecycle/test_lifecycle_concurrency.py tests/integration/r2/narrative_lifecycle/test_handoff_admission.py` | 107 passed, 0 failed, 0 skipped |
| `DATABASE_URL=$POSTGRES_TEST_URL uv run alembic upgrade head && downgrade 6c7c4a0e0001 && upgrade head` | clean round-trip |

The 17 SQLite skips (full pytest run) resolve to 12 unique locations, all
environment-conditional by design and all now backed by a real-PostgreSQL run
above: 7 are "concurrency races need real row-level locking (PostgreSQL only)"
(M6's own `test_m6_postgres_concurrency.py` x2, `test_adaptation_concurrency.py`,
`test_screenplay_admission.py`, plus M5C's `test_lifecycle_concurrency.py` x4 and
`test_handoff_admission.py` x2), 1 is "isolation level is a PostgreSQL-only
precondition" (M5C boundary test), 3 are "the SQLite test engine runs with
foreign keys disabled" (M5C/M6 repository tests), 1 is a macOS-only `_scproxy`
mutmut check, and 1 is an unrelated drama-script-generator skip pre-dating M6.
Zero are M6-required skips left unexercised on the dialect where they are
required — every PostgreSQL-only M6 test above genuinely ran and passed against
real PostgreSQL 18.6, not merely structurally reviewed.

## Donor parity and Golden A/B evidence

- `tests/integration/donor_parity/` (Take shot vocabulary + Huohuo/Shuangwen
  drama fields, both real `node --import tsx` subprocess runs against pinned
  TypeScript donor source, not mocked): 142 passed, 0 skipped, 0 failed.
- M4 Golden A regression (`tests/integration/r2/m4/`,
  `tests/unit/r2/production_intelligence/`): 292 passed, 0 skipped, 0 failed —
  confirms Golden A/v1 hashes and existing Director/OpenMontage routing remain
  unchanged after the Task 13 async conversion and Task 14 dual-read retrofit.
- M6 Golden B dual-profile acceptance
  (`tests/integration/r2/test_m6_dual_profile_acceptance.py`): 10 passed, 0
  skipped, 0 failed — 2 baseline shared-Canon slice tests (Task 15) plus 8
  adversarial mutation tests (Task 16), each asserting the mutation fails at its
  owning boundary, writes no partial state, and leaves the sibling
  branch/profile slice unaffected.
- `tests/unit/r2/contracts/test_fingerprints.py::test_upgrading_a_shot_to_v2_changes_the_content_fingerprint`
  proves the v1->v2 dual-read requirement directly: identical semantic content
  upgraded to `ShotSpecV2` shape produces a different content fingerprint (so
  stale readiness/candidates are correctly invalidated), while the v1
  fingerprint itself is unchanged and reproducible.

## Graph generation/coverage

- Codebase Memory project `home-anhtuan-content-production-os-m6`, status
  `ready`, indexed at `head_sha = 636c86d85c126000dee6ecda34e53460895f6e93`
  (this exact final HEAD): 26,743 nodes, 151,706 edges.
- `index_status` (verbose): 0 skipped files; 3 `parse_partial` files, all
  frontend CSS (`app.css`, `studio.css`, `index.css`), unrelated to the M6
  backend surface; all other `not_indexed` entries are by-design
  gitignore/skip-list/fast-pattern exclusions (frontend `*.test.ts(x)` files,
  lockfiles, license files), none of which are part of M6's scope.

## Document hashes and scope

- `docs/r2/evidence/R2_M6_DOCUMENT_APPROVAL.json`'s four recorded document
  hashes (design/plan/adr/research) still match their current file contents
  exactly (`verify_m6_scope.py`'s `document_hashes` check: PASS).
- `verify_m6_scope.py --checkpoint M6-FINAL`'s `scope` check confirms all 101
  paths changed since the M6-A base (`8b1959e7`) are within the declared
  cumulative allowlist for Tasks 5-17, cross-checked individually against the
  plan's own per-task `Files:` declarations (see `scripts/r2/verify_m6_scope.py`
  commit `636c86d8` for the full per-task breakdown and rename/addition notes).

## Checkpoint-review lineage

- M5C base: `R2_M5C_FINAL_VERIFICATION.md` (accepted 2026-09-15 by explicit
  human override, Codex unavailable) — confirmed still present and current.
- M6-A: no separate `R2_M6_A_REVIEW.md` was produced; Task 0's own prerequisite
  gate (`m5c_accepted`, `clean_tree`, `base_sha`, `document_hashes`,
  `graph_evidence`) was satisfied inline at the time and is re-verified above.
- M6-B / M6-C / M6-D: no separate review files were produced. The operator
  explicitly deferred per-checkpoint review to this single combined Task 17
  pass ("tam thoi sang task tiep theo, chung ta sa review lai sau" /
  "ban hay chay full gate sau do hay liet ke nhung muc, file can review, toi se
  review thu cong"). This file and the accompanying scope-verifier extension
  are that combined review's evidence trail.
- M6-E / Task 17 (this file): independent Codex review never run; closed by
  explicit human override on 2026-09-16 — see Status above.

## Handoff

`M6_FINAL_HANDOFF_HEAD` = `636c86d85c126000dee6ecda34e53460895f6e93` (this
file's commit is the only change on top of it). No push, merge, migration
against a non-isolated database, provider call, worker start, or deploy
follows from this file without separate explicit Human approval (spec §17.8
equivalent). M7 may treat this head as its accepted upstream base per the
operator's override recorded above. `docs/r2/evidence/R2_M6_IMPLEMENTATION_HANDOFF.json`
records the same evidence in machine-readable form with `status: "ACCEPTED"`.
