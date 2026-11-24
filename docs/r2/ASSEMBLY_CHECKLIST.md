# Assembly checklist — progress and work to do

The single tracker of the assembly ([GOAL](../GOAL.md), [plan](ASSEMBLY_PLAN.md), [handoff](evidence/ASSEMBLY_HANDOFF.md),
[acceptance](evidence/ASSEMBLY_ACCEPTANCE.md)). Update the box and the evidence column in the same commit as the work.
Legend: `[x]` done · `[~]` in progress · `[ ]` to do · `[!]` blocked · **S** = needs the sponsor.

## Current priorities (sponsor 2026-11-24, after film 1)

1. Vietnamese interface and control: DramaClaw UI in Vietnamese (D25), Xia Director usable in Vietnamese.
2. Remake from an existing video (D22) and advertising / affiliate-marketing videos for TikTok and YouTube first.
3. The rest of M2–M6 after these.

Priority 2 tasks ([research](../research/2026-11-24-r2-remake-and-ads-donors.md)):

| | Task | Evidence |
|---|---|---|
| [ ] | Remake as a new story: old app ADR-0161 transcript (`video-sources`) → connector `--from-video <url>` → DramaClaw film | research §4.1 |
| [x] | **S** OpenMontage driver: both prepared (sponsor 2026-11-24); `python -m assembly.openmontage.run --driver claude|codex`, resumable at checkpoints | ASSEMBLY_ACCEPTANCE OpenMontage drivers |
| [~] | OpenMontage installed pinned (`4f682c8`); `localization-dub` probed to the first checkpoint with both drivers; next: finish one dub and a product ad from stills | research §4.2 |
| [ ] | Publishing to TikTok/YouTube via Postiz with affiliate links (per-post sponsor approval) | research §4.3 |

## Sponsor items

| | Item | Status / evidence |
|---|---|---|
| [x] | **S** Cloudinary account in DramaClaw → Settings → Media Storage (cloud name corrected) | 2026-11-23: DramaClaw `upload_image_file` → `res.cloudinary.com/…/dramaclaw-relay/…`, fetched back; Admin API listings 200 |
| [x] | **S** OpenRouter, Gemini, BytePlus keys pasted in DramaClaw → Models & Channels → My Config | 2026-11-23, ASSEMBLY_ACCEPTANCE M1.0 |
| [x] | Video route for first films = local Wan (D27) | 2026-11-23 |
| [x] | GOAL amendment: donor interface languages allowed (DramaClaw Vietnamese UI) | `docs/GOAL.md` rule 1 |
| [x] | Media relay: Cloudinary default + inline option (D28) | plan D28 |
| [x] | Story language per story: `zh` (huohuo + translation) or `vi` (old app's Vietnamese engine via ArcReel story-run API) (D29) | 2026-11-23 |
| [ ] | **S** After the first film: budget decision (D20) | — |

## M0 — DramaClaw up

| | Task | Evidence |
|---|---|---|
| [x] | Release images (upgraded 2.0.2 → **2.1.3** on 2026-11-24, sponsor decision), loopback ports, NewAPI initialized | ASSEMBLY_ACCEPTANCE M0; PORTING upgrade section |
| [x] | Pin images by digest; media-catalog auto-update off; check 2.0.2 against `b299bfd` — digests in `override.yml`, containers recreated, config kept; auto-update false; image built from `1ec0236`, which differs from `b299bfd` in 4 `src/novelvideo` files (freezone canvas paste only) | 2026-11-23 |

## M1 — models, voices, local video

| | Task | Evidence |
|---|---|---|
| [x] | M1a voice adapter `assembly/voice_adapter/` (data: URL in, SHA-256 → VieNeu preset, MP3 out at `host.docker.internal`, unknown = error) + tests — code, unit tests, service unit done; transport verified from inside the DramaClaw container (fal request → MP3); DramaClaw's own TTS task with an uploaded sample left for M2 | film 1: DramaClaw's own TTS task voiced all 18 beats via NewAPI `assembly-voice` (2026-11-24) |
| [x] | M1a casting (`assembly/voices/`: VieNeu catalog from its own preset file, registry, casting rule by gender/region) + tests — done; sample generation and upload to DramaClaw come with the connector (M2) | film 1: narrator + 3 characters cast and uploaded to every voice slot |
| [x] | M1a DramaClaw ComfyUI channel with the local Wan workflow (Wan2.2 TI2V 5B GGUF, `assembly/config/comfyui/wan22-5b-i2v.json`, bridge `172.17.0.1:8189`); clip through NewAPI 160 s | ASSEMBLY_ACCEPTANCE M1a Wan |
| [x] | `assembly/config/dramaclaw-profile.json` (applied in DramaClaw "My Config"; image route = VolcEngine-type channel per probe; `watermark: false` defaults; embedding `gemini-embedding-001` 768) — (OpenRouter text, Gemini vision spread, OpenAI-type channel → BytePlus Seedream for `LingShan-G2`, Seedream 4.0 second pool, VolcEngine Seedance) | D5–D8 |
| [x] | `docs/r2/ASSEMBLY_MODELS.md` slot → model → pool → fallback | written 2026-11-23 |
| [x] | M1.0 probes per model incl. base64 on Seedream and the ComfyUI channel — all pass | ASSEMBLY_ACCEPTANCE M1.0, M1a Wan |
| [ ] | Inline relay option in DramaClaw (approved donor change, rebuilt image, PORTING) — if probes allow | D28 |
| [x] | Cloudinary daily cleanup job — `assembly/ops/cloudinary_cleanup.py` runs inside the api container, timer `cloudinary-cleanup.timer` 04:30 daily; runs clean (HTTP 200), probe asset deleted with `RELAY_MAX_AGE_HOURS=0` | D28 |

## M2 — first films from "Chiếc đồng hồ của ông", both spines

| | Task | Evidence |
|---|---|---|
| [x] | Connector core — `assembly/connector/` on DramaClaw's own Hermes toolset (ported whole, CE owner mode), playbook auto-advance loop on `pipeline/status`, state file + `--state` resume, stop on non-advancing step, task errors surfaced; unit tests; live run pending | film 1 produced end to end (2026-11-24); `test_connector_film.py` |
| [x] | Ingest text with `Chapter N` markers; configure (9:16, realistic, third person, Vietnamese, Wan backend, Seedream sketches/renders, subtitles) — code done (`setup.prepare_project`) | film 1 |
| [~] | **Narrated film** (prose → `spine_template = narrated`) end to end — produced 2026-11-24 (53 s); visible defects; awaiting the sponsor's viewing | ASSEMBLY_ACCEPTANCE M2 film 1 |
| [ ] | **Drama film** (prose → huohuo `drama_script_formatter` via `POST /api/v1/agent/drama_script_formatter/chat` → headers rewritten to `INT./EXT. <nơi> - <thời gian>` → `spine_template = drama`), character voices per `Name: line` | round B §9; huohuo `agent-skills/drama_script_formatter` |
| [x] | Identity images for every identity; voices cast after characters | film 1: 3 main characters, 5 identities, images generated |
| [ ] | CP1 extension: review the portrait prompts (`face_prompt`, appearance) before any portrait is generated — **deferred by the sponsor 2026-11-24** (portraits generated as now) | sponsor note |
| [x] | Narrated Vietnamese narration: DramaClaw zh rewrite (third person) → line translation with names restored (`assembly/connector/rewriter.py`) | film 1: 18 Vietnamese lines, speakers kept |
| [ ] | Acceptance by eye: Vietnamese speech and subtitles, two characters consistent, sync — recorded | ASSEMBLY_ACCEPTANCE |
| [ ] | `lib/story_translation.py`: public `translate_text` | |

| [ ] | Upgrade smoke procedure: on each donor upgrade re-vendor the toolset, run donor tests, M1 probes and a two-beat smoke film before real runs | research 2026-11-24 §4.3 |
| [x] | Explicit-model rule: every costly connector call names its model/backend (no donor defaults) | ledger 2026-11-24 |
| [ ] | **S** D20: paid text/vision (and video) models, with film 1's call counts | research 2026-11-24 §4.2 |

| [~] | Xia Director chat agent enabled (Codex via `assembly-agent` channel); answers in Vietnamese; unreliable on the free model (1/2 turns empty); next: try `director-auto` on the drama film | ASSEMBLY_ACCEPTANCE Xia Director |

## M2b — thin Vietnamese console

| | Task | Evidence |
|---|---|---|
| [~] | Checkpoints CP1–CP5 from the Hermes playbooks in the connector (CP1 both modes, CP2–CP5 step mode; `--mode`, `--approve CPn`); film 1 runs with CP1 waived (sponsor 2026-11-23) | `test_connector_film.py` |
| [ ] | Run list (All / Active / Done / Failed), start form (four idea sources, setting, spine, mode auto/step) | D21, D22 |
| [ ] | Step timeline with Continue / Pause / Redo, deep links into huohuo and DramaClaw screens, errors panel, film player | |
| [ ] | Catalog of functions with status and where they run | |

## M3 — story stage

| | Task | Evidence |
|---|---|---|
| [ ] | huohuo built from the pinned checkout with our override (env presets, host gateway, loopback, random token) | plan §0 |
| [ ] | Connector: create novel, premise, outline, memory init, generate-remaining with resume (`mode: "remaining"`), fetch chapters | |
| [ ] | Translation with the Hán-Việt name glossary | plan M3.3 |
| [ ] | First `original` story → read by the sponsor | |
| [ ] | Connector `vi` path: ArcReel story-run API (`draft_brief` → `start_run` → poll → `approve_run` → `export_run`) → text into the film stage | D29 |
| [ ] | First story in each language from the same premise → the sponsor reads both | D29 |

## M4 — finish and review

| | Task | Evidence |
|---|---|---|
| [ ] | Finish post-stage: captions, loudness −14 LUFS, music bed, ambience | |
| [ ] | Review post-stage report-only — first use DramaClaw's own verifiers (enabled in CE, on demand only, not called by the pipeline or the Hermes toolset): `beats/{b}/verify`, `verify-frame`, `score`/`score-batch`, `verify/consistency`, `verify/continuity`, `verify/episode-overview`; report per episode at CP3/CP5; then the two-reviewer pass where they leave gaps. Portraits have no automatic check in DramaClaw (human CP1 only) | plan §0; `verification/routes.py` |

## M6 — operations (and D25)

| | Task | Evidence |
|---|---|---|
| [x] | DramaClaw Vietnamese UI — **shipped by the donor in v2.1.3** (`locales/vi`, 7 138/7 138 keys; `SUPPORTED = zh, en, vi, pt`); switch once with `?lng=vi` or the account menu (kept per browser); no donor change needed | 2026-11-24, Chrome check |
| [ ] | Backups of three stacks (keys excluded) + restore drill; autostart; alerts | |
| [ ] | Run queue for parallel series (bounded by pools) | D19 |
| [ ] | Jianying draft export post-stage (ArcReel) | verification §3 |
| [ ] | Local image adapter in front of ComfyUI (when pools run out) | plan §0 |

## M5 — coverage

| | Task | Evidence |
|---|---|---|
| [ ] | shenbi comedy/fanfic skills, ViMax children's adaptation as huohuo genre skills; old app's packs where no donor has them | coverage matrix |
| [ ] | Audiobook from a story; remake from another video (old app's ADR-0161 unit) | D22 |
| [ ] | OpenMontage driver research, then its forms | |
