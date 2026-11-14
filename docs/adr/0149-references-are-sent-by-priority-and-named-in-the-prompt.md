---
status: accepted
---

# References are sent by priority and named in the prompt

Decided 2026-11-14 by the main agent (identity ID-1 and ID-4; measurements in `docs/r2/evidence/prompt-dialect-ab-2026-11-14/`).

The local image route has fewer reference slots than a shot can carry, and its backend kept the first ones and dropped the rest without a word; the prompt never said which reference showed whom.

1. **Priority order.** A storyboard's references are assembled as: product references (unchanged, ADR for ad fidelity), the cast's sheets (one per character, derivative sheets per ADR-0146), the previous storyboard of the same scene (it carries the room, light and props), then scene and prop sheets, then extra references. A backend with fewer slots therefore loses the least useful ones. Existing storyboards whose shot has both a previous storyboard and a scene or prop sheet get a new reference order, so their visual basis changes and they are regenerated on the next run.
2. **No silent truncation.** The ComfyUI image backend logs which references did not fit its slots.
3. **Names bind to images.** The prompt's `Characters:` block (ADR-0142) says which reference image shows each character ("Lan (reference image 2)"), counted over the references actually sent, so a backend without reference labels can still match picture and person. Preview counts them by the same assembly (`storyboard_reference_labels`).
4. **A fourth slot** is available as `endpoint-definition-4ref.json` (FLUX.2 klein takes up to four). Importing it on the host replaces the three-slot endpoint (host step, done by the Human or by the agent with the Human's go-ahead).

Measured, and not adopted: cropping the sheet to the front view or adding a face crop did not change framing or identity on klein (shot size is handled by ADR-0148), and several references of one person made the model draw the person twice; one reference per character stays the rule.

## Amended after the release review (2026-11-14, `R2_CRAFT_REVIEW_2026-11-14.md` H1)
The currency planner (`lib/artifact_planner.py`) now assembles a storyboard's expected references in the same order as execution (products, cast, previous storyboard, scene and prop sheets) and resolves a derivative reference name (`owner/derivative`) to the derivative's sheet, as execution does; before, every new storyboard with both a previous storyboard and a setting sheet was stale on arrival, and a shot naming a derivative was never planned. `tests/integration/lib/test_storyboard_reference_parity.py` pins the parity. Existing storyboards made in the old order with both kinds of reference are stale once after deploy and are regenerated.
