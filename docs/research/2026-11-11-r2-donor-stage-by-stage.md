# How ArcReel writes a story, stage by stage, against shenbi and huohuo-drama

Date 2026-11-11. Research only; nothing here is decided. Goal: find every stage where ArcReel's method or product
quality is worse than a donor's and name a concrete fix. Sponsor priorities: product quality first, fully automatic
runs (no Human step), a local 9B writer (`qwen3.5-vimax:9b` on Ollama, about 93 s per call), commercial-quality
Vietnamese stories that are publishable on their own.

## 1. Method, pins, labels

- **AR** (ArcReel): worktree `/home/anhtuan/.codex/worktrees/9b89/content-production-os`, branch
  `impl/autonomous-production`, HEAD `d35a85338` plus the uncommitted edits present on 2026-11-11 (driver.py,
  cast_checks.py, story_adapter.py and others; they are part of the state read). Paths are relative to
  `server/story_authoring/` unless they start with `server/` or `lib/`. Line numbers are of that working tree.
- **SH** (shenbi): clone at pin `10efa7cc`. Paths relative to the clone root. Read only, never run.
- **HUO** (huohuo-drama): `/home/anhtuan/content-os-r1-8/work/huohuo-drama`, pin `f104b85`. `ws/` means
  `workbench-server/src/services/novel/`, `meta` means `workbench-server/src/common/novel/novel-meta.ts`. Read only.
- **Reused, not repeated**: the two inventories of 2026-11-09 (`2026-11-09-r2-donor-long-novel-and-skill-gaps.md`,
  `2026-11-09-r2-donor-writing-capabilities.md`) and the failure-mode note
  (`2026-11-11-r2-donor-failure-modes.md`, "FM row n" below). Since that note, ADR-0127 implemented: the idea anchor
  on every planning prompt (`driver.py:592`), a seed redraw when it drops the idea's names (`driver.py:670`), the
  plan-conflict precheck folded into the plan revision (`driver.py:1246`, `cast_checks.py:187`), at most two withheld
  cards and bans in the plan grammar (`prompts/schemas.py:124,149-150`), replans that see the failed plan
  (`driver.py:1188`) up to `PLAN_REPLANS = 3`, deterministic near-name and gender-opening fixes before any review
  (`driver.py:1503`, `cast_checks.py:98,136`), and budget top-ups for a story blocked below its bound
  (`server/production_run/story_adapter.py:128,503`). ADR-0125 drew the idea; ADR-0126 locked gender.
- **Labels**: FACT = cited; INFER = my reasoning; UNKNOWN = needs a real run. "Cheap" = under one day; "large" =
  more. "+n calls" is model calls per story at the 9B writer's ~93 s each.
- **Not checked**: production run state and logs (out of scope), the HUO frontend, SH skills not named below.

Verdict scale is about product quality for a 9B local writer: **better**, **equal**, **worse**.

## 2. Stages

### Stage 1. Idea / premise intake and generation

- SH: the author dictates intent and the AI only tidies it; intent "must be anchored to this book, never invented"
  (`skills/shenbi-intent-management/SKILL.md:56,59`); originality is scored later in foundation review
  ("反套路/原创性" 10 of 100, `skills/shenbi-foundation-review/SKILL.md:120`).
- HUO: a premise call writes 200-500 characters covering world, protagonist, core conflict, tone and selling point
  (`agent-skills/novel_premise/SKILL.md:3-5`; `ws/novel-writing.ts:137-162`, temperature 0.78). The outline must add
  three novelty tags (selling-point deflection, unusual pressure source, unusual use of the ability), checked
  non-empty in code (`agent-skills/novel_outline/SKILL.md:4`; `ws/novel-outline-appeal-novelty.ts:13-30`).
- AR: a given idea is used as is; an automatic run draws one structured profile (idea, genre pack, tone, audience,
  length) in one call, closed sets settled in code, near-duplicates of the last 20 projects redrawn once
  (`idea_draw.py:144-185`, `idea_profile.py:57-70`; ADR-0125). The drawn idea must state protagonist, want,
  obstacle, cost of failure and "one detail that makes it unlike other stories" (`idea_draw.py:170-171`).
- Same/different: AR asks for the same ingredients as HUO's premise; neither donor checks premise quality in code
  beyond non-empty tags. AR is the only one that is automatic and duplicate-aware.
- **Verdict: equal.** No fix needed at this stage; the weakness is that the selling point and stakes are not kept
  as fields after the seed (stage 2).

### Stage 2. Seed, characters, world, story bible, style bible

- SH: 17 genesis steps (`src/shenbi/pipeline/genesis.py:60-83`) ending in an independent foundation review that
  must reach 80/100, core conflict at least 15/25, and lists voice distinctness, independent motives and real flaws
  (`skills/shenbi-foundation-review/SKILL.md:80-82,173-203`). Every major character carries a `voice_profile`
  (speech patterns, catchphrases, avoid patterns), fear, deep goal and arc; "without a voice fingerprint every
  supporting character sounds the same" (`skills/shenbi-character-design/SKILL.md:59-62,143`). The style target is a
  measurable band (sentence 12-25 characters, one long sentence per scene followed by a short one, paragraphs 2-4
  sentences alternating with one-line dialogue; `src/shenbi/pipeline/style_seed.py:36-39`).
- HUO: book fields theme, world rules, outer and inner desire, protagonist flaw, cast cores, ending direction,
  emotion palette; every person with a role must be named "name | title | relation | motive"
  (`agent-skills/novel_outline/SKILL.md:4,6`; `ws/novel-outline-drama-fields.ts:13-22`).
- AR: one seed call (`prompts/planning.py:45-65`): title, premise, genre, tone, pov, central conflict, ending
  direction, 2-5 characters (name, role, relation, description, goal, gender, address), 1-4 places. Then a story
  bible call (logline, core promise, world rules, conflicts, forbidden contradictions; `prompts/planning.py:68-76`)
  and a style bible call (narration style, rhythm, emotional texture, dialogue style, forbidden style, 3-8 rules;
  `prompts/planning.py:79-89`). The seed has no review; only the idea's names are checked (`driver.py:670`).
- FACT (the key finding of this stage): of the style bible only `style_rules` reaches the scene writer
  (`driver.py` `story_bible_input`, `narrative.py:493-500`). `narration_style`, `sentence_rhythm`,
  `emotional_texture`, `dialogue_style`, `forbidden_style`, the seed's `tone` and `pov`, and the bible's
  `world_rules`, `forbidden_contradictions`, `core_promise` are read by no drafting, repair or audit prompt (grep of
  `server/` finds them only in `prompts/schemas.py` and `prompts/planning.py`; the bible JSON reaches only the chapter
  plan prompt, `prompts/planning.py:155`). Three planning calls produce text the writer never sees.
- **Verdict: worse.** (a) The voice the style bible defines never reaches the prose, so tone and POV person rest on
  the 9B model's defaults. (b) Characters have no voice or flaw, so the CHARACTER audit judges "voice changes"
  (`audits.py:119-150`) against nothing. (c) No foundation check.
- Fixes: F1 (voice block to the writer), F6 (voice and flaw per character), F7 (seed foundation check).

### Stage 3. Book plan, volumes, outline, hook ledger

- SH: short outline = generate, six-point review, revise, rerun the review until it passes
  (`skills/shenbi-short-outline/SKILL.md:51-95`); long books add volume OKRs, thread map, pacing and a foreshadowing
  lifecycle (inventory A2, A6).
- HUO: phased outline (skeleton, volume chunks, gap patch; `ws/novel-writing.ts:375-546`) with 13 drama fields per
  chapter: time, place, cast, catalyst, desire, obstacle, stakes shift, choice, conflict layer, emotion craft,
  ending question, information delta, theme echo (`ws/novel-outline-drama-fields.ts:24-60`;
  `agent-skills/novel_outline/SKILL.md:5`). The premise is resent verbatim to every outline call (FM row 1).
- AR short story: one outline call with arc, three acts and per chapter only `core_task`, `threads_advanced`,
  `turning_point` (`prompts/schemas.py:82-95`, `prompts/outline.py:23-35`); deterministic checks plus a judged
  six-point review that now includes the idea (`prompts/outline.py:38-62`); one revision, re-checked in code only
  (`driver.py:1116-1155`). AR book: skeleton with volume objective, 3-5 key results and turning point; rows in
  chunks of 8 with role, at most one plant and two payoffs; code checks for role rotation, ending role, due hooks
  and payoff-after-plant, up to 3 code-driven revisions, one judged review, then `settle_plan` fixes the rest in
  code (`book.py:299-367`, `prompts/book.py:36-124`, `driver.py` `_volume_rows`).
- Same/different: AR's book ledger is closer to SH (ids, due chapter, code checks) and never stops a run, which
  suits automation. AR's chapter rows carry no desire, obstacle, choice or ending question.
- **Verdict: book plan equal (better for automation); short outline and chapter rows worse** in dramatic
  specificity: a 9B planner given only "core task / turning point" tends to produce tasks without a choice or a
  question that pulls the reader on (INFER; matches FM's observation that plans contradicted themselves).
- Fix: F4 (three drama fields on outline chapters and book rows).

### Stage 4. Chapter plan, writing brief, beats

- SH: an eight-section memo per chapter (task with the goal's source priority, reader expectation, hooks to pay and
  cards to keep, function of quiet passages, key choice through "why / interest / persona", 1-3 required changes,
  hook ledger operations, do-not with "none" legal; `skills/shenbi-chapter-planning/SKILL.md:150-172`), plus a scene
  budget with a **verbatim closing-hook sentence per scene**, a time anchor and a POV line, all machine-checked
  (`SKILL.md:66-98`; gate `src/shenbi/gates/g4/chapter_planning.py`).
- HUO: a writing-brief call per chapter (150-400 characters: goal, cast, mood, length emphasis, end hook, a 15-item
  consistency ledger; `agent-skills/novel_writing_brief/SKILL.md:3-6`, `ws/novel-writing.ts:231-300`); beat
  budgets weighted toward the middle (3 beats 0.20/0.45/0.35; `ws/novel-chapter-beat-budget.ts:38-55`).
- AR: one plan call with goal, reader expectation, at most 2 withheld cards and 2 bans, 1-3 required changes, 3-5
  scenes (summary, location and POV as grammar enums, cast, 2-4 beats, emotional turn, plot function, dialogue
  flag) (`prompts/planning.py:92-159`, `prompts/schemas.py:128-151`); a judged consistency review plus the code
  conflict check, one revision kept only if conflicts fall (`driver.py:1157-1255`).
- Defects found: the prompt still says "withheld_cards và do_not tối đa 3 mục" (`prompts/planning.py:143`) while the
  grammar allows 2 (`prompts/schemas.py:124`). Scene length is split evenly (`prompts/drafting.py:196-199`), so the
  turning-point scene gets the same room as the set-up. There is no closing-hook sentence, so "end on a concrete
  hook" is an abstract instruction (`prompts/drafting.py:164`).
- **Verdict: worse** (no declared closing hook, flat scene budgets, a prompt/grammar mismatch). AR is better than
  both donors on schema-enforced names and places.
- Fixes: F4 (closing hook), F5 (weighted scene targets and position duties), F12 (prompt says 2).

### Stage 5. Context assembly for drafting

- SH: per chapter a deterministic package: entity-index facts for the plan's entities, embeddings, and always the
  book spine, `audit_drift` (recent audit weaknesses) and style profile, budgeted by chapter role 8 000-18 000
  tokens (`src/shenbi/pipeline/context_assemble.py:1-67`). The writer restates "AI-voice to guard against, from the
  recent audit_drift" before drafting (`skills/shenbi-chapter-drafting/SKILL.md:121-123`). Short stories keep the last
  2-3 chapter summaries plus bible and character cards (`skills/shenbi-short-drafting/SKILL.md:78-82`).
- HUO: previous chapter tail (1 600 chars), an end snapshot (time, place, last event), the previous chapter's state
  card, the chapter outline as a hard end stop, beat budgets, world block on chapter 1
  (`ws/novel-writing.ts:903-1009`; `ws/novel-chapter-end-snapshot.ts:1-4`).
- AR: a compiled Canon context pack rendered as locked facts (character `locked_line`, place descriptions), scene
  purpose, beats, style rules, the last two paragraphs of the previous scene and 200-character openings of older
  scenes; a book adds a memory block of part summaries, the last 3 chapter summaries, character states and due
  hooks (`prompts/drafting.py:74-113`, `book.py:509-530`, `driver.py:1335-1393`).
- FACT gaps: (a) stage 2's voice fields are absent. (b) A short story's scene sees no account of what happened in
  earlier chapters, only the previous scene's last paragraphs and older openings; the plan's verified
  `required_changes_by_end` of earlier chapters are never shown. (c) Earlier chapters' audit findings never feed
  forward. (d) The context's "[Nhịp bắt buộc]" block lists beats sorted alphabetically (`narrative.py:346`,
  `creative_constraints=sorted(set(scene.beats))`) while the prompt lists them in plan order
  (`prompts/drafting.py:178`): two orders for one scene. (e) The digest's `time_place` (`book.py:157`) is not in the
  memory block (`book.py:509-530`).
- **Verdict: worse.** Fixes: F1, F3, F12.

### Stage 6. Scene/chapter drafting (prompt, length, decoding)

- SH: two chapters per call (about 6 400 characters), a PRE_WRITE_CHECK restating task, hooks, bans, last three
  endings to avoid, closing tension beat, emotion, sensory anchor; a POST self-check; chapter-end tension words in
  the last 8 paragraphs as a hard gate; per-scene closing hook verbatim; style modulated by chapter role; two sensory
  channels per scene (`skills/shenbi-chapter-drafting/SKILL.md:58-72,105-150`).
- HUO: one chapter per call or beat by beat with frozen earlier prose (`ws/novel-chapter-beat-generate.ts:421`,
  `ws/novel-chapter-beat-budget.ts:227-233`); chapter 1 opens on conflict within ~300 characters, later chapters
  anchor the seam then strike; the last beat must stop on an open question, no warm release
  (`ws/novel-chapter-beat-generate.ts:165-217`); "paragraph length varies naturally, dialogue may be one sentence,
  never a fixed sentence count per paragraph" (`agent-skills/novel_chapter_writer/SKILL.md:11`); an automatic polish
  call after every draft (`ws/novel-writing.ts:867,1340`, `ws/novel-prose-polish.ts:62`); temperature 0.8.
- AR: one scene per call, 600-1 000 syllables, grammar-bounded as an exact number of paragraphs each 280-700
  characters (`prompts/drafting.py:121-143`, `driver.py:1465-1472`, `generation.py:100-125`); the prompt also asks
  "mỗi đoạn 3–5 câu" (`prompts/drafting.py:182-183`). Decoding temperature 0.7, top_p 0.8, top_k 20, repeat
  penalty 1.1 (`driver.py:200`), thinking off (`lib/text_backends/ollama.py:134`).
- Same/different: AR's length control is the strongest of the three (grammar, not self-counting; SH's own skill
  records self-counts inflated 16-97%, `SKILL.md:110`). Scene-sized calls suit a 9B better than SH's 6 400-character
  bundles (INFER).
- FACT conflict: the craft rule "Đoạn văn dài ngắn xen kẽ" (`prompts/drafting.py:38`) and the `UNIFORM_PARAGRAPHS`
  check (`audits.py:582-590`) ask for varied paragraphs, while the grammar forbids any paragraph under 280
  characters and the prompt fixes 3-5 sentences each. A line of dialogue cannot be its own paragraph. INFER: the
  prose reads as uniform blocks with dialogue buried mid-paragraph, the opposite of commercial Vietnamese fiction
  and of both donors' rule; `dialogue_lines` counts only lines that start with a dash or quote
  (`checks.py:639,686`), so it may also miss inline dialogue.
- **Verdict: length control better; rhythm, dialogue layout, openings and closing hooks worse.**
- Fixes: F2 (blocks may hold dialogue lines), F5 (position duties), F4 (closing hook), F1 (voice).

### Stage 7. Deterministic checks

- SH: per-artifact gates and six cross-chapter invariants (FM rows 5, 8, 9, 12), transition-word density, a
  closing-hook exact match, a chapter-end tension window.
- HUO: deterministic prechecks for invented major states, injuries, presence, seam replay, outline overshoot and
  next-chapter leak (FM rows 6, 10, 11), stable cast facts (FM row 7).
- AR: CJK, unterminated text, paragraph cut, length window, meta leak and meta narration, foreign words, markup,
  cross-scene replay, near-duplicate, trigram repetition, unknown and near names (`checks.py:748-850`); stock phrases,
  not-but, uniform paragraphs (`audits.py:559-592`); genre fatigue (`genre_packs.py:183`); gender per character
  (`cast_checks.py:49`); long-span reuse, repeated openings, voice drift (`craft_checks.py:45,75,132`); plan conflicts
  (`cast_checks.py:187`); idea names (`cast_checks.py:284`).
- **Verdict: equal on prose hygiene (AR better on Vietnamese-specific checks); worse on cross-chapter invariants**
  (POV person, time anchor, life status, age, next-chapter leak), which FM rows 6-11 already rank and ADR-0127 did not
  implement. Fix: F13 (carry-over), plus the closing-hook check of F4.

### Stage 8. Model audits and reviews

- SH: grouped audits (factual, character, craft, plan) plus resonance and sensitivity, run as independent agents;
  seven serial auditors were merged into domain groups (`src/shenbi/pipeline/chapter_loop.py:132-140,228-275`);
  deterministic anti-AI values are computed and injected so the judge reads them instead of counting
  (`src/shenbi/pipeline/review_checklist.py:278-300`).
- HUO: a 21-dimension continuity check with deterministic prechecks, a craft check with ten drama gates
  (desire, obstacle, choice, hook, information delta, emotion shown, theme echo, conflict layer, stakes shift,
  opening promise; all must be present or weak; `ws/novel-chapter-craft-check.ts:29-84`) and an appeal audit;
  minimum scores 78 and 70 (`meta:190,216`).
- AR: six judged dimensions per chapter per cycle (continuity, memo, character, anti-AI, craft, safety), every
  finding quoted verbatim or discarded, up to 3 blocking claims re-read by an independent confirmation
  (`audits.py:119-150,227-310`, `driver.py:1587-1642`); a manuscript critic with a confirmed ending check
  (`audits.py:445-510`, `driver.py:1779-1855`).
- FACT gaps: the CONTINUITY audit's "[Tóm tắt trước đó]" is the earlier chapters' plan goals
  (`driver.py:1603`), not what was written, even for a book whose digests exist. The anti-AI judge's findings are
  always stylistic (`audits.py:209-217`) yet cost one call per chapter cycle. The production story owner passes no
  judge route (`server/production_run/story_adapter.py` has no judge; `driver.py:240-242` falls back to the
  writer), so the 9B model audits itself; HUO warns against same-family judging (inventory B3).
- **Verdict: evidence discipline better than both; context of the continuity audit worse; drama coverage worse**
  (no desire/obstacle/choice gate). Fixes: F3 (feed the audit what happened), F4 (drama fields make MEMO check
  them), F11 (merge anti-AI into craft with injected counts).

### Stage 9. Repair loops and their limits

- SH: 1-2 minor findings → spot patch; 3+ or one critical → rewrite the chapter; at most 3 rounds, then the best
  version (`skills/shenbi-short-drafting/SKILL.md:99-106`); retries accumulate failure families so they do not
  oscillate (FM row 3).
- HUO: patch or regenerate up to 30 times with a stagnant-streak stop of 5 (`meta:169-170`,
  `ws/novel-chapter-pipeline.ts:715-915`); craft rewrites up to a cap (`ws/novel-chapter-craft-hook.ts:138-202`);
  humanize up to 3 times toward a detector target of 39 (`meta:245-261`).
- AR: per scene, certain fixes in code first, then regenerate (too short), deterministic fixes, span patch or
  length normalizing, all inside 6 calls per round with a best-version fallback (`driver.py:1447-1540`,
  `repair.py:51-55,248-343`); per chapter, review-driven patches with a no-worse check, missing required changes as
  scene rewrites, humanize when a scene has 3 voice findings (`driver.py:1645-1682,2195-2215`), and up to 3 replans
  that see the failed plan (`driver.py:1686-1699`).
- FACT gap: a chapter-review repair receives only the character facts as context and an empty history
  (`driver.py:1670`: `..., scene_findings, facts, []`), so it neither sees the scene's plan nor what the previous
  cycle tried. A 9B patcher without the beats can "fix" a continuity line by breaking a beat (INFER).
- **Verdict: bounds and automation better than both; repair context worse.** Fix: F8.

### Stage 10. Cross-chapter continuity, digests, book memory

- SH: state settling into append-only truth rows, memory distillation by layers, cross-chapter invariants
  (inventory A4, A5, B1).
- HUO: chapter-end memory (summary under 50 characters, state changes, hooks; `ws/novel-memory/novel-memory-manager.ts:455-511`),
  end snapshot and state cards for the seam (`ws/novel-chapter-end-snapshot.ts:1-4`).
- AR book: a digest per chapter (summary, events, character states, hook operations, new threads, time and place;
  names attested; `book.py:151-158,453-457`, `prompts/book.py:141-160`) folded into memory with windows of 8
  chapters and 6 parts (`book.py:459-500`). AR short story: no digest at all; only plan goals carry forward.
- **Verdict: book equal to HUO, simpler than SH; short story worse** (nothing of what was written carries
  forward). Fix: F3 (0 calls, from the plans' verified required changes); the digest call for short stories is the
  +3-call option.

### Stage 11. Ending, hook payoff, manuscript-level review

- SH: a ten-step closure (resolve foreshadowing, distill memory, volume consolidation, volume score, arc-payoff
  review, ...) ending at a Human checkpoint (`src/shenbi/pipeline/closure.py:1-12,64-90`).
- HUO: chapter-level only; no manuscript-level judge found in `ws/` (UNKNOWN beyond the files read).
- AR: the critic reads the whole short story (or a book part's digests plus its last chapter) and must quote the
  ending; an unresolved ending is re-read against the approved ending and, if confirmed, the final scene is rewritten
  once (`driver.py:1779-1855`); a book's last chapter rewrites its final scene once for hooks still open
  (`driver.py:979-989`); hooks not paid become stylistic findings (`driver.py:991-1010`).
- FACT: after that one rewrite a still-missing ending is escalated (`checks.py:61,66-77`) to NARRATIVE_CRITICAL, and
  the automatic commit accepts every non-hard finding "as is" (`server/production_run/narrative_authority.py:145-174`).
  So an autopilot story whose ending was never resolved can be committed and handed to the film flow. (The story
  adapter's docstring still says such a manifest "is never approved automatically",
  `server/production_run/story_adapter.py:7-8`, which is stale.)
- **Verdict: review method better than both; the floor on what is published worse** for a no-Human product: the
  donors stop for a person where AR publishes. Fix: F10.

### Stage 12. Packaging, commit/acceptance, hand-off

- SH: 3-5 titles, blurbs and selling points with evidence, cover prompt, platform tags, Human picks
  (`skills/shenbi-short-packaging/SKILL.md:51-95`).
- HUO: a title call with strong rules (bans hollow literary titles, length band, one line) (`ws/novel-writing.ts:166-229`).
- AR: one packaging call (redrawn once if fewer than 3 selling points verify), selling-point quotes checked in
  code, blurb claims checked by two judge calls, flagged blurbs sorted last (`driver.py:1857-1950`,
  `prompts/packaging.py:23-43`, `audits.py:595-668`); the export takes `titles[0]` (`driver.py:2017`) with no check
  of the prompt's own title rules (2-6 words, natural, no repeated word; `prompts/packaging.py:26-27`). Commit is
  manifest-bound and automatic; hand-off is idempotent (`handoff.py:1-15`).
- **Verdict: blurb and selling-point fidelity better than both; title choice worse than HUO's rules-in-prompt plus
  AR's own unchecked rules.** Fix: F9.

### Stage 13. Recovery, budget, automation

- SH: per-step retry caps of 3 and an escalation checkpoint a Human resolves (`src/shenbi/pipeline/state.py:63-64`,
  FM row 4); crash snapshots.
- HUO: stop the batch on error; rewrite caps and stagnant streaks (`meta:169-170`).
- AR: fingerprinted nodes resume without regenerating, epochs fence late results (`driver.py:1-17`, FM row 18); the
  structural call bound (`driver.py` `run_call_bound`), automatic top-ups up to twice on a free route
  (`server/production_run/story_adapter.py:128,503-526`, ADR-0127 point 2), no Human step anywhere.
- **Verdict: better** than both for the sponsor's fully-automatic goal. No fix; F11 would lower call count.

## 3. Ranked fixes (highest product-quality gain per cost first)

Every fix below adds no model call unless it says so. Each is "cheap" (under a day, tests included) unless marked.

1. **F1. The writer sees the story's voice.** Add a "[Giọng truyện]" block to the scene prompt: seed `tone` and `pov`,
   style bible `narration_style`, `sentence_rhythm`, `emotional_texture`, `dialogue_style`, `forbidden_style`
   (bounded, ~600 characters); add the bible's `forbidden_contradictions` to "[Sự thật đã khóa]". The same block goes
   to span repair. Gain: tone and POV person stop depending on 9B defaults; three planning calls stop being wasted.
   Files: `server/story_authoring/prompts/drafting.py` (`scene_draft_prompt` gains a `voice` argument),
   `server/story_authoring/driver.py` (`_ensure_scene` builds it from `story.seed`, `story.style`, `story.bible`;
   `style_in` and `bible_in` are already scene inputs, `driver.py` `_write_chapters`). Cheap.
2. **F12. Remove self-contradicting instructions.** "tối đa 3" → "tối đa 2" (`prompts/planning.py:143`); render
   beats in plan order or drop the duplicate "[Nhịp bắt buộc]" block (`prompts/drafting.py:89-101`, `:178`; the order is lost
   at `narrative.py:346`); fix the stale docstring (`server/production_run/story_adapter.py:7-8`). Hours.
3. **F3. What happened so far, and what went wrong, carried forward.** For a short story: a "[Đã xảy ra]" block from
   earlier chapters' `chapter_goal` and `required_changes_by_end` (MEMO-verified), and a "[Cần tránh]" block with the
   2-3 most frequent finding codes and one quoted example from earlier `chapter_review[c]` records (SH `audit_drift`).
   For a book: add the last digest's `time_place` to `memory_block`. Feed the same story-so-far text (or, for a book,
   the digests' summaries) to the CONTINUITY audit instead of plan goals. Files: `prompts/drafting.py`
   (`render_context`), `driver.py` (`_ensure_scene`, `_review_chapter` `previous`; add the earlier
   `chapter_review` heads to the scene's inputs so resume stays exact), `book.py` (`memory_block`). Cheap. Option:
   chapter digests for short stories too, +3 calls (one per chapter, ~5 min).
4. **F6. Each character has a voice and a flaw.** `SeedCharacter` gains optional `voice` (≤ 80 characters: how they
   speak, words they use) and `flaw` (≤ 80); the seed prompt asks for them; `locked_line` includes the voice, so the
   writer and the CHARACTER audit share one reference. Optional fields keep stored seeds valid (as `gender` did).
   Files: `prompts/schemas.py`, `prompts/planning.py` (`seed_prompt`), `book.py` (`bound_seed`, volume
   `new_characters`). Cheap.
5. **F5. Scene budgets and duties by position.** Weight scene targets toward the turn (HUO 0.20/0.45/0.35 for three
   scenes, scaled for 4-5, then clamped to the 600-1 000 window) instead of an even split; give the first scene of
   chapter 1 "open on a confrontation or dialogue in the first paragraph", the first scene of a later chapter "one
   sentence anchoring where the last chapter ended, then the conflict", and the last scene of a non-final chapter
   "stop on an open question, no warm release". Files: `prompts/drafting.py` (`target_syllables_for` takes the scene
   index; duties in `scene_draft_prompt`), `driver.py` (call site of `target_syllables_for`). Cheap.
6. **F4. Drama fields and a declared closing hook.** Outline chapters and book rows gain `obstacle`, `choice`
   (the protagonist's decision) and `ending_question`; the chapter plan gains `closing_hook` (one concrete sentence
   for the last scene of a non-final chapter). The draft duty names it; a deterministic check compares the last two
   paragraphs' content words with it (overlap below a calibrated floor → stylistic finding that joins the humanize
   targets) and the MEMO audit reads it in the memo block. Files: `prompts/schemas.py`, `prompts/outline.py`,
   `prompts/book.py`, `book.py` (`BookRow`, `PlannedRow`), `prompts/planning.py`, `prompts/drafting.py`,
   `audits.py` (`_memo_block`), `craft_checks.py` (the check), `driver.py`. About one day; calibrate the floor on a
   real run first (FM row 13: no blocking deterministic checks without a fixture).
7. **F8. Review-driven repair sees the scene's plan and its history.** Pass the scene's rendered context (or at least
   its beats, the chapter memo and the voice block) instead of `facts` alone, and keep each scene's repair history
   across review cycles ("these problems from earlier rounds must stay fixed"). Files: `driver.py:1670` and the review
   record that stores the history. Cheap.
8. **F2. Paragraph blocks may hold dialogue lines.** Keep the grammar's block count and per-block ceiling (they bound
   length, commit `32209195c`), but let a block contain line breaks: one narration paragraph, or an exchange of
   dialogue lines. Lower the block floor, render each line as its own paragraph, replace "mỗi đoạn 3–5 câu" with "đoạn
   kể 2–4 câu, mỗi lời thoại một dòng riêng". Recheck `dialogue_lines`, `UNIFORM_PARAGRAPHS` and the paragraph split
   (`"\n\n"`) in checks. Files: `generation.py` (`prose_schema` pattern allows `\n`), `prompts/drafting.py`,
   `checks.py`, `audits.py` (`anti_ai_findings`), `craft_checks.py`. **Large** (1-2 days): measure length and looping
   on a fixture before shipping.
9. **F9. Pick a title that passes the prompt's own rules.** A code filter: 2-6 words, every word a Vietnamese
   syllable (`checks.py` `is_vietnamese_syllable`), no repeated word, not only a character name; take the first
   title that passes; when none passes, the existing second packaging draw (`driver.py:1873`) is asked again with the
   problems named. Files: `prompts/packaging.py` (`title_problems`), `driver.py` (`_packaging`, export title at
   `driver.py:2017`, book title in `_commit_book_state`). Cheap; +1 call only when every title fails, inside the
   packaging cap.
10. **F7. A foundation check on the seed.** Deterministic first: exactly one character marked as the protagonist,
    non-empty and distinct `central_conflict`, `ending_direction`, and (with F6) a stated stake. Then one judged review
    against SH's core-conflict and distinctness items, answered by one revision only if it finds problems. Cost +1
    call, +1 on failure (~1.5-3 min per story); add 2 to `run_call_bound`'s planning term. Files:
    `prompts/planning.py` (`seed_review_prompt`), `driver.py` (`produce_seed`, `run_call_bound`),
    `cast_checks.py` (deterministic seed problems). Cheap.
11. **F11. Merge the anti-AI judge into the craft judge, with injected counts.** The anti-AI judge's findings are
    always stylistic; SH merged its serial auditors and injects deterministic counts. Give the CRAFT call the
    deterministic voice findings as facts and drop `ANTI_AI` from `CHAPTER_DIMENSIONS`. Saves 1 call per chapter
    cycle (3-9 per short story, ~5-14 min), which pays for F7. Files: `audits.py`, `driver.py` (`run_call_bound`).
    Cheap to code, **needs an A/B on two real stories** because a 9B judge may do worse with a merged instruction
    (INFER).
12. **F10. A publishable floor for autopilot.** When the final quality record still holds an escalated `NO_ENDING`, a
    hard `STORY_LENGTH`, or an unconfirmed blocking `MEMO_COMPLIANCE` in the last chapter, the story is committed but
    marked not publishable; autopilot does not hand it to the film flow and instead replans the last chapter once
    under a new contract. Cost when it fires: about one chapter, ~40-50 calls (~1-1.3 h). Files:
    `server/production_run/narrative_authority.py`, `server/production_run/story_adapter.py`, `driver.py`
    (`_manuscript_review`), `commit.py`. **Large**; it touches the commit authority, so it needs its own ADR.
13. **F13. Carry-over invariants from the failure-mode note** (not implemented by ADR-0127): POV person against the
    seed `pov` (narration "tôi" outside quotes), a structured life status, age as a locked fact, a time anchor in plan
    and digest, a next-chapter leak check (FM rows 6-11). All 0 calls; each cheap, but each needs a real-run fixture
    first (FM row 13).

## 4. Facts versus inferences, and unknowns

- FACT-only conclusions: the unused style and bible fields (F1), the plan-goal continuity summary (F3), the
  prompt/grammar mismatches (F12), the repair context (F8), the unchecked title (F9), the paragraph floor against the
  varied-paragraph rule (F2), the auto-commit of an escalated missing ending (F10), and the same-model judge in
  production.
- INFER: the size of the quality gain of each fix, that scene-sized calls suit a 9B better than SH's bundles, that
  uniform blocks read worse to Vietnamese readers, and that a merged judge keeps its accuracy.
- UNKNOWN: how often today's production stories hit `NO_ENDING` after the rewrite; whether the 9B writer follows a
  voice block of ~600 characters without dropping beats (measure on one real chapter); HUO's manuscript-level review,
  if any, outside the files read.
