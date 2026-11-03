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
