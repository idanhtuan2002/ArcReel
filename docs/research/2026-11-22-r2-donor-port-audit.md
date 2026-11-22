# Donor port audit: which ADRs re-implemented a donor unit that could have been ported whole

Date: 2026-11-22. Read-only research for the sponsor's question "the project is assembled from the best donor parts;
why re-implement instead of taking a donor unit with its config and tests?". No code changed. Labels: **FACT** (read
here, with path), **INFER**, **UNKNOWN**. Licensing is out of scope (project policy).

## Method

- `grep` over `docs/adr/*.md` for donor names (ViMax, DramaClaw, huohuo, shenbi, OpenMontage, take, StoryBox,
  Calliope, VGA, AIVPE, open-edit, openfilm): 37 ADRs match; 3 are false positives (`OCC` = optimistic concurrency in
  ADR-0003/0076/0077).
- What the repo actually carries from donors: `git ls-files vendor` and provenance words in `lib/ server/ r2/`.
- Local donor checkouts and their tests (pins as in
  [donor stage mechanisms](2026-11-08-r2-donor-stage-mechanisms.md) and
  [video-quality donor mechanisms](2026-11-13-video-quality-donor-mechanisms.md)).

## Facts

1. **Only one donor unit is vendored whole.** `vendor/openmontage/` (41 files, the Remotion composer) is used by
   `r2/m3/remotion_engine.py`. Every other donor mechanism named in an ADR was rewritten in our code (FACT:
   `git ls-files vendor`).
2. **Local donor checkouts and their tests** (FACT, counted `test_*.py` / `*.test.ts`):

   | Donor | Checkout | Lang | Tests |
   |---|---|---|---|
   | DramaClaw (DC) | `~/.cache/r2-donors/dramaclaw-full` @ b299bfd | Python | 566 |
   | OpenMontage (OM) | `~/content-os-r1-8/work/OpenMontage` @ 08e2151 | Python + TS | 111 |
   | ViMax (fork) | `~/ViMax` @ 63bb9c7 | Python | 50 (wiring, camera tree, storyboard; none for `reference_image_selector` / `best_image_selector`) |
   | take | `~/content-os-r1-8/work/take` @ 47c1721 | TS | 11 |
   | huohuo-drama | `~/content-os-r1-8/work/huohuo-drama` @ f104b85 | TS + skills | 0 |
   | Calliope, VGA, AIVPE, open-edit, openfilm, shenbi | not checked out (read via `gh api` at pins) | mixed | UNKNOWN |

3. **DramaClaw ships a tested identity unit** for exactly the drama gap we hit today (characters and props drifting
   between shots): `src/novelvideo/agents/identity_planner.py` (1,495 lines: per-episode identity requirements,
   appearance/face/body schemas with validators that reject observed model corruption, character promotion,
   language), the identity runner, a render identity guard and multi-view / scene reference prompts. Tests:
   `test_identity_planner_appearance_validation.py`, `..._character_promotion.py`, `..._language.py`,
   `test_identity_runner_result.py`, `test_render_identity_guard.py`, `test_render_multiview_reference_prompt.py`,
   `test_scene_reference_prompt.py`, `test_api_character_identity_costume.py`, `test_character_identity_age_group.py`,
   `test_wysiwyg_consistency.py`, `test_storyboard_prompt_visual_authority.py`. It is coupled to `pydantic_ai`,
   DC's `sqlite_store`, `cognee` graph access and `novelvideo.models` (FACT: imports of `identity_planner.py`).
4. **ViMax ships the reference and selection agents** we re-derived: `agents/character_extractor.py` (90 lines),
   `character_portraits_generator.py` (86), `reference_image_selector.py` (237), `best_image_selector.py` (148).
   ADR-0142 took the extractor's two-part design and rewrote it; ADR-0134 and ADR-0112 cite the selectors.
5. **No donor qualifies a reviewer or a model.** ADR-0113 itself records: "Every donor that supports new models
   without code (ViMax, DramaClaw, Jellyfish) routes text through one OpenAI-compatible protocol chosen by
   configuration; none gates a model by qualification." AIVPE uses a Gemini Flash judge directly with two guards (a
   high-severity issue caps the score at 69; an unparseable verdict is rejected, not scored 0). The labeled-corpus
   qualification (ADR-0113/0134 and the drama corpus work of 2026-11-16..22) is our own mechanism.
6. **Side scripts duplicated donor units again on 2026-11-22**: `identity_stills.py` and `recurring_extras.py` in
   `/mnt/arcreel/D/ArcReel/operations/reviewer-corpus-drama-2026-11-16/` re-implement appearance planning, portraits,
   reference painting and recurring-prop pinning (stopped the same day).

## ADR classification

| Class | ADRs | Donor source | Verdict |
|---|---|---|---|
| A. Vendored whole | M3 render (0079/0080) | OM Remotion composer | Right pattern. |
| B. Donor numbers or prompt rules, re-coded | 0133 (openfilm loudness, open-edit checks, TS), 0140 (VGA moves, grades), 0143 (VGA mixer values), 0144 (AIVPE shot grammar, TS) | small, TS or prompt-only | Acceptable: little code to port; the donor is TS or a prompt. |
| C. Re-implemented where a Python donor unit exists | **0142** (character appearance), **0134** (continuity judge vs references), **0112** (per-unit judge, retry), **0146** (attested character states), 0141 (Calliope continuity ledger, not checked out) | DC identity unit with tests; ViMax extractor/portraits/selectors; Calliope `agent/continuity.py` | **Port candidates.** These are where drama consistency failed. |
| D. Prompt/skill donors, rewritten in Vietnamese | 0114–0120, 0126–0128, 0155, 0157, 0158, 0166 (huohuo, shenbi, StoryBox) | huohuo TS + skills, 0 tests; shenbi skills | Rewriting is mostly justified (no code/tests; Chinese market prompts translated to Vietnamese). Copy the skill texts verbatim as reference fixtures where we follow them closely. |
| E. Own mechanism, no donor | reviewer/launch qualification (0113, 0134 "qualified judge"), corpus building | none | Sponsor decision: keep, simplify to AIVPE-style guards, or narrow. Costs days of GPU and the Gemini free quota. |
| Architecture, not donor | 0003, 0075–0078, 0082, 0094, 0099, 0101, 0102, 0104, 0110, 0124, 0129, 0138, 0139 | ArcReel upstream / own | Not in scope. |

## Inferences

- INFER: the costliest re-implementations are in class C, because they are the image-consistency path that produces
  what every reviewer sees. The drama reviewer qualification failed twice on corpus continuity (identity, then a dog)
  that DC's identity unit and ViMax's reference selection already address.
- INFER: "port whole" for DC means porting its schemas, validators, prompts and tests and replacing only the storage
  and model-call seams (`sqlite_store`, `cognee`, `pydantic_ai` Agent → our text-route client). Its tests that use
  `pydantic_ai.models.function.FunctionModel` need that seam faked the same way.
- INFER: ViMax's selectors have no donor tests; porting them means writing tests at the port (still far less work
  than re-deriving the rules).

## Unknowns

- Whether DC ranks candidates per beat with a VLM in tested code (ADR-0112 cites it; `tests/` has no ranking test by
  name; `test_image_generation_selection.py` is about model options).
- Calliope's continuity ledger tests (not checked out).
- How much of ADR-0142's current code would be replaced vs adapted by DC's identity unit (needs a side-by-side read).

## Proposed order (for the sponsor)

1. **Rule** (sponsor): adopting a donor mechanism ports the whole unit — code, prompts, config defaults, tests,
   fixtures — pinned to the donor commit; only the seam is ours; re-implementation needs a written reason.
2. **Port DC's identity unit** into the character pipeline (side-by-side with ADR-0142 first, then replace), with its
   tests adapted at the seam.
3. **Port ViMax `reference_image_selector` + `best_image_selector`** into storyboard generation, with tests written
   at the port.
4. **Decide the qualification gate** (sponsor): keep as is, or replace the labeled-corpus qualification with the
   AIVPE guards plus a short smoke check.
5. Build any future reviewer corpus through the app's own pipeline, not side scripts.
