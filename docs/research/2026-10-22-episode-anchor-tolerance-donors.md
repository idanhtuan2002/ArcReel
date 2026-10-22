# Episode-planner anchor tolerance: donor review

Date: 2026-10-22. Scope: how the V1 episode planner (`lib/episode_planner.py`) maps the model's `end_anchor` text back to a source offset, why a local 9B model (`qwen3.5-vimax:9b`) failed it on a Vietnamese source, and how related donors cut a novel into episodes.

## Observed failures (facts)

Captured by instrumenting `_resolve_boundaries` on a copy of the `accept-clean` project (evidence `docs/r2/evidence/R2_V2_PLANNER_LOCAL_9B.json`). Mismatch classes between the model anchor and the source:

| Class | Example (model -> source) |
|---|---|
| quote kind swapped | `'Hạnh ơi…'` -> `"Hạnh ơi…"` |
| closing quote added | `…đừng bỏ lũ trẻ này'` -> `…lũ trẻ này, chúng…` |
| closing quote / period swapped | `thầy ạ".` -> `thầy ạ."` |
| narration wrapped in quotes | `'Thầy Tuấn ngắt lời…'` -> no quotes in source |
| ellipsis shortening (tail) | `'Con đừng bỏ mẹ,' bà thì thầm...` |
| word changed | `Cô đừng bỏ mẹ` -> `Con đừng bỏ mẹ` |
| two sentences merged / invented | `…đừng bỏ lũ trẻ này,' giọng khàn khản vì nước mặn…` (tail comes from another sentence) |
| out of order | anchor 11 lies before anchor 10 |
| ends mid-sentence | `…ông nói với giọng khàn đặc,` |

After the first retry the model often degenerated (one invented anchor repeated for every episode, or every anchor shortened with `...`).

## Donors (pinned commits, facts)

| Donor | Pin | How episodes are cut | Source mapping |
|---|---|---|---|
| ArcReel upstream | `upstream/main` (fetched 2026-10-22) | LLM `end_anchor`, same tiers as this fork (exact, then NFC + punctuation/whitespace fold); adds manual cuts, replan candidates and `NoCutPointError` (`lib/episode/episode_planner.py`) | `_resolve_boundaries` identical to the fork before this change; retry exhaustion still raises |
| ai-short-film | `3dc93a62` | Source split into one block per non-empty line (`backend/app/utils/script_indexer.py: build_script_blocks`); the single planning LLM returns `start_block`/`end_block` ids | No text quoting. `parsing/range_utils.py: normalize_minimum_ranges` clamps ids, forces monotonic ranges, snaps the first range to 0 and the last to the end; `fallback_even_ranges` when too few ranges. Boundaries are always line ends |
| DramaClaw | `b299bfd9` | Deterministic `ChapterDetector`: one episode per chapter (`sqlite_store.py: build_episodes_from_chapters`); the AI mode returns chapter ranges (`agents/episode_planner.py`, `_validate_and_fix_episodes` renumbers) | No text quoting; boundaries are chapter boundaries |
| Jellyfish | `a9678194` | Text addressed by paragraph chunk ids (`chunk_id` like `chapter1_p03`, `api/v1/routes/film/common.py`) | No text quoting |
| Huohuo Drama | `f104b853` | `splitNovelChapters` (regex) for import; LLM quotes are checked with `normalizeLite`, which removes all whitespace and punctuation including quotes, dashes and ellipsis (`services/novel/novel-outline-compliance.ts`) | Punctuation-insensitive comparison, no offsets |
| ViMax | local `63bb9c7` | `RecursiveCharacterTextSplitter` chunks + RAG retrieval per event (`agents/novel_compressor.py`) | No quoting; `difflib.SequenceMatcher` ratio >= 0.85 tolerates name typos (`pipelines/idea2video_pipeline.py`) |
| Novel Studio, Shenbi, Take, StoryBox | pins in `R2_STORY_DONOR_BASELINE.json` / research notes | No novel-to-episode source mapping | — |

## Inferences

- No donor asks a model to copy source text verbatim and then requires an exact match; the robust donors address source units by id (line, paragraph, chapter) and cut only on structural boundaries.
- Huohuo and ViMax show two tolerances that are safe when the result must still be unique: compare letters and digits only, and accept a near match at a high similarity threshold.
- Switching the planner to block ids would change the prompt contract, the draft schema and the upstream-shared planner; it is out of scope for a fix on the V2 line.

## Decision (taken under sponsor delegation)

Keep the upstream anchor contract and make the matcher and boundaries tolerant, each tier still requiring a unique match:

1. Exact. 2. NFC + punctuation width + quote kind + whitespace width folding. 3. Strip added edge quotes / trailing sentence punctuation. 4. Letters-and-digits skeleton (case-insensitive), from Huohuo `normalizeLite`. 5. Ellipsis: leading or middle -> last segment; trailing -> previous segment, then the cut goes to the end of that sentence. 6. Sentence-aligned near match (`SequenceMatcher` >= 0.85 and 0.08 ahead of any rival, after ViMax).
- Every end snaps forward to the next sentence end or paragraph break (at most 400 chars, never reaching the next episode's end), after the donors that only cut on structural boundaries.
- A rejected anchor's reason names the closest source sentence (similarity >= 0.5) so the retry can copy it.
- After retry exhaustion the longest valid prefix across attempts is committed and the rest is planned in the next batch, matching the existing per-batch episode cap.
- The prompt asks for anchors that end at a sentence end, without added quotes or ellipsis.

## Independent review (Codex) and follow-up rules

A read-only Codex review of the change found five defects, each fixed test-first:

1. A multi-sentence anchor could be accepted on its last sentence alone at an earlier, unrelated passage. Acceptance now uses the whole anchor. The last sentence alone is accepted only when the leading sentences do not strongly match a place after it, so the order is consistent. This covers anchors that merge two non-adjacent source sentences, which a live batch produced.
2. One occurrence followed by trailing whitespace was counted as two fuzzy hits. Candidates now collapse by skeleton span. Only regions that do not overlap the best region count as rivals.
3. Abbreviations (`Dr.`, `TP.`, single initials) and in-sentence pause ellipses (`我们……不知道`, `... rồi`) were taken as sentence ends. Boundary detection is now one contextual function, `_sentence_close_at`.
4. A straight quote opening the next sentence (`ends."Second`) was absorbed by the previous episode. A straight quote directly followed by a letter or digit is no longer treated as a closing mark.
5. The longest-prefix fallback skipped the final whitespace-tail snap. Both paths now use `_finalize_ends`.

A live batch then produced an episode made of a single comma. Two consecutive anchors fell inside one source sentence, one before the comma and one after it. Two consecutive anchors in the same sentence are now rejected; the later one gets a specific reason. The valid prefix stops before the pair, so no episode ends mid-sentence or consists only of punctuation.

## Unknowns / not covered

- Out-of-order and invented anchors remain model errors; only the prefix rule and the hint mitigate them.
- Thresholds (0.85 / 0.08 / 400 chars) are taken from ViMax and the observed Vietnamese sentence lengths, not tuned on a corpus.
- A block-id contract (ai-short-film, Jellyfish) would remove quoting errors entirely; it stays a candidate for an upstream-level change.
