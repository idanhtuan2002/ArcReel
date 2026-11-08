# Best-of-N and judge-and-retry for automatic media: what donors and primary sources do

Date: 2026-11-08. Worktree `9b89` at `49876f4ce` (branch `impl/autonomous-production`). Builds on
[2026-11-03-r2-stronger-models-for-automatic-quality.md](2026-11-03-r2-stronger-models-for-automatic-quality.md)
(reviewer model choice; not redone here) and
[2026-11-08-r2-comfyui-graph-rerun-batch-preview.md](2026-11-08-r2-comfyui-graph-rerun-batch-preview.md)
(batch variants, targeted regenerate). Facts, inferences and unknowns are labelled; "Inference" is mine, not a
source claim. Donor code was read at the pinned commits below; nothing was run, no service was touched.

## 1. Question and scope

For the fully automatic run (idea, story, script, MEDIA with storyboards/clips/TTS, RENDER, MASTER, QUALITY,
PACKAGE, EXPORT), how do donors and primary sources implement:

- **(A)** generate N candidates, judge, pick the best;
- **(B)** generate one, judge at once, regenerate on failure with a retry limit and feedback to the generator?

At which granularity (image, shot clip, TTS line, script, whole video), with what judge (VLM, LLM, CLIP/aesthetic
or reward scores, rule checks), what criteria, how ties/failures/budgets are handled, and what evidence is stored.
Then: what ArcReel should adopt. Out of scope: licensing (project policy), code changes, model selection for the
whole-final reviewers.

## 2. ArcReel today (facts)

**MEDIA: no judging, one task per asset, retry on absence only.**
- `server/production_run/media_adapter.py:101-122` plans one step, `unit_key="media"`, `calls_per_target=80`
  (line 80). `inspect` (128-157) asks the workflow planner for the next action per episode: it submits it, or waits
  on active tasks, or passes when the plan asks for `export`. Nothing in this stage looks at pixels or audio.
- `_submit` (190-215): each tool call has a sub key = action type + digest of script and requested ids
  (`_requests`, 255-290). `owner_attempts >= max_attempts` (default 2, line 93) raises
  `OwnerBlocked("MEDIA_RETRY_LIMIT")` (199-200). An attempt is recorded write-ahead before each submit. So a retry
  happens only when the planner still lists the asset as missing/failed (task failure), never because the image
  is bad.
- Storyboards: `server/media_tools/storyboards.py:102` selects targets from the script and enqueues per segment;
  `segment_ids` and `force` exist (media_adapter.py:269-290) for targeted runs. TTS has planner-driven
  `REGENERATE_TTS` for `tts_stale` and `tts_duration_unavailable` (`lib/generation_result.py:139,147`), i.e.
  metadata conditions, not audio-quality conditions.
- Clips: the 2026-11-03 handoff records the debug run as 19 clips from still images (Ken Burns; "static clips");
  clip generation is therefore deterministic at that backend (`docs/r2/evidence/R2_AUTONOMOUS_PRODUCTION_HANDOFF.md`
  line 28). Unknown for a video-model backend.

**Seeds and versions.**
- ComfyUI requests roll a fresh seed per request unless one is passed (`lib/custom_provider/comfyui/
  request_builder.py:303-325`: `requested if requested is not None else rng.randrange(...)`); the effective seed is
  returned and recorded (lines 119-124).
- `lib/version_manager.py:425` `add_version(resource_type, resource_id, prompt, source_file, **metadata)` keeps every
  version; `commit_staged_version(s)` (496, 609) and `get_current_version` (284); a candidate telemetry join
  exists: `version_candidate_ref` and `_record_version_span(..., selected=)` (129-156), with `master_version` set
  only when the version became the selected one. Inference: the store already has "candidate" and "selected"
  vocabulary; nothing selects automatically.
- Queue: one active task per asset (`lib/db/models/task.py:61` `idx_tasks_dedupe_active`). The manual "make N
  versions" runs them in turn, stopping at the first non-success (`frontend/src/actions/generation.ts:439-461`).

**QUALITY: one judge level, the whole final.**
- Evidence per reviewer: 8 frames (`FRAME_COUNT=8`, `evaluators.py:43`, `frame_times` at 267), the subtitle sidecar
  and the narration; per-frame one-picture questions (broken, upside-down alone and vs 180-degree pair, illustrates
  its narration line); then 1-5 scores on five dimensions and findings (module docstring, `evaluators.py:1-13`).
  Fixed thresholds: `MIN_FLIPPED_FRAMES=2`, `MIN_BROKEN_FRAMES=2`, `MIN_MISMATCHED_FRAMES=2` (60-65); gemma uses a
  5-of-8 flipped rule after 2026-11-03 (handoff line 30). Rule checks (blackdetect share `MAX_BLACK_SHARE=0.2`,
  cropdetect, subtitle vs narration) in `final_checks.py:21,76-` run with every review.
- Decision: both reviewers must accept (all five scores >= `PASSING_SCORE=4`, no CRITICAL/MAJOR;
  `r2/automation/assessment.py:20-51`). Different identities, not a writer, qualified, same subject digest, right
  language (64-90). One accepts, one rejects: `REVIEWER_DISAGREEMENT` BLOCK (91-92). Both reject: REWORK to the
  earliest repairable stage of any CRITICAL/MAJOR finding (94-102).
- The frame findings carry `repair_stage=MEDIA` but `unit_key=f"episode:{n}"` (`evaluators.py:182-226`), although the
  evaluator holds per-frame times and cue lines (`frame_times`, `cue_at`). Inference: the judge could name the
  failing segment and currently does not.
- `quality_gate`: `record` turns a judged rejection into a recorded REWORK disposition and still reaches PACKAGE and
  EXPORT (`quality_adapter.py:128,147-151`); `enforce` returns a REWORK outcome, unless the new final is byte-identical
  to the previous generation's, which blocks `REWORK_WITHOUT_CHANGE` (152-153, 317-323).
- Limits: `unit_repair_limit` <= 2 and `final_evaluation_limit` <= 3 (`r2/contracts/automation.py:125-126`);
  REWORK jumps to `repair_stage`, bumps `generation`, counts per `(stage, unit_key)`, and drops affected targets;
  over the limit is `FAILED_QUALITY/REPAIR_LIMIT` (`r2/automation/transitions.py:85-113`).
- Inference (from the above plus handoff line 30): a whole-final REWORK to MEDIA with an episode-wide `unit_key`
  re-enters a stage whose planner sees every asset present, regenerates nothing, renders the same final, and ends
  `REWORK_WITHOUT_CHANGE`. The loop is wired but has no unit-level lever for MEDIA.

**Reviewer qualification (mandatory).** `scripts/r2/qualify_reviewers.py` and `server/production_run/
qualification.py:91-100`: a reviewer fails once it accepts any CRITICAL_DEFECT case, or accepts fewer than 80% of
CLEAN cases in a split. The corpus `docs/r2/evidence/autonomous-qualification-2026-11-01/manifest.full.json` has 40
finals (CALIBRATION/HOLDOUT x CLEAN/CRITICAL_DEFECT, 10 each; checked). Handoff 2026-11-03: gemma3 false
"upside-down" on upright frames (sun glare, reflections), qwen2.5vl visual 3/5 on static clips; Gemini
`gemini-3.6-flash` reviews local finals at 3/5 and Lite models accept real defects
(2026-11-03 research, section 6).

**In-house precedent for judge-and-repair (STORY).** `server/story_authoring/driver.py` header (lines 1-16): every
node has a call cap (`NODE_CAPS`, 108-116: scene_draft 6, chapter_review 12, outline 4); scenes go through draft,
deterministic L1 checks, deterministic fixes, span repair, length normalizing, regeneration; the chapter loop has
four L2 audits and at most two cycles; "A node that cannot be made acceptable inside its cap stops the run in a
typed blocked phase". `_step` (383-394) counts GENERATE attempts against the cap. The scene loop keeps
`best = (prose, findings)` when `_weight(findings) <= _weight(best[1])` and, when the cap is spent, returns the best
version with an escalated finding (`BEST_VERSION_KEPT`, ~802). Repair is span-local with the attempt history fed
back (`repair.py:286-330`, `attempt_history`). Judge-and-retry with feedback, best-version fallback and typed block
already exist for text; none exists for media.

**Real run 2026-11-08 (task brief, not re-measured):** STORY 4 h 10 min, MEDIA about 10 min for 15 tasks, about 19
storyboards per episode in earlier runs at about 1 min per image on local FLUX.2 klein; reviewers scored story 3-4/5,
visual 4-5/5.

## 3. Donor findings

### 3.1 ViMax (`/home/anhtuan/ViMax`, commit `63bb9c764cecd66af77cd4305f6869359325b2d5`, 2026-08-23)

**Fact: a best-of-N selector exists but nothing calls it.**
- `agents/best_image_selector.py` defines `BestImageSelector`: inputs are reference images with text, a target
  description and a list of candidate images; the model returns `BestImageResponse{best_image_index, reason}`
  (lines 51-58). The prompt (lines 13-41) ranks candidates on Character Consistency (gender, ethnicity, age, face,
  body, outlook, hairstyle), Spatial Consistency (relative positions, layout, perspective) and Description Accuracy;
  "if none are ideal, choose the relatively best option and explain its shortcomings"; "Prioritize images without
  white borders, black edges, or any additional framing". Granularity: one target frame, N candidates, one VLM call
  with all images.
- Failure handling: `@retry(stop_after_attempt(3))` on the call (78-81); an index outside range logs "defaulting to
  0" and returns candidate 0 (141-146). No scores, no threshold, no tie rule, no stored evidence beyond a log line.
- `grep -rniE "BestImage|best_image"` over the checkout (excluding the file itself) returns no caller. The frame
  path generates one image and saves it: `pipelines/script2video_pipeline.py:609-615`
  (`generate_single_image(prompt, reference_image_paths, size="1600x900")`). So ViMax ships a pattern-A component but
  its pipeline runs N=1.

**Fact: what ViMax does instead is selection of references and rule-check-and-retry.**
- `agents/reference_image_selector.py` (prompt 19-22, 67-70, guidelines ~100) picks up to 8 reference images and
  writes the edit prompt, prioritizing the same camera and the most recent prior frames. This improves consistency
  before generation, not after.
- Rule judge with retry: `tools/image_orientation.py:21-26` `ensure_not_portrait` raises "Generated image is
  portrait-oriented ... retrying for a landscape frame" when `height > width * 1.05` (env
  `VIMAX_IMAGE_PORTRAIT_RETRY_TOLERANCE`); the image tools call it after generation
  (`tools/image_generator_nanobanana_google_api.py:87-94`, also the openrouter and yunwu tools) and the
  tenacity `@retry(stop_after_attempt(3), wait_exponential, reraise=True)` at line 30 retries the whole call.
  Retries on text steps use the same `stop_after_attempt(3)` pattern (`agents/storyboard_artist.py:188,296,441`;
  scene tests in `tests/test_wrong_output_guards.py`).
- Inference: ViMax's lesson is that its authors wrote the VLM best-of-N selector but did not wire it, and their
  active quality control for images is a cheap deterministic guard with bounded retry.

### 3.2 DramaClaw (`github.com/dramaclaw/dramaclaw`, commit `b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83`; `src/novelvideo/verification/`)

The only donor with a real multi-candidate selection pipeline and VLM verifiers. Judge model: the project's
structured-output model through `pydantic_ai` (`output_retries=2`), images compressed to JPEG; prompts in Chinese.

**Pattern A, per storyboard sketch (beat), N candidates from a pool** (`sketch_selector.py`, `run_sketch_select`):
1. Candidates = fresh (non-stale by content hash) cells of the beat's sketch pool (lines ~100-125). How many are
   generated per beat: not read.
2. T1 colour prefilter: deterministic detection that each expected character's marker colour is present
   (`detect_colors(..., threshold=0.008)`); missing colour disqualifies (136-158).
3. T2 VLM fact check per surviving candidate (`image_verifier.py`, `SKETCH_VERIFY_PROMPT`): checks only factual
   contradictions (character count and gender: critical; core action contradicted: critical; scene type, time/light,
   missing key prop, composition direction: warning); lists what it must not judge (expression, beauty, detail,
   style). Pass rule: "score >= 6.0 and no critical issue", and "宁可通过也不要误判" ("better to pass than misjudge,
   default pass when unsure"). Output `{passed, score 0-10, issues, suggested_action: none|regenerate|edit_script}`
   (`models.py:15-22`). Prompt input is sanitized (`sanitize.py`).
4. All candidates disqualified: it does not fail; it relaxes, keeps all of them as `relaxed` and marks the pick
   `provisional` with `recommended_action="regenerate"` (197-204).
5. T3 score per candidate (`SKETCH_SCORE_PROMPT`: script_match and identity_clarity 0-10, total = mean; "不确定时偏向高分").
6. Pick: one candidate, take it; top-2 gap `> score_gap_for_auto_select` (1.0), take the top; smaller gap, T4
   `SketchComparer` compares the top 3 in one VLM call and returns `selected_index`; invalid index falls back to
   the top score, with graded `selection_confidence` (0.95 max down to 0.2) (206-285).
7. Output per beat: all candidates with `{pool_id, score, disqualified, reason, relaxed}`, `selected_reason`,
   `selected_score`, `selection_confidence`, `recommended_action` in {accept, regenerate}; `needs_regeneration`
   when the selected total `< quality_threshold` (7.0). The summary lists accepted, provisional and
   needs-attention beats for the orchestrating agent (288-320).

**Pattern B, per first frame** (`frame_verifier.py`, `FRAME_VERIFY_PROMPT`): sees the sketch and the HD frame;
checks face distortion, limb distortion (extra fingers), text/watermark artefacts (critical) and content loss, style
drift, colour anomaly (warning); same pass rule (6.0, no critical, default pass); `suggested_action` is
`regenerate` on failure. The verifier only reports; the regeneration decision belongs to the agent that calls the
tool (the code has no loop). No retry cap found in the verifier package; `convergence_log.py` stores per-round
`residual_count`, `fixed_count`, `new_failures` per episode and phase ("feeds the upcoming convergence loop
controller", docstring), written by `cli/run_gate.py`.

**Whole-episode and consistency judges:** `episode_reviewer.py` builds a numbered contact-sheet grid of the
episode's frames and returns an overview with `overall_passed = total >= 6.0 and no critical`; issues carry
`suggested_action` in {swap_candidate, regenerate, info} per beat (`models.py:192-214`). `consistency_verifier.py`
scores face/hair/skin/gender/clothing per identity (pass: face >= 7 and clothing >= 7, zero tolerance on face).
`render_repair_context.py:60-77` groups bad beats into regeneration grids of at most 6 (`2x3_1-1`). So DramaClaw
connects whole-episode judging to per-beat repair through beat numbers, which ArcReel's findings lack.

**Inference:** DramaClaw tolerates false accepts (default pass) because a human or agent reviews downstream; its
judges are narrowly scoped factual checkers rather than quality graders, each with a deterministic prefilter.

### 3.3 OpenMontage (upstream `calesthio/OpenMontage`, pin `08e2151fa02de28a5d6a312b3d575692bf147ad7`; this repo vendors only `vendor/openmontage/remotion-composer`)

- `tools/base_tool.py:98-101,121-125`: `Determinism` is DETERMINISTIC/SEEDED/STOCHASTIC and `RetryPolicy` is
  `max_retries=0, backoff_seconds=1.0, retryable_errors=[]`: infrastructure retry on tool errors, no quality input.
  `ToolResult` carries `seed`, `model`, `cost_usd` (129-138), which is the evidence a regeneration needs.
- The judge is the host LLM agent. `skills/meta/reviewer.md`: every stage self-reviews against the manifest's
  `review_focus` and `success_criteria`; findings are `critical|suggestion|nitpick|investigation`; each critical
  finding must carry `proposed_fix`; 1+ critical means revise "max 2 rounds"; after two rounds still critical it
  is "Pass with warnings ... Never block indefinitely" (Step 6). CHAI rules (arXiv 2604.21718): accurate, complete,
  constructive critique.
- Generated assets (`skills/pipelines/explainer/asset-director.md`): image loop is "refine the prompt and regenerate
  (max 2 retries)" (line 120), with a pitfall "One retry then give up: ... refine the prompt specifically, do not
  just retry the same prompt" (261); a sample-first gate before batch (one TTS, one image; max 3 sample iterations,
  70-82); a pre/post prompt self-review with the (pre, critique, post) triplet logged in asset metadata (193-205);
  budget check against a cost tracker before generating (58-67). `tools/analysis/visual_qa.py` only extracts frames,
  probes and checks audio level and caption occlusion; "Returns frame paths so the agent can visually inspect".
  There is no automatic VLM pass or best-of-N.
- Inference: OpenMontage's transferable parts are the feedback format (finding to proposed fix to prompt rewrite),
  the escalating retry with changed prompt, the pass-with-warnings after N rounds, sample-before-batch and the
  recorded (seed, cost, prompt-revision) triplet. Its judge is not automatic and so does not need qualification.

### 3.4 Jellyfish, Butterfly, ai-short-film (quick pass)

- Jellyfish (`Forget-C/Jellyfish`, `a9678194ddf2d9be3ccbe78d4287d87d5089e123`):
  `backend/app/services/studio/shot_video_readiness.py` is a precondition gate (reference frames, prompt, duration,
  default video model, provider key, no active video task), `ready = all(item.ok)` (line 203). It judges inputs,
  not outputs; it also counts pending candidates per shot, which are human-reviewed. A separate
  `chains/agents/consistency_checker_agent.py` checks scripts. Not read further. Relevance: the cheap pre-generation
  readiness check that ArcReel's planner already approximates.
- Butterfly (`04e694ce4ceecb4ea651724e8be3199bd1959edd`) prompt_director validators and ai-short-film
  (`3dc93a62bf472e46cb5edf2999971769a4989cab`) continuity: not re-read this round; no claim about their retry or
  selection behaviour.

## 4. External primary sources

- **ImageReward** (`THUDM/ImageReward`, `78f8051059b34fef8e0032ccb40561c23a2ddbbb`): README usage
  `model.inference_rank(prompt, img_list)` returns `ranking` and `rewards` for several generations of one prompt;
  `ImageReward/ImageReward.py:139` encodes the prompt and each image with a BLIP cross-attention head. README claim:
  trained on 137k expert comparisons, outperforms CLIP (38.6%), Aesthetic (39.6%) and BLIP (31.6%) at predicting
  human preference. Fact: a ~1B-class reward model that ranks N candidates for one prompt; scores are relative
  within a group. Unknown here: its quality on FLUX.2 klein outputs with references and on 9:16 storyboards; its
  GPU and VRAM footprint next to FLUX on an 8 GB card.
- **VQAScore / t2v_metrics** (`linzhiqiu/t2v_metrics`, `6ecb74f92028f42c7e64546d3a71e98c8c73068f`): README
  exposes `t2v_metrics.VQAScore(model='qwen2.5-vl-7b' | 'qwen3-vl-8b' | 'gpt-4o' ...)`, scoring image-text pairs
  and videos (`fps=8.0` or `"dynamic"`), with a customizable question (`'Is this figure showing "{}"? Please
  answer yes or no.'`, answer `Yes`). It implements the GenAI-Rank benchmark (ranking among generated images,
  paper arXiv 2406.13743; the paper's claims were not read this round). Fact: yes-probability from a VLM as a
  prompt-alignment score, the same family as ArcReel's `probabilities` method (`evaluators.py:151-180`).
  Inference: ArcReel already runs qwen2.5vl; per-image VQA-style yes-probabilities need no new model.
- **ComfyUI batch/seed**: covered in the 2026-11-08 ComfyUI note (batch count queues the same graph N times;
  seed control fixed/increment/randomize). ComfyUI core ships no selection node; selection is the human's.
- **CHAI** (arXiv 2604.21718, cited by OpenMontage and `t2v_metrics`): critiques must be accurate, complete,
  constructive. Not read first-hand; only its use in OpenMontage's skills was read.

## 5. Comparison

| Pattern | Where used | Granularity | Judge | Cost per unit | Fit for ArcReel |
|---|---|---|---|---|---|
| A: N candidates, rank, pick | DramaClaw `run_sketch_select`; ViMax `BestImageSelector` (unwired); ImageReward/VQAScore as scorers | one beat/frame, N images | colour prefilter + VLM fact check + VLM score + VLM compare of top 3 (DramaClaw); one multi-image VLM call (ViMax); reward model (ImageReward) | N x 1 min GPU + one judge call per candidate | Good for storyboards: cost is minutes, `versions.json` stores candidates. Needs a ranking-only judge qualification |
| B1: generate, rule check, retry | ViMax `ensure_not_portrait` + tenacity 3x | one image | deterministic (aspect) | one extra image on failure | Very good: no model qualification; add black/blank/size/NSFW-free checks |
| B2: generate, VLM verify, regenerate | DramaClaw `FrameVerifier`/`ImageVerifier` (verifier only; caller loops) | one frame | VLM, default pass when unsure | judge call + 1 min per retry | Good if strict-side and capped; local VLM false-reject cost is small |
| B3: critique to prompt rewrite, max 2 rounds, then pass with warnings | OpenMontage reviewer and asset-director | stage / asset | host LLM agent | LLM tokens | Feedback format worth copying; judge not automatic |
| B4: judge whole output, repair earliest stage | ArcReel QUALITY; DramaClaw `episode_reviewer`; OpenMontage stage review | whole final / episode | two qualified VLMs (ArcReel); one VLM on contact sheet (DramaClaw) | one run of 8 frames x 2 reviewers (about 8 min measured on 2026-11-03) | Exists; needs unit-level findings or the lever is dead (section 2) |
| B5: text node judge and span repair, capped, best kept | ArcReel STORY driver | scene / chapter / outline | rules + LLM audits | tokens, hours | In-house; design template for media |
| Preconditions | Jellyfish readiness; ArcReel planner | shot | rules | none | Already covered |
| Per-clip best-of-N | none in donors | clip | n/a | video-model GPU | No: ArcReel clips are Ken Burns stills locally; deterministic |
| Per-script / per-video best-of-N | none | script / final | n/a | 4 h per STORY, 3.5 h per episode | No |

## 6. Recommendation (ranked by value / cost)

Principle (inference): put cheap, repeatable judging at the cheapest granularity where it can act (one storyboard
= about 1 min), keep the whole-final judge as the last line, and make it able to act on a unit.

1. **Deterministic per-image gate with bounded retry (B1). Highest value/cost; no qualification needed.** After each
   storyboard/asset image, check: decodes, expected size and orientation (ViMax guard), not blank or black (mean and
   variance), not a test pattern or near-duplicate of its neighbour. On failure: re-enqueue the same asset with a new
   seed, at most 2 extra attempts (reuse the `MEDIA_RETRY_LIMIT` accounting, but count by asset not by action key);
   after that keep the best remaining version and record a typed exception (STORY's `BEST_VERSION_KEPT` pattern)
   instead of blocking MEDIA. Cost: seconds per image plus one image per rare failure (about 1 min GPU each).
2. **Per-storyboard best-of-N with a ranking-only VLM judge (A), default N=2, ceiling 3.** Generate N versions of
   one asset as versions of the same asset (sequential, since the queue allows one active task per asset; or N
   seeds inside one task), judge, set the winner as the selected version, keep losers in `versions.json` with the
   seed. Judge: reuse a qualified local VLM, one call per group, candidates shuffled to cancel position bias, criteria
   from ViMax (character consistency against the reference sheet, spatial layout, description accuracy, no borders)
   and DramaClaw (facts first: character count, core action; explicit non-criteria: beauty). Ties and judge errors:
   take the first candidate that passed rule checks (random order is baseline behaviour, so a failing judge degrades
   to N=1 quality; inference). Never block on this judge. Cost for one episode of about 19 storyboards at about 1 min
   each: N=2 adds about 19 GPU-min (+100%); N=3 adds about 38 GPU-min. Judge calls: about 19 x 1 call, unknown
   seconds each (see section 7). Roughly 0.5-1 h per episode on top of a MEDIA stage that took about 10 min for 15
   tasks. Compared with STORY's 4 h this is acceptable; compared with MEDIA it multiplies MEDIA by 2-3x.
3. **Make QUALITY findings addressable per segment (B4 made effective).** Map each failing frame to its segment via
   `frame_times`/`cue_at`, emit findings with `unit_key=f"episode:{n}:segment:{id}"` (`transitions.py:85-113` already
   accepts `target + ":"` prefixes), and let MEDIA's REWORK path pass those ids with `force` to
   `handle_generate_storyboards` (`_requests` already supports `scope selected` and `segment_ids`). With a count
   `MIN_*_FRAMES=2` rule, name the frames involved. This is the missing lever behind `REWORK_WITHOUT_CHANGE`
   and gives the existing `unit_repair_limit=2` a meaning. Depends on a trustworthy judge (item 4); until then keep
   `quality_gate="record"` for local profiles.
4. **Qualification the judges need under ArcReel's rules.**
   - Items 1: none (deterministic; unit-test thresholds on good/bad fixtures).
   - Item 2 (ranking-only, cannot accept or reject output): a lighter selection qualification on a labelled set of
     candidate groups (for example 30 groups, each with one known-better and one known-defective storyboard from
     the existing `qualification` corpus authoring path): it must pick the defective candidate in at most 10% of
     groups in both orders (position-bias check). Record model identity, prompt digest and corpus digest with the
     receipt, as `reviewer-receipts` do. Because a wrong pick costs no more than N=1, this is a smaller bar than the
     "zero accepted defects" bar of final review (qualification.py:91-100); that is an inference the sponsor should
     confirm.
   - Item 3 and any absolute per-image accept/reject VLM judge: full qualification on the same rule (zero accepted
     CRITICAL_DEFECT, at least 80% CLEAN accepted per split), measured on images not finals; do not reuse the final-level
     receipts (different task and evidence digest).
5. **TTS (cheap rule judge, B1).** Verify duration against the planned segment, no long silence, no clipping (ffmpeg
   `silencedetect`, `astats`); retry `REGENERATE_TTS` at most 2 with the existing planner action. An ASR round trip to
   compare the transcript with the script is an inference not found in a donor; cost unknown.
6. **Sample-before-batch (OpenMontage).** Optional: generate one image, one TTS line first and require the rule gate
   to pass before the batch; cheap, catches mis-configured workflows early.

**Do not adopt:** per-clip best-of-N (clips are deterministic locally), per-script or per-video best-of-N (3.5-4 h
each), CLIP/aesthetic scores as the sole judge (they miss character identity and counts; ImageReward ranks
prompt-image preference, not continuity with a reference), a default-pass judge for the final gate.

**Budget and limits.** Add policy fields next to the existing ones (`r2/contracts/automation.py:125-134`):
`image_candidates` (1-3, default 1 until qualified, 2 after), `image_retry_limit` (0-2), both frozen into
`RunPolicy` at start like `quality_gate`; estimate `estimated_tasks` (`media_adapter.py:113`) as
`calls_per_target * units * image_candidates` so the run's task/budget admission sees it. Hard stop: the per-asset
cap, never an unbounded loop; no cloud judge unless the run policy allows paid routes with a per-call ceiling
(`preflight.py`).

**Evidence design.** Per asset store, in the version metadata, for every candidate: seed, prompt digest, rule-check
results, judge model identity, prompt digest, score or rank, `selected` flag, and `selection_reason` (DramaClaw's
`selected_reason`/`confidence` shape; ViMax stores only a log line). Roll up per run in the step's owner receipt:
counts of candidates, rule failures, retries, best-version-kept exceptions; surface them in `run_report`
(`server/production_run/report.py:113-126`) and the existing `version.recorded` span
(`lib/version_manager.py:139-156`). A convergence table in the style of DramaClaw's `convergence_rounds`
(residual, fixed, new failures per round) fits the REWORK generations.

**Files that would change.**
- Item 1/2: `server/media_tools/storyboards.py` (N versions, rule gate, selection), `lib/version_manager.py` (selected
  flag/metadata helpers; no schema change expected), `lib/custom_provider/comfyui/request_builder.py` (pass distinct
  seeds; already supported by `requested`), `server/production_run/media_adapter.py` (attempt accounting, estimate,
  typed exception), new `server/production_run/image_judge.py` (rules plus ranking call; reuse the Ollama client of
  `evaluators.py`), `r2/contracts/automation.py` (policy fields), `server/production_run/report.py`, frontend run
  report and `VersionTimeMachine.tsx` (show "chosen automatically", already lists versions), i18n en/vi/zh.
- Item 3: `server/production_run/evaluators.py` (unit keys per frame), `server/production_run/quality_adapter.py`
  (unit-scoped REWORK), `r2/automation/assessment.py` (`combine` picks the earliest unit), `media_adapter.py` (REWORK
  ids), possibly `r2/automation/transitions.py` (no change expected; prefix matching exists).
- Item 4: `scripts/r2/` selection-qualification script plus a labelled group corpus under `docs/r2/evidence/`.
- Needs an ADR before code (new judge authority over assets, run-policy fields); main agent owns that decision.

**Suggested order:** 1, then 3 (it repairs an existing dead loop and needs no new model), then 2 behind the policy
field with default 1, 4 for item 2 before raising the default, then 5.

## 7. Unknowns

- Seconds per judge call on the local 8 GB GPU for one image or a 2-3 image group (qwen2.5vl:7b; model swap cost
  against FLUX.2 klein in the same VRAM; whether Ollama and ComfyUI can be resident together). The 8-minute figure
  is for the two-reviewer final review only.
- Whether a local VLM ranks storyboard candidates better than random; none was measured. The 2026-11-03 findings are
  about absolute defect detection on finals, a different task.
- How many candidates DramaClaw generates per beat and how its agent loops on `suggested_action`; the verifier package
  has no cap and the orchestrating agent code was not read.
- Whether FLUX.2 klein seeds are reproducible per seed (the ComfyUI note left this open) and the real
  per-image variance across seeds that best-of-N would exploit.
- Which clip backend runs in production for video generation: if a video model replaces Ken Burns, per-clip rule checks
  (frozen/black frames, motion) and a clip-level retry may be worth a separate round.
- ViMax's other call sites for `BestImageSelector` outside the checkout (web/ and tests contain none); Butterfly and
  ai-short-film behaviour; the GenAI-Bench/VQAScore paper's best-of-N result and ImageReward's reported best-of-N gain
  (README claims read, papers not).
- Whether the sponsor accepts a lighter qualification bar for a ranking-only judge (section 6.4).

## 8. Verification (main agent, 2026-11-08)

Re-checked against source: `server/production_run/evaluators.py:182-226` (frame findings carry `repair_stage=MEDIA`
with the episode `unit_key`), `server/production_run/media_adapter.py:190-232` (attempt cap per sub key; MEDIA passes
when every storyboard/video/audio id is current, so an automatic REWORK to MEDIA with present media regenerates
nothing), ViMax `63bb9c7` (`BestImageSelector` defined, no caller in the repo), DramaClaw `b299bfd9`
`src/novelvideo/verification/sketch_selector.py:48-69,97,137-158` (`run_sketch_select`, `score_gap_for_auto_select=1.0`,
colour prefilter, `selected_is_provisional`). The Human FINAL_FILM REWORK shipped in r2-v2.2.4 is consistent with this:
it relies on the Showrunner replacing media first.
