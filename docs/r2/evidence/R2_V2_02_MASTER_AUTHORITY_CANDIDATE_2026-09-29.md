# R2 V2-02 master authority unification — candidate evidence (2026-09-29)

This is an implementation candidate awaiting an independent review. It is not accepted.

- **Decision:** `docs/adr/0096-v2-the-m7-master-head-is-the-sole-master-authority.md`
- **Plan:** `docs/superpowers/plans/2026-09-29-r2-v2-02-master-authority-unification.md`
- **Branch:** `feat/r2-v2-02-master-authority`, from `r2-v2/main` `7f2f3e3b`.
- **Candidate code HEAD:** `0cb1a896a54c0d16aac27a575f98570360750696`.
  - `3de5f786`: the feature.
  - `0cb1a896`: the projection pre-check and the 409 mapping.

## Deviations from the plan

- **Composition split.** The DB composition sits in `server/services/master_authority.py`. The
  pure pieces and the port-based unit sit in `r2/host_hardening/master_authority.py`, which
  keeps `r2` free of `lib.db` imports.
- **Additions:**
  - `GoldenAHostIntegration.version_file_for` and `.check_approvable`;
  - `ProductionApprovalService.check`, split out of `promote` with unchanged behavior.
- **Test layout.** The Gate route fixtures moved to `tests/integration/server/routers/conftest.py`
  and `GateProjectManager` moved to `tests/fakes.py`, as `scripts/audit_tests.py` requires.
- **Real media.** Gate C masters must now probe as media (M7 H3–H4), so the route fixtures use
  real MP4 shots.

## Verification at `0cb1a896`

| Command | Result |
|---|---|
| `pytest -n 4 --timeout 300` over `tests/unit/r2/host_hardening`, `…/test_master_authority_unit.py`, `…/test_host_hardening_promotion.py`, `tests/integration/server/routers`, `tests/unit/r2/m3`, `…/test_backfill_master_authority.py`, `tests/unit/r2/test_master_authority_boundaries.py`, `tests/unit/lib/test_candidate_store.py`, `tests/unit/r2/production` (SQLite) | 1229 passed, 1 skipped |
| The same V2-02, Gate, promotion and backfill integration files on PG16 (`arcreel_v201`, head `c9e1f4a2b701`) | 56 passed |
| The approval-service, M4 approved-master, manifest-recovery, master-promotion and architecture-boundary suites (SQLite) | 70 passed |
| `tests/integration/r2/m3/test_host_integration.py` (real Remotion renders), at `3de5f786` | 2 passed (277 s) |
| ruff, ruff format, basedpyright, lint-imports, deptry, audit_tests | clean |

## Not run (coverage limits)

- **`tests/integration/r2/test_m6_dual_profile_acceptance.py`:** real Remotion renders, measured
  at about 800 s per pair. It exceeded a 400 s bound on the base branch as well. The change it
  covers, `ProductionApprovalService.check`, is a behavior-preserving extraction with passing
  unit tests.
- **The full golden restore drill and the browser e2e test**, which need renders plus a
  backup/restore. The drill gains the `MASTER_AUTHORITY_DIVERGED` check. A V2 release must run
  the drill.
- **The full backend suite**, per the sponsor's instruction to limit full runs.
