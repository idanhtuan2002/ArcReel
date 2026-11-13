---
status: accepted
---

# A character's story states become derivative sheets automatically

Decided 2026-11-14 by the main agent (craft program P1-10 / identity ID-5).

Costume and state variants (derivatives, ADR-0072) existed for people editing a project, but the automatic run never created them: one sheet per character could not show a wedding dress, an injury or the same person as a child, so the storyboard drifted from the story and the continuity judge flagged a scripted change as identity drift.

1. **Extraction finds states with evidence.** The automatic asset extraction returns, per character, at most four `states`: lasting visible changes the text states for a stretch of the story (another outfit, an injury, a clearly different age, soaked or dirty after an event), each with a short name, an image-edit `change` relative to identity and outfit, and the exact source sentence as `evidence`. A state whose evidence the source does not contain (whitespace and case folded) is dropped, as an unnamed character is (DramaClaw's attestation). Kept states are registered as derivatives (`characters.<name>.derivatives.<state>.description`). This follows Jellyfish's costume timeline (`backend/app/schemas/skills/script_processing.py@a967819`: per character, state notes with evidence spans) and FilmWorld's entity states.
2. **The workflow asks for their sheets.** Once a character's own sheet is current, each derivative appears in the character sheet collection under its reference name (`Lan/áo cưới`) as missing, current or stale. The MEDIA owner sends those names to a derivative-sheet tool that submits the same edit task as the asset page (`character_derivative`: the owner's sheet edited by the change, under a fixed guard), and plain asset names to the asset tool. Projects edited by people get the same next action for a derivative without a sheet.
3. **Shots and the judge use the state.** Script planning already lists derivative reference names, so a shot names `Lan/áo cưới`; the storyboard receives the derivative sheet and the cast block gives the base description plus the change (ADR-0142). The continuity judge now resolves `owner/derivative` to the derivative's sheet and the combined description, so a scripted change is judged against the right picture.
