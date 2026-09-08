# R2 M5A Final Verification

Durable, append-only Canon authority: pinned branches, atomic approved-delta
commits, deterministic immutable-version resolution, and proven recovery and
concurrency on PostgreSQL 16.

## Heads

- Starting head (`m4_handoff_head`, accepted M4 Gate D): `2173463e88218248d8805e4f20df2102d1d6743a`
- Verified head (`M5A_VERIFIED_HEAD`, ran every PASS gate below): `fdda92c8e6edae5624da5e96abb114570893a57f`
- Branch: `feat/r2-m5a-canon-authority` (worktree `/home/anhtuan/content-production-os-m5a`)
- The verified head descends from the exact accepted M4 handoff; `git log 2173463e..fdda92c8` is
  four pre-existing M5A design/plan docs commits followed by 14 M5A implementation commits.

## Migration current / head

| Command | SQLite (migration test) | PostgreSQL 16 |
|---|---|---|
| `uv run alembic current` | n/a | `5a7c4a0e0001 (head)` |
| `uv run alembic heads` | `5a7c4a0e0001 (head)` | `5a7c4a0e0001 (head)` |

Migration `5a7c4a0e0001_add_canon_authority` (parent `c04b7d93e5a1`) is additive: four tables
(`canon_branches`, `canon_deltas`, `canon_versions`, `canon_resolved_projections`), the
`canon_branches` self-FK and version→branch / version→version / version→delta / projection→version
foreign keys all `RESTRICT`, the branch head/parent version pointers carrying no physical FK, the
`uq_canon_deltas_approval_ref` unique constraint, and the `uq_canon_branches_one_main_per_scope`
partial unique index (`sqlite_where` / `postgresql_where` on `branch_type = 'MAIN'`).
`upgrade → upgrade (idempotent) → downgrade base → upgrade head` all exit 0 on PostgreSQL 16.

## PostgreSQL 16 (disposable acceptance database)

| Field | Value |
|---|---|
| `SELECT version()` | `PostgreSQL 16.15 on x86_64-pc-linux-musl, compiled by gcc (Alpine 15.2.0) 15.2.0, 64-bit` |
| Container name | `r2-m5a-postgres` |
| Container ID | `39805f2ce88dba7a69d975eb902398870ab219cb0b865e7136908500773b82e1` |
| Immutable image ID | `sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685` |
| Image reference | `postgres:16-alpine` |
| Ownership label | `com.content-production-os.r2-m5a = 1` |
| Port | `127.0.0.1:55435 -> 5432/tcp` |
| Database | `arcreel_r2_m5a`, user `arcreel`, password redacted (local-only) |

`DATABASE_URL=postgresql+asyncpg://arcreel:<redacted>@127.0.0.1:55435/arcreel_r2_m5a`

## Focused M5A tests

- Command: `uv run python -m pytest tests/unit/r2/contracts/test_narrative.py tests/unit/r2/narrative tests/integration/r2/narrative tests/integration/lib/db/repositories/test_canon_repo.py tests/integration/lib/db/migrations/test_alembic_canon_authority.py tests/unit/lib/db/models/test_canon.py tests/unit/scripts/r2/test_verify_m5a_scope.py -q`
- Result: **134 passed**, 0 failed, exit 0 (SQLite).

## Full backend tests

- Command: `uv run python -m pytest -n 4 --dist loadfile -q`
- Result: **12585 passed, 2 skipped**, 0 failed, 0 errors, exit 0 (SQLite).

## PostgreSQL acceptance runs

- Repo-wide DB regression: `uv run python -m pytest -m "uses_db and not sqlite_only" -n 4 --dist loadfile -q`
  → **599 passed**, 0 failed, exit 0. This is the CI-compatible regression (per-test PostgreSQL
  schema + outer transaction / SAVEPOINT); it is not the concurrency authority.
- Serial M5A authority (deterministic concurrency evidence):
  `uv run python -m pytest -q -n 0 tests/integration/lib/db/repositories/test_canon_repo.py tests/integration/r2/narrative/test_canon_transaction.py tests/integration/r2/narrative/test_canon_concurrency.py tests/integration/r2/narrative/test_canon_integrity.py tests/integration/r2/narrative/test_canon_resolver.py tests/integration/r2/narrative/test_canon_resolution.py`
  → **62 passed**, 0 failed, exit 0.

## Static gates (verified head, all exit 0)

| Command | Result |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 1746 files already formatted |
| `uv run basedpyright --warnings` | 0 errors, 0 warnings, 0 notes |
| `uv run lint-imports` | Contracts: 9 kept, 0 broken (incl. "R2 narrative core does not depend on Host persistence") |
| `uv run deptry lib server alembic scripts tests r2` | Success! No dependency issues found. |
| `uv run python scripts/audit_tests.py --check` | 闸门通过：0 处违规 |

## Recovery

- Missing projection → deterministic rebuild + durable re-persist:
  `test_missing_projection_is_rebuilt_and_persisted`, `test_rebuilt_projection_is_durable_after_the_service_call` — PASS (PostgreSQL + SQLite).
- Corrupt disposable projection → replaced by a fresh replay: `test_corrupt_projection_is_replaced_by_a_rebuild` — PASS.
- Corrupt authoritative delta / unsupported historical hash version → fail closed with `CanonIntegrityError`:
  `test_corrupt_authoritative_delta_fails_closed`, `test_unsupported_historical_hash_version_fails_closed` — PASS.
- New-engine restart: `test_committed_head_survives_an_engine_restart` (`sqlite_only`, dispose engine → reopen same file → head resolves identically) and `test_committed_head_survives_a_fresh_resolution_session` (dialect-aware) — PASS.
- Concurrent missing-projection rebuilders converge to one row: `test_two_missing_projection_rebuilders_converge` — PASS.

## Concurrency

- Same-base same-branch commits → exactly one `CanonCommitResult`, one `CanonBaseVersionConflict`, local version count 2: `test_same_base_concurrent_commits_have_exactly_one_winner` — PASS (PostgreSQL row-lock; SQLite `BEGIN IMMEDIATE` fallback).
- Different branches commit independently: `test_different_branches_commit_independently` — PASS.
- Two `MAIN` branch creations race in one scope → one snapshot, one `CanonIdentityConflictError` (partial unique index): `test_racing_two_main_branch_creations_yields_one_conflict` — PASS.
- Same `approval_ref` races on two branches → one committed delta, one `CanonApprovalError`, loser leaves no delta/version/projection: `test_racing_the_same_approval_ref_on_different_branches` — PASS.
- Fault injection at all seven `CanonCommitStage` boundaries → prior authority byte-identical:
  `test_fault_at_each_commit_boundary_preserves_prior_authority[*]` — PASS.

## Scope proof

- `git diff --name-status 2173463e...fdda92c8`: 41 changed paths, all within the implementation allowlist,
  exactly one file under `alembic/versions/` and it is the reserved `5a7c4a0e0001_add_canon_authority.py`.
- `git diff --check 2173463e...fdda92c8`: exit 0 (no whitespace errors).
- `uv run python scripts/r2/verify_m5a_scope.py --base 2173463e --head fdda92c8 --mode implementation`: exit 0.
- No second migration, no M5B/M5C, no Canvas, no provider, no server runtime activation, no production
  activation, no operating-database migration, no push, no publish.

## Deviations from the plan (deliberate, reviewed)

1. **Single worktree.** Per operator decision, the existing M5A design worktree was rebased onto
   the accepted M4 handoff and renamed `feat/r2-m5a-canon-authority` instead of creating a separate
   `-impl` worktree; the four M5A docs commits sit directly on `2173463e`. Task 0's substantive
   steps (M4 verification, migration-parent proof, graph re-index, baseline gates,
   `R2_M5A_STARTING_STATE.json`) were still executed.
2. **`tests/integration/r2/narrative/_canon_authority.py`** is one path beyond the plan's Task 11
   allowlist: a shared Canon-authority seeding module for the five narrative integration test files
   (keeps identical fixtures out of ≥3 files per `audit_tests.py`). Added to the M5A scope-verifier
   allowlist.
3. **Retired the M4 architecture PR guard.** `scripts/r2/audit_m4_architecture.py` +
   `tests/integration/r2/m4/test_m4_architecture_audit.py` are a single-purpose M4-PR tripwire —
   `_M5_MARKERS` pre-registered `r2/canon`, `r2/narrative`, `r2/adaptation`, `r2/m5`, `r2/epistemic`
   to keep M5 code out of the M4 PR. M4 is merged (Gate D COMPLETE_WITH_WAIVER), so the guard could
   only fire on legitimate M5A work and CI (`tests/integration -n 4`) would fail every M5 branch.
   The permanent M4 fitness sensors remain in
   `tests/unit/r2/production_intelligence/test_architecture_boundaries.py` (import-linter + AST).
   Both paths added to the M5A scope-verifier allowlist as deletions.
4. **Formatted the M5A plan doc's embedded code blocks.** `uv run ruff format --check .` (repo-wide,
   never run in the design worktree) reformatted only the Python code fences in
   `docs/superpowers/plans/2026-09-07-r2-m5a-canon-authority-and-transactions.md` — whitespace only,
   no change to the plan's substance.
5. **Two integrity corruptors are `sqlite_only`.** `test_pinned_parent_on_the_wrong_branch_is_reported`
   and `test_local_parent_out_of_scope_is_reported` corrupt columns that carry a physical `RESTRICT`
   foreign key (`canon_branches.parent_branch_id`, `canon_versions.parent_version_id`); PostgreSQL
   rejects the corrupting `UPDATE`, so the executable checker is the sole guard only on SQLite
   (`foreign_keys = OFF`), which is what those tests prove. Their non-FK counterparts (branch head
   pointers, delta→version linkage) run on both dialects.
