# R2 V2-00 — branches and restored staging baseline (2026-09-29)

This record implements strategy §5, items 11 and 12, after the sponsor's V2 start decision
(`R2_V2_START_DECISION_2026-09-29.json`).

## Lineage

| Branch | Head | Purpose |
|---|---|---|
| `r2-v1/maintenance` | `2484789f` | V1 maintenance line. It descends from the annotated tag `r2-v1.0.0` (`54240210`), adding the operator CLI, runbook fixes and records. |
| `r2-v2/main` | `2484789f` at creation | V2 development line, created from the same V1 lineage. Worktree: `.worktrees/r2-v2-main`. |

V1 fixes land on `r2-v1/maintenance` first and are merged forward into `r2-v2/main`.

## Staging baseline

| Item | Value |
|---|---|
| Source | the operator cycle 1 backup set `bs-20260928T190438Z`, manifest `sha256:7bbca1200fade0a39ee8a41808d9c1cecf8d676de3988aae649eef35ada72c16`, release `0610b51b` |
| Database | its own container `arcreel-v2-staging-pg` (`postgres:16`, volume `arcreel-v2-staging-pgdata`, 127.0.0.1:55470) |
| Data root | `~/arcreel-v2-staging/data` |
| Restore | `scripts.r2.deployment_backup restore`, using the PG16 client shims |
| Verify | target `v2-staging-1`: `checks_passed: true`, no reason codes; 82 tables, 51 files, 9 references, 4 media decoded |

## Rule for schema evolution

Each V2 migration is rehearsed against a fresh restore of this baseline before it is accepted
(strategy §5 item 12): restore, then `alembic upgrade head`, then `verify`. The staging database
is never a development or test database.
