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
| P0-6 VieNeu emotion cues + pauses | waiting on a listening check | cue `[thở dài]` adds 0.48 s on the deployed v3 Turbo but is experimental upstream and unverifiable without listening; samples in `/mnt/arcreel/D/ArcReel/ace-step-cache/tts-cue/` (plain, sigh, laugh). Implementation touches the narration audio basis; build only if the Human hears a real sigh. |
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
| ID-7 DreamO bake-off, cloud LoRA | blocked on the Human | DreamO runs on FLUX.1-dev, a gated Hub repo (needs the sponsor's licence acceptance and an HF token); a cloud LoRA needs a GPU we do not have on free tiers |

Verification so far (HEAD `ceb92e7ab`): `tests/integration/lib/test_presentation_renderer.py`, `tests/integration/server/production_run/test_render_master_adapter.py`, `tests/integration/lib/test_project_manager.py`, `tests/unit/server/production_run/test_render_finish_inputs.py` 83 passed 2 skipped; read-model and jianying 25 passed; ruff, basedpyright 0, lint-imports 23 kept, audit_tests 0.

## Host steps for the Human (after deploy)
1. Start the audio services: `nohup /mnt/arcreel/D/ArcReel/ace-step-api.sh &` and `nohup /mnt/arcreel/D/ArcReel/mmaudio-ambience.sh &` (both currently running from this session).
2. Add to `~/arcreel-v2-staging/v2-release-start.sh`: `export ARCREEL_MUSIC_URL=http://127.0.0.1:8001 ARCREEL_MUSIC_FREE_URLS=http://127.0.0.1:8188/free ARCREEL_AMBIENCE_URL=http://127.0.0.1:8002 ARCREEL_FACE_ID_URL=http://127.0.0.1:8003`; also start `/mnt/arcreel/D/ArcReel/faceid.sh`. After deploy, save each project's automation settings once (the narration launch profile changed: ADR-0151).
3. Optional: import `docs/r2/evidence/media-local-2026-10-30/flux2-klein-reference/endpoint-definition-4ref.json` to replace endpoint ce-3 (four reference slots).

## Known pre-existing failure (not from this program)
`tests/unit/lib/test_tts_skeleton.py::TestOrphanAudioRestartLost::test_orphan_audio_running_marked_restart_lost`: the test's fake queue lacks `requeue_free_restart_lost` (added by `0d09aaab9`, ADR-0129/0130, already in r2-v2.5.17).

## Next (resume here)
All items are done, measured, deferred with reasons or blocked on the Human. Remaining before release: run the trial story→film with a cloud writer, read the film against these changes (framing, looks, music, ambience, best-of-2), then the release review.
