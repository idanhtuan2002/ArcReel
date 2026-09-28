# R2 V1-06 — closing gate (2026-09-28)

**Packet:** V1-06, covering E1 remediation, the paid-route inventory, route qualification and the U3 backport. Decisions are in ADR-0091 and its amendment.

## Candidate

| What | Value |
|---|---|
| Code HEAD for the gates | `489085413cad789b563102f063140dfc1ed06ecb`: the last V1-06 commit, which includes every confirmation-review fix |
| Independent review | `R2_V1_06_INDEPENDENT_REVIEW_2026-09-28.md`: CHANGES_REQUIRED; F1–F15 fixed or disclosed |
| Confirmation review | `R2_V1_06_CONFIRMATION_REVIEW_2026-09-28.md`: CHANGES_REQUIRED (N1 major); N1–N6 fixed in `4b137f64`, `fe472726` and `9bac8e94`, and amendment item 1 corrected in `48908541` |

## Gates

| Gate | Command | Result |
|---|---|---|
| Static | `ruff check .`, `ruff format --check .`, `basedpyright --warnings`, `lint-imports`, `scripts/audit_tests.py --check` | clean: 0 errors, 0 warnings; 20 kept, 0 broken; 0 violations |
| deptry | `deptry lib server alembic scripts tests r2` | no dependency issues |
| Backend full (SQLite) | `pytest -n 4 --dist loadfile -q -p no:cacheprovider` at `48908541` | `1 failed, 14975 passed, 44 skipped` in 1:35:30 (see below) |
| PG16 dialect | the CI `postgres-compat` job, reproduced locally on disposable `postgres:16` at `8568a195` (V1-06 plus O2a code): `alembic upgrade head` ×2, `downgrade base`, `upgrade head`; then `pytest -m "uses_db and not sqlite_only" -n 4 --dist loadfile` | alembic exit 0; `1068 passed` in 1:26:25, 0 failed |

**The one full-suite failure** is `tests/integration/scripts/r2/test_verify_m7_scope_git.py::test_verify_m7_scope_passes_against_the_real_baseline_and_repo`.

- **Cause.** The test asserts a clean working tree. Uncommitted V1-07 files were in the tree while the suite ran, which trips it by design.
- **Rerun.** The test passed on the clean tree at `48908541` (`2 passed`) and again at `8568a195` (among `86 passed`).
- **Limit.** No other test failed. The suite was not rerun end to end on a clean tree, because its runtime is 1.5 hours; the sponsor asked to limit full runs.

## Verdict

V1-06 is **ACCEPTED on its reviewed scope**, with these limits:

- **E1 stays `PENDING_GATES`.** A full `COMPATIBLE` verdict needs the runner-written 12-gate manifest, and the browser gate belongs to V1-07.
- **Every video route stays disabled** until offline adapter evidence exists.
- **The Agent and trial runs are refused** in `PRODUCTION_CANDIDATE`.
- **No paid canary has run.** Paid canaries need the operator's separate authorization.
- **The known limits of the ADR-0091 amendment apply.**
