# R2 M5A Final Verification

Durable, append-only Canon authority: pinned branches, atomic approved-delta
commits, deterministic immutable-version resolution, and proven recovery and
concurrency on PostgreSQL 16. Verified after the Codex review fixes (all eight
findings resolved — see the last section).

## Heads

- Starting head (`m4_handoff_head`, accepted M4 Gate D): `2173463e88218248d8805e4f20df2102d1d6743a`
- Verified head (`M5A_VERIFIED_HEAD`, ran every PASS gate below): `2d648546dc971af6cc8072a2765de27fa4e9472a`
- Branch: `feat/r2-m5a-canon-authority` (worktree `/home/anhtuan/content-production-os-m5a`)
- The verified head descends from the exact accepted M4 handoff: four pre-existing M5A
  design/plan docs commits, 14 M5A implementation commits, 8 Codex-review fix commits, and one
  commit that removes the pre-review evidence draft (added then removed — absent from the net diff).

## Migration current / head

| Command | SQLite (migration test) | PostgreSQL 16 |
|---|---|---|
| `uv run alembic current` | n/a | `5a7c4a0e0001 (head)` |
| `uv run alembic heads` | `5a7c4a0e0001 (head)` | `5a7c4a0e0001 (head)` |

Migration `5a7c4a0e0001_add_canon_authority` (parent `c04b7d93e5a1`) is additive: four tables, the
`canon_branches` self-FK plus version→branch / version→version / version→delta / projection→version
foreign keys all `RESTRICT`, the branch head/parent version pointers carrying no physical FK,
`ck_canon_branches_branch_type`, `ck_canon_branches_parent_pairing`, `uq_canon_deltas_approval_ref`,
`uq_canon_versions_committed_delta_id`, `uq_canon_versions_branch_version_number`, and the
`uq_canon_branches_one_main_per_scope` partial unique index (`branch_type = 'MAIN'`).
`upgrade → upgrade (idempotent) → downgrade base → upgrade head` all exit 0 on PostgreSQL 16.

## PostgreSQL 16 (disposable acceptance database)

| Field | Value |
|---|---|
| `SELECT version()` | `PostgreSQL 16.15 on x86_64-pc-linux-musl, compiled by gcc (Alpine 15.2.0) 15.2.0, 64-bit` |
| Container name | `r2-m5a-postgres` |
| Container ID | `25825a2652786f43dce6bd6f40fa800f7516674b4d8c32e8487cb257512ab28b` |
| Immutable image ID | `sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685` |
| Image reference | `postgres:16-alpine` |
| Ownership label | `com.content-production-os.r2-m5a = 1` |
| Port | `127.0.0.1:55435 -> 5432/tcp` |
| Database | `arcreel_r2_m5a`, user `arcreel`, password redacted (local-only) |

## Focused M5A tests

- Command: `uv run python -m pytest tests/unit/r2/contracts/test_narrative.py tests/unit/r2/narrative tests/integration/r2/narrative tests/integration/lib/db/repositories/test_canon_repo.py tests/integration/lib/db/migrations/test_alembic_canon_authority.py tests/unit/lib/db/models/test_canon.py tests/unit/scripts/r2/test_verify_m5a_scope.py -q`
- Result: **144 passed**, 0 failed, exit 0 (SQLite).

## Full backend tests

- Command: `uv run python -m pytest -n 4 --dist loadfile -q`
- Result: **12595 passed, 2 skipped**, 0 failed, 0 errors, exit 0 (SQLite).

## PostgreSQL acceptance runs

- Repo-wide DB regression: `uv run python -m pytest -m "uses_db and not sqlite_only" -n 4 --dist loadfile -q`
  → **607 passed**, 0 failed, exit 0. CI-compatible (per-test PostgreSQL schema + outer transaction /
  SAVEPOINT); not the concurrency authority.
- Serial M5A authority (deterministic concurrency evidence):
  `uv run python -m pytest -q -n 0 tests/integration/lib/db/repositories/test_canon_repo.py tests/integration/r2/narrative/test_canon_transaction.py tests/integration/r2/narrative/test_canon_concurrency.py tests/integration/r2/narrative/test_canon_integrity.py tests/integration/r2/narrative/test_canon_resolver.py tests/integration/r2/narrative/test_canon_resolution.py`
  → **70 passed**, 0 failed, exit 0.

## Static gates (verified head, all exit 0)

| Command | Result |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 1747 files already formatted |
| `uv run basedpyright --warnings` | 0 errors, 0 warnings, 0 notes |
| `uv run lint-imports` | Contracts: 9 kept, 0 broken (incl. "R2 narrative core does not depend on Host persistence") |
| `uv run deptry lib server alembic scripts tests r2` | Success! No dependency issues found. |
| `uv run python scripts/audit_tests.py --check` | 闸门通过：0 处违规 |

## Recovery

- Missing / corrupt / mismatched-branch projection → deterministic rebuild + durable re-persist:
  `test_missing_projection_is_rebuilt_and_persisted`, `test_corrupt_projection_is_replaced_by_a_rebuild`,
  `test_projection_with_a_mismatched_branch_id_is_rejected_and_rebuilt`,
  `test_rebuilt_projection_is_durable_after_the_service_call` — PASS.
- Corrupt authoritative delta / unsupported historical hash version → fail closed with `CanonIntegrityError`.
- New-engine restart: `test_committed_head_survives_an_engine_restart` (`sqlite_only`) and
  `test_committed_head_survives_a_fresh_resolution_session` (dialect-aware) — PASS.
- Concurrent missing-projection rebuilders converge to one row: `test_two_missing_projection_rebuilders_converge` — PASS.

## Concurrency

- Same-base same-branch → one `CanonCommitResult`, one `CanonBaseVersionConflict`, local version count 2 — PASS.
- Different branches commit independently — PASS.
- Racing two `MAIN` creations → one snapshot, one `CanonIdentityConflictError` — PASS.
- Racing one `approval_ref` on two branches → one committed delta, one `CanonApprovalError`, loser writes nothing — PASS.
- Fault injection at all seven `CanonCommitStage` boundaries → prior authority byte-identical — PASS.

## Scope proof

- `git diff --name-status 2173463e...2d648546`: 41 changed paths, all within the implementation allowlist,
  exactly one file under `alembic/versions/` and it is the reserved `5a7c4a0e0001_add_canon_authority.py`.
  The pre-review evidence draft was added then removed and is absent from the net diff.
- `git diff --check 2173463e...2d648546`: exit 0.
- `uv run python scripts/r2/verify_m5a_scope.py --base 2173463e --head 2d648546 --mode implementation`: exit 0.
- No second migration, no M5B/M5C, no Canvas, no provider, no server runtime activation, no production
  activation, no operating-database migration, no push, no publish.

## Codex review resolution (all eight findings fixed, test-first, one commit each)

| # | Finding | Fix commit |
|---|---|---|
| B2 (blocker) | narrative version 1 recorded `parent_version_id=None` instead of the pinned parent; integrity checker inverted | `fix(r2): pin narrative version 1 to its parent version` |
| M3 (major) | `ADD_FACT` then `RETIRE_FACT` in one delta bypassed the interval + retirement rules | `fix(r2): close the ADD_FACT then RETIRE_FACT validation gap` |
| M4 (major) | cached projections were not bound to their branch (`branch_id` is outside the content hash) | `fix(r2): bind cached canon projections to their branch` |
| M1 (major) | missing DB `ck_canon_branches_parent_pairing` and `uq_canon_versions_committed_delta_id` | `fix(db): add the required canon authority constraints` |
| M2 (major) | integrity checker silently skipped a narrative branch pinned to an earlier-sorting narrative parent | `fix(r2): verify every branch in nested narrative lineage` |
| B1 (blocker) | mutable `CanonDelta` could be mutated by a caller across the awaited lock; only the hash string was re-checked | `fix(r2): isolate the delta from a concurrent caller mutation` |
| m1 (minor) | branch-creation idempotency ignored `created_at` | `fix(r2): compare created_at in branch-creation idempotency` |
| m2 (minor) | five `# type: ignore[arg-type]` without an inline reason (CONTRIBUTING) | `refactor(db): drop the unreasoned type-ignore comments in canon_repo` |

Open question deferred (spec is silent): `_fact_active_collision` compares fact values with Python `==`,
so JSON `true` and `1` compare equal. Left as-is; a canonical-JSON-bytes comparison is the alternative
if the value-equivalence rule is ever defined.

## Deviations from the plan (deliberate, reviewed)

1. **Single worktree.** The M5A design worktree was rebased onto the accepted M4 handoff and renamed
   `feat/r2-m5a-canon-authority` instead of a separate `-impl` worktree; Task 0's substantive steps were
   still executed.
2. **`tests/integration/r2/narrative/_canon_authority.py`** — one shared Canon-authority seeding module
   for the five narrative integration test files, beyond the plan's Task 11 allowlist; added to the M5A
   scope-verifier allowlist.
3. **Retired the M4 architecture PR guard** (`scripts/r2/audit_m4_architecture.py` +
   `tests/integration/r2/m4/test_m4_architecture_audit.py`) — a single-purpose M4-PR tripwire
   (`_M5_MARKERS` pre-registered `r2/narrative` etc.) that could only fire on legitimate M5 work; CI
   (`tests/integration -n 4`) would fail every M5 branch. Permanent M4 fitness sensors remain in
   `tests/unit/r2/production_intelligence/test_architecture_boundaries.py`. Both paths added to the M5A
   scope-verifier allowlist as deletions.
4. **Formatted the M5A plan doc's embedded code blocks** — repo-wide `ruff format --check .` (never run
   in the design worktree) reformatted only the Python code fences; whitespace only.
5. **Two integrity corruptors are `sqlite_only`** (`test_pinned_parent_on_the_wrong_branch_is_reported`,
   `test_local_parent_out_of_scope_is_reported`): they corrupt `RESTRICT`-FK columns that PostgreSQL
   rejects outright, so the executable checker is the sole guard only on SQLite (`foreign_keys = OFF`).
