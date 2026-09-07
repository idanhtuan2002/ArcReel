# R2-M4 Final Verification

- Starting head: `863ab4993b3dce725fb5f12b5d2f2a74a79031a3`
- Final head: `01e71a809b449f8470dd35b9eec86183ab0d9f6d`
- Branch: `feat/r2-m4-production-intelligence`
- Worktree clean: **False**
- H1 / R2-HOST-001: **OPEN**

## Suites

| Suite | pass | fail | skip | result |
|---|--:|--:|--:|---|
| m4_focused | 177 | 0 | 0 | PASS |

## Golden baseline: 12/12 — PASS

MUT-01..MUT-08: 8/8 (see test_golden_12_mutations.py).

## Frozen regression re-baselining

```json
{
  "all_pass": true,
  "expected": {
    "host_frozen": 349,
    "m1_frozen": 41,
    "m2_frozen": 53,
    "m3_focused": 122
  },
  "note": "Exact node-id / file selections recovered from the pinned corpus commits (M1 9330bcf3, M2 9cc04edd, M3 1985b815; Host set from the M2 plan). Figures match the M4 plan Global Constraints and R2_M4_BASELINE_CI_REMEDIATION.md; no re-baselining occurred.",
  "results": [
    {
      "expected": 41,
      "fail_count": 0,
      "pass_count": 41,
      "result": "PASS",
      "selection_ref": "docs/r2/evidence/frozen_selections/m1_contracts.nodeids.txt",
      "skip_count": 0,
      "suite_id": "m1_frozen"
    },
    {
      "expected": 53,
      "fail_count": 0,
      "pass_count": 53,
      "result": "PASS",
      "selection_ref": "docs/r2/evidence/frozen_selections/m2_production.nodeids.txt",
      "skip_count": 0,
      "suite_id": "m2_frozen"
    },
    {
      "expected": 122,
      "fail_count": 0,
      "pass_count": 122,
      "result": "PASS",
      "selection_ref": "docs/r2/evidence/frozen_selections/m3_focused.nodeids.txt",
      "skip_count": 0,
      "suite_id": "m3_focused"
    },
    {
      "expected": 349,
      "fail_count": 0,
      "pass_count": 349,
      "result": "PASS",
      "selection_ref": "docs/r2/evidence/frozen_selections/host_arcreel_focused.paths.txt",
      "skip_count": 0,
      "suite_id": "host_frozen"
    }
  ]
}
```

## Real execution evidence

| method | seam | result |
|---|---|---|
| REUSE | fixture-local | PASS |
| SCREEN_CAPTURE | fixture-local | PASS |
| DETERMINISTIC | ffmpeg-deterministic | PASS |
| COMPOSITE | ffmpeg-deterministic | PASS |
| GENERATED_IMAGE | real local/approved provider | WAIVER_REQUIRED |
| GENERATED_VIDEO | real local/approved provider | WAIVER_REQUIRED |

Real-evidence result: **INCOMPLETE_PENDING_WAIVER**

## Architecture

- Blocking violations: **0**
- Unapproved Host runtime changes: **0**
- DB migrations added by M4: **0**

This milestone does not claim RECOVERY_VERIFIED or PRODUCTION_CANDIDATE; H1 remains OPEN.

