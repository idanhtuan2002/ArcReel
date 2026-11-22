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

## Catalog progress (2026-11-15, sponsor: "tiếp tục đến khi xong")
Catalog `docs/r2/R2_CONTENT_FORMS_CATALOG.md`; gap analysis `docs/research/2026-11-15-r2-forms-genres-video-types-vs-vision.md`.
- Rank 1 genre packs: **r2-v2.5.27** (ADR-0158), 28 packs. Not deployed yet.
- Rank 2 audiobook + sleep story: **r2-v2.5.28** (ADR-0159). Smoke on VieNeu: 35.5 s rendered in 19.2 s, M4B chapters correct. Not deployed yet.
- Rank 3 micro-drama polish: **r2-v2.5.29** (ADR-0160): burned captions, title and next-episode cards, hook < 4 s. Not deployed yet.
- Rank 4 hybrid motion (next): findings — the queue strips any caller-given video identity (`lib/generation_queue.py:161` `without_video_execution_identity`) and the worker materializes one per task from the project route (`lib/config/resolver.py:923` `resolve_video_backend`, payload bucket keys `video_provider_i2v`); media currency compares against the project's route. Per-shot motion needs a design across queue, worker and currency (an ADR first): which shots, which route per shot, how the planner expects a per-shot identity. Local i2v route exists in `fiction_drama_vi_v1` (`custom-3` `wan2.2-ti2v-5b-gguf`); cloud video adapters stay `UNQUALIFIED`.
- Trial 6 (r2-v2.5.26, started 15:24:27) still in STORY at the time of writing.
- Deploy needed for 2.5.27–2.5.29 (one deploy of `r2-v2.5.29` carries all three); stop the agent's DB watcher first.
- r2-v2.5.29 deployed 16:15 (carries 2.5.27–2.5.29). Trial 6 continues (STORY, chapter 3).
- Rank 6 video → story source: **r2-v2.5.30** (ADR-0161; `yt-dlp` added with the sponsor's consent). Not deployed yet.
- Rank 7 documentary narration: **r2-v2.5.31** (ADR-0162). Ranks 8–9 narration forms (story, top list, quiz, explainer from one fact pack): **r2-v2.5.32** (ADR-0163). Explainer charts/diagrams still open.
- Rank 10 product ad: deferred. The `content_mode=ad` workflow needs an automated selling-point owner and product-faithful pictures (reference-image generation); local klein cannot hold a product's look, so it waits for the Seedream canary.
- Rank 11 trailer: **r2-v2.5.33** (ADR-0164), cut from a succeeded run's verified finals; fixed-plan smoke 30.4 s at −14.2 LUFS. End-to-end planner run waits for a multi-episode film.
- Rank 12 L1a English film: **r2-v2.5.34** (ADR-0165): `fiction_narration_en_v1` (Gemini TTS), English reviewer prompts (Vietnamese digests unchanged), per-language corpus env. English corpus built at `/mnt/arcreel/D/ArcReel/operations/reviewer-corpus-en-2026-11-15/` (`build_en.py`: Vietnamese corpus stories' `narration_en`, stills from the Vietnamese clean finals, one Gemini TTS call per story cut at Whisper word pauses). Host setting `ARCREEL_REVIEWER_CORPUS_EN` and the reviewer qualification run are the remaining steps.
- Releases 2.5.30–2.5.34 not deployed yet (deployed: 2.5.29).
- Known pre-existing failure (also at HEAD before 2.5.34): `tests/integration/server/production_run/test_qualification_jobs.py::test_a_reviewer_that_accepts_a_defect_is_not_recorded` — reviewer_b's job qualifies but the status does not show it recorded; its fake routes share provider and model ids. Not investigated further.
- Rank 13 voiced drama on stills (ADR-0166): phase A in r2-v2.5.35 (voice cast); **phase B committed `464d2a4c8`** (untagged): character units of a `character_speech_delivery=tts` project are spoken line by line in their voices and joined (basis kind version 2); planner currency reads `tts_character_voices` back from the version record (regression test `test_a_voiced_character_version_keeps_its_voices_for_currency`). Related tests: 62 files, 1750 passed; 2 known pre-existing failures (`test_tts_skeleton` orphan audio restart, `test_remote_mcp` tool set). Next: phase C (`fiction_drama_vi_v2`, drama reviewer prompt, qualification, two-character smoke). Phase C progress: drama reviewer corpus built 2026-11-17 (40 cases, `/mnt/arcreel/D/ArcReel/operations/reviewer-corpus-drama-2026-11-16`). 2026-11-22: `character_speech_delivery` is now settable (PATCH /projects + drama settings switch) in **r2-v2.5.75** = `c83255a13` (pushed; not deployed). Tests: router 53 passed, frontend `pnpm check` 2750 passed. Next after deploy: create the drama project (POST /projects content_mode=drama), upload a two-character story, set TTS, PUT /automation/settings launch_profile_id=fiction_drama_vi_v2 (trial 7 routes), POST /automation/qualification/reviewers, then the smoke run. 2026-11-22 (r2-v2.5.75 deployed): drama project `drama-smoke-chiec-ong-ho-62d166d0` created via API (content_mode=drama, storyboard, live_premium_drama, episode_adaptation=screen, character_speech_delivery=tts; source: original two-character story `chiec-dong-ho-cua-ong.txt`, Khang + Vy); quality profile `01a201de-a9bc-79cb-99cf-b6f79ee7b499` published with trial 7's policy; settings = trial 7 routes/fallbacks with launch_profile_id fiction_drama_vi_v2; project backends aligned (still-clip, klein-ref i2i, Ernie complex). Reviewer qualification started 13:09 (+07). Remaining launch blockers: LAUNCH_PROFILE_NOT_QUALIFIED/MISSING_QUALIFIED_REVIEWER (qualification), INSUFFICIENT_DISK cleared 2026-11-22 (user approved: 81 old `bs-*` deploy backups deleted, newest 5 and governance archives kept; `/` 25 GB free). Trial 7: episodes 2–4 SUCCEEDED; episode 5 run 37fdb3bd BLOCKED_CONFIGURATION WORKFLOW_RETRY (three TTS lines failed on sibling script writes; the plan named a withheld unit's `retry`) — fixed in **r2-v2.5.76** = `0dd3d7e58` with planned episode titles kept (episodes 4/5 were saved as `looks`/`Example Domain`). Episodes 2/4 renamed to their planned titles; episode 5 (planned `Nhịp chèo đầu tiên`) waits until its run ends (rename writes the pinned script); episode 1 has a Chinese title and no recorded outline title. Open: sibling TTS/video tasks fail `formal artifact input changed` because each commit writes `generated_assets` into the script the others claimed (digest over whole file); readiness returns 500 when a project has no quality profile. Local reviewer qualification for fiction_drama_vi_v2 (13:09–13:49) FAILED, stopped early: qwen2.5vl:7b caught every defect reviewed but rejected 3/10 clean calibration cases (c05 visual 3; c07, c09 FRAMES_NOT_ILLUSTRATING_NARRATION — dialogue lines do not describe the picture, so the narration-calibrated probability check (cut 0.15) cannot separate clean drama ~0.11 from defects 0.10–0.12); gemma3:4b accepted defect d01 (dialogue from another story). Receipts: /mnt/arcreel/D/ArcReel/operations/reviewer-receipts/reviewer_{a,b}/ (case ids collide with the narration corpus; filter by time). Plan B started 13:52: custom-7 (AI Studio free key) models gemini-3.5-flash and gemini-2.5-flash enabled (endpoint gemini-generate; review method WATCH: picture + audio), reviewer_a=gemini-3.5-flash, reviewer_b=gemini-2.5-flash, max_cost_per_call 1. Free tier 20 req/model/day (reset 15:00 ICT): a 429 ends the job; re-run reuses stored reviews. Result 13:59: both Gemini reviewers FAILED with real verdicts (no quota errors): gemini-3.5-flash rejected clean c01/c02/c05 (continuity 2, VISUAL_INCONSISTENCY); gemini-2.5-flash rejected clean c02/c05/c07 (CHARACTER_VISUAL_INCONSISTENCY, AUDIO_VOICE_INCONSISTENCY) while catching every defect it reviewed (d01 scored 1/1/1/1/1). Root cause = corpus, not reviewers: the drama corpus's clean cases reuse the English narration corpus stills (`build_drama.py` `stills()` → reviewer-corpus-en-2026-11-15/images), made per scene with no identity, so a two-character dialogue (c01 Lan + Khang) shows a child, a girl with an old man, then two women. Strong reviewers rightly reject them. NEXT (decision): rebuild the drama corpus clean half with identity-consistent stills of exactly the two speaking characters (production path: character sheets + flux2-klein-4b-ref i2i on local ComfyUI), keep the injected defects, then re-qualify Gemini (and re-check qwen/gemma). Until then fiction_drama_vi_v2 cannot qualify any reviewer. 2026-11-22 afternoon: r2-v2.5.76 deployed; trial 7 ep 5 run 37fdb3bd resumed — TTS E5S15-17 regenerated, MEDIA passed (one video still failed once on `formal artifact input changed` and was redone), then QUALITY blocked ASSESSOR_FAILED: reviewer_a qwen2.5vl FAILED (likely GPU OOM while I painted corpus test stills 14:23–14:28), reviewer_b gemma3 accepted. The FAILED review was stored and reused, so resume blocked again at once — fixed in **r2-v2.5.77** = `be2a8eb19` (failed review set aside as `.failed.json` when the run blocks; resume asks again within the attempt limit; evaluator logs the error). Tests: test_quality_adapter + test_evaluators + test_qualification_jobs 38 passed on PG16. After deploying 2.5.77: resume 37fdb3bd twice (first resume sets the failed review aside and blocks; second asks again) — only when the GPU is free. Corpus rebuild: `identity_stills.py` (Ollama qwen3.5-vimax:9b plans appearance + shots; FLUX.2 klein t2i portraits; klein-ref scene stills with the visible speakers' portraits as references; workflow /var/tmp/ar9b/flux2-klein-reference.json) — story 0 checked by eye: both characters consistent across shots. `build_drama.py` now reads `stills/`; old clips/finals/manifests kept as `*-v1`. Full rebuild running in background (log scratchpad rebuild.log), ~2 h GPU; do not start GPU runs meanwhile.
- 2026-11-15 ~22:20 host hang + hard reboot: NTFS data disk `/dev/nvme1n1p1` came back dirty, so `/mnt/arcreel/D`, Ollama, ComfyUI, local media services and the app did not start. Recovered with `ntfsfix -d` and a service restart (Human, sudo). Trial 7 (`d75c3948`, project `chuyen-o-cuoi-trial-7-58def97e`) resumed by itself: the orphan adaptation task was marked `restart_lost` and the run resubmitted it. Before the hang, API requests took 200–250 s while ADAPTATION ran for ~35 min. Watch for memory pressure. A Windows chkdsk of that disk is still advisable.
- 2026-11-15 late, trial 7 (`d75c3948`) blocked at ADAPTATION. Three fixes:
  - **r2-v2.5.37** `22f617fc8`: in narration mode a speakerless quoted line becomes narration. Deployed 22:4x.
  - **r2-v2.5.38** `a567c97f8`: a run of an uploaded story records `source_language`. Trial 7 had none, so its episodes were counted per character (one is 191 B) and titled in Chinese.
  - **r2-v2.5.38** `cfb031347`: RESUME after spent task attempts (`OWNER_TASK_FAILED` / `ADAPTATION_FAILED`) retries the stage in a new lineage. Before this, every RESUME re-read the same failed tasks.
  - Tests: production_run unit+integration on PG, 3241 passed. One failure was already there before these changes: the `test_text_adapter` inventory fixture still uses the old character fields.
  - Trial 7's episode plan is still the Chinese, character-counted one. A clean trial needs the episode planning reset after deploying 2.5.38.
- 2026-11-16, **r2-v2.5.40** = `acadfbcda`:
  - `f00bf75e9` (r2-v2.5.39, deployed): a missing story language is recorded only at run start. On RESUME it moved the pinned source revision, and trial 7's lineage was lost.
  - `e3f54cdb5`: `update_run_project` refuses any run-owned write that would move a pinned input (`RUN_WRITE_WOULD_MOVE_INPUT`). A source-scan test keeps other direct writes out of `server/production_run`.
  - `53d17ee29`: an adaptation `source_excerpt` that is cut short ("...") or runs on past its sentence is anchored to the source sentence its start (at least 24 letters, matching one place only) begins. Trial 7's new run (`454e9a8f`) failed three tasks on this.
  - ADR-0166 phase C:
    - `12a9ac53a`: `fiction_drama_vi_v2` profile, preflight `CHARACTER_SPEECH_DELIVERY_MISMATCH`, drama voice availability, the setting witnessed and carried by the autopilot template.
    - `39035a697`: MEDIA casts voices through the `text_voice_cast` task. Writes are guarded; `VOICE_CAST_FAILED` is retried on resume.
    - `acadfbcda`: drama reviewer prompts, with narration digests unchanged; corpus `ARCREEL_REVIEWER_CORPUS_DRAMA`.
  - Tests: production_run unit and integration on PG, 3205 passed. One failure was already there before these changes (the `test_text_adapter` inventory fixture).
  - Remaining for phase C, on the host: a drama reviewer corpus, reviewer qualification for `fiction_drama_vi_v2`, and a two-character smoke run.
- 2026-11-16, **r2-v2.5.42**. Trial 7 blocked twice at SCRIPT with EXTERNAL_INPUT_CHANGED. In both cases a later step of the run had changed the adaptation basis:
  - The script step registered "Chú Tư". Fixed in `4201b5f37`: added characters keep the adaptation current.
  - Saving the script renamed the episode to "第1集". Fixed in `239dca4f3` and `e3d4b79d1`: a missing script title falls back to the planned title, and a title-only change keeps the adaptation current.
  - An independent read-only audit (Opus agent) of pinned inputs against later writers led to `f8323e7c9` (remote MCP tool parity, stale tests) and the resume fixes in this release:
    - an input-changed block with an unmoved witness retries the stage;
    - MEDIA, RENDER and QUALITY attempt-limit blocks retry on resume;
    - a stale script with current media still completes an episode;
    - a busy resource blocks as RESOURCE_UNAVAILABLE;
    - voice casting never registers a character.
  - Open LOW findings: a version-restore error in storyboard selection crashes one tick and loses that unit's pick. EXPORT compares the re-extracted JPEG thumbnail byte for byte, which ffmpeg may not reproduce exactly.
  - Tests:
    - production_run, router, adaptation, voice, MCP and tts on PG: all pass.
    - script_generator and project_manager: 251 pass without PG. Their PG-only failures also occur at r2-v2.5.41.
- 2026-11-16, trial 7 at MEDIA, releases r2-v2.5.43–2.5.48 (all pushed; 2.5.45 deployed):
  - The project had no `image_provider_i2i` or `video_backend`, so every storyboard failed with `image_capability_missing_i2i`. I set them like san-xuat. **2.5.43** makes preflight check the project's real media lanes.
  - **2.5.44**: stale storyboards whose videos are current complete an episode.
  - The "Mái chèo" prop was regenerated from the UI six times during MEDIA, which redrew the storyboards and left the videos stale. **2.5.45**: MEDIA remakes stale videos.
  - Each resume redid best-of-2 selection. **2.5.46**: a kept choice (`kept_version`) survives a new lineage.
  - Remakes were refused with `reference_duration_confirmation_required`, and MEDIA just retried. **2.5.47**: a call that queued nothing blocks with the real refusal. **2.5.48**: remakes confirm the tiers the tool proposes. I checked the refusal by POSTing generate/video for E1S01 (planned 2 s, TTS 2.8 s, tier 3 s).
  - Tests: production_run on PG, 3269 passed, 0 failed.
- 2026-11-16 11:46, **trial 7 SUCCEEDED** on r2-v2.5.48. Run `454e9a8f`, episode 1, generation 7. Stage times: MEDIA done 11:42, RENDER 11:43, QUALITY 11:45, EXPORT 11:46. Quality (record gate):
  - reviewer_a `qwen2.5vl:7b` rejected: story 4, visual 3, audio 5, continuity 4, pacing 4; MINOR finding that frame 3 does not match its subtitle.
  - reviewer_b `gemma3:4b` accepted: 4/4/5/4/4; MINOR findings: harsh light on Ông Ba's face, and Hải's feet on the steps while he appears on the boat.
  - The best-of-2 selection was redone once in generation 7 because generation 6's evidence predates `kept_version`.
- 2026-11-16, ADR-0166 phase C, continued (r2-v2.5.66):
  - `8f9f56eac`: a drama final is reviewed against its spoken lines.
    - Before: the quality adapter read the narration from script segments, and a drama script has none. Every drama final went to review with an empty narration, and the subtitle check failed it as CRITICAL. The phase C smoke run would have stopped at QUALITY.
    - Now: the bare lines are checked against the subtitles. `FinalEvidence.dialogue` ("Name: line") feeds the drama review prompt. A corpus case may name a dialogue file.
  - Drama reviewer corpus builder:
    - Script: `/mnt/arcreel/D/ArcReel/operations/reviewer-corpus-drama-2026-11-16/build_drama.py`.
    - Content: the 20 Vietnamese corpus stories, rewritten as two-character dialogue by OpenRouter Ernie with Particle as fallback, and checked in code. Lines are voiced by local VieNeu, a male and a female voice per story. Stills come from the English corpus. The defects are the same 10 types.
    - Each case carries `narration.txt` and `dialogue.txt`.
    - Run: `OR=<openrouter key> uv run python build_drama.py` (`one` builds story 0 only).
  - The host start script `v2-release-start.sh` sets `ARCREEL_REVIEWER_CORPUS_DRAMA` to that manifest (backup `.before-drama-corpus.20261116`). It applies at the next deploy.
  - Remaining for phase C:
    - build the corpus (the sponsor runs it with the OpenRouter key);
    - after trial 7's run frees the GPU, qualify the reviewers for `fiction_drama_vi_v2` from the run panel;
    - run the two-character smoke run.
- 2026-11-17, r2-v2.5.68–2.5.74 (all deployed; 2.5.74 is on production):
  - Trial 7, episode 2:
    - A video batch is no longer withheld for one unit's duration tier.
    - The app deadlocked on the project lock (an event-loop wait under the lock). Fixed.
    - API calls left pending by a dead worker no longer keep usage unknown.
    - An unknown usage is re-measured as a new append-only reference (AUTO_PRODUCTION_IMMUTABLE).
    - Continuity verdicts are kept by frame digest across runs.
  - UI changes:
    - autopilot in the header;
    - run status and pause in the operations summary;
    - the run banner only on editing pages;
    - run news in the workspace notifications.
  - Run d87361b8 rendered episode 2's film at 11:58. Its QUALITY findings are not read yet.
  - Next steps (phase C):
    1. The sponsor runs `build_drama.py` with the OpenRouter key.
    2. Qualify `fiction_drama_vi_v2` from the run panel.
    3. Run a two-character drama smoke.
  - Also open: rename episode 2's title, which is "visual_layer_ep02".

