---
status: proposed
---

# Port DramaClaw's identity planner whole for per-episode character states

Proposed 2026-11-22 under the sponsor's rule "Donor 整体移植" (AGENTS.md) and the
[donor port audit](../research/2026-11-22-r2-donor-port-audit.md) (class C). Donor: DramaClaw @ b299bfd
(`~/.cache/r2-donors/dramaclaw-full`), `src/novelvideo/agents/identity_planner.py` (1,495 lines) and its tests.

## Context

ADR-0142 (base appearance) and ADR-0146 (states as derivatives) re-derived ideas that DramaClaw ships as one tested
unit. Ours extracts at most four states in one pass over the whole source; nothing says which state a character is in
for a given episode, so a shot that names the bare character always gets the base sheet. DramaClaw plans identities
per episode:

- **Pass 0** filters the episode's cast (aliases from the character table on its structured pipeline; no graph).
- **Pass A** gives every cast member exactly one *default identity* for the episode's present-day scenes, named by
  life stage or a long-lived outfit, never by plot words; a missing default aborts the plan.
- **Pass B** adds *other identities* that need their own stable look (flashback ages, a second long-lived outfit,
  a photo or TV image), not one-off states (dirty, wet, injured once).
- New identities get an `AppearanceDescription` (outfit/hair 10–200 chars; for an age variant also face, body and
  `age_group`, all or none), whose validators reject polluted model output (schema field names, reasoning text,
  tool-call frames, replacement characters) and are retried.
- Identities are reused across episodes by `(character, visual_state)`; the episode records
  `identity_default_map`.

## Decision

1. **Vendor the unit at the pin.** `vendor/dramaclaw/` gets `identity_planner.py`, the `CharacterIdentity` model and
   age-group helpers it needs, `utils/source_language.py`, with prompts unchanged, plus their tests
   (`test_identity_planner_appearance_validation.py`, `..._language.py`, `..._character_promotion.py`,
   `test_character_identity_age_group.py`, `test_identity_runner_result.py`). Edits inside vendored files are limited to
   import paths and are listed in `vendor/dramaclaw/PORTING.md`.
2. **Add `pydantic-ai-slim[openai,google]==1.107.0`** (DramaClaw's pin) so the planner's `Agent` calls and the tests'
   `FunctionModel` seam run unchanged. The model is built from the project's text route (OpenAI-compatible endpoint
   for Ollama and cloud, Google for Gemini).
3. **Our code is the adapter only:** a store implementing the `cognee_store` members the planner uses
   (`get_all_characters`, `get_character`, `resolve_name`, `add_character_identity`, `update_character_identity`,
   `load_episode_content`, and the structured-pipeline path so the graph members are never reached) over
   `project.json` characters and the episode's adapted script text.
4. **Mapping.** A DramaClaw identity `(character, visual_state)` is our derivative `character/visual_state`
   (ADR-0072/0146), its description the identity's appearance (plus face and body for age variants), and its sheet
   made by the existing derivative-sheet task. The episode stores its default map; a shot naming the bare character
   uses that episode's default derivative. The base description of ADR-0142 stays the character's own sheet.
5. **Replaces ADR-0146 item 1** (single-pass state extraction) for automatic runs once the port passes its donor tests
   and one real episode; items 2–3 (sheets, shots, judge) are reused unchanged.

## Open before acceptance

- Which story text an episode reads (`load_episode_planning_content` → our adapted episode script or its source span).
- Vietnamese output: DramaClaw detects only Chinese or English (Vietnamese → English). Descriptions feed image
  prompts, which are English today, so English is acceptable; character names stay as written.
- Pass 0 cost on a 9B local writer versus a cloud route; the planner defaults to `gemini-3.5-flash`.
