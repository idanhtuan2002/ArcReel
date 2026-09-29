# R2 V2-02b — serialize Gate C per artifact (2026-09-29)

This is an implementation candidate awaiting an independent review.

## Defect

`tests/integration/server/routers/test_gates_master_authority.py::test_overlapping_gate_c_approvals_of_one_artifact_end_consistent`
failed 2 of 6 runs on `r2-v2/main` `cca1eeaf` (SQLite). The race:

1. A stages, then B stages. The manifest now holds B's content fingerprint.
2. B promotes, then A promotes, so the head is A.
3. B's projection is superseded.
4. A's projection is refused by `ProductionApprovalService.check`, because of the fingerprint.

The database head is left without its projection.

## Fix

`5d387e4a059cdce97c4ef25c5d3cf85627a477ee` on `fix/r2-v2-02b-serialize-gate-c`, from `cca1eeaf`.

- **What runs under the lock.** `server/services/master_authority.py::serialized_artifact`
  holds the artifact's `master_authorities` row write lock for one transaction. Gate C stages,
  checks, promotes (`master_authority_unit(..., defer_commit=True)`) and projects inside it,
  then commits.
- **Refused projections.** A refused projection rolls the promotion back and returns 409
  `master_conflict`.
- **After the commit.** The export and the Gate C receipt follow it.
- **The first row.** A concurrent first creation of the row is retried, bounded to 5 attempts.

## Verification at `5d387e4a059cdce97c4ef25c5d3cf85627a477ee`

| Run | Result |
|---|---|
| `test_gates_master_authority.py`, 5 repeated runs on SQLite; the overlapping test runs 3 concurrent rounds each | 6 passed ×5 |
| The same file, 3 repeated runs on PG16 (`arcreel_v201`) | 6 passed ×3 |
| The master-authority unit, Gate export and router, and backfill suites on PG16 | 40 passed |
| host_hardening, Gate routers, M3, backfill, architecture, candidate store and production suites on SQLite | 1247 passed, 2 skipped |
| ruff, basedpyright, lint-imports, deptry and audit_tests | clean |

## Limits

- **SQLite.** A Gate C holds the database write lock for its stage copy and projection. Other
  writers wait up to the 30 s busy timeout. Production runs PostgreSQL.
- **Commit failures.** A commit that fails after the projection leaves the projection ahead
  until a retry with the same `approval_record` converges.

---

# Codex review 1 (job `task-mumbkyt0-9t44fw`, reviewed HEAD `18c50eec`), verbatim

**HEAD reviewed:** `18c50eece5633fced6d52e45a8d7bcebb22b625f`  
**Verdict:** **CHANGES_REQUIRED**

| Severity | File:line | Scenario | Confidence |
|---|---|---|---|
| High | [gates.py:389](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:389) | The artifact lock ends before composite export. Approval A can begin copying its final, approval B can then promote and export a newer final, and A can replace B’s export afterward. Both requests can return 200 while `output/` contains A’s bytes under B’s head. The overlapping test uses shots, so it does not exercise this window. | High |
| High | [master_authority.py:81](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/services/master_authority.py:81) | Projection changes files before the enclosing database commit. If that commit fails or is cancelled, rollback restores the old database head but cannot restore its file projection. The evidence document acknowledges projection ahead until a retry; no commit-failure recovery test establishes that a retry occurs. | High |
| Medium | [test_gates_master_authority.py:188](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:188) | Three timed rounds increase the chance of overlap but do not force the critical interleaving. The test checks final agreement, not export consistency or a failed commit. | High |

The no-op `UPDATE` is a valid lock acquisition for an existing row on PostgreSQL and a write-lock acquisition on SQLite by inspection. The same session carries promotion through projection; its nested savepoints and deferred promotion commit do not themselves end the outer transaction.

**Commands run:** `git status`, `git rev-parse`, `git diff cca1eeaf..18c50eec`, `git log`, targeted `rg`/`nl` source inspection, and the requested bounded pytest command. Pytest failed before collection: Python found **no usable temporary directory** in `/tmp`, `/var/tmp`, `/usr/tmp`, or the checkout. No tests ran. The checkout remained clean.

**Coverage limits:** The codebase graph was approval-blocked, so call paths were verified from source. PostgreSQL concurrency, cancellation, and commit failure were not fault-injected in this read-only environment.

```json
{
  "schema_version": 1,
  "status": "V2_02B_NOT_ACCEPTED",
  "reviewed_head": "18c50eece5633fced6d52e45a8d7bcebb22b625f",
  "reviewer": "codex",
  "reviewed_at": "2026-09-29T06:55:20Z",
  "required_skips": [
    "Targeted pytest failed before collection: no usable temporary directory"
  ],
  "material_unknowns": [
    "PostgreSQL concurrent composite export behavior was not executed",
    "Database commit failure and cancellation after file projection were not fault-injected"
  ]
}
```

## Resolution — `1c22dccf`

The two-phase Gate C:

- **Phase 1** stages, checks and promotes under the row lock, then commits.
- **Phase 2**, under the row lock again and only while the promoted candidate is still the
  head, restores its semantic state, projects, and writes the composite export.

| Finding | Fix | Test |
|---|---|---|
| High: export outside the lock | Phase 2 writes the export under the lock, only for the current head | `test_an_approval_superseded_before_its_projection_writes_nothing` forces a newer approval between an older one's promotion and its projection. It asserts that the older one gets 409 and that the export holds the newer bytes, and it fails without the phase-2 head check |
| High: projection before commit | The projection now always follows the commit, so files never run ahead of the database | by construction |
| Medium: the timed test does not force the interleaving | The forced-interleaving test above. The overlapping test runs on independent connections (`concurrent_session_factory`, file WAL SQLite, or PG) | — |

**Verification at `1c22dccf`:**

- `test_gates_master_authority.py`: 7 passed ×3 on PG16, 7 passed ×3 on SQLite.
- The master-authority unit, Gate export and router, and backfill suites on PG16: 40 passed.
- The broad SQLite suites: 1248 passed, 2 skipped.
- Static gates: clean.

**Known behaviour.**

- **Superseded approvals.** An approval superseded before phase 2 returns 409
  `master_superseded` (runbook §4b).
- **Transient refusals.** Between phase 1 and phase 2, a master-consuming read of the same
  artifact may get a transient 409 `master_diverged`.
