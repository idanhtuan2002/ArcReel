---
status: accepted
---

# The writer sees what the plan made

Decided 2026-11-11 by the main agent (sponsor: product quality first, fully automatic). Research: [stage-by-stage comparison](../research/2026-11-11-r2-donor-stage-by-stage.md) and its verification and build specs, [deep dive](../research/2026-11-11-r2-donor-deep-dive.md). Both found that ArcReel plans well and then writes without most of what it planned, where the donors carry their style, cast and story so far into every writing call.

Adopted now (no real-run fixture needed; no extra model call unless stated):

1. **Voice (F1).** Every scene prompt and every review-driven repair carries a bounded "[Giọng truyện]" block: the seed's point of view and tone, the style bible's narration, rhythm, emotion, dialogue and forbidden style, and the story bible's forbidden contradictions. It is prompt text, not a context-pack segment, so pack hashes and resumed runs are unchanged.
2. **Self-contradicting instructions removed (F12).** The plan prompt states the grammar's own list limit; the context no longer repeats the pack's sorted beats (the scene prompt shows them in plan order).
3. **What happened so far (F3, +2 calls per short story).** A short story drafted from a new brief digests each chapter but the last, as a book part does; later scenes read "[Đã xảy ra ở các chương trước]" (summaries, time and place, character states) and the continuity audit reads what was written instead of the plans' goals. Briefs drafted before carry no flag (`carries_digests`) and keep their exact inputs.
4. **Review repair keeps its ground (F8).** A repair sees the scene's own plan, the chapter's secrets and bans, the voice, and what earlier rounds fixed; a repair that brings back a passage an earlier round removed is rejected (donor shenbi `0cdc218` anti-regression list).
5. **Position duties (F5).** The story's first scene opens on dialogue or a clash; a chapter's first scene joins the seam; a non-final chapter stops on an open question or a coming threat (donor huohuo beat rules).
6. **Characters (F6).** Generated characters carry a voice and a flaw, locked with their gender and address; stored seeds read as before.
7. **Seed foundation (F7, +1 call only on failure).** One protagonist, a conflict and an ending that do not restate the premise, distinct voices; a failing seed is drawn once more naming every problem, together with any idea name it dropped.
8. **Title (F9, +1 call only when no title passes).** The export and book title take the first offered title that keeps the packaging rules (2–8 Vietnamese syllables, no repeated syllable, not only a name, not only hollow words), else the working title.
9. **Ending (F10a, ~one chapter only when it fires).** When the rewritten final scene still does not close the story, the last chapter is planned once more toward the outline's ending; the structural bound counts it.
10. **Natural paragraphs at export (F2).** The exported manuscript lays each scene out again in code: dialogue lines start paragraphs with their attribution, narration takes one to three sentences; words are unchanged and scene texts, checks and quotes are untouched.
11. **Small guards (history-mined H1, H3, H11, H12).** A short-scene retry states measured and target lengths; patch repairs must not change who, when, conditions, scope, negation or attribution; the character audit checks outsiders' kin terms; a broken U+FFFD character is an integrity finding; quoted speech inside narration counts as dialogue.
12. **Autopilot keeps a drawn idea.** A story autopilot turned on again before part 1 was committed writes the idea drawn for the project earlier instead of drawing a new one.

Deferred until a real-run fixture or a decision: weighted scene lengths (F5), the closing-hook check (F4), merging the anti-AI judge (F11), the carry-over invariants (F13), an independent judge route (F14), refusing automatic approval of an unresolved ending (F10b, conflicts with fully automatic runs), applying natural paragraphs to scene texts, and the "[Cần tránh]" block of earlier review findings.
