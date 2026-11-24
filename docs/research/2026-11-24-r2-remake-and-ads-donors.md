# Remake from an existing video, and advertising / affiliate videos (TikTok, YouTube first)

Date: 2026-11-24. Sponsor priority after film 1. Labels: **FACT**, **INFER**, **UNKNOWN**. Inventory first (research
rule 1–3), then options; no option is decided here except where only one exists.

## 1. What already exists (FACT)

| Source | Unit | State |
|---|---|---|
| Old app (ArcReel/R2, production `r2-v2.5.90`) | ADR-0161 "a video becomes a story source": `yt-dlp` audio of one URL → Groq `whisper-large-v3` transcript → `source/<slug>.txt` + origin record "transformed variant only"; API `POST/GET /projects/{p}/video-sources` | built and smoke-tested 2026-11-15; YouTube reuse policy noted (meaningful difference, storyline + commentary) |
| OpenMontage @ `08e2151` (upstream `2e003e6`) | starts from "a YouTube video, Short, Reel, TikTok, or local clip" → 2–3 differentiated concepts, cost estimate, a sample before full production (README) | not installed; agent-driven |
| OpenMontage pipelines | `clip-factory` (long video → many short social clips), `localization-dub` (transcript → translated subtitles, dubbed audio, optional lip-sync), `podcast-repurpose`, `talking-head`, `avatar-spokesperson`, `screen-demo`, `animated-explainer`, `documentary-montage`, `cinematic`, `hybrid` | stages idea → script → scene_plan → assets → edit → compose → publish |
| OpenMontage product films | README example "Products Come to Life": approved product stills pinned as first/last frames, image-to-video motion, narration, sound, custom composition; TikTok-style word captions (Remotion) | showcase uses paid providers (Kling via fal, Chirp3-HD) |
| DramaClaw v2.1.3 | Freezone skills are beat-level (sketch/frame/scene-360/review); no remake or ad flow | running |
| ArcReel upstream (v0.29) | "product material / ad mode" (verification round §3) | not ported |
| This host | `postiz` skill (scheduling posts to TikTok, YouTube and 26 other channels) | available; publishing needs the sponsor's explicit approval per post |

## 2. The forms the sponsor asked for (INFER)

1. **Remake as a new story** — another video's plot told anew (Vietnamese narration/drama): ADR-0161 transcript → our
   film path (DramaClaw via the connector). Everything exists; only the hand-off is missing.
2. **Repurpose the footage** — cut, re-caption, dub into Vietnamese, re-edit: OpenMontage `clip-factory`,
   `localization-dub`, `podcast-repurpose`.
3. **Advertising / affiliate videos** — product stills or a product link → short vertical ad with voice-over and
   captions: OpenMontage product-film path (or ArcReel upstream's product mode). Affiliate links and posting are
   publishing steps (Postiz), not generation.

## 3. The open question: who drives OpenMontage (UNKNOWN, needs a decision)

OpenMontage has no server or UI of its own; an AI coding agent reads its `AGENTS.md`, pipeline definitions and skills
and runs its tools (README: "Works with Claude Code, Cursor, Copilot, Windsurf, Codex"). Options:

| Driver | Quality | Cost | Note |
|---|---|---|---|
| Claude Code headless on this host | strong tool use | the sponsor's Claude subscription quota (recurring) | the donor's intended mode; needs approval (resource rule) |
| Codex CLI with our free NewAPI models | weak: the same free model left 1 of 2 Xia Director turns empty and guessed API paths | free | likely unreliable |
| Our connector following OpenMontage's pipeline definitions without an agent | deterministic | free | re-implements the agent's judgement (concepts, scene plans) — against GOAL rule 2 unless only the mechanical stages are driven |

Providers: OpenMontage's showcase uses paid video/TTS; our free stack (local Wan, VieNeu, Seedream once-only, Gemini
vision 20/day/model) can be configured, but quality will be as limited as film 1's (UNKNOWN until probed).

## 4. Recommended order

1. **Now, no new cost:** remake-as-story — hand the old app's ADR-0161 transcript to the connector as the story input
   (one connector option `--from-video <url>`; the transcript step stays the old app's unit).
2. **Decision for the sponsor:** OpenMontage driver (Claude Code headless vs free Codex) — then install OpenMontage
   pinned, probe `localization-dub` (Vietnamese dub of a short clip) and one product ad from stills.
3. **Publishing (later, per-post approval):** Postiz to TikTok/YouTube with affiliate links in captions.
