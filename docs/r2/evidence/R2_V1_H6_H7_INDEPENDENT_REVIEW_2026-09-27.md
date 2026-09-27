# R2 V1 H6/H7 independent review — 2026-09-27

Reviewer: a separate agent with its own context, read-only. Reviewed HEAD:
`1f287029` (diff `e8385978..1f287029`). The tree was clean at the start and at
the end.

**Verdict: CHANGES_REQUIRED.** There are 0 critical, 6 important and 6 minor
findings.

## Important

| ID | Finding | Evidence |
|---|---|---|
| I1 | A failed target verification writes `REJECTED` into the source set's `state.json`, and later restores refuse the set (`deployment_backup.py` verify, `load_restorable_manifest`). A target-side verdict corrupts source-side authority. | Probe run |
| I2 | The DB password reaches `pg_dump`/`pg_restore` argv, which is visible in `ps` and `/proc/*/cmdline`. This contradicts the CLI docstring and the runbook. | Argv-recording wrapper |
| I3 | `RedactingFormatter` regexes are O(n²) on long whitespace-free tokens. A single 80k-character token takes 21–29 s. | Timing |
| I4 | VERIFIED proves less than frozen H6 / spec §8 steps 6–7. `current_version` pointers are not resolved; Artifact Manifest entries are not resolved; the release SHA is not checked; the set is marked VERIFIED without Golden A/B. | Probe (`current_version: 7`, no records → VERIFIED) + reading |
| I5 | Raw provider job IDs are still logged at about 10 backend sites (kling, vidu, agnes, dashscope, ark, gemini, image kling/vidu). The canary test uses a synthetic executor. | Reading |
| I6 | Inline (non-queued) text generations have no durable request join: `api_calls` has `task_id` only. | Reading |

## Minor

- **M1.** Sequence writes (`nextval`/`setval`) during capture evade the write
  counter. The after-capture fence checks are untested.
- **M2.** Span values are not policed. `candidate_id` embeds a user-authored
  `resource_id`, and a caller-supplied `X-Request-ID` is accepted with a
  permissive shape.
- **M3.** Credential exclusion applies only to the `data` root; a
  `claude_data` root may hold CLI credentials. The `system_setting` key
  regex is heuristic.
- **M4.** The production tracer install writes OpenTelemetry private globals.
- **M5.** The migration test is SQLite only; the reviewer ran PostgreSQL
  upgrade/downgrade manually and it was OK. The boundary test asserts an
  implementation detail. A pre-existing private-attribute pattern is reused.
- **M6.** The manifest stores only a configuration digest.
  `BackupSetRepository` / `backup_sets` are now unused outside tests.

## Previous `m7d_prerequisite_review` findings

| Finding | Status |
|---|---|
| C1 | Partly resolved (I4) |
| C2 | Mostly resolved (I6) |
| C3 | Resolved at claim level (I4 for the label) |
| I-a | Resolved |
| I-b | Resolved by redesign |
| I-c | Mostly resolved (I2, M3) |
| I-d | Partly resolved (I5) |

## Reviewer verification

- 498 targeted tests passed (SQLite).
- 20 + 4 passed on disposable PostgreSQL 18.
- Alembic on PostgreSQL: upgrade, downgrade and re-upgrade OK.
- Static checks clean.

Not run: the full suite, frontend/website, Golden/E2 and real provider backends.
