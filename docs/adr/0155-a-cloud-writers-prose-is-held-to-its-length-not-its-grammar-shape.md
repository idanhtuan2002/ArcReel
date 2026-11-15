---
status: accepted
---

# A cloud writer's prose is held to its length, not to the local grammar's shape

Decided 2026-11-15 by the main agent (sponsor: quality first; "kiểm tra các lượt bị loại OUTPUT_INVALID").

A scene is drafted as exactly N paragraphs of 280–700 characters (32209195c). For the local writer this shape is a grammar that Ollama enforces while sampling, so a draft never breaks it; it bounds the scene's length and stopped the 9B model's loops. A cloud writer only receives the schema (`strict: false`); the shape is then checked after the call. In trial 4 (`particle-1:free`) 10 of 64 calls were refused `OUTPUT_INVALID` ("a paragraph is empty or too short"), all scene drafts. Reproduced with the app's prompt: the refused drafts had 9 paragraphs instead of 8, some of 217–275 characters — dialogue paragraphs of three or four full sentences, as the prompt asks ("mỗi đoạn 3–5 câu"). Good prose was thrown away and redrawn.

1. A prose reply is accepted within 25% of the planned paragraph count (rounded down: 8 → 6–10; 2–3 stays 2–3) and of the paragraph ceiling; a paragraph under 120 characters (or the step's own floor when that is lower) is a fragment and is refused. The refusal names the count or the paragraph length.
2. The scene's length is still checked by its own window (`check_scene_prose`: short, outside 600–1000, over the hard maximum), so the relaxed shape does not let a scene grow or shrink unchecked.
3. The local grammar and the schema sent to every writer are unchanged; a local draft still lands in the exact shape.
