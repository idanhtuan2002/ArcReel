---
status: accepted
---

# A craft judge of another family

Decided 2026-11-11 by the main agent (sponsor: product quality first, at least as good as the donors; runs stay fully automatic and local). Research: [donor deep dive](../research/2026-11-11-r2-donor-deep-dive.md) F11 and F14. Measured on the production GPU (RTX 2070, 8 GB) with the production review prompt and decoding, on real chapters of `tests/fixtures/story_real/`.

What was measured:

1. **Swap time.** The writer (`qwen3.5-vimax:9b`) and `gemma3:12b` do not fit on the card together: each switch reloads, 18–19 s either way (`gemma3:4b`: 9 s).
2. **Independent judging (F14).** A committed chapter with two planted continuity defects (a husband locked as dead ten years walks in; a deep cut healed overnight) and its own real defect (the closing sentence comments on "the last chapter"), two seeds per judgment:
   - continuity: the writer judging itself and `gemma3:12b` both quote both planted defects 2 of 2; `gemma3:12b` once invented a contradiction in the clean chapter; `gemma3:4b` quotes 1 of 4 and most of its quotes are not in the chapter;
   - machine voice and craft: `gemma3:12b` quotes the chapter's own meta sentence in 10 of 12 judgments, the writer in 1 of 8.
   The writer's continuity reading holds; its craft and voice reading is where a second family adds.
3. **Merging voice into craft (F11).** Three real chapters, the ANTI_AI and CRAFT instructions apart against one CRAFT judgment that also reads machine voice with the deterministic counts (stock phrases, "không phải… mà là", paragraph spread) computed on the prose:
   - on the writer, the merged judgment returns only voice issues (23 of 23): its craft reading is lost, so the writer keeps the two judgments apart;
   - on `gemma3:12b`, the merged judgment keeps both (15 voice, 13 craft over six judgments; 8 quotes discarded against 35 for the two apart) in one call of about 186 s at the production 32k context, against about 270 s for the writer's two calls.

Decided:

1. **A craft judge route.** A brief may name `craft_judge_selection`: a local model of another family that reads CRAFT and machine voice in one chapter judgment; the writer's judge reads continuity, memo compliance, character and safety, confirms blocking claims and reviews plans and the manuscript as before. Its issues typed `giọng máy…` are `ANTI_AI` findings (stylistic, feeding the humanizing repair as before); the rest are CRAFT findings. ANTI_AI is then not asked apart, so a chapter cycle makes one call fewer. The route is part of the brief's digest that Gate A greenlights; briefs drafted before it keep their digest and their judgments.
2. **Chosen automatically.** A story whose writer is local and that names no judge route gets `gemma3:12b` on the writer's own Ollama provider when that provider enables it; a project names another model with `story_craft_judge`, or `off`. A provider without the model keeps the writer judging alone, as before.
3. **Meta narration caught in code.** The defect only the second family saw is now deterministic: narration naming "chương này/sau/cuối/tiếp theo/kế tiếp" or the reader ("người đọc", "độc giả") is `META_NARRATION`, cut with no model call. On the 42 real scenes it fires on exactly that sentence.

Not adopted: the second family for every judgment (continuity holds on the writer, and its one invented contradiction would cost a repair); `gemma3:4b` as a judge; merging voice into craft on the writer.

Still open: the merged judgment's quotes overlap the two-apart judgments' by about a third per chapter, within what two seeds of one judgment differ by; a real run's humanize and craft repair counts per chapter, against the runs before this ADR, settle it.
