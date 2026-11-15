# Craft and identity quality program (2026-11-13)

Sponsor instruction: build every ranked addition of `docs/research/2026-11-13-r2-film-craft-quality.md` (P0-1 → P2) and `docs/research/2026-11-13-r2-character-identity-and-donor-fixes.md` (ID-1 → ID-7), best quality first. Reuse donor code where it does the job best; build only what cannot be reused. Branch `impl/r2-film-quality` (worktree `.worktrees/r2-film-quality`). Deployed: `r2-v2.5.17`. Not pushed.

Donor checkouts: `/tmp/claude-1000/-home-anhtuan-content-production-os/9ab4f1ca-8a43-4753-9ca3-6b5ec550b684/scratchpad/donors/` (VGA = video-generation-automation@e46e9d3, Jellyfish a967819, ViMax, openfilm, open-edit, OpenChatCut, Calliope, ai-video-production-editor, huobao-drama b48e6b2, ai-short-drama 3991bbb). These are scratch copies: re-clone if missing.

| Item | Status | Commit / note |
|---|---|---|
| P0-1 camera move on held pictures | done | `ceb92e7ab`, ADR-0140 (VGA AnimeScene moves) |
| P0-2 project colour grade | done | `ceb92e7ab`, ADR-0140 (VGA color_grade presets) |
| lint-imports contract broken since r2-v2.5.17 | fixed | `8191d201f` |
| P0-3 scene look record (time of day, key light, palette, mood) | done | `e0699b04e`, ADR-0141 (Calliope ledger design) |
| P0-4 character bible + canonical block | done | `2289e06ee`, ADR-0142 (ViMax static/dynamic features, BFL) |
| P0-5 music bed (ACE-Step 1.5) + ducking | done | `edd9d037f`, ADR-0143; also fixes master lengthening (FINAL_DURATION_MISMATCH). Host: `/mnt/arcreel/D/ArcReel/ace-step-api.sh`, env `ARCREEL_MUSIC_URL`, `ARCREEL_MUSIC_FREE_URLS` |
| P0-6 VieNeu emotion cues + pauses | done (cues) | ADR-0152; sponsor confirmed the cues sound real 2026-11-14. Pauses not built: no native control, unit timing already follows measured audio |
| P0-7 shot grammar (angle, coverage, variety) | done | `8f1dda78d`, ADR-0144 (AIVPE directorAgent, ShotBench) |
| P1-8 image-prompt dialect per model | done: measured, no change | `8af1d0270`, `docs/r2/evidence/prompt-dialect-ab-2026-11-14/`: no dialect wins; shot size ignored by all (reference sheet pulls framing → ID-1) |
| P1-9 numeric look-consistency check | done | `5b614da68`, ADR-0145 |
| P1-10 wardrobe/state derivatives in the run | done (= ID-5) | `2f86da4ca`, ADR-0146 (Jellyfish CostumeTimeline) |
| P1-11 ambience bed | done | `67ca6f0e6`, ADR-0150 (MMAudio shim on port 8002) |
| P1-12 screen direction | done | `02f83cca6`, ADR-0147 (judge already checks; planner now writes blocking) |
| P2-13 foley / leitmotif / ShotVL | deferred with reasons | per-clip foley needs a real video route (stills have no motion to sync); a leitmotif needs per-scene cues (one cue per episode today); ShotVL-3B needs GPU room the 2070 lacks while ComfyUI is resident, and ADR-0148's framing line addresses shot size at generation |
| P2-14 BytePlus guides via browser | done | `docs/research/2026-11-14-byteplus-seedance-seedream-prompt-guides.md` (headless Chrome) |
| ID-1 reference selection, view crops, 4th slot | done | `775569ffa` ADR-0148 (framing line), `e8c0e14c1` ADR-0149 (priority, warning, 4-slot definition; crops measured and not adopted) |
| ID-2 N candidates + pick | done | `ff085078a`, ADR-0151 (best-of-2 ranked by face identity; host needs `ARCREEL_FACE_ID_URL`) |
| ID-3 face-cosine instrument + calibration | done | `ff085078a`, ADR-0151 (corpus 2: 36/37 pairs, AUC 0.885; faceid shim port 8003) |
| ID-4 reference name binding | done | `e8c0e14c1`, ADR-0149 |
| ID-5 costume/state timeline → derivatives | done | `2f86da4ca`, ADR-0146 |
| ID-6 face repair loop | measured, not wired | `219cda6fd`: klein edit repairs 2 of 4 look-alike frames; acceptance rule cos ≥ 0.29 and composition ≥ 0.85 keeps exactly those. Blocked on artifact currency for repaired versions (needs an ADR) and trial numbers |
| ID-7 identity model bake-off | in progress | sponsor 2026-11-14: Qwen-Image-Edit-2511 (Apache-2.0, not gated) instead of DreamO (FLUX.1-dev non-commercial, gated); licences in `docs/research/2026-11-14-model-licences-and-identity-alternatives.md` |

Verification so far (HEAD `ceb92e7ab`): `tests/integration/lib/test_presentation_renderer.py`, `tests/integration/server/production_run/test_render_master_adapter.py`, `tests/integration/lib/test_project_manager.py`, `tests/unit/server/production_run/test_render_finish_inputs.py` 83 passed 2 skipped; read-model and jianying 25 passed; ruff, basedpyright 0, lint-imports 23 kept, audit_tests 0.

## Host steps for the Human (after deploy)
1. Start the audio services: `nohup /mnt/arcreel/D/ArcReel/ace-step-api.sh &` and `nohup /mnt/arcreel/D/ArcReel/mmaudio-ambience.sh &` (both currently running from this session).
2. Add to `~/arcreel-v2-staging/v2-release-start.sh`: `export ARCREEL_MUSIC_URL=http://127.0.0.1:8001 ARCREEL_MUSIC_FREE_URLS=http://127.0.0.1:8188/free ARCREEL_AMBIENCE_URL=http://127.0.0.1:8002 ARCREEL_FACE_ID_URL=http://127.0.0.1:8003`; also start `/mnt/arcreel/D/ArcReel/faceid.sh`. After deploy, save each project's automation settings once (the narration launch profile changed: ADR-0151).
3. Optional: import `docs/r2/evidence/media-local-2026-10-30/flux2-klein-reference/endpoint-definition-4ref.json` to replace endpoint ce-3 (four reference slots).

## Known pre-existing failures (not from this program)
`tests/unit/lib/test_tts_skeleton.py::TestOrphanAudioRestartLost::test_orphan_audio_running_marked_restart_lost`: the test's fake queue lacks `requeue_free_restart_lost` (added by `0d09aaab9`, ADR-0129/0130, already in r2-v2.5.17); the same cause fails 3 tests in `tests/integration/lib/test_generation_worker_module.py`. `tests/integration/server/test_remote_mcp.py::test_remote_mcp_returns_typed_workflow_plan_and_rejects_bad_project` expects `adapt_episode`/`translate_story` tools; no change to `server/remote_mcp.py` or `server/agent_runtime` since the tag. `tests/integration/server/production_run/test_qualification_jobs.py::test_both_reviewers_are_qualified_on_the_host_corpus_and_recorded` fails on the deployed tag `r2-v2.5.17` too (run 2026-11-14 07:53; time-dependent, passed earlier the same night).

## Next (resume here)
All items are done, measured, deferred with reasons or blocked on the Human. Remaining before release: run the trial story→film with a cloud writer, read the film against these changes (framing, looks, music, ambience, best-of-2), then the release review.

## Release r2-v2.5.18 (2026-11-14)
- Tag `r2-v2.5.18` (local, lightweight) on `impl/r2-film-quality`; contains ADR-0140 … 0152 and the review fixes. Independent review `R2_CRAFT_REVIEW_2026-11-14.md`: round 1 REJECT (H1 planner/execution reference order), round 2 **ACCEPT** at `cf4b6b70e`; leftovers fixed in `f3c19746b`.
- No database migration.
- Deploy (Human, real terminal): `sudo ~/arcreel-v2-staging/m8e-review-stop.sh`, `sudo ~/arcreel-v2-staging/v2-deploy.sh r2-v2.5.18`, `sudo ~/arcreel-v2-staging/v2-release-start.sh`. The start script already exports the four service URLs (patched 2026-11-14) and the three services have systemd units.
- After deploy (agent, by Chrome): save each project's automation settings once (narration launch profile changed: ADR-0151 → re-records launch qualification); check one storyboard preview shows the framing line and cast block; confirm the run panel shows no `LAUNCH_QUALIFICATION_CHANGED`.
- Expected after deploy: storyboards made under 2.5.17 that have both a previous storyboard and a scene/prop sheet are stale once and regenerate (ADR-0149); new scripts carry scene looks, camera angles, narration cues.
- Rollback: no migration, so `v2-deploy.sh r2-v2.5.17` restores the code, but **only cleanly before 2.5.18 writes any script**: scripts written by 2.5.18 carry `image_prompt.look`, `composition.camera_angle` and `narration_cue`, which 2.5.17's strict script models (`extra="forbid"`) report as invalid, so their episodes would need those keys removed (or the script regenerated) after a rollback.
- Licence note for a commercial release: `docs/research/2026-11-14-model-licences-and-identity-alternatives.md` (MMAudio and InsightFace weights are non-commercial; both are switched off by unsetting their URL).

## Release r2-v2.5.20 (2026-11-15; supersedes r2-v2.5.19, not deployed)
- Trial run with a cloud writer (project `san-xuat-tu-ong-7fb4ef4b`, idea "Chuyến đò cuối") stopped twice `BLOCKED_QUALITY` in STORY: seed (`ernie`) and outline review (`particle-1`), all on `OUTPUT_TRUNCATED`. Cause reproduced with the app's prompts: the free cloud writers are reasoning models and reasoning counts against the 4,096 output cap.
- `0422ed663`: a sentence-opening word of the idea ("Trên …") is no longer taken for a character name (it cost every story one seed redraw).
- `09b926169` ADR-0153: cloud story calls are sent and reserved with the step cap + 12,288 reasoning tokens; a cloud brief's output budget grows per call by half of it. Re-run of seed → outline → review with the new budget: ernie, particle-1, deepseek-v4-1-flash all stop normally (largest call 10,415 tokens).
- Tests: `tests/unit/server/story_authoring` + `tests/integration/server/story_authoring/test_cloud_routes.py` (363 passed); story_authoring integration + production_run story adapter / crash recovery / idea draw (114 passed, 25 Postgres-only skipped → 33 passed on PG 55480); ruff, basedpyright, lint-imports, audit_tests clean.
- Launch qualification: recording a configuration that was recorded before (switching the writer back) was skipped as already stored, so readiness kept `LAUNCH_QUALIFICATION_CHANGED`; re-recording now moves that record forward (test `test_recording_an_earlier_configuration_again_makes_it_current`, SQLite + PG).
- No migration. Deploy (Human): `sudo ~/arcreel-v2-staging/m8e-review-stop.sh`, `sudo ~/arcreel-v2-staging/v2-deploy.sh r2-v2.5.20`, `sudo ~/arcreel-v2-staging/v2-release-start.sh`.
- After deploy: writer of `san-xuat-tu-ong-7fb4ef4b` = `ernie-5.5-flash-preview:free` (fallbacks particle-1 → deepseek-v4-1-flash → ling-3.2-flash → gemma-4-31b → local qwen3.5-vimax:9b); start the trial again.

## Release r2-v2.5.21 (2026-11-15)
- r2-v2.5.20 deployed 2026-11-15 by the Human; launch re-record fix verified on prod (readiness ready right after recording).
- Trial 3 (writer `ernie`): seed passed with the reasoning allowance, then `story_bible` spent 16,384 tokens on three draws → `BLOCKED_QUALITY`. Reproduced 6 draws: ernie reasoning 12k–51k chars, `reasoning.effort=low` does not bound it. Writer switched to `particle-1` (ernie kept as fallback). Trial 4 started 10:23:35 and passed seed → outline (one outline draw truncated at 16,384).
- ADR-0154: a step that spends its call cap without an acceptable output moves the story to the next writer (same rules as ADR-0139, same checks). Tests: story adapter (22, PG), story_authoring + production_run unit/integration + automation transitions (775 passed, PG); static gates clean.
- No migration. Deploy (Human) when convenient: the deploy parks running tasks and resumes them (ADR-0130). `sudo ~/arcreel-v2-staging/m8e-review-stop.sh`, `sudo ~/arcreel-v2-staging/v2-deploy.sh r2-v2.5.21`, `sudo ~/arcreel-v2-staging/v2-release-start.sh`.

## Release r2-v2.5.22 (2026-11-15)
- r2-v2.5.21 deployed (second attempt; the first failed `OFFLINE_FENCE_VIOLATED` because the agent's own watcher and qualification script were connected to the prod DB).
- ADR-0155: trial 4 refused 10/64 calls `OUTPUT_INVALID`, all scene drafts off the local grammar's exact shape (9 paragraphs instead of 8, dialogue paragraphs of 217–275 chars). Cloud prose is now accepted within 25% of the planned shape; fragments (< 120 chars) are refused; scene length stays checked by its window. Tests: story_authoring unit + integration 462 passed; static gates clean.
- Deploy (Human): stop the agent's DB-connected background tasks first, then `sudo ~/arcreel-v2-staging/m8e-review-stop.sh`, `sudo ~/arcreel-v2-staging/v2-deploy.sh r2-v2.5.22`, `sudo ~/arcreel-v2-staging/v2-release-start.sh`.

## Release r2-v2.5.23 (2026-11-15)
- r2-v2.5.22 deployed 11:34. Donor check for ADR-0155 recorded in the ADR.
- ADR-0156: endpoint `ark-seedream` (Seedream through `ArkImageBackend`, references in `image`, `watermark: false`), endpoint `gemini-tts` (`GeminiAudioBackend`, 30 voices, cue tags → `<sigh>`/`<laugh>`). Tests: custom provider + audio + image backends + router catalog + i18n 1458 passed; integration custom provider / config resolver / capability overrides / narration 309 passed (1 known pre-existing failure `test_tts_skeleton` orphan audio); frontend `pnpm check` 2719 passed; static gates clean.
- After deploy: switch BytePlus `seedream-4-5-251128` to endpoint `ark-seedream`; the sponsor adds a custom provider "Gemini TTS" (base `https://generativelanguage.googleapis.com`, their Gemini key, model `gemini-3.8-flash-tts`, endpoint `gemini-tts`); run the media qualification canary for both routes; then the cloud arm of the comparison.

## Release r2-v2.5.24 (2026-11-15)
- r2-v2.5.23 deployed; provider `custom-7` "Gemini TTS" added by the sponsor (TTS models only enabled, default `gemini-3.8-flash-tts`); BytePlus Seedream 4.5/4.0 switched to `ark-seedream`. Smoke through the app's builders: Gemini TTS WAV 24 kHz 6.2 s; Seedream with one reference keeps the ferryman's face, hat and clothes, 1600x2848, no watermark.
- ADR-0157: a plan finding is span-patched in the round's first cycle; rewrite and replan only when it survives. Trigger: trial 4 chapter 1 replanned twice (one note a pronoun slip), 61 review calls. Tests: story_authoring unit + integration + story adapter 485 passed (PG); static gates clean.
- Deploy (Human): the agent stops its DB watchers first.

## Release r2-v2.5.25 (2026-11-15)
- r2-v2.5.24 deployed 13:09. Trial 4's production run had already ended `FAILED_QUALITY` at 12:41: chapter 1's review was truncated on three judgments after three replans (220 calls), and the raw `OUTPUT_TRUNCATED` block carried no `CAP_EXHAUSTED` marker, so ADR-0154 did not move the story.
- Fix (ADR-0154 amendment): an exhausted judgment blocks with the marker. Test `test_a_review_the_writer_cannot_finish_hands_the_story_on`; story_authoring + story adapter 486 passed (PG).

## Release r2-v2.5.26 (2026-11-15)
- Trial 5 (r2-v2.5.25, started 13:24:58, adopted trial 4's story): chapter 1 sealed, chapter 2 drafted; ADR-0154 moved the writer particle-1 → deepseek-v4-1-flash → ernie, then the run failed `REPAIR_LIMIT` (unit_repair_limit 2) at 14:22; `chapter_review[2]` truncated at 14,336 output tokens on all three writers (finished draws 7–8.6k).
- ADR-0153 amended: `REASONING_ALLOWANCE` 28,672 (gemma-4's 32,768 completion cap is the tightest listed writer). ADR-0154 amended: each move is its own repair unit `story:writer:<provider>/<model>`. Tests: story_authoring + story adapter + crash recovery + automation transitions 596 passed (PG); static gates clean.
