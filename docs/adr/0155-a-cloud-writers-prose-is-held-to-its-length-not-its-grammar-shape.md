---
status: accepted
---

# A cloud writer's prose is held to its length, not to the local grammar's shape

Decided 2026-11-15 by the main agent (sponsor: quality first; "kiểm tra các lượt bị loại OUTPUT_INVALID").

A scene is drafted as exactly N paragraphs of 280–700 characters (32209195c). For the local writer this shape is a grammar that Ollama enforces while sampling, so a draft never breaks it; it bounds the scene's length and stopped the 9B model's loops. A cloud writer only receives the schema (`strict: false`); the shape is then checked after the call. In trial 4 (`particle-1:free`) 10 of 64 calls were refused `OUTPUT_INVALID` ("a paragraph is empty or too short"), all scene drafts. Reproduced with the app's prompt: the refused drafts had 9 paragraphs instead of 8, some of 217–275 characters — dialogue paragraphs of three or four full sentences, as the prompt asks ("mỗi đoạn 3–5 câu"). Good prose was thrown away and redrawn.

1. A prose reply is accepted within 25% of the planned paragraph count (rounded down: 8 → 6–10; 2–3 stays 2–3) and of the paragraph ceiling; a paragraph under 120 characters (or the step's own floor when that is lower) is a fragment and is refused. The refusal names the count or the paragraph length.
2. The scene's length is still checked by its own window (`check_scene_prose`: short, outside 600–1000, over the hard maximum), so the relaxed shape does not let a scene grow or shrink unchecked.
3. The local grammar and the schema sent to every writer are unchanged; a local draft still lands in the exact shape.

## Donor check (2026-11-15, before deploy, sponsor's request)
Read at the pins of `docs/research/2026-11-09-r2-donor-writing-capabilities.md`:
- shenbi `10efa7c`: length is a chapter band only (`gates/shared.py:302` `chapter_word_min_max`; skill `shenbi-length-normalizing`: < 3000 expand, > 10000 compress); a length retry carries the persisted draft and an expand-don't-rewrite directive (`pipeline/chapter_loop.py:1318-1333`, `pipeline/retry_routing.py:45-52`) because blind full rewrites oscillated and degraded. No paragraph shape.
- huohuo `f104b85`: chapter band `0.88–1.08 × target` (role-soft `0.55–1.12`), blocking only under `0.97 × min` (`services/batch/batch-generation.ts:85-101`); the prompt states the target and asks to thicken the outline's own beats (`services/novel/novel-chapter-target.ts`). No paragraph shape.
- novel-studio-ai `9b690ae`: plain prose, "字数尽量接近 target" (`src/lib/ai/prompts.ts:157-167`), no check. StoryBox `ba24ff6`, dramaclaw `b299bfd`: no paragraph or length shape on prose.
No donor holds a cloud writer to a per-paragraph shape; each bounds the whole text's length and repairs length by targeted edits. ArcReel already repairs a scene's length by rewriting at most six paragraphs within 0.85–1.15 of their length (`repair.py:53-56`, `LENGTH_SYSTEM`), the shenbi pattern; with this ADR a scene off its window goes to that repair instead of being redrawn.
