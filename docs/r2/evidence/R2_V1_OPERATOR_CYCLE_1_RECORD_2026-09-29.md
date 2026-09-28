# R2 V1 operator cycle 1 — record (2026-09-28/29)

The agent compiled this record from the trial server log, the trial database (read-only queries),
the backup ledger and the verification verdict. The sponsor ran every step and chose to skip the
narrative journal. The journal template (`R2_V1_OPERATOR_CYCLE_1_JOURNAL.md`) therefore holds no
operator narrative. The friction points below are the ones the agent observed in the conversation.

## Environment

| Item | Value |
|---|---|
| Code | `0610b51b` (tag `r2-v1.0.0` plus the operator CLI), detached worktree `.worktrees/r2-v1-operator-trial` |
| Release mode | `PRODUCTION_CANDIDATE`, logged at each start (23:23, 01:53, 02:04) |
| Database | disposable-for-trial `postgres:16` container `arcreel-v1-trial-pg`, own volume |
| Data root | `~/arcreel-v1-trial/data` |
| Paid providers | none configured; no paid call |

## Product and decisions

The project is `du-an-01-649c62c1` ("du an 01"). Its content is the Golden A H.264 explainer, and the sponsor performed every step.

| Gate | Time (+07) | Record |
|---|---|---|
| A: Greenlight | 01:15:05 | UI; source digest `sha256:01183d75…` |
| B: script lock | 01:16:22 | UI; `LOCK`, source `sha256:01183d75…`, script `sha256:da84aec9…` |
| C: shots SH01–SH03 | 01:34:36 | operator CLI; 3 receipts |
| C: final | 01:36:43 | operator CLI; `audio_decision = MUTE`, verified silent by the server; final 75.16 s, `sha256:1bcd60c2ee2765e7b5a4aef886963abc1bbb2b23c42bf0f796364a1150431aa6` |
| Review | 01:53–02:03 | four deliverable token downloads (UI) |
| D: Publish Approval | 01:59:28 and 02:04:11 | UI; both `APPROVE_PUBLISH`, `youtube`/`private`, the same final digest |
| Manual publication | — | not done in this cycle |

## Backup and restore

| Item | Result |
|---|---|
| Backup 1 | `bs-20260928T185254Z`, taken before Gate D; superseded |
| Backup 2 | `bs-20260928T190438Z`, `COMPLETE`, 51 files, 82 tables, manifest `sha256:7bbca120…2c16`, recovery point 2026-09-28T19:04:39Z |
| Credential handling | 5 credential-bearing tables sanitized, as designed |
| Restore check | new empty database `arcreel_restore_20260928t190456z` and data root; restore 1.8 s |
| Verify | `checks_passed: true`, no reason codes; 82 tables, 51 files, 9 references, 4 media decoded; target `trial-20260928T190456Z` at `0610b51b` |

## Friction observed (agent-observed)

| # | Severity | What happened | Fix or disposition |
|---|---|---|---|
| 1 | blocker (fixed) | Gate C had no operator surface; the API needs a full rendered-candidate command | `scripts/r2/v1_operator.py` (`0610b51b`) |
| 2 | blocker (fixed) | The runbook's start command `python -m server.app` fails | runbook fixed (`9fc6cef6`) |
| 3 | friction | Markdown code fences pasted into the shell started a subshell whose output was swallowed | the guide shows bare command lines |
| 4 | friction | `$DU_AN` was lost in a new shell | the guide uses the literal project name |
| 5 | friction | A `<placeholder>` was typed literally in `restore-check` | `restore-check.sh` defaults to the newest set |
| 6 | friction | The operator backed up before Gate D, then again after | the guide orders Gate D before the backup |
| 7 | note | Gate D was recorded twice with identical content; the reason is not recorded | append-only history keeps both; harmless |
| 8 | product gap | No-provider production can only make the Golden A content (a fixture-specific director) | V2 input |
| 9 | product gap | The sponsor wants autonomous research and story writing. V1 has no M9, and it refuses the host Agent in release mode | V2 input (strategy §7 condition 4) |

## Verdict

The cycle completed end to end in release mode, with no failed step:

- A → B → C (shots) → C (final) → review and download → D → backup → restore into a clean target
  → verify.

The agent judges it a **stable operator release cycle** on this objective evidence. The sponsor
waived the narrative journal and asked to proceed to the next step. That is recorded in
`R2_V2_START_DECISION_2026-09-29.json`.
