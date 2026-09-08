# Frozen regression selections for R2-M4 Gate C

Recovered as exact pytest node-id / file sets, not directory globs (directories
have grown since these baselines with C04 and M4 additions).

| Selection | Source commit | Count | How recovered |
|---|---|---|---|
| `m1_contracts.nodeids.txt` | `9330bcf3` (M1 corpus) | 41 | `pytest --co -q tests/unit/r2/contracts/` at the corpus commit |
| `m2_production.nodeids.txt` | `9cc04edd` (M2 corpus) | 53 | `pytest --co -q tests/unit/r2/production/ tests/integration/r2/production/` at the corpus commit |
| `m3_focused.nodeids.txt` | `1985b815` (M3 tip / pinned baseline) | 122 | `pytest --co -q tests/unit/r2/m3/ tests/integration/r2/m3/ tests/unit/r2/production/ tests/integration/r2/production/ tests/unit/r2/contracts/` at the corpus commit |
| `host_arcreel_focused.paths.txt` | M2 plan Step 6 file set | 349 | verbatim from `docs/superpowers/plans/2026-09-06-r2-m2-artifact-bridge-implementation-plan.md` |

Run each against the M4 final HEAD with `pytest -q $(cat <file>)`. Required exact
outcomes: 41 / 53 / 122 / 349. These match the M4 plan Global Constraints and the
post-remediation acceptance in `R2_M4_BASELINE_CI_REMEDIATION.md` — no
re-baselining occurred.
