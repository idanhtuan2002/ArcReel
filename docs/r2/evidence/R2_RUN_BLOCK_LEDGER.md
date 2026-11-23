# Run block ledger

One line per production-run block (AGENTS.md "资源浪费防线"). Class: **G** our run/governance layer, **Q** our
quality-gate machinery, **C** content behaviour we wrote, **D** donor unit, **E** environment (disk, GPU, quota),
**T** a true problem the block rightly caught. Review the ledger every ten lines
([audit](../../research/2026-11-23-r2-resource-waste-audit.md)).

| Date | Run | Stage | Reason | Class | False block? | Root cause | Fix |
|---|---|---|---|---|---|---|---|
| 2026-11-22 | b961dc0a | MEDIA | WORKFLOW_FIX_INPUT | G | yes | silent unit flagged `tts_not_applicable` under TTS delivery | r2-v2.5.85 |
| 2026-11-23 | b961dc0a | MEDIA | MEDIA_RETRY_LIMIT | G | yes | same mode, not swept: video task, checkpoint facts, selection needed a TTS duration | r2-v2.5.87 |
| 2026-11-23 | b961dc0a | MEDIA | EXTERNAL_INPUT_CHANGED | G | yes | completeness copy in `media_adapter` read audio `not_applicable` as incomplete | r2-v2.5.88 |
| 2026-11-23 | b961dc0a | resume | PREFLIGHT INSUFFICIENT_DISK | E | yes | deploy backups never pruned | backups pruned; retention patch for `v2-deploy.sh` |
| 2026-11-23 | 010a7912 (ep 2) | SCRIPT | WORKFLOW_INVALID_SCRIPT_STRUCTURE | C | no (true) | `characters_in_scene` names "Cô gái", who was never registered (project has one character, ông Khang); the same run's identity planner (r2-v2.5.90) gave ông Khang a default "老年时期" with an empty appearance | open: cast registration + full DramaClaw identity chain port |
| 2026-11-23 | assembly 01M84JWC (film 1) | create | HTTP 400 project name | E | no (true) | DramaClaw names allow letters/digits/underscores only | connector slugifies names (b9aa303ae+) |
| 2026-11-23 | assembly 01M84JWC | ingest | 项目类型只能在重新导入时修改 | E | no (true) | spine must be set by PATCH before ingest | connector fix |
| 2026-11-23 | assembly 01M84JWC | build_characters | model_not_found DC-character-builder-LLM | C | no (true) | DramaClaw Custom feature list lacks CHARACTER_BUILD (donor gap) | `CHARACTER_BUILD_MODEL` env in override |
| 2026-11-23 | assembly 01M84JWC | face prompts | 429 ERNIE free pool | G | no (true) | one free text model for every DC-*-LLM | text retries; OpenRouter `models` fallback chain (`assembly/ops/newapi_text_fallback.py`) |
| 2026-11-23 | assembly 01M84JWC | portraits | no main characters / 400 Seedream size < 3 686 400 px | C | no (true) | extraction set no `is_main`; DramaClaw fixed 1K images vs Seedream 4.5 minimum | grading (playbook 6.5); `assembly/image_adapter` |
| 2026-11-23 | assembly 01M84JWC | identity_plan | 429 ERNIE (identity_planner, episode_prop_planner) | G | no (true) | same class as the face-prompt 429; async tasks were not awaited | fallback chain; connector awaits every async start |
| 2026-11-24 | assembly 01M84JWC | script_writer | stall: waited on task `content_rewriter` that does not exist | C | no (true) | DramaClaw's rewrite task type is `content_rewrite` (Hermes reference says `content_rewriter`); its output is zh/en only (`source_language.py`), so a Vietnamese story got Chinese first-person narration | connector skips the rewrite (playbook: optional), clears stale adapted content, stops on missing tasks after 300 s |
| 2026-11-24 | assembly 01M84JWC | script_writer | literal script failed: upstream `finish_reason: "error"` (plugin labelled it a content filter) | G | no (true) | a free model in the chain failed mid-call; the script was also being cut from the stale Chinese `beat_source_text` | narration now = DramaClaw zh rewrite + checked translation to Vietnamese written to adapted content and `beat_source_text`; direct Vietnamese rewrite dropped (free model reasoned 8-12k tokens with no output) |
