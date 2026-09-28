# R2 V1 operator cycle 1 — journal

This is the operator's record of the first real V1 release cycle, the V2 start gate
condition 3 ("one stable operator release cycle has been observed", strategy §7).

- **Filled in by:** the operator.
- **Environment:** `~/arcreel-v1-trial`, a separate PostgreSQL 16 container
  (`arcreel-v1-trial-pg`) and a separate data root, running code `0610b51b`, which is tag
  `r2-v1.0.0` plus the operator CLI.
- **Release mode:** `PRODUCTION_CANDIDATE`.
- **Guide:** `~/arcreel-v1-trial/HUONG_DAN.md`.

## Summary (fill in at the end)

| Item | Value |
|---|---|
| Dates | |
| Product (project name, topic) | |
| Paid providers used | none / … |
| Total paid cost | |
| Final digest (Gate D) | |
| Backup set and restore check | |
| Verdict: stable cycle? | yes / no, and why |

## Step log

Record every step, including the ones that went smoothly.

| # | Step | Start–end | Result | Problem, confusion or workaround | Cost |
|---|---|---|---|---|---|
| 1 | Start the server (`./start.sh`), log in | | | | |
| 2 | Create the project in the UI | | | | |
| 3 | Gate A: Greenlight (source digest from `./op.sh digests`) | | | | |
| 4 | Gate B: Lock script (source and script digests) | | | | |
| 5 | Produce the shots (`./op.sh produce --project …`) | | | | |
| 6 | Review the shot files in `data/<project>/production/` | | | | |
| 7 | Gate C: shots (`./op.sh approve-shots --project …`) | | | | |
| 8 | Gate C: final (`./op.sh approve-final --project … --audio MUTE`) | | | | |
| 9 | Download and review the final (Project settings, Final Cut) | | | | |
| 10 | Gate D: Publish Approval | | | | |
| 11 | Publish manually (optional; platform, URL) | | | | |
| 12 | Stop, back up (`./backup.sh`), start again | | | | |
| 13 | Restore check (`./restore-check.sh backups/bs-…`) | | | | |

## Findings

Record each finding as it happens. A finding that no existing owner can fix is a V2 gap.

| # | Severity (blocker / friction / note) | What happened | Expected | Owner or proposed fix |
|---|---|---|---|---|
| | | | | |
