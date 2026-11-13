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
| P1-11 ambience bed | todo | |
| P1-12 screen direction | todo | |
| P2-13 foley / leitmotif / ShotVL | todo | |
| P2-14 BytePlus guides via browser | todo | |
| ID-1 reference selection, view crops, 4th slot | todo | ViMax reference_image_selector |
| ID-2 N candidates + pick | todo | ViMax best_image_selector; ADR-0112 |
| ID-3 face-cosine instrument + calibration | todo | |
| ID-4 reference name binding | todo | |
| ID-5 costume/state timeline → derivatives | done | `2f86da4ca`, ADR-0146 |
| ID-6 face repair loop | todo | rules: repair only the picked image; independent acceptance; weight by face size |
| ID-7 DreamO bake-off, cloud LoRA | todo | |

Verification so far (HEAD `ceb92e7ab`): `tests/integration/lib/test_presentation_renderer.py`, `tests/integration/server/production_run/test_render_master_adapter.py`, `tests/integration/lib/test_project_manager.py`, `tests/unit/server/production_run/test_render_finish_inputs.py` 83 passed 2 skipped; read-model and jianying 25 passed; ruff, basedpyright 0, lint-imports 23 kept, audit_tests 0.
