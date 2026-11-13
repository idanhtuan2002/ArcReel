# Storyboard prompt dialect A/B on FLUX.2 klein 4B (craft program P1-8), 2026-11-14

Question: does an English structured (BFL JSON) or English prose prompt beat the current prompt (Chinese/Vietnamese YAML with the `Characters:` block, ADR-0142) on the production image route?

Setup: local ComfyUI, `flux-2-klein-4b-Q4_K_M.gguf`, text encoder `Qwen3-4B-Q4_K_M.gguf`, 4 steps, 576×1024, one reference slot = the character's three-view sheet (`characters/Nam.png` of production project `san-xuat-tu-ong-7fb4ef4b`, read only). Shots E1S02 (medium shot, nervous entry, bulb on the right) and E1S03 (close-up, leaning into steam). Variants: A = `render_storyboard_image_prompt` of the stored shot; B = the same content as BFL JSON in English; C = English prose, subject first. Seeds 11 and 22. Script: `ab_prompts.py.txt` (run as Python); prompts: `*.txt`; contact sheets: `E1S02_sheet.jpg`, `E1S03_sheet.jpg` (columns A, B, C; rows seed 11, 22). Judged by the main agent by eye.

| Criterion | A (current) | B (EN JSON) | C (EN prose) |
|---|---|---|---|
| E1S02 light from the right | 0/2 | 1/2 | 2/2 |
| E1S02 nervous expression | weak | clear | clear |
| E1S03 action (leans into steam) | 2/2 | 1/2 | 1/2 (one "eating") |
| E1S03 light from the right, steam beams | 2/2 | 2/2 | 2/2 |
| Identity to the sheet (face, hair) | closest on E1S03 | close | close |
| Requested shot size (medium, close-up) | 0/4 | 0/4 | 0/4 |

Confound: the English text described "a white T-shirt" (from E1S02's scene text) where the sheet shows grey, so B and C drift from the sheet's shirt on E1S03 by instruction.

Conclusions:
- No dialect wins across shots; switching would add an LLM translation step for no shown gain. The prompt dialect stays as is (P1-8 closed: measured, no change).
- **Shot size is ignored by every dialect**: four requested medium/close shots all came out full-body or medium-long. Inference: the full-body three-view sheet in the reference slot pulls the framing; ID-1 (the sheet view and a face crop matched to the shot size) is the lever to test next.

## Follow-up: reference views and a framing line (ID-1), 2026-11-14

Same route and shot E1S03 (requested close-up), seeds 11, 22, 33; script `ab_refs.py.txt`.

1. **Reference choice** (`E1S03_references.jpg`, rows: whole three-view sheet / front panel only / front panel + face crop; columns: seeds). The rows are nearly identical; the seed decides the composition. No reference choice produced a close-up, and identity did not visibly change. Inference: on this model the full-body sheet is not what pulls the framing wide.
2. **Framing line** (`E1S03_framing.jpg`, rows: an English line "Framing: close-up, head and shoulders fill the vertical frame, background softly out of focus." / the same in Chinese, placed first; columns: seeds). The English line tightens all three seeds from a seated full-body framing to a chest-up medium close-up; the Chinese line helps less. Still not a true close-up: the long environment description keeps pulling the frame out.

Decision: the storyboard prompt now leads with an English framing line derived from `shot_type` and a non-eye-level `camera_angle` (`lib/prompt_builders.framing_line`). Reference views stay as they are for framing; ID-1 keeps its other goals (slot priority, the fourth slot, no silent truncation, name binding).

## Four reference slots (ID-1), 2026-11-14

`docs/r2/evidence/media-local-2026-10-30/flux2-klein-reference/endpoint-definition-4ref.json` adds a fourth `ReferenceLatent` slot (FLUX.2 klein takes up to 4 references: https://docs.bfl.ai/flux_2/flux2_overview). `validate_comfyui_definition`: no errors, no warnings. Real render on the RTX 2070 with sheet + front panel + face crop + the previous storyboard (`four_reference_slots.jpg`, 110 s including the first load): it runs, and the previous storyboard carried its school bag into the new shot. It also drew **a second copy of the character in the background**: three references of one person invite duplicates. Rule kept in production: one reference per character (ViMax `reference_image_selector.py`: at most one view per character); the extra slot goes to the previous storyboard and the setting.
