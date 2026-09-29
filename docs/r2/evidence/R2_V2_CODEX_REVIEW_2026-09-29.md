# R2 V1→V2 lineage — Codex independent review (2026-09-29)

> Saved verbatim from `/codex:result task-mum0cgan-iolyho` (Codex session `01a0ead0-5f5d-7332-867a-326716b2b00d`). The resolution is recorded at the end.

**HEAD reviewed:** `ea831dda2d4879b5c14ebaf2e26c873afe351177` (`r2-v2/main`, clean worktree). Reviewed ranges: `54240210..HEAD` and the V1-07/V1-08 range `8568a195..54240210`.

**Verdict: CHANGES_REQUIRED.** The Agent budget path has accounting and reservation defects, and Gate C's audio check can misclassify a final with multiple audio streams.

## Major findings

1. **CONFIRMED — resumed Agent spend can be booked twice.**
   - A new `ManagedSession` starts with zero booked cost, but a resumed CLI process may restore earlier cost.
   - The first result is therefore booked in full, including spend already recorded before the reconnect, and settlement charges that amount to the new reservation.
   - Example: a restored total of `$0.40` followed by `$0.05` of new spend can book `$0.45` again.
   - Where: `session_manager.py:225`, `:971`, `:1273`; SDK research, line 25.
2. **CONFIRMED — a canary setup failure leaves a claimed budget hold.** `run_agent_canary` reserves and claims before `load_provider_env_overrides()`, but only enters its reconciliation `finally` afterwards. Where: `qualify_route.py:237`, `:242`; `budget_guard.py:47`.
3. **CONFIRMED — a reconciliation failure loses the automatic retry handle.** `_settle_budget` clears `budget_reservation_ref` before reconciling, and `reconcile_agent_connection` logs database failures without raising them. Where: `session_manager.py:1432`; `budget_guard.py:227`.
4. **CONFIRMED — Gate C checks only the first audio stream.** `ffmpeg -map 0:a:0` measures one stream, so a silent first track with an audible second track can receive a verified `MUTE` receipt. Where: `deliverables.py:121`, `:147`.
5. **PLAUSIBLE — the per-project ceiling can be exceeded by concurrent claimers.** The running count is read in a SELECT and one task is updated separately. Where: `task_repo.py:577`, `:611`.

## Minor findings and evidence limits

- **CONFIRMED — cancellation can bypass the startup release.** Both Agent startup paths catch `Exception` after reserving, so `asyncio.CancelledError` skips `_release_budget`. Where: `session_manager.py:597`, `:939`.
- **CONFIRMED — the factual script lock records caller-supplied digests without checking the source or script.**
  - The drill checks only that the latest action is `LOCK`. It does not compare digests, and it does not check ordering against the first Gate C receipt.
  - So the dossier's "bound to exact revisions" relies on the operator's values. ADR-0092 discloses the missing runtime enforcement.
- **Found accurate:**
  - the V1 dossier's disclosure of the migration runner's failure, the sponsor exception and the E1 `INCOMPATIBLE` result;
  - the migration against the ORM for the script-lock table and the audio-decision column.

## Commands and coverage (reviewer)

- **Run:** git status, rev-parse, log and diff over both ranges; bounded source reads.
- **`git diff --check`:** flagged whitespace in captured gate logs.
- **Tests:** targeted pytest could not start, because `uv` hit a read-only filesystem.
- **Not used or not rerun:**
  - codebase-memory was blocked;
  - the historical PG16, browser and restore evidence was not rerun.

```json
{
  "schema_version": 1,
  "status": "M7_IMPLEMENTATION_NOT_ACCEPTED",
  "accepted_candidate_head": null,
  "reviewer": "Codex, independent read-only reviewer",
  "reviewed_at": "2026-09-29",
  "required_skips": 45,
  "material_unknowns": [
    "Targeted tests could not start on the read-only filesystem",
    "Concurrent project-ceiling behavior was not reproduced against PostgreSQL",
    "No live Agent canary or provider route was exercised",
    "Historical migration, browser, and restore evidence was inspected but not rerun"
  ]
}
```
