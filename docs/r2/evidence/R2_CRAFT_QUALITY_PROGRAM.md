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
