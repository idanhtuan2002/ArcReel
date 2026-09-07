# R2-M4 Final Verification

- Gate D status: **INCOMPLETE_PENDING_WAIVER** (`gate_d_pass=False`)
- Starting head: `863ab4993b3dce725fb5f12b5d2f2a74a79031a3`
- Verified head: `593fce5a56014c6f2602876c5f7c8f01b391aedb` (expected `593fce5a56014c6f2602876c5f7c8f01b391aedb`, match: True)
- Branch: `feat/r2-m4-production-intelligence`
- Worktree clean (strict / modulo generated evidence): **False / True**
- H1 / R2-HOST-001: **OPEN**

> This evidence certifies the tree at `verified_head`. When committed it is a
> docs-only child of that commit; no code, test, or contract path changes.

## Repo-wide gates

| gate | result |
|---|---|
| ruff_check | PASS |
| ruff_format | PASS |
| basedpyright | PASS |
| deptry | PASS |
| lint_imports | PASS |
| audit_tests | PASS |

## Suites

| suite | pass | fail | skip | result |
|---|--:|--:|--:|---|
| m4_focused | 270 | 0 | 0 | PASS |
| m1_frozen (expected 41) | 41 | 0 | 0 | PASS |
| m2_frozen (expected 53) | 53 | 0 | 0 | PASS |
| m3_focused (expected 122) | 122 | 0 | 0 | PASS |
| host_frozen (expected 349) | 349 | 0 | 0 | PASS |

## Golden baseline: 12/12 — PASS

| shot | expected director/method | actual | result |
|---|---|---|---|
| SH01 | OPENMONTAGE/REUSE | OPENMONTAGE/REUSE | PASS |
| SH02 | OPENMONTAGE/SCREEN_CAPTURE | OPENMONTAGE/SCREEN_CAPTURE | PASS |
| SH03 | OPENMONTAGE/DETERMINISTIC | OPENMONTAGE/DETERMINISTIC | PASS |
| SH04 | OPENMONTAGE/COMPOSITE | OPENMONTAGE/COMPOSITE | PASS |
| SH05 | TAKE/GENERATED_IMAGE | TAKE/GENERATED_IMAGE | PASS |
| SH06 | TAKE/GENERATED_VIDEO | TAKE/GENERATED_VIDEO | PASS |
| SH07 | TAKE/GENERATED_VIDEO | TAKE/GENERATED_VIDEO | PASS |
| SH08 | TAKE/COMPOSITE | TAKE/COMPOSITE | PASS |
| SH09 | ARCREEL_NATIVE/STOCK | ARCREEL_NATIVE/STOCK | PASS |
| SH10 | ARCREEL_NATIVE/DETERMINISTIC | ARCREEL_NATIVE/DETERMINISTIC | PASS |
| SH11 | ARCREEL_NATIVE/GENERATED_IMAGE | ARCREEL_NATIVE/GENERATED_IMAGE | PASS |
| SH12 | ARCREEL_NATIVE/GENERATED_VIDEO | ARCREEL_NATIVE/GENERATED_VIDEO | PASS |

## Fault overlays

| mutation | expected | observed | result |
|---|---|---|---|
| MUT-01 | PASS | PASSED | PASS |
| MUT-02 | PASS | PASSED | PASS |
| MUT-03 | PASS | PASSED | PASS |
| MUT-04 | PASS | PASSED | PASS |
| MUT-05 | PASS | PASSED | PASS |
| MUT-06 | PASS | PASSED | PASS |
| MUT-07 | PASS | PASSED | PASS |
| MUT-08 | PASS | PASSED | PASS |

## Real execution evidence

| seam | via | result | detail |
|---|---|---|---|
| REUSE | fixture-local | PASS |  |
| SCREEN_CAPTURE | fixture-local | PASS |  |
| DETERMINISTIC | ffmpeg-deterministic | PASS |  |
| COMPOSITE | ffmpeg-deterministic | PASS |  |
| GENERATED_IMAGE | real local/approved provider | WAIVER_REQUIRED | no local GPU model or Human-approved provider seam configured in this environment |
| GENERATED_VIDEO | real local/approved provider | WAIVER_REQUIRED | no local GPU model or Human-approved provider seam configured in this environment |

Real-evidence result: **INCOMPLETE_PENDING_WAIVER**; unresolved seams: ['GENERATED_IMAGE', 'GENERATED_VIDEO']; approved waivers: 0

## Architecture

- Blocking violations: **0**
- Unapproved Host runtime changes: **0**; DB migrations by M4: **0**

This milestone does not claim RECOVERY_VERIFIED or PRODUCTION_CANDIDATE; H1 remains OPEN.

