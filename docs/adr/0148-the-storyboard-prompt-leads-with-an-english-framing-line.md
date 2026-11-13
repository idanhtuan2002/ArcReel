---
status: accepted
---

# The storyboard prompt leads with an English framing line

Decided 2026-11-14 by the main agent from measurements on the production image route (`docs/r2/evidence/prompt-dialect-ab-2026-11-14/`).

Shot size lived only as an enum inside the prompt's YAML composition block, and FLUX.2 klein ignored it: none of ten requested medium or close shots came out at that size, whatever the prompt dialect or reference view. A single English framing sentence placed first tightened every seed toward the requested size; the same sentence in Chinese helped less.

`render_storyboard_image_prompt` (execution and preview alike) therefore starts a structured shot's prompt with `Framing: <size phrase>[, <angle phrase>].`, from a fixed map of the nine shot sizes (for example "close-up, the face fills most of the frame, background softly out of focus") and of the four non-eye-level angles (ADR-0144). Text-shaped prompts get no line. The shot's visual basis is unchanged (it is built from the stored prompt), so existing storyboards stay current.
