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
