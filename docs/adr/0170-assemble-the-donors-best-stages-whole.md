---
status: accepted
---

# Assemble the donors' best stages whole: huohuo writes, DramaClaw films, we connect

Decided 2026-11-23. The sponsor's model ("take the whole story-writing part of the donor that writes best, the whole
film-making part of the donor that makes films best, … our job is only to connect them"), confirmed after the
[off-course research](../research/2026-11-23-r2-why-the-project-went-off-course.md) and the
[assembly options](../research/2026-11-23-r2-assembly-options.md): no bake-off, choose from the research we have,
keep everything of DramaClaw and only substitute models, and do the connecting and configuration well.
Supersedes, for new work, the frozen rule "Do not merge donor repositories wholesale" (`R2_06` invariant 6.3,
`R2_01` §26 roles, §28.7); ArcReel/R2 is frozen as it is and keeps serving production until the assembly replaces it.

## Decision

1. **Story stage — huohuo-drama @ `f104b85`, whole.** It is "the only donor with a true long-form novel engine"
   (`2026-11-08-r2-donor-stage-mechanisms.md` §2) and runs unattended through its own API: `generate-premise` →
   `dramas/:id/outline` → `dramas/:id/memory/init` → `dramas/:id/generate-remaining/stream`
   (`workbench-server/src/routes/novel/novel.ts`). It writes Chinese (no language handling in `services/novel/`),
   so the finished story is translated to Vietnamese before filming. Text model: OpenRouter
   `baidu/ernie-5.5-flash-preview:free` through huohuo's OpenAI-compatible `baseUrl` (a Chinese-native model for
   Chinese prompts; ranked best free writer in `docs/r2/cloud-free-quota-registry.md`).
   Rejected: our story engine — it re-implemented huohuo/shenbi mechanisms (class C of the
   [waste audit](../research/2026-11-23-r2-resource-waste-audit.md)) and ended five story runs FAILED_QUALITY on
   11-14/15.
2. **Translation — our existing story translation** (`lib/story_translation.py`, ADR-0120), called by the connector.
   No donor ships a book-length zh→vi translator; this one is in production.
3. **Film stage — DramaClaw @ `b299bfd`, whole**: import → episodes → identities, scenes, props → storyboards → video
   → voice → compose → export, its UI and its NewAPI gateway, run by its own `docker-compose.yml`. Nothing inside it
   changes except model settings; a donor change is allowed only where a required model has no substitute, and is
   then recorded in `vendor/dramaclaw/PORTING.md`. Strongest in asset analysis, episode planning, storyboards and
   identities (same study, §3–§6). Video defaults already match a key we hold (`DEFAULT_VIDEO_MODEL` /
   `NEWAPI_VIDEO_MODEL = seedance-1.0-pro-fast`, BytePlus free pool).
4. **Non-fiction and repurposing — OpenMontage @ `08e2151`, whole**, after the drama path runs.
5. **Our code is the connector only**: create the story in huohuo (or take an uploaded story file), export it, translate
   it, `POST /projects/{p}/ingest/upload` and `/ingest/start` into DramaClaw, follow `/pipeline/status` and the
   remaining stage APIs to the export, and hand the film back — fully automatic, with retries and a log. Model
   substitution is configuration of each donor (huohuo AI config rows, DramaClaw NewAPI channels and model env vars),
   written down in `docs/r2/ASSEMBLY_MODELS.md`.

## Port

- huohuo-drama @ `f104b85`, DramaClaw @ `b299bfd`, OpenMontage @ `08e2151`: run whole from pinned checkouts, not
  copied into our code. Their tests stay theirs.
- Ours: the connector and the model configuration. The `vendor/dramaclaw` identity-planner port and its wiring in
  ArcReel (ADR-0168) stop here: DramaClaw runs its own identity planner inside its pipeline.

## Consequences

- No new governance, pipeline stage or release in ArcReel except production fixes.
- Open items are configuration: a Vietnamese voice for DramaClaw's IndexTTS2 slot (`INDEXTTS2_NEWAPI_MODEL`), image
  models for its `newapi_gpt_image2` / `LingShan-*` selections, and NewAPI channels for Gemini, OpenRouter and
  BytePlus.
