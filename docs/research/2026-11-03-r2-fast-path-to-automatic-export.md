# Fast, low-waste path to a fully automatic export

Date: 2026-11-03, branch `impl/autonomous-production` at `9a2775820`. Sponsor request: research every way to solve the
remaining and likely problems quickly, without wasting time or resources. Companion: model options in
[2026-11-03-r2-stronger-models-for-automatic-quality.md](2026-11-03-r2-stronger-models-for-automatic-quality.md).

## 1. Where the time went (facts, 2026-11-02/03 debug runs)

- About 25 run-path defects were found one at a time; after each fix the debug e2e restarted from scratch and needed
  15-80 min (and 3 h with the real writer) to reach the failing stage again. Most of the elapsed time was replaying
  stages that had already passed.
- Task durations in the last run (queue + execution): asset sheets 30 × ~110-125 s (project-wide, ComfyUI 1 worker);
  episode plan 388 s (plus a failed 284 s attempt); asset inventory 217 s; script 103 s; script plan 38 s;
  storyboards ~57 s; still clips ~12 s; TTS ~8 s. Real writer story: 3 h 13 min (2026-11-02).
- Two local-model failure modes cost the most per occurrence: a degenerate generation that ran into the 1800 s Ollama
  read timeout (episode plan, script), and quarantine/retry loops.
- The fixes that worked were cheap offline probes against the failing artifacts (rebuild the plan, call the tool or
  reviewer on the saved project) taking seconds to minutes, followed by a full rerun only to confirm.

## 2. Existing capabilities to reuse (facts)

- `RESUME` (`server/production_run/service.py::_resume`): a run blocked `BLOCKED_CONFIGURATION` or
  `BLOCKED_INPUT_CHANGED` resumes RUNNING at the same stage (no rebind keeps the input lineage), after preflight and a
  grant renewal. This is the operator's path after fixing a cause; it re-executes only the blocked stage.
- Qualification writes one receipt per case named by case and model identity; reviews carry `prompt_digest`,
  `model_identity` and `evidence_digest`, so a receipt is reusable exactly when all three match.
- Per-stage evidence and outputs persist in the run's project directory and database; nothing forces a fresh project.

## 3. Options, by value per hour

### A. Iteration speed (development loop, no product change)

1. **Resume harness (highest value).** Keep the e2e database, data directory and governance custody between processes;
   after a code fix restart the app with the activated lifespan and `POST …/production-runs/{id}` RESUME. Each fix then
   costs only the blocked stage (minutes) instead of a replay (15 min-3 h). Snapshot (`pg_dump` + project tar) after
   the expensive stages to rerun later stages repeatedly.
2. **Offline stage probes** as the first response to any block (plan/next-action dump, settle, reviewer probe,
   ComfyUI workflow probe): seconds to minutes, no GPU replay.
3. Fail fast checks before long steps (already: service/model/corpus checks, empty data dir, early attestor probe).

### B. Runtime efficiency (small product changes)

1. **Bound local generations:** for local (Ollama) structured text tasks cap `num_predict` to a size the task can need
   (e.g. 8-16 k) instead of the 64 k default, so a degenerate loop truncates in minutes and the existing retries take
   over, instead of a 30-min read timeout.
2. **Qualification receipt reuse:** skip a case whose stored receipt has the same model identity, prompt digest and
   evidence digest. Unchanged reviewers requalify in seconds; a changed method reruns only that model (~45 min instead
   of ~90).
3. **Settle character references:** in the script stage's settle step, add registered character names that occur in a
   segment's `novel_text` to `characters_in_segment` (exact registered names, through `patch_episode_script`). The
   storyboard then gets its reference sheet; the last run's visual-consistency loss (score 3/5) came from a segment
   that named the boy but listed no character.
4. Story length: the real writer needs ~3 h for the 7000-11000-syllable brief contract. Faster options are a cloud
   writer (minutes, cents) or a shorter local contract (a product decision). Otherwise run the official e2e once,
   unattended.
5. Asset sheets are gated project-wide by the upstream workflow; keep (paid once per run with the resume harness).

### C. Quality gate

1. Cloud reviewers (Gemini Flash watches the actual mp4 with audio; ~$0.01 per review, ~$1 to qualify) — fastest
   route to a real PASS; needs sponsor approval for paid external calls.
2. Local fallback: gemma orientation OR → AND, requalify gemma only (with receipt reuse), plus B3 for consistency.

### D. Risks not yet exercised on real media

PACKAGE and EXPORT have run only in integration tests with real FFmpeg; with the resume harness they are minutes
away once QUALITY passes. The official e2e (fresh project, real writer, real qualification) still has to run once for
evidence.

## 4. Recommended sequence

1. A1 resume harness, B1 local generation bounds, B2 receipt reuse, B3 character settle (no cost, ~2-3 h of work).
2. Resume the blocked debug run at QUALITY with the local fallback (C2) — or with Gemini reviewers if approved (C1).
3. Reach PACKAGE/EXPORT by resume, fix anything found by probe + resume.
4. One official e2e from a fresh project, unattended (≈3 h story + qualification from reuse + media), and record the
   evidence.

## 5. Second, deeper pass (2026-11-03): assumptions checked against code and real data

### Resume harness — feasible, with two traps (code read)
- `_resume` accepts `BLOCKED_CONFIGURATION` and `BLOCKED_INPUT_CHANGED`; without a rebind the run returns to RUNNING at
  the same stage. RESUME renews the run's automation grant inside the parent Showrunner grant's expiry.
- The custody that RESUME needs lives in the previous run's `custody/` and `run/` directories plus database rows.
  Traps: pytest wipes `--basetemp` at start, so a resume process needs a different basetemp pointing at the old
  custody; and the resume process must not re-run `e2e_sessions` (it drops `alembic_version` and the immutability
  triggers) or `prepare_qualified_custody`.

### Local generation bound — sizing (code read + measurement)
- `OllamaChatTextBackend` uses `num_ctx` 32768; callers pass `max_output_tokens` 64000, so a degenerate generation
  stops only when the context fills: about 25-38 min at the measured ~11 tokens/s of `qwen3.5-vimax:9b`, past the
  1800 s read timeout. Real structured outputs need ~2.5-6 k tokens (19-segment plan / visual layer). A 12 k cap
  bounds the worst case at ~18 min and turns it into a truncation, which the text-task retry already handles.

### Reviewer false positive — the proposed fix was wrong; the data supports a threshold (experiment)
- `gemma3:4b` orientation answers, per sampled frame (`orientation-probe/` evidence): the 180° comparison question
  almost never names the rotated copy (real upside-down finals: 0-4 of 8), so requiring both answers (AND) would
  stop detecting real defects. The standalone question carries the signal.
- Standalone "upside down?" yes-count over 8 frames, whole corpus (40 cases): every CLEAN final 0-1; both real
  UPSIDE_DOWN_FRAMES finals 7; the real run's final that was falsely rejected 3 (water-reflection shots).
- Fix: raise `MIN_FLIPPED_FRAMES` from 2 to 5 of 8 sampled frames (more than half). It keeps both real defects
  (7) and clears the false positive (3) and all clean cases. Trade-off: a single upside-down shot inside a long
  episode would go unnoticed (the corpus has no such defect). Bind the threshold into the gemma review method so the
  prompt digest changes, and requalify gemma (~45 min; qwen's record is unaffected).

### Character settle — matching rule (design check)
- Registered names overlap ("Nam" inside "Mẹ Nam"; short names such as "Tu"). Match registered names as whole words,
  case-sensitive, longest first, and drop a match that lies inside a longer match, so "Mẹ Nam" does not also add
  "Nam". Add only names the segment does not already list; patch through `patch_episode_script`.

### Quality gate after a justified rejection — open policy question (donor check)
- Shenbi (`docs/research/2026-10-21-r2-v2-task6-blocks-donor-recheck.md`): "Quality never ends a run" — a chapter
  still failing after its revision rounds falls back to its best version and the Human may accept it as is. The
  story stage already follows this (`079de5ecd`). The automatic video export is bound to an M10 PASS disposition; an
  analogous "export the best version with the recorded FAIL disposition" in automatic mode would change that
  contract and is a sponsor decision, not an engineering fix.

### Revised sequence
1. Resume harness; 12 k local output cap; gemma threshold + its requalification; character settle. No cost.
2. Resume the blocked debug run at QUALITY. If qwen still scores visual 3 after the character settle, the remaining
   options are Gemini reviewers (approval) or a stronger writer.
3. PACKAGE/EXPORT by resume; then one official e2e from a fresh project.
