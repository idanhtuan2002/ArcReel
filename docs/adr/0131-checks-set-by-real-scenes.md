---
status: accepted
---

# Checks set by real scenes

Decided 2026-11-11 by the main agent (sponsor: do the fixture-first items F4, F5, F11, F13, F14 now). Research: [donor deep dive](../research/2026-11-11-r2-donor-deep-dive.md) §4. Fixtures: `tests/fixtures/story_real/`, 42 scenes of five stories the production writer (`qwen3.5-vimax:9b`, local) wrote, two of them committed, read through the story drafts API.

What the fixtures showed, and what is built from it:

1. **JSON in prose** (not in the research; found here). One scene opens ten paragraphs with `{ "paragraph_2": "…`. A paragraph opening with a JSON key is `JSON_LEAK` (hard structural); the keys, quotes and brackets are cut with no model call and the prose inside is kept.
2. **Notes on the cast in prose** (found here). One scene carries a paragraph "minh: cô gái 22 tuổi…; lan: vợ của…; thai: doanh nhân 30 tuổi…". A paragraph of three or more "name: description" items separated by semicolons is `NOTES_LEAK` (hard structural); the paragraph is cut with no model call.
3. **F13.1 POV person.** Two scenes of third-person stories narrate in the first person (16 and 24 narration "tôi"); no scene of a committed story carries more than one. More than two narration "tôi" in a scene of a story whose seed `pov` is not first person, or none in a first-person story's scene of 600 syllables or more, is `POV_PERSON` (narrative critical, repaired). Narration is counted with dialogue removed.
4. All of 1–3 and ADR-0126 item 4 fire on exactly the drifted scenes of the fixtures and on no scene of a committed story (`tests/unit/server/story_authoring/test_real_fixtures.py`). They run when a scene is drafted and again at chapter review; at review, JSON and notes are cut with no model call.
5. **F4 drama fields and a closing hook.** A generated short outline states each chapter's `obstacle`, `choice` and `ending_question`; a generated chapter plan states `closing_hook`, the sentence the chapter ends on; the plan prompt shows the outline chapter's fields, the last scene's draft and repair are told to end on the hook. Stored outlines and plans carry none and read as before. Whether the last scene ends on it is `CLOSING_HOOK`, stylistic (recorded, never repaired): no fixture carries a declared hook, so the threshold (half of the hook's words in the last two paragraphs) is not yet measured. The tension-word variant is not built: every fixture chapter ending but one already carries a tension word, so it would not separate.

Measured and not built:

- **F13.2 next-chapter leak.** The next chapter's goal shares 0.42–0.80 of its words with the current chapter's last scene, the current chapter's own goal 0.47–0.88: word overlap does not separate a leak from continuity.
- **F13.3–F13.5 age, life status, time anchors.** Ages appear only in one story and agree; the committed river story turns on a son believed dead who is alive, which a life-status check would flag; no scene carries an explicit date. Nothing to calibrate on, and one certain false positive.
- **F5 weighted scene budgets.** No fixture shows a turning scene cut short; the per-scene window stays.
- **F11 merging the anti-AI judge into the craft judge** and **F14 an independent judge route** need model calls on the production GPU (an 8 GB card the 9B writer already overflows); they wait until the GPU is free, then F14 measures the model swap time first.
