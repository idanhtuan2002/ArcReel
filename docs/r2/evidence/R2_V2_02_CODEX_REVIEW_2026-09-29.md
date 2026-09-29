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
