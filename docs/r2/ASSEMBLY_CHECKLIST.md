# Assembly checklist — progress and work to do

The single tracker of the assembly ([GOAL](../GOAL.md), [plan](ASSEMBLY_PLAN.md), [handoff](evidence/ASSEMBLY_HANDOFF.md),
[acceptance](evidence/ASSEMBLY_ACCEPTANCE.md)). Update the box and the evidence column in the same commit as the work.
Legend: `[x]` done · `[~]` in progress · `[ ]` to do · `[!]` blocked · **S** = needs the sponsor.

## Sponsor items

| | Item | Status / evidence |
|---|---|---|
| [ ] | **S** Cloudinary account, pasted in DramaClaw → Settings → Media Storage | D28 |
| [ ] | **S** OpenRouter, Gemini, BytePlus keys pasted in DramaClaw → Models & Channels → Custom (after M1 profile) | M1 |
| [x] | Video route for first films = local Wan (D27) | 2026-11-23 |
| [x] | GOAL amendment: donor interface languages allowed (DramaClaw Vietnamese UI) | `docs/GOAL.md` rule 1 |
| [x] | Media relay: Cloudinary default + inline option (D28) | plan D28 |
| [x] | Story language per story: `zh` (huohuo + translation) or `vi` (old app's Vietnamese engine via ArcReel story-run API) (D29) | 2026-11-23 |
| [ ] | **S** After the first film: budget decision (D20) | — |

## M0 — DramaClaw up

| | Task | Evidence |
|---|---|---|
| [x] | Release images 2.0.2, loopback ports, NewAPI initialized | ASSEMBLY_ACCEPTANCE M0 |
| [ ] | Pin images by digest; media-catalog auto-update off; check 2.0.2 against `b299bfd` | plan §0 |

## M1 — models, voices, local video

| | Task | Evidence |
|---|---|---|
| [ ] | M1a voice adapter `assembly/voice_adapter/` (data: URL in, SHA-256 → VieNeu preset, MP3 out at `host.docker.internal`, unknown = error) + tests | |
| [ ] | M1a casting `assembly/connector/voices.py` (after `characters`; per age group after `identity_plan`; region by setting D18) + tests | |
| [ ] | M1a DramaClaw ComfyUI channel with the local Wan workflow; one clip probe | D27 |
| [ ] | `assembly/config/dramaclaw-profile.json` (OpenRouter text, Gemini vision spread, OpenAI-type channel → BytePlus Seedream for `LingShan-G2`, Seedream 4.0 second pool, VolcEngine Seedance) | D5–D8 |
| [ ] | `docs/r2/ASSEMBLY_MODELS.md` slot → model → pool → fallback | |
| [!] | M1.0 probes per model incl. base64 on Seedream and the ComfyUI channel (needs keys) | D28 |
| [ ] | Inline relay option in DramaClaw (approved donor change, rebuilt image, PORTING) — if probes allow | D28 |
| [ ] | Cloudinary daily cleanup job | D28 |

## M2 — first films from "Chiếc đồng hồ của ông", both spines

| | Task | Evidence |
|---|---|---|
| [ ] | Connector core: REST client, run state file, resume, retries (media 1, text 3), class rule for no-op steps, stop on repeat | plan §0, §5 |
| [ ] | Ingest text with `Chapter N` markers; configure (`ethnicity`, `narration_style`, `sketch_image_selection`, 720×1280) | |
| [ ] | **Narrated film** (prose → `spine_template = narrated`) end to end | |
| [ ] | **Drama film** (prose → huohuo `drama_script_formatter` via `POST /api/v1/agent/drama_script_formatter/chat` → headers rewritten to `INT./EXT. <nơi> - <thời gian>` → `spine_template = drama`), character voices per `Name: line` | round B §9; huohuo `agent-skills/drama_script_formatter` |
| [ ] | Identity images for every identity; voices cast after characters | |
| [ ] | Acceptance by eye: Vietnamese speech and subtitles, two characters consistent, sync — recorded | ASSEMBLY_ACCEPTANCE |
| [ ] | `lib/story_translation.py`: public `translate_text` | |

## M2b — thin Vietnamese console

| | Task | Evidence |
|---|---|---|
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
| [ ] | Review post-stage report-only (two reviewers, AIVPE guards) | plan §0 |

## M6 — operations (and D25)

| | Task | Evidence |
|---|---|---|
| [ ] | DramaClaw Vietnamese UI (translate 5 886 strings, `SUPPORTED`, switcher, rebuild web image) | D25 |
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
