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
