---
status: accepted
---

# A character's appearance leads every shot prompt

Decided 2026-11-13 by the main agent (craft program P0-4).

The automatic asset extraction wrote a free-text description and was told not to invent visual details, so characters came out vague and alike; the storyboard prompt named nobody's look, leaving identity to the reference sheet alone.

1. **Extraction designs a character in two parts** (ViMax `agents/character_extractor.py` static/dynamic features). `identity` is what stays the same in every scene: age, gender, height and build, face, skin, hair, distinguishing marks, in concrete visual words. `outfit` is what the character wears through most of the story, each garment with a colour name and a hex code bound to that garment, plus one signature item. Where the text is silent the model designs plausible details and keeps the characters clearly different at a glance. The registered `description` is `identity` then `outfit`; scenes and props keep the rule not to invent.
2. **Every storyboard prompt starts with its cast.** `render_storyboard_image_prompt` (execution and preview alike) puts a `Characters:` block first: one line per character in the shot with its current appearance (a derivative is the base description plus its change). The same words reach every shot of that character, and earlier words weigh more (BFL FLUX.2 prompting guide: repeat the full character description in every panel; hex works best bound to an object). A text-shaped prompt that already carries the block is not given a second one.
3. Interactive asset analysis (`agent_runtime_profile/.claude/agents/analyze-assets.md`) keeps its rule to use the author's own words: there a person wrote the source.

Not covered: per-view crops and a face crop as references (ID-1), and outfit changes through the story as derivatives (ID-5).
