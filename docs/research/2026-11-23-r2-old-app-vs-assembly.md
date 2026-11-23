# The old app (ArcReel/R2, 2.5 months) against the new assembly (ADR-0170): what carries over

Date: 2026-11-23. The sponsor asked: find what the old version does well and what the new one still needs, and take
it over **without changing the project's direction** (ADR-0170: huohuo writes, our translation, DramaClaw films whole,
we only connect and configure). Labels: **FACT** (source), **INFER**. Old capabilities from ADR-0089 … 0169 and the
tracker; DramaClaw read at `b299bfd` through codebase-memory (project `home-anhtuan-.cache-r2-donors-dramaclaw-full`).

## 0. The guardrail for every carry-over

A capability carries over only as one of three things, never as a change inside a donor or a rebuilt donor stage:
1. **Configuration** of a donor (model channels, env vars, a voice).
2. **Connector feature** (what happens between stages: hand-off, translation, batch, retries, alerts, logs).
3. **Post-stage on the donor's output** (applied to DramaClaw's exported film, which stays untouched).

## 1. Where the donors are already as good or better — do not carry over

| Old capability (ADR) | Covered by | Evidence |
|---|---|---|
| Story writing, book plan, memory, audits, genre packs, repairs (0116, 0117, 0119, 0127, 0128, 0131, 0154, 0157, 0158) | huohuo novel engine | "the only donor with a true long-form novel engine" (2026-11-08 study §2); API `generate-premise` … `generate-remaining` |
| Episode adaptation and splitting (0114) | DramaClaw ingest + `EpisodePlannerAgent` | "most complete" (same study §4) |
| Asset extraction, identities, derivative states (0142, 0146, 0168) | DramaClaw structured extraction + `identity_planner` | "strongest extraction design" (§3); identity planner runs inside its pipeline |
| Storyboards, references, best-of-N, continuity checks (0112, 0134, 0141, 0145, 0147–0149, 0151) | DramaClaw sketch → render grids, `verification/` (`sketch_selector`, `consistency_verifier`, `continuity_verifier`, `image_verifier`, `frame_verifier`, render identity guard) | "richest" (§6); FACT module list `src/novelvideo/verification/` |
| Script and shot grammar (0144) | DramaClaw literal script writing, keyframe prompt builder | §5 |
| Voice per character (0166) | DramaClaw voice assignment + per-identity reference audio (`seedance2_i2v/voice_clone.py`) | FACT |
| Usage and cost accounting (0093, 0137 part) | DramaClaw's NewAPI gateway (per-key quota and usage) | INFER: NewAPI is a metering gateway; verify on install |

## 2. What the old app does well and the assembly lacks — carry over

| # | Old capability (ADR / source) | Gap in the assembly (FACT) | Carries over as | Priority |
|---|---|---|---|---|
| 1 | **Vietnamese voices**: VieNeu local TTS with voice cloning, Gemini TTS (0156), voice cast (0166) | DramaClaw's main voice slot is IndexTTS2 through NewAPI (`INDEXTTS2_NEWAPI_MODEL=index-tts-2`), Chinese/English; edge-tts exists in its TTS generator | **Configuration**: a Vietnamese voice in that slot (VieNeu or Gemini TTS behind an endpoint NewAPI can call, or edge-tts `vi-VN` voices) | P0 — no Vietnamese film without it |
| 2 | **Free-tier model map and fallback order** (`docs/r2/cloud-free-quota-registry.md`, 0139): which free model writes, judges, draws, in what order, with probed quality | DramaClaw ships aliases (`DC-*`, `LingShan-*`, `newapi_gpt_image2`) for its own gateway | **Configuration**: NewAPI channels (OpenRouter, Gemini, BytePlus) with priorities; huohuo's text `baseUrl` pointed at the same NewAPI so both donors share one gateway, one usage ledger | P0 |
| 3 | **Story translation** zh→vi paragraph for paragraph (0120) | huohuo writes Chinese | **Connector feature** (already in ADR-0170) | P0 |
| 4 | **Local media routes**: ComfyUI FLUX klein images, Wan/still-clip video (0099–0101), Ollama | DramaClaw reaches models through NewAPI or its own adapters (OpenRouter, OpenAI, NewAPI image calls in `nanobanana_grid.py`) | **Configuration** when cloud free pools run out: expose ComfyUI behind an OpenAI-compatible image endpoint NewAPI can route to (a small proxy, no DramaClaw change) | P2 — only when quotas run out |
| 5 | **Finishing the final film**: loudness to −14 LUFS and delivery-fault checks (0133), instrumental music bed (0143), scene ambience (0150), grade and moved held pictures (0140), captions + title + next-episode card with donor-sourced limits (0160, `8f445ddbc`) | DramaClaw compose: concat, optional subtitles, `add_bgm` flag not used by the runner, no loudness step, default 720×1280 (`task_backend/runners/video.py` `run_compose_episode`) | **Post-stage** on DramaClaw's exported MP4: our finish step (master, music, ambience, captions) applied to the file | P1 — parity with what the old app already delivered |
| 6 | **Final-film review**: two configured reviewers with the AIVPE guards and deterministic checks (dead air, transcript vs script, delivery faults) (0112, 0133, 0169) | DramaClaw reviews images and episodes in text (`verification/episode_reviewer.py`), not the finished film | **Post-stage** after finishing; a REWORK verdict sends the episode back to DramaClaw's regeneration through its API | P1 |
| 7 | **Full automation around the stages**: autopilot, batches, take-over of unfinished work, restarts survive deploys, alerts outside the app (0124, 0125, 0129, 0130, 0137) | DramaClaw stages are separate APIs ("run them in sequence, skip steps, or resume", 11-08 study §1); huohuo novel writing is per call | **Connector features**: run the stage sequence, resume from the last finished stage, retry, alert (Telegram/notification) | P0 (sequence, resume) / P2 (autopilot, alerts) |
| 8 | **Operations**: deploy script, backups and restore drills, power-loss recovery, systemd autostart (0090, 0130; runbooks) | The donors bring Docker setups only | **Configuration and runbook**: Docker volumes of DramaClaw/huohuo in the backup set; autostart; a retention of three backup sets | P2 |
| 9 | **Packaging and publishing**: package with metadata in the film's language (0115, 2.5.57), trailer from the finished film (0164) | DramaClaw exports SRT + ZIP (`export/episode_export.py`); no trailer; OpenMontage has `export_bundle` | **Post-stage** (our packager now; OpenMontage's bundle when OpenMontage joins) | P3 |
| 10 | **Other forms from a story**: audiobook and sleep story (0159), documentary forms from a fact pack (0162, 0163), a video as source (0161) | Not in DramaClaw; OpenMontage covers non-fiction and repurposing | **Later stages**: audiobook = story + Vietnamese TTS as its own output; documentary and repurposing = OpenMontage whole (ADR-0170 item 4) | P3 |
| 11 | **Vietnamese operator surface**: UI in Vietnamese, run status, film preview | DramaClaw UI `zh`/`en` only (`frontend/src/i18n/index.ts`) | **Connector feature**: a small Vietnamese page to start a run, watch stages, see the film and verdicts; DramaClaw's UI stays for detailed work (English) | P2 |
| 12 | **Lessons and knowledge**: donor studies, model probes, Ollama and test gotchas, the waste audit and run ledger | — | Documents stay; the run ledger and the per-turn rules apply to the connector | — |

## 3. What does not carry over

The R2 governance layer (authority planes, Canon kernel, grants, custody, attestation, offline fences, launch and
reviewer qualification, production-run controller), M8 canvas lineage (DramaClaw has its own canvas), the learning
engine, and our story/film pipeline stages listed in §1. They keep running in the frozen ArcReel for existing projects
until the assembly replaces it.

## 4. Gaps in both, to watch

- **Vietnamese inside DramaClaw**: its prompts are Chinese/English and its asset language detection knows zh/en; a
  Vietnamese story goes through it with dialogue kept verbatim (literal script writing) and image prompts in English.
  Whether names and on-screen text stay right is to be seen on the first film. Fix only by configuration or, if
  unavoidable, a recorded donor seam (ADR-0170 item 3).
- **Chinese settings from huohuo**: a premise can ask for a Vietnamese setting; names and customs after translation
  are to be checked on the first story.

## 5. Order (does not change the direction)

1. P0 with the first film: Vietnamese voice in DramaClaw's slot (#1), NewAPI channels from the free-tier map (#2),
   connector sequence + resume (#7), translation (#3).
2. P1 for parity: finish post-stage (#5) and final-film review (#6).
3. P2 for daily use: Vietnamese run page (#11), backups/autostart (#8), local routes when quotas run out (#4),
   autopilot and alerts (#7).
4. P3: packaging/trailer (#9), audiobook, OpenMontage forms (#10).
