# R2 V1→V2 lineage — Codex confirmation review (2026-09-29)

Job `task-mum16oi9-cmfuu1`, Codex thread `01a0eae5-df6c-7fd0-83a9-b172bfec3314`, reviewed HEAD
`94445e281b9246195192bb81ff9860fe8e0f8712`. This confirms the fixes recorded in
`R2_V2_CODEX_REVIEW_2026-09-29.md`. The reviewer output is saved verbatim below; the main
agent's resolution follows it.

---

## 1. HEAD reviewed

`94445e281b9246195192bb81ff9860fe8e0f8712` on `r2-v2/main`. The worktree was clean.

## 2. Verdict

**CHANGES_REQUIRED.** The revised code closes the audio and canary failures, but resumed Agent accounting, final settlement retry, and startup cancellation remain incomplete. The targeted tests could not start in this read-only environment.

## 3. Per-finding status

| Original finding | Status | File:line evidence | Does a test exercise the original failure? |
|---|---|---|---|
| 1. Resumed spend booked twice | PARTIALLY_FIXED | [session_manager.py](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/server/agent_runtime/session_manager.py:1457) applies a baseline only when the in-memory last-exit record matches; [line 1288](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/server/agent_runtime/session_manager.py:1288) subtracts it from the next reported total. That record is initialized empty at line 381. | **Yes, narrow case:** `test_a_resumed_process_books_only_spend_beyond_the_restored_totals` at [test_accounting_characterization.py:1175](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/tests/unit/lib/test_accounting_characterization.py:1175) would fail on the old code. It does not test restart, another session exiting, or a non-restored total above the baseline. |
| 2. Canary setup failure leaves a hold | FIXED | [qualify_route.py:238](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/scripts/r2/qualify_route.py:238) loads credentials before reservation at line 240. | **Yes:** `test_a_canary_setup_failure_leaves_no_budget_hold` at [test_qualify_route.py:247](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/tests/integration/scripts/r2/test_qualify_route.py:247) makes credential loading fail and checks the held total; it would fail on the old ordering. |
| 3. Failed reconciliation loses retry handle | PARTIALLY_FIXED | [session_manager.py:1471](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/server/agent_runtime/session_manager.py:1471) retains the reference on a `False` result, but [line 1441](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/server/agent_runtime/session_manager.py:1441) discards the session after the final eviction attempt even if settlement failed. | **Yes, narrow case:** `test_a_failed_settlement_keeps_its_reference_for_a_retry` at [test_accounting_characterization.py:1210](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/tests/unit/lib/test_accounting_characterization.py:1210) manually invokes settlement twice; it would fail on the old code. It does not exercise final eviction. |
| 4. Gate C checks only first audio stream | FIXED | [deliverables.py:146](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/r2/m3/deliverables.py:146) counts audio streams; lines 150–164 measure each and take the loudest peak. | **Yes:** [test_gates_export.py:443](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/tests/integration/server/routers/test_gates_export.py:443) uses a silent first track and audible second track. The old first-track check would accept its `MUTE` decision. |
| 5. Concurrent claims exceed project ceiling | FIXED at code level | [task_repo.py:623](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/lib/db/repositories/task_repo.py:623) takes a PostgreSQL transaction advisory lock keyed by project and media lane; lines 628–639 recheck the running count in the update. SQLite uses the update predicate without that lock. | **Yes on PostgreSQL:** [test_task_repo_admission.py:98](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/tests/integration/lib/db/repositories/test_task_repo_admission.py:98) holds one claim uncommitted while a second claims another task; the old code could admit both. It skips on SQLite, and I could not run it. |
| Minor: cancellation bypasses startup release | PARTIALLY_FIXED | [session_manager.py:615](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/server/agent_runtime/session_manager.py:615) and [line 962](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/server/agent_runtime/session_manager.py:962) now catch `BaseException` during reservation/options setup. Cancellation during `actor.start()` still bypasses cleanup at [lines 649–659](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/server/agent_runtime/session_manager.py:649) and [1001–1013](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/server/agent_runtime/session_manager.py:1001). | **No** direct startup-cancellation test found in the inspected tests. |
| Minor: script-lock digests unchecked | PARTIALLY_FIXED | [gates.py:83](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/server/routers/gates.py:83) checks digest *format*. The drill compares recorded digests and timing at [golden_restore_drill.py:482](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/tests/drills/r2/golden_restore_drill.py:482). The route still records caller-supplied digest values at [gates.py:195](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/server/routers/gates.py:195) without checking the actual source or script. | **No** for the original mismatch: [test_gates_export.py:453](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/tests/integration/server/routers/test_gates_export.py:453) tests malformed format only. No new drill test was in the reviewed diff. |

## 4. New findings

| Severity | File:line | Scenario description | Confidence |
|---|---|---|---|
| Major | [session_manager.py:381](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/server/agent_runtime/session_manager.py:381), [1459](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/server/agent_runtime/session_manager.py:1459) | The baseline exists only in `SessionManager` memory and has one slot per project. After a server restart, or after another session replaces that slot, a resumed CLI that restores earlier cumulative cost has no matching baseline; its first result can book prior spend again. | PLAUSIBLE — the code path is direct; restored CLI behavior was not reproduced here. |
| Major | [session_manager.py:1288](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/server/agent_runtime/session_manager.py:1288), [1474](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/server/agent_runtime/session_manager.py:1474) | If a resumed CLI **does not** restore cost but its first new total equals or exceeds the remembered old total, the “smaller total” reset does not run. Booking and settlement subtract the old baseline, undercounting this connection’s spend. | PLAUSIBLE — no test establishes this CLI sequence. |
| Major | [session_manager.py:1441](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/server/agent_runtime/session_manager.py:1441), [budget_guard.py:47](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/lib/budget_guard.py:47) | A failed reconciliation on final eviction leaves the claimed reservation unreconciled while the session holding its retry reference is removed. Claimed holds do not expire. | CONFIRMED from the eviction, settlement, and hold-lifetime code paths; no failure was reproduced by a runnable test. |

The advisory key includes project and media lane, and the lock is acquired before the update in the same transaction ([task_repo.py:623](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/lib/db/repositories/task_repo.py:623), [659](/home/anhtuan/content-production-os/.worktrees/r2-v2-main/lib/db/repositories/task_repo.py:659)). I found no directly evidenced deadlock or starvation defect in that bounded path. Its concurrent behavior remains unverified here.

## 5. Commands run

- `git rev-parse HEAD && git status --short && git log --oneline --max-count=6` → HEAD `94445e281b9246195192bb81ff9860fe8e0f8712`; status produced no entries.
- `git diff --stat ea831dda..HEAD`, `git diff --name-only ea831dda..HEAD`, bounded `git diff`, `nl`, and `rg` source reads → inspected the fix diff, seven finding paths, and relevant tests.
- `git diff --check ea831dda..HEAD` → exit 0, no output.
- Requested pytest command → **exit 2 before collection**: `Could not acquire lock … Read-only file system … /home/anhtuan/.cache/uv/.tmpop1DbL`.
- One retry with `UV_CACHE_DIR=/home/anhtuan/content-production-os/.worktrees/r2-v2-main/.venv/uv-cache` → **exit 2 before collection**: `Failed to initialize cache … failed to create directory … Read-only file system`.
- Codebase-memory project listing succeeded, but `index_status` and `search_graph` returned `MCP tool call requires approval, but approval policy is never`; source reads supplied the review evidence.

## 6. Coverage limits

No pytest test was collected or run. PostgreSQL concurrency, actual SDK restore behavior, server restart behavior, startup cancellation, and the modified restore drill were not executed. I did not run full suites, renders, provider calls, or live infrastructure checks. The graph index could not be used for call-chain verification; negative claims above are bounded to the inspected files and tests.

## 7. JSON verdict

```json
{"schema_version":1,"status":"M7_IMPLEMENTATION_NOT_ACCEPTED","accepted_candidate_head":"94445e281b9246195192bb81ff9860fe8e0f8712","reviewer":"codex","reviewed_at":"2026-09-29T02:03:36Z","required_skips":["Targeted pytest could not start because both uv cache locations were read-only"],"material_unknowns":["Actual CLI cost restoration across server restart and multiple sessions was not reproduced","PostgreSQL concurrent claim test was not run","Startup cancellation and final settlement failure were not reproduced","Codebase-memory graph queries were approval-blocked"]}
```

---

## Resolution (main agent, 2026-09-29)

The fixes are `e8a89567` on `r2-v1/maintenance`, merged into `r2-v2/main` as `5e5e95cc`.

| Finding | Fix | Test |
|---|---|---|
| 1. Resume baseline (partial), and new Major findings 1 and 2 | The in-memory per-project slot is removed. Before a resumed process starts, the host reads the CLI's global config and applies the CLI's own rule, `lastSessionId == resumed id` (bundled CLI: `Xha`, and `Giy` for the path). The rule survives host restarts. It handles another session's exit, and a non-restored resume books from zero. | `test_a_resumed_process_books_only_spend_beyond_the_restored_totals`, `test_a_resume_the_cli_does_not_restore_books_its_whole_total` (Major 2), `test_cli_restored_totals.py` (7 cases) |
| 3. Retry handle (partial), and new Major finding 3 | A session dropped with an unreconciled reservation hands it to the patrol, which retries it until it succeeds; shutdown retries once more. At host startup, every claimed `agent_session:` hold is committed at its reserved amount, the process's hard cap. Canary holds are not touched. | `test_an_evicted_session_whose_settlement_failed_is_retried_by_the_patrol`, `test_orphaned_agent_holds_are_committed_at_their_reserved_amount` |
| Minor: cancellation during `actor.start()` | Both connect paths settle on `BaseException` and re-raise the cancellation. | `test_a_new_session_cancelled_while_starting_releases_its_budget`, `test_a_resume_cancelled_while_starting_releases_its_budget` |
| Minor: script-lock digests | The drill's Gate B check is the pure function `script_lock_problem`, and a mismatch is tested. By ADR-0092 the server records the operator's lock of named revisions, as Gate A does; the release dossier verifies them. | `test_golden_restore_drill_gate_b.py` (5 cases) |

**Remaining known limits (ADR-0093):**

- A config race with another session's graceful exit in the same project can undercount by at most one connection's spend.
- The startup sweep assumes one host process.

**Verification:**

- **At `e8a89567` (maintenance):** 1084 passed in the affected SQLite scope (agent runtime unit tests, accounting, budget guard, canary, host_hardening). The budget guard and canary suites passed on PG16: 22 passed.
- **At `5e5e95cc` (V2):** 1089 passed and 1 skipped (the PostgreSQL-only test) on SQLite. On PG16 (`arcreel_v201`, head `c9e1f4a2b701`), 19 passed, including the concurrent-admission test.
- **Static gates:** ruff, basedpyright (0/0), lint-imports (20 kept), deptry and audit_tests are clean.
