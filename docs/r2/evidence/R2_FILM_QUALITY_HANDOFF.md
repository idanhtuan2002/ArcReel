# Film quality work — handoff (2026-11-13)

Worktree `.worktrees/r2-film-quality`, branch `impl/r2-film-quality` from `c7e1004a3` (= tag `r2-v2.5.16`). Not pushed, not released. Sponsor is preparing cloud accounts and API keys; the work below needs none.

## Done (commits on the branch)
| Commit | What | Verification run |
|---|---|---|
| `86dce6d0c` | research: donor mechanisms, cloud cost paths, roadmap synthesis (`docs/research/2026-11-13-*.md`) | docs only |
| `b2111797e` | ADR-0133: renderer masters finals to −14 LUFS / −1 dBTP (linear loudnorm, picture copied, loudness in manifest); MINOR delivery findings (loudness off target, dead air ≥ 3 s, subtitle > 20 cps, < 5/6 s, > 7 s) in local and Gemini reviews | `tests/integration/lib/test_presentation_renderer.py` 9 passed; `tests/integration/server/production_run/test_render_master_adapter.py` + `tests/unit/server/production_run` 137 passed / 2 skipped; final-check/reviewer selection 63 passed / 4 skipped; basedpyright 0/0 on touched files; lint-imports 23 kept |
| `94dba95af` | ADR-0134: storyboard continuity judge (11 ordered checks, verdict computed in code, high severity caps 69, `prompt_fix`), qualification rule (≥ 30+30 cases, recall ≥ 0.8, false drift ≤ 0.15, unanswered ≤ 5%) and `scripts/r2/qualify_continuity_judge.py` with derived identity swaps | `tests/unit/server/production_run/test_continuity_judge.py` 16 passed; basedpyright 0/0 |
| `806ec1d30` | `scripts/r2/bakeoff_video_engines.py` (same shots × engines, ledger costs under `__bakeoff__`, `--dry-run` estimate) + `docs/r2/bakeoff/plan.example.json` | `tests/unit/scripts/r2/test_bakeoff_video_engines.py` 3 passed |

Not run: full suite (policy), frontend (untouched), heavy Remotion/M6 render tests (r2/m3 untouched).

## Findings that change the plan
1. **Every cloud video adapter profile is `UNQUALIFIED`** in `r2/provider_capabilities/registry.json` (gemini, dashscope, ark, vidu, kling ×3, openai, grok, minimax, custom). In `ARCREEL_RELEASE_MODE=PRODUCTION_CANDIDATE` (production) `assemble_backend` refuses them and `qualify_route` refuses even the canary (ADR-0091 F1). Run the bake-off with the release mode unset. Before production use, the winning engines need adapter-level `OFFLINE_VERIFIED` evidence (precedent `R2_M8C_SPATIAL_ADAPTER_OFFLINE_VERIFICATION_2026-10-13.md`) and **sponsor approval of the status change**, then a route canary.
2. **Veo 3.1 Preview ids are dead.** Official deprecations page (aistudio.google.com/docs/deprecations, read 2026-11-13): `veo-3.1-generate-preview`, `-fast-`, `-lite-` shut down 2026-10-22; replacement `gemini-omni-1.2-flash`. Our defaults still point at them: `lib/config/service.py:16` (`_DEFAULT_VIDEO_BACKEND`), `lib/cost_calculator.py:23`, migration maps in `lib/system_config.py:212` and `lib/config/migration.py:105`. Upstream ArcReel already calls Omni through the Interactions API (`4221a0cdc`, `b59f93382` on `upstream/main`, which has a refactored `lib/backends/` layout) → backport, do not rewrite. Whether `veo-3.1-*-001` works with an AI Studio key is unknown (pages silent).
3. **Registry prices for Ark/Kling/MiniMax/Vidu are CNY (China platforms)**; BytePlus/Kling international bill USD at different rates (cost doc §1). Bake-off costs come from the ledger with these prices until the international price tables are added.

## Next, in order
1. (needs keys) `--dry-run`, then bake-off on 3 shots; Vietnamese TTS A/B; qualify a cloud continuity judge (build `cases.json` from cloud-made storyboards, `--derive-swaps`).
2. Backport Gemini Omni from upstream and move the defaults off dead Veo ids (follow `.claude/rules/provider-capabilities.md`, `docs/api-docs/AGENTS.md`).
3. Offline adapter verification for the 1–2 winning engines; sponsor approves status; route canary.
4. ADR-0134 step 3: MEDIA regenerates drift storyboards once with `prompt_fix` as a task payload addendum (worker builds the prompt from the script item in `server/services/generation_tasks.py:1616`; addendum must be recorded in provenance), `continuity.json` evidence.
5. Real motion profile (cloud i2v) + OpenMontage slideshow-risk / no-silent-downgrade gate; music bed with ducking once a music source exists; drama via Kling elements + lip-sync.

## Sponsor decisions (2026-11-13)
- **Adapter status change approved** ("duyệt chuyển trạng thái"): the agent may set `OFFLINE_VERIFIED` on the adapter profiles of the bake-off winners once their ADR-0091 F1 offline evidence file is complete (same form as the spatial precedent). The route canary remains a separate operator step.
- **Gemini free tier allowed for trial content** ("cho phép đưa nội dung thử nghiệm lên gói miễn phí của Gemini"), accepting that free-tier inputs may be used by Google.
