# R2 V2-02 — Codex independent review (2026-09-29)

Job `task-mum8fa3z-lkl91d`, thread `01a0eb9f-6592-7aa0-a241-0d7eb1d2fb88`, reviewed HEAD `7c5eb6cc`. The reviewer output is saved
verbatim; the main agent's resolution follows it.

---

## 1. HEAD reviewed

`7c5eb6cc5ff8a8dc147f060d7492cd9c4d36b258` on `feat/r2-v2-02-master-authority`, range `git diff 7f2f3e3b..7c5eb6cc`. The worktree remained clean.

## 2. Verdict

**CHANGES_REQUIRED.** Gate C can report success while its file projection disagrees with the database head, and an already issued download token can serve a file master after the database head changes.

## 3. Findings

| Severity | File:line | Scenario | Confidence |
|---|---|---|---|
| Major | [gates.py:523](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/routers/gates.py:523) | Token issuance verifies the database, but download later calls `verified_export_snapshot` without a database check. If the head changes before download, the old file master and export can still be served during the token’s lifetime. The new divergence test checks token issuance, not this sequence. | CONFIRMED |
| Major | [gates.py:355](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/routers/gates.py:355), [gates.py:370](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/routers/gates.py:370) | Two Gate C requests for one artifact can commit heads A then B, then project B then A. The last projection writes stale A without checking that A is still the head; both requests can return success, leaving readers diverged. The pre-check occurs before either commit and does not close this race. | CONFIRMED |
| Major | [master_authority.py:168](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/r2/host_hardening/master_authority.py:168) | Registration derives its “expected” digest from the version file as it exists *after* staging. If that file changes between staging and registration, `prepare_candidate` verifies the changed bytes against the digest just calculated from those same bytes. A first promotion can therefore commit bytes different from the rendered asset and the version record’s `output_sha256`. The test changes bytes only after a candidate is registered. | CONFIRMED |
| Moderate | [master_resolver.py:47](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/r2/host_hardening/master_resolver.py:47), [test_master_authority_unit.py:147](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/tests/integration/r2/host_hardening/test_master_authority_unit.py:147) | A missing file projection is explicitly treated as agreement with an existing DB head. Thus `verify_masters` passes after a committed promotion whose projection never appeared; it cannot itself establish the ADR’s claimed head-to-projection equality. The restore drill has other product checks, but its new `MASTER_AUTHORITY_DIVERGED` check also inherits this blind spot. | CONFIRMED |
| Moderate | [gates.py:222](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/routers/gates.py:222), [host_hardening.py:859](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/lib/db/repositories/host_hardening.py:859) | Concurrent registration of the same candidate can raise repository `CandidateIdentityConflictError`. It is absent from `_MASTER_CONFLICTS`, so this expected conflict becomes a server error instead of the stated 409. | CONFIRMED |
| Moderate | [backfill_master_authority.py:47](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/scripts/r2/backfill_master_authority.py:47) | Backfill skips every non-video file master, while `verify_masters` includes projected masters regardless of kind. If an existing project has an R2 approved master for another artifact kind, the release step leaves that project divergent on every rerun. The supplied tests cover video masters only. | PLAUSIBLE |

The tests also omit the download-after-issuance sequence, overlapping Gate C projections, and mutation before first registration. Those omissions allow the corresponding tests to pass with the defects above.

## 4. Commands run

- `git status --short --branch`, `git rev-parse HEAD`, `git diff --stat 7f2f3e3b..7c5eb6cc`, `git log --oneline 7f2f3e3b..7c5eb6cc`: confirmed range, branch, HEAD, and clean tree.
- `git diff --check 7f2f3e3b..7c5eb6cc`: passed.
- Exact `nl`, `sed`, `rg`, and diff reads of the specified documents, changed files, relevant promotion/resolver/version code, and tests: completed.
- Targeted `.venv/bin/python -m pytest -q -p no:cacheprovider …` with `TMPDIR=/dev/shm`: produced no result and was interrupted. A bounded single-file attempt with plugin autoload disabled timed out after 30 seconds with no test output (`exit 124`).

## 5. Coverage limits

The code graph did not list this worktree, and its status call required approval unavailable in this read-only session; structural findings use direct source inspection. No fresh test pass is claimed. The candidate evidence records passing tests at earlier commit `0cb1a896`, not this reviewed HEAD. PostgreSQL concurrency, the full restore drill, and browser export flow were not run.

## 6. JSON verdict

```json
{
  "schema_version": 1,
  "status": "V2_02_NOT_ACCEPTED",
  "reviewed_head": "7c5eb6cc5ff8a8dc147f060d7492cd9c4d36b258",
  "reviewer": "codex",
  "reviewed_at": "2026-09-29T05:29:16Z",
  "required_skips": [
    "Targeted pytest run did not complete in the read-only environment; bounded single-file run timed out during startup or collection without output",
    "PostgreSQL concurrency tests, full golden restore drill, and browser export flow were not run"
  ],
  "material_unknowns": [
    "Behavior of overlapping Gate C projections under a real PostgreSQL and filesystem schedule",
    "Whether existing deployments contain non-video R2 approved masters"
  ]
}
```

---

## Resolution (main agent, 2026-09-29) — fix `6e732fb6`

| Finding | Fix | Test |
|---|---|---|
| Major: download after token issuance skips the database check | `download_deliverable` calls `_require_consistent_masters(DEFAULT_USER_ID, …)` before serving; the host resolves every subject to `DEFAULT_USER_ID` (`server/auth.py`) | `test_a_diverged_master_is_refused_by_every_consuming_route` now downloads with a token issued before the head moved (409) |
| Major: overlapping Gate C projections land out of order | The stage → check → promote → project → export section runs under `artifact_master_lock`: a PostgreSQL session advisory lock on `master-authority:<user>:<project>:<artifact>`, or a process-local lock on a single-writer database | `test_overlapping_gate_c_approvals_of_one_artifact_are_serialized` records `stage, project, stage, project`; without the lock it fails with `[409, 200]` (verified by temporarily removing the lock). It passed on PG16 too |
| Major: the expected digest is recomputed from the file after staging | `GoldenAHostIntegration.staged_version` returns the version record's `output_sha256`, and `promote_staged` takes `expected_content_digest`. `prepare_candidate` refuses changed bytes | `test_bytes_changed_after_staging_are_refused_before_the_first_registration` (no head, no candidate row) |
| Moderate: a missing projection passes verify | `verify_project_masters` raises for a database head with no projection | the unit verify test now expects `{}` to diverge |
| Moderate: a concurrent `CandidateIdentityConflictError` becomes a 500 | Added to `_MASTER_CONFLICTS` (409) | by inspection; the race needs two sessions inserting the same id |
| Moderate: backfill skips non-video masters, but verify includes them | Both cover `EPISODE_VIDEO` only. No host route approves another kind: Gate C `resource_type` is `Literal["videos"]` and `artifact_key_for` is always `episode_video`. Backfill also reports missing output digests and digest mismatches as diverged | backfill tests |

**Verification at `6e732fb6`:**

- **SQLite:** 1247 passed, 1 skipped. The suites are V2-02, Gate, M3, production, M4 approved-master, candidate store and architecture.
- **PG16:** 58 passed (`arcreel_v201`).
- **Static gates:** ruff, basedpyright 0/0, lint-imports, deptry and audit_tests are clean.

---

# Confirmation review (job `task-mum8xb76-95rsgo`, reviewed HEAD `f6e573f0`)

The reviewer output is saved verbatim below.

## 1. HEAD reviewed

`f6e573f0508f193affe601c611725686f56a4bec` on `feat/r2-v2-02-master-authority`. The worktree was clean.

## 2. Verdict

**CHANGES_REQUIRED.** The fix addresses several prior failure modes, but the new lock can exhaust the PostgreSQL connection pool, and SQLite serialization does not extend across processes.

## 3. Per-prior-finding status

| Finding # | Original severity | Status | Current file:line evidence | Original failure covered by a test? |
|---|---|---|---|---|
| 1. Download after token issuance | Major | FIXED | [gates.py:529](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/routers/gates.py:529), [gates.py:538](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/routers/gates.py:538) recheck the database before serving. | **Yes:** [test_gates_master_authority.py:97](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/tests/integration/server/routers/test_gates_master_authority.py:97) issues a token, moves the head, then downloads. |
| 2. Overlapping Gate C projections | Major | PARTIALLY_FIXED | [gates.py:385](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/routers/gates.py:385) locks staging through projection; [master_authority.py:69](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/services/master_authority.py:69) uses only a process-local SQLite lock. | **Yes, within one process:** [test_gates_master_authority.py:166](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/tests/integration/server/routers/test_gates_master_authority.py:166). No cross-process test. |
| 3. Digest recomputed after staging | Major | FIXED | [host_integration.py:330](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/r2/m3/host_integration.py:330) returns the recorded digest; [master_authority.py:167](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/r2/host_hardening/master_authority.py:167) passes it to byte verification. | **Yes:** [test_master_authority_unit.py:135](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/tests/integration/r2/host_hardening/test_master_authority_unit.py:135) changes bytes before first registration. |
| 4. Missing projection passes verification | Moderate | FIXED | [master_authority.py:209](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/r2/host_hardening/master_authority.py:209) raises when a database head has no projection. | **Yes:** [test_master_authority_unit.py:151](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/tests/integration/r2/host_hardening/test_master_authority_unit.py:151) checks the empty projection. |
| 5. Candidate identity conflict returns 500 | Moderate | FIXED | [gates.py:223](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/routers/gates.py:223) includes `CandidateIdentityConflictError` in the 409 mapping. | **No:** no test creates the concurrent insertion conflict. |
| 6. Backfill skips non-video masters | Moderate | PARTIALLY_FIXED | [master_authority.py:76](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/services/master_authority.py:76) now excludes non-video projections from verification, while [backfill_master_authority.py:48](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/scripts/r2/backfill_master_authority.py:48) still skips them. This removes the reported divergence by narrowing the checked set; it does not backfill every existing file master as [ADR-0096:42](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/docs/adr/0096-v2-the-m7-master-head-is-the-sole-master-authority.md:42) specifies. | **No:** [test_backfill_master_authority.py:53](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/tests/integration/scripts/r2/test_backfill_master_authority.py:53) creates video masters only. |

These are source-review assessments; the targeted tests did **not** pass in this environment.

## 4. New findings

| Severity | File:line | Scenario | Confidence |
|---|---|---|---|
| Major | [master_authority.py:61](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/services/master_authority.py:61), [engine.py:52](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/lib/db/engine.py:52), [gates.py:359](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/routers/gates.py:359) | **Pool starvation:** a PostgreSQL approval holds one pooled connection for its session-level advisory lock, then opens another for promotion. At the configured 30-connection maximum, 30 simultaneous approvals can occupy every connection before the promoting requests obtain their second connection. Requests then wait for pool timeout. The composite pre-check runs before lock acquisition ([gates.py:307](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/routers/gates.py:307)); I found no opposing lock order there. | High; derived from code and pool configuration, not exercised on PostgreSQL. |
| Major | [master_authority.py:63](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/services/master_authority.py:63) | **Possible pooled lock leak:** acquisition precedes the `try`, and the `finally` awaits an unshielded unlock. If cancellation or an error prevents that unlock from completing while the physical connection remains reusable, transaction rollback does not release a *session-level* advisory lock. A later borrower can inherit it. Normal body errors do reach the unlock. | High risk; cancellation and connection-reuse behavior needs a PostgreSQL fault test. |
| Major | [master_authority.py:69](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/services/master_authority.py:69), [gates.py:388](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/routers/gates.py:388) | **SQLite across processes:** the fallback lock exists only in one Python process. Two workers sharing the SQLite database and manifest can again promote A then B but project B then A, because the database commit and file projection are separate steps. | High for a multi-process deployment; deployment topology was not verified. |

The stricter missing-projection rule can return a transient 409 to composite approval, publish approval, token issuance, or download between promotion commit and projection ([master_authority.py:209](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/r2/host_hardening/master_authority.py:209), [gates.py:234](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/routers/gates.py:234)). **Judgment:** this is an acceptable refusal while authority and projection disagree, rather than a new correctness defect.

For digests, the current staging writer records bare lowercase hex ([host_integration.py:281](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/r2/m3/host_integration.py:281)); both Gate C and backfill call `staged_version`, which returns lowercase `sha256:` form ([host_integration.py:330](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/r2/m3/host_integration.py:330), [gates.py:350](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/routers/gates.py:350), [backfill_master_authority.py:63](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/scripts/r2/backfill_master_authority.py:63)). Candidate verification compares that form exactly ([candidate_store.py:97](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/lib/candidate_store.py:97)). I found no inconsistency for records produced by this writer; uppercase `SHA256:` prefixes are not normalized.

The download route’s `DEFAULT_USER_ID` matches the current auth mapping: authenticated subjects become that ID at [auth.py:430](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/auth.py:430), and the token is checked for its project at [auth.py:164](/home/anhtuan/content-production-os/.worktrees/r2-v2-02/server/auth.py:164). It is a single-user model, not evidence of a new per-user authorization bypass in this fix.

## 5. Commands run

- `git rev-parse HEAD`, `git branch --show-current`, `git status --porcelain=v1`: exact requested HEAD and branch; clean worktree, exit 0.
- `git diff --stat 7c5eb6cc..f6e573f0` and `git diff --stat 7f2f3e3b..f6e573f0`: both ranges resolved; exit 0. Relevant diff hunks and current numbered source were inspected.
- `git diff --check` for both ranges: exit 0, no output.
- `TMPDIR=/dev/shm .venv/bin/python -m pytest -q -p no:cacheprovider` over the three targeted integration files, bounded by `timeout 240s`: exit **1**; **15 setup errors, 0 passed**. The first setup hung in Alembic/aiosqlite until pytest-timeout at 120 seconds; remaining tests errored from that setup.
- The same pytest form over `tests/unit/r2/host_hardening/test_master_authority.py` and `tests/unit/r2/test_master_authority_boundaries.py`, bounded by `timeout 45s`: exit **124**, no test output or pass count.

## 6. Coverage limits

No current-HEAD test pass is claimed. PostgreSQL lock cancellation, pool saturation, and SQLite multi-process scheduling were not exercised. The graph catalog did not list this worktree, so structural review used the exact diffs and direct source inspection. Historical version records with nonstandard digest prefixes and actual deployment worker count were not available to verify.

## 7. Final JSON object

{"schema_version":1,"status":"V2_02_NOT_ACCEPTED","reviewed_head":"f6e573f0508f193affe601c611725686f56a4bec","reviewer":"codex","reviewed_at":"2026-09-29T05:43:07Z","required_skips":["Targeted integration pytest: 15 setup errors after Alembic/aiosqlite setup timed out; no tests passed","Targeted unit pytest: external 45-second timeout, exit 124, no result","PostgreSQL cancellation and pool-saturation tests, SQLite multi-process test, restore drill and browser flow not run"],"material_unknowns":["Whether cancellation can return a PostgreSQL connection to this pool with its session-level advisory lock still held","Actual multi-process SQLite deployment topology","Historical version-record digest prefix formats"]}

---

## Resolution of the confirmation review (main agent) — fix `6933bf40`

| Finding | Fix | Test |
|---|---|---|
| Major (new): pool starvation from a lock connection held beside the promotion session | The session advisory lock was removed. Each step uses one connection: promotion, then projection | by construction |
| Major (new): a session-level lock can leak on cancellation | The lock is now the projection transaction's row or database write lock, which ends with the transaction (commit, rollback or connection close) | `test_a_projection_holds_the_artifact_until_it_commits` (PostgreSQL) |
| Major (new) and prior 2 (partial): SQLite across processes | `project_if_current` rewrites the `master_authorities` row unchanged first. That takes the PostgreSQL row lock, or the SQLite database write lock across processes (`busy_timeout` 30 s, `lib/db/engine.py`). It then projects only if the promoted candidate is still the head; otherwise it returns 409 `master_superseded` and writes nothing | `test_a_superseded_promotion_is_not_projected`, `test_overlapping_gate_c_approvals_of_one_artifact_end_consistent` |
| Prior 6 (partial): ADR says every file master | ADR-0096 §5 now scopes verification and backfill to `EPISODE_VIDEO`, the only kind any host route approves (Gate C `resource_type` is `Literal["videos"]`, and `artifact_key_for` is `episode_video`) | backfill tests |
| Prior 5: no test for a concurrent identity conflict | unchanged; the mapping is verified by inspection | — |

**Known limit.**

- **Where it applies.** On SQLite, a projection holds the database write lock while it writes
  the manifest and the export copy.
- **What can go wrong.** Other writers wait up to the 30 s busy timeout.
- **Why this is acceptable.** V1 and V2 production run on PostgreSQL, and SQLite is the
  development database.

**Verification at `6933bf40`:**

- **SQLite:** 1248 passed, 2 skipped (PostgreSQL-only).
- **PG16:** 60 passed (`arcreel_v201`).
- **Static gates:** ruff, basedpyright 0/0, lint-imports, deptry and audit_tests are clean.
