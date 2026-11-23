# Shot timing, on-screen text and per-episode identities: what the donors do

Date: 2026-11-23. Research done after the sponsor pointed out that r2-v2.5.89 and the identity wiring
(r2-v2.5.90) used numbers and prompt text of our own. Labels: **FACT** (file @ commit), **INFER**.

## A. Shot timing and on-screen text (settled, `8f445ddbc`)

| Question | DramaClaw @ b299bfd | huohuo-drama @ f104b85 | OpenMontage @ 08e2151 | Taken |
|---|---|---|---|---|
| Spoken shot length | scene = TTS duration (`cli.py:391`); `adjust_video_duration` trims a longer clip, speeds a shorter one ≤1.5× or freezes the last frame (`generators/video_composer.py:697`) | each shot muxed with its TTS using `-shortest` (`workbench-server/src/services/drama/compose-ffmpeg.ts:417`) | "voice starts immediately", "no long pauses — dead air = scroll" (`skills/creative/short-form.md`) | ends with its speech (no tail) |
| Silent shot | — (every scene narrated) | slideshow clip `max(3 s, audio)`; a silent video keeps its length | "No static holds: Max 3 seconds" | at most 3 s |
| Captions | ASS from VTT | SRT, FontSize 20 | "Max chars/line 30", "Max lines 2", within the 900×1400 safe zone | 30 × 2 |
| Title | separate 3 s black card, one line (`_create_title_card`, `normalize_video_title`) | — | "Hook in frame 1 … no intro"; on-screen text "3-5 words", top 40 % of the safe zone | top overlay 1.8 s (ADR-0160), 30 × 2 |

The OpenMontage skill is vendored verbatim (`vendor/openmontage/skills/creative/short-form.md`) and cited where the
values live (`lib/screen_text.py`, `server/production_run/render_adapter.py`). Not ported: DramaClaw's speed-up or
freeze of a clip shorter than its speech — our duration tiers already make the clip cover the speech (ADR-0018).

## B. How DramaClaw uses an episode's identities after planning them (FACT)

- The script writer `workflows/literal_script_writing.py` (1 474 lines) reads `episode.identity_default_map` and the
  episode's identity ids (`LiteralScriptWritingWorkflow.run`, lines 480–560).
- Per scene block, `_compile_scene_block_context` (lines 1107–1224) narrows the candidate identities **from text
  evidence**: an identity matches when the block names its character, an alias, its id or its identity name; when a
  character has several matches, the ones whose identity name appears in the block (header counts extra) win; with no
  evidence it falls back to the episode default; if there is no default either, all stay candidates and it logs why.
- Line by line, a **sticky** identity per character carries from the episode default into each block and is shown to
  the model (`sticky_section`, lines 631–640); beats carry `{{角色名_身份名}}` markers that later stages resolve
  (`utils/identity_refs.py`, `models.extract_char_identities_from_markers`).
- Donor tests for this part: `test_literal_script_writing_audio_type.py` only; the identity narrowing has no test of
  its own.

What we shipped in r2-v2.5.90 instead (INFER: a re-implementation of a small part): a prompt block listing each
character's default look, and after the model answers, every bare character name replaced by the default derivative.
That drops DramaClaw's text-evidence narrowing (a flashback block that names "幼年" keeps the child identity there)
and its sticky carry.

**Open, to settle before changing the code:** our script planner is scene-based (`drama` normalized script), theirs
is line-based beats. Porting `_compile_scene_block_context` and the sticky carry needs a map from their `SceneBlock`
(header + lines) to our scene units; the unit is a pure function of block text, identity metadata and the default
map, so it can be vendored whole with a seam that builds `SceneBlock` from our adapted episode text.

## C. Run state, resume and sibling writes (to research next)

Before any proposal on D1–D3 of the [waste audit](2026-11-23-r2-resource-waste-audit.md): how DramaClaw (Celery
runners, `sqlite_store` column patches, task state), OpenMontage (pipeline checkpoints) and huohuo-drama (task
service, batch jobs) keep a run going across restarts, retries, concurrent writes and edits, with file references.
