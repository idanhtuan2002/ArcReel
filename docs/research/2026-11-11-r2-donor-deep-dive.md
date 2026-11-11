# Donor deep dive: verified claims, build specs for F1–F13, and fixes mined from donor history

Date 2026-11-11. Research only; nothing here is decided. Second round after
[the stage-by-stage comparison](2026-11-11-r2-donor-stage-by-stage.md) ("SBS" below). Sponsor priorities: product
quality first, fully automatic runs, a local 9B writer (`qwen3.5-vimax:9b`, ~93 s per call), commercial
Vietnamese stories that can be published on their own.

## 1. Method, pins, labels

- **AR** (ArcReel): worktree `/home/anhtuan/.codex/worktrees/9b89/content-production-os`, branch
  `impl/autonomous-production`, **HEAD `99934cb6d`**, clean. SBS read `d35a85338` plus uncommitted edits; those
  edits are now commit `d7c838033`, so most SBS line numbers still hold, with small shifts (section 2). Paths are
  relative to `server/story_authoring/` unless they start with `server/`, `r2/` or `lib/`.
- **SH** (shenbi): clone at **pin `10efa7c`**, 1 176 commits, full history. Read only, never run. History mining:
  all 732 subjects that are not `docs/chore/ci/test/build/style`, the 488 subjects that match the quality keywords
  in the brief (fix, 修复, 实弹, 回归, 误报, 漂移, 重复, 截断, 名字, 性别, OOC, 崩, 降智, 注水, hook/钩, POV, …), and
  the full message and the relevant diff of about 35 commits named in section 5.
- **HUO** (huohuo-drama): `/home/anhtuan/content-os-r1-8/work/huohuo-drama`, **pin `f104b85`**. Git history exists:
  29 commits, subjects terse ("fix novel bug", "novel 3.0"). Evidence is the file lists of the last three commits and
  the header comments of the modules the last one (`f104b85`) adds. `ws/` = `workbench-server/src/services/novel/`,
  `cn/` = `workbench-server/src/common/novel/`.
- **Not read**: production state, logs, `.env`, credentials; the V1 trial environment (it holds a credentials file,
  so it was not searched); the HUO frontend. No test was run.
- **Labels**: FACT = cited from source at the pin. INFER = reasoning. UNKNOWN = needs a real run.
  **SAFE NOW** = can ship without a real-run fixture (prompt text, plumbing, or a check that only records a
  stylistic finding). **FIXTURE FIRST** = a deterministic check that changes what is repaired or blocked, or a
  change whose quality effect is uncertain enough to need an A/B on real output (SH's rule, FM row 13).
  "+n calls" = model calls per short story at ~93 s each.

## 2. Verification of the stage-by-stage claims

Status: **confirmed**, **partly right** (substance right, detail or citation off), **wrong**.

| # | SBS claim | Status | Evidence at `99934cb6d` (corrected citation) |
|---|---|---|---|
| V1 | Of the style bible only `style_rules` reaches the scene writer | **confirmed** | `story_bible_input` puts only `style.style_rules` into the bible input (`driver.py:2151-2165`); the policy reader turns them into CREATIVE_POLICY segments (`narrative.py:493-500`), rendered as "[Quy tắc văn phong]" (`prompts/drafting.py:94-95,102`). A grep of `server/ lib/ r2/` finds `narration_style`, `sentence_rhythm`, `emotional_texture`, `dialogue_style`, `forbidden_style`, `world_rules`, `forbidden_contradictions`, `core_promise` only in `prompts/schemas.py:63-78` and `prompts/planning.py:71-82`. |
| V2 | The bible JSON reaches only the chapter-plan prompt | **partly right** | Also the style-bible prompt (`prompts/planning.py:88-89`) and the book outline prompt (`prompts/book.py:53`). The seed JSON (with `tone`, `pov`) reaches the outline, bible, style and book prompts (`prompts/outline.py:34-35`, `prompts/planning.py:76,86`, `prompts/book.py:50`). No drafting, repair or audit prompt sees any of them. |
| V3 | Paragraph grammar 280–700 chars and "3–5 câu" block standalone dialogue lines | **partly right** | Floor 280 (`prompts/drafting.py:125,136-137`), ceiling ≤700 (`:126,140-143`), exact paragraph count (`:130-133`), "mỗi đoạn 3–5 câu" (`:182-183`). **But** the string pattern admits the JSON escape `\n` (`script_guard.py:76`: `\\["\\/bfnrt]`), and `validate_story_content` keeps it (`generation.py:342-350`), so a block *can* carry single line breaks; nothing in the prompt invites it. `dialogue_lines` uses `re.MULTILINE` (`checks.py:639`), so a `\n—` inside a block would count. In practice (INFER) the "3–5 câu per element" instruction makes every displayed paragraph a 3–5 sentence block with dialogue inline. |
| V4 | `dialogue_lines` may miss inline dialogue | **confirmed, worse than stated** | `_DIALOGUE_LINE = ^\s*(?:—\|–\|-\|“\|")` (`checks.py:639,686-687`): a quote “…” in mid-paragraph is not counted, so `NO_DIALOGUE` (`checks.py:848`, stylistic) fires on scenes that do have dialogue. |
| V5 | A short story carries no "what happened" forward | **confirmed** | Short story: every earlier scene is visible (`narrative.py:170-176`), but the prompt shows only the last two paragraphs of the scene just before and 200-character openings of older scenes (`prompts/drafting.py:104-110,116-118`). Earlier plans' `required_changes_by_end` reach only later *plan* prompts (`prompts/planning.py:108-117`). No digest exists outside books (`driver.py:1301-1304`). |
| V6 | CONTINUITY audit's "[Tóm tắt trước đó]" is earlier chapters' plan goals | **confirmed** (line shift) | `previous = " ".join(p.chapter_goal for p in story.plans[: chapter - 1])` at **`driver.py:1605`** (SBS: 1603). In a book part it is this part's goals only; the book's digests are not used. |
| V7 | Review repair receives only facts and an empty history (`driver.py ~1670`) | **confirmed** | `self._repair_once(scene_node, scene_epoch, scene_head["prose"], scene_findings, facts, [])` at **`driver.py:1669-1671`**; `facts` is the locked lines only (`:1604`). `span_repair` would render a context block and a history (`repair.py:303-311`), so the plumbing exists. Scene-level repairs do get the full rendered context and a running history (`driver.py:1536`). |
| V8 | "tối đa 3" in the prompt vs grammar 2 | **confirmed** | Prompt `prompts/planning.py:143`; grammar `PLAN_LIST_MAX = 2` (`prompts/schemas.py:124,348-349`). The unbound `ChapterPlan` still says 3 and 4 (`:130,132`), which only matters for stored data. |
| V9 | Beats sorted alphabetically (`narrative.py ~346`) | **confirmed, and the fix SBS proposed is not possible as stated** | `creative_constraints=sorted(set(scene.beats))` (`narrative.py:346`). The R2 contract itself sorts and de-duplicates this field (`r2/contracts/narrative_plan.py:35-36,256,292`), and it is part of the contract digest (`r2/narrative_context/compiler.py:127`). "Render beats in plan order" through the pack cannot work without changing the R2 contract; the fix is to stop rendering the pack's copy (F12). `set()` also drops a repeated beat. |
| V10 | Export title = `titles[0]` unchecked | **confirmed** (two sites) | `title = packaging.titles[0].title` at **`driver.py:2019`** (SBS: 2017) and the book title `self._title or packaged.titles[0].title` at **`driver.py:1094`**. The prompt's own rules are at **`prompts/packaging.py:24-25`** (SBS: 26-27). |
| V11 | An unresolved `NO_ENDING` is committed automatically | **confirmed** | Critic emits `NO_ENDING` as HARD_STRUCTURAL (`audits.py:491-503`); the final scene is rewritten once (`driver.py:1815-1820`); a second confirmed one is escalated to NARRATIVE_CRITICAL (`checks.py:61,64-75`); the authority accepts NARRATIVE_CRITICAL "as is" (`server/production_run/narrative_authority.py:145-174`). An *unconfirmed* `NO_ENDING` (the 9B judge reading its own ending) becomes NARRATIVE_CRITICAL directly (`audits.py:310-318`, `driver.py:1840-1857`). Docstring `server/production_run/story_adapter.py:7-8` is stale. |
| V12 | Production judge = the 9B writer | **confirmed** | The adapter calls `draft_brief` without `judge_provider_id/judge_model_id` (`server/production_run/story_adapter.py:298-310`); `draft_brief` then sets `judge_selection=None` (`service.py:245-247,338`); `StoryBrief.judge` falls back to the writer (`driver.py:240-242`). Every audit, confirmation and critic call is the writer judging itself. |
| V13 | Other AR citations (idea anchor 592, seed redraw 670, cast checks 98/136/187/284, decoding 200, think off, digest `time_place` not in memory block, anti-AI judge always stylistic) | **confirmed** | `driver.py:592,670,200`; `cast_checks.py:98,136,187,284`; `lib/text_backends/ollama.py:134`; `book.py:157,509-530`; `audits.py:209-216`. Shifted: plan precheck `driver.py:1248` (SBS 1246); deterministic fixes `:1505` (SBS 1503); review `:1589-1719`; manuscript review `:1781-1838`; packaging `:1859-1947`. |
| V14 | SH citations (genesis 17 steps, foundation review 80/100 and core conflict ≥15, voice_profile iron rule, style band, closing hook per scene, memo eight sections, audit_drift, self-count inflation 16–97 %, merged auditors, injected counts, retry caps 3) | **confirmed** | `src/shenbi/pipeline/genesis.py:58-82`; `skills/shenbi-foundation-review/SKILL.md:78-82,118-120,173-203`; `skills/shenbi-character-design/SKILL.md:59-62,143`; `src/shenbi/pipeline/style_seed.py:36-39`; `skills/shenbi-chapter-planning/SKILL.md:66-98,150-172`; `skills/shenbi-chapter-drafting/SKILL.md:110,113-125`; `src/shenbi/pipeline/chapter_loop.py:132-140`; `src/shenbi/pipeline/review_checklist.py:277-300`; `src/shenbi/pipeline/state.py:63-64`. |
| V15 | HUO citations (premise temp 0.78, drama fields, ten craft gates, beat weights, opening/ending rules, "never a fixed sentence count", thresholds 78/70, humanize 3×/39, title rules) | **confirmed**; title detail **partly right** | `ws/novel-writing.ts:147`; `ws/novel-outline-drama-fields.ts:24-60`; `ws/novel-chapter-craft-check.ts:29-84`; `ws/novel-chapter-beat-budget.ts:38-55`; `ws/novel-chapter-beat-generate.ts:164-217`; `agent-skills/novel_chapter_writer/SKILL.md:11`; `cn/novel-meta.ts:169-170,190,216,245-261`. The title rule is a separate one-line title call with an 8–16 character band (4–9 for epics) and a ban list of hollow literary words (`ws/novel-writing.ts:166-229`), plus a length floor in code (`:224-226`). |

Verdict: every FACT-level conclusion of SBS holds. Two need correcting for implementation: V3 (the grammar already
admits line breaks inside a block, which opens a cheaper F2) and V9 (beat order cannot be fixed through the pack).

## 3. What the first comparison got wrong or missed

1. **F2 was sized as "large" because it assumed a grammar change.** HUO solves the same problem in code: a
   deterministic re-paragrapher (`cn/novel-paragraph-format.ts:1-6,124-183,240-256,349-428`) splits walls into
   1–3 sentence paragraphs, gives dialogue its own paragraph, rotates sentence targets `[1,3,1,2,3,1]` so lengths
   do not come out uniform, and merges orphan fragments ≤12 characters. Applied to ArcReel's export
   (`render_markdown`, `driver.py:2249-2255`), it changes no grammar, no length control and no check. SH's opposite
   failure must be guarded too: models told to avoid monologue produce extreme micro-paragraphs (SH `02d3381`:
   "ch114 measured 190 paragraphs, median 6 characters").
2. **Beat order (V9)** cannot be restored through the contract; drop the pack's beat block.
3. **`NO_DIALOGUE` false positives (V4)**, a small real bug SBS mentioned only as "may".
4. **The manuscript critic's findings are never acted on.** Only `NO_ENDING` triggers anything
   (`driver.py:1815-1820`); every other critic issue is NARRATIVE_CRITICAL (`audits.py:209-216`) and is recorded,
   then accepted by the autopilot (`narrative_authority.py:145-174`). Likewise every chapter finding still open at
   the seal (`driver.py:1702-1717`). SBS F10 looked only at `NO_ENDING`.
5. **Same-model judging had no fix number.** SBS noted it as FACT but ranked nothing for it. With the writer
   confirming its own claims, `unconfirmed()` turns a real missing ending into an acceptable finding (V11). It is
   ranked below as F14.
6. **Scene budgets cannot be weighted as SBS F5 proposed** without changing the per-scene window: a 3-scene chapter
   already sits at the 1 000-syllable target ceiling (`prompts/drafting.py:196-199`, `checks.py:742-745`), so
   0.20/0.45/0.35 only shortens the set-up scene and the chapter. Duties are cheap; weights need a fixture.
7. **The voice block must stay out of the context pack.** The pack is recompiled at commit and its hash must match
   generation (`narrative.py:170-172`). F1 and F3 have to be prompt-side text like the book `memory` argument
   (`prompts/drafting.py:75,111-112`), never new pack segments.
8. **Generic retry notes.** `REGENERATE_NOTE` (`driver.py:170-173`) tells the writer "too short or copied" with no
   numbers. SH found generic retry feedback "nothing actionable across 3 attempts" and fixed it with measured values
   and a copyable template (`5b517c3`, `a16216e`, `32adb2c`).
9. **Humanize repairs can change facts.** SH's humanizer study added a six-way fact-conservation check for style
   rewrites (agent, time, condition, scope, negation, attribution, plus certainty: "guess" must not become "know")
   (`docs/superpowers/specs/2026-11-04-spec96-anti-ai-tell-alignment.md:86`). ArcReel's humanize repair uses the
   continuity patch prompt (`repair.py:202-210`), which has no such clause.

## 4. Build specs for F1–F13 (and F14)

Each spec: donor mechanism (FACT), ArcReel design, tests, cost, ship class.

### F1. The writer sees the story's voice — SAFE NOW, 0 calls

- **Donors.** SH always injects the style profile and the book spine into the drafting package
  (`src/shenbi/pipeline/context_assemble.py:1-14`), and the style target is a measurable band: narration 12–25
  characters per sentence, dialogue 4–12, "at least one ≥35-character surging sentence per scene followed within 3
  sentences by a ≤10-character short one", paragraphs averaging 2–4 sentences "alternating with one-line dialogue"
  (`src/shenbi/pipeline/style_seed.py:36-39`). `057425b` ("style_directives … mechanical injection proof") made
  injection testable. HUO puts its prose guide in the writer's system prompt every call (`ws/novel-writing.ts:1037-1052`)
  with "**文风优先** … 叙述与对话都要有人味" ("style first; narration and dialogue must sound human", `:1077`).
- **Design.**
  - `prompts/drafting.py`: new `voice_block(seed, style, bible) -> str`, ≤ 700 characters, each field clipped with
    `_opening(text, 140)`:

    ```
    [Giọng truyện — giữ suốt cảnh]
    - Ngôi kể: {seed.pov}. Không đổi ngôi kể; ngôi thứ ba thì lời kể không xưng "tôi".
    - Giọng điệu: {seed.tone}
    - Lối kể: {style.narration_style}
    - Nhịp câu: {style.sentence_rhythm}
    - Cảm xúc: {style.emotional_texture}
    - Lời thoại: {style.dialogue_style}
    - Tránh lối viết: {"; ".join(style.forbidden_style[:4])}
    [Không được mâu thuẫn]
    - {each of bible.forbidden_contradictions[:4]}
    ```
  - `scene_draft_prompt` gains `voice: str = ""`, rendered between "[Cảnh này]" and "[Quy tắc cứng]".
  - `driver.py` `_ensure_scene` (`:1331-1447`) builds it from `story.seed`, `story.style`, `story.bible`. Their heads
    (`seed_in`, `bible_in`, `style_in`) are already scene inputs (`:1295-1296`), so fingerprints stay exact and
    resume is unchanged. Not a pack segment (section 3 item 7).
  - Repairs: append the same block to the `context` passed to `_repair_once` for humanize targets (F8).
- **Schema.** None; all fields are required in stored bibles today.
- **Tests.** Prompt contains each field once; clipping keeps ≤ 700 characters; a book part uses the carried style
  (`driver.py:642-648`); `render_context` output and the pack hash are unchanged (regression on
  `compile_scene_context`).
- **Risk.** UNKNOWN whether a 9B model keeps beats when the prompt grows ~700 characters; measure on one real chapter
  (beats covered, MEMO findings) before and after.

### F2. Natural paragraphs and dialogue lines — re-paragraph in code (export SAFE NOW; scene heads FIXTURE FIRST), 0 calls

- **Donors.** HUO prompt rule: "叙述每段 1～3 句（单段硬上限 3 句）… 对话/惊觉/拟声可 1 句成段 … 严禁一句一段的诗化；也严禁一段塞 4 句以上"
  ("narration 1–3 sentences per paragraph, hard cap 3; dialogue, a jolt or an onomatopoeia may stand alone; never
  one-sentence-per-paragraph poetry, never 4+ sentences", `workbench-server/src/agents/webnovel-prose-style.ts:95-97`),
  and HUO enforces it in code after generation (`cn/novel-paragraph-format.ts`, called from
  `ws/novel-prose-polish.ts:55-57`): quote-aware sentence split (`:40-64`); `splitWallIntoParagraphs` flushes a
  paragraph on sentence targets rotating `[1,3,1,2,3,1]` and character targets `[52,200,60,120,220,48]`
  (`:131-183`), flushes before a dialogue sentence once 40 characters are buffered (`:165-167`), never inside an
  open quote (`:174-176`); if paragraph-length CV < 0.5, alternates short/long (`:196-238`); orphan paragraphs ≤12
  characters merge into the next (`:258-372`). SH counter-evidence: `02d3381` adds a paragraph floor because "two
  consecutive chapters burned 3 gate attempts each … extreme micro-paragraphing (median 6-7 chars/para) driven by
  over-executing the anti-monologue directive"; dialogue paragraphs are "quote + attribution + action beat".
- **Design.**
  - New `layout.py` (pure): `natural_paragraphs(text: str) -> str`. Vietnamese sentence split on `.!?…` followed by
    space and an upper-case letter, a dash or an opening quote, never inside “…” or `\"…\"`; a sentence that holds a
    quote or starts with `—`/`–` is a dialogue sentence; narration paragraphs take 1–3 sentences on the rotating
    targets; a dialogue sentence starts a new paragraph and keeps its attribution and one action sentence with it
    (SH's "quote + attribution + action beat"); orphans ≤ 3 syllables merge forward; a scene's first and last
    sentence never move across scene boundaries.
  - Apply first in `render_markdown` (`driver.py:2249-2255`) to each scene. The export is a manifest-bound blob
    (`driver.py:2022-2028`) and the hand-off reads only it (`handoff.py:3-6,142`), so checks, quotes, repairs and the
    commit's revisions are untouched.
  - Prompt (`prompts/drafting.py:174,182-183`): "Mỗi phần tử của mảng là một khối văn bản" and replace "mỗi đoạn 3–5
    câu" by "mỗi khối 3–6 câu; lời thoại đặt trong ngoặc kép “…” kèm người nói, mỗi lượt lời một câu riêng". The
    grammar stays as is (commit `32209195c` keeps length bounded).
  - Later, after a fixture: apply at the scene head too, then re-check `UNIFORM_PARAGRAPHS` (`audits.py:583-591`),
    `gender_findings` (paragraph split `cast_checks.py:58`) and `NEAR_DUPLICATE`.
- **Tests.** Golden Vietnamese samples: a wall with two quoted exchanges becomes narration/dialogue paragraphs; a
  quote with internal `.` is not split; no paragraph has more than 3 narration sentences; orphan merge; no text lost
  (`"".join(split()) ` before = after); idempotent; length CV of output ≥ 0.3 on a uniform input.
- **Risk.** UNKNOWN how the 9B writer currently lays out dialogue (no stored real prose was found in the worktree).
  Export-only application is reversible and needs no fixture; widen it with one.

### F3. What happened so far, and what went wrong, carried forward — 0-call part SAFE NOW; digest part +3 calls, SAFE NOW

- **Donors.** SH short stories keep "the last 2–3 chapter summaries + story bible + character cards" in the window
  (`skills/shenbi-short-drafting/SKILL.md:78-82`); the drafter restates "AI-voice to guard against, from the recent
  audit_drift" before writing (`skills/shenbi-chapter-drafting/SKILL.md:122`). HUO's next chapter sees an end
  snapshot (time, place, last event) and the previous state card (`ws/novel-writing.ts:903-912,986-1001`).
- **Design.**
  1. **Short-story digests (+3 calls).** Reuse the book digest: `prompts/book.py:141-160` `chapter_digest_prompt`
     with `hooks=[]`, and `_chapter_digest` (`driver.py:950-974`) after each chapter's final review
     (`driver.py:1300-1302`) for short stories too. Render a "[Đã xảy ra ở các chương trước]" block of each earlier
     digest's `summary` and `time_place` plus the last digest's character states, passed as `memory` to
     `render_context` (the book path already does this, `driver.py:1352-1370,1385`). Add the digests to the scene's
     inputs as the book path does (`:1356-1362`) so resume stays exact. Bound: `run_call_bound` adds
     `chapters * NODE_CAPS["chapter_digest"]` for short stories (`driver.py:2120-2124`).
  2. **0-call fallback** if (1) is rejected: the block from earlier plans' `chapter_goal` and
     `required_changes_by_end`, each change marked unverified when an open `MEMO_COMPLIANCE:` finding in that
     chapter's `chapter_review[c]` record names it.
  3. **"[Cần tránh]"** (0 calls): from earlier `chapter_review[c]` records, the 3 most frequent finding codes with one
     quote each, ≤ 300 characters. Add those review heads to the scene inputs.
  4. **CONTINUITY audit**: `previous` (`driver.py:1605`) becomes the digests' summaries (book and short story), or
     (2) as fallback.
  5. **Book**: add the last digest's `time_place` to `memory_block` (`book.py:509-530`).
- **Tests.** Short story: scene of chapter 2 contains chapter 1's digest summary; resume with unchanged heads makes
  no call; replanning chapter 1 re-digests it; CONTINUITY prompt contains the summary; `memory_block` shows
  `time_place`.
- **Cost.** +3 calls (~4.7 min) per short story, +1 per replanned chapter. Quality-first argument: it is the only
  route to "what was written" for both the writer and the continuity judge.

### F4. Drama fields and a declared closing hook — prompt/schema SAFE NOW; the check FIXTURE FIRST

- **Donors.** HUO outline rows carry 13 fields, among them 欲望/阻碍/人物选择/章末问题 (desire, obstacle, choice,
  ending question) (`ws/novel-outline-drama-fields.ts:24-60`), and the craft judge rates each on the page as
  有/弱/无 with an excerpt (`ws/novel-chapter-craft-check.ts:29-56,109-131`). SH's memo "key choice through Why /
  Interest / Persona" (`skills/shenbi-chapter-planning/SKILL.md:165`) and a required "章尾张力拍: 未答之问／未说破之瞒／未合拢之缝 + 具体指向对象"
  ("closing tension beat: an unanswered question / an unspoken concealment / an unclosed gap, plus the concrete
  person or thing it points at", `:333-335`). The scene budget carries a **verbatim closing-hook sentence** that
  "drafting writes verbatim as the scene's last line; G4 matches it exactly — write the final sentence, not a
  summary" (`:66-73,98`). The gate: last 8 paragraphs merged, ≥30 characters, and a `?`, a tension word or two
  digit runs (`src/shenbi/gates/g4/chapter_drafting.py:982-1060`). Motivating runs: `90f9602` ("no_hook … ch60 3x
  retries … drafting varied the closing style and dropped the hard marker"; fix: the planner declares the closing
  beat upstream), `5b517c3` (per-paragraph floor missed real hooks of 24–29 characters; windowed), `8f3da91`
  (concealment words count as tension).
- **Design.**
  - `prompts/schemas.py`: `OutlineChapter` gains `obstacle`, `choice`, `ending_question: str | None = None`;
    `bound_short_outline` and the book row grammar require them (`create_model` override, as `gender` in
    `bound_seed`). `ChapterPlan` gains `closing_hook: str | None = Field(default=None, max_length=200)`;
    `bound_chapter_plan(..., needs_hook=True)` requires it. Stored data stays readable (defaults `None`).
  - `prompts/outline.py` rule lines: "- obstacle: điều cụ thể cản nhân vật chính trong chương; choice: quyết định
    nhân vật chính tự đưa ra (vì sao, được gì, đúng tính cách ra sao); ending_question: câu hỏi cụ thể người đọc
    mang sang chương sau."
  - `prompts/planning.py` (memo part): "- closing_hook: MỘT câu văn hoàn chỉnh sẽ là câu cuối của chương: một câu
    hỏi chưa có lời đáp, một bí mật chưa nói ra, hoặc một nguy cơ sắp tới, chỉ đích danh người hay vật. Chương cuối
    truyện: câu khép lại hình ảnh cuối." The plan prompt shows the outline chapter's `obstacle/choice/ending_question`.
  - `prompts/drafting.py` duty for the last scene: "Câu cuối cùng của cảnh là: “{closing_hook}” (có thể đổi vài chữ
    cho liền mạch, không đổi ý)."
  - `audits.py` `_memo_block` adds `closing_hook`; the MEMO instruction adds "câu móc cuối chương không xuất hiện".
  - `craft_checks.py` `closing_hook_findings(plan, last_scene)`: pass if the normalized hook occurs in the last two
    paragraphs, or content-word Jaccard ≥ τ (start 0.5, calibrate); otherwise `CLOSING_HOOK` STYLISTIC quoting the
    last sentence. Add a tension-window variant later (Vietnamese words: "?", "chưa", "vẫn chưa", "không biết",
    "giấu", "bí mật", "nợ", "hạn", "ai đó") — only after measuring false positives on real chapters.
- **Tests.** Old plan JSON without `closing_hook` validates; bound grammar requires it; prompt renders it; check
  passes on exact and near text and fires on a missing one.
- **Cost.** 0 calls. ~1 day. Ship the planning/prompt part now; keep the check stylistic until a fixture sets τ.

### F5. Position duties now; weighted scene budgets later — duties SAFE NOW, weights FIXTURE FIRST

- **Donors.** HUO chapter 1: "首句即压力方对白或拍桌/踹门类动作；环境最多一句锚 … 约前300字内必须出现压力方对白或动作"
  ("first sentence is the pressure side's dialogue or a slam/kick action; at most one sentence of setting; within
  ~300 characters the pressure's dialogue or action must appear"); later chapters: "先轻锚承接上章已发生事实 …
  承接后立刻进入本拍冲突或对白 … 禁止照抄上章末特色词组" ("first a light anchor to what last chapter left, then
  straight into conflict or dialogue; never copy last chapter's closing phrases"); last beat: "停在急/盼钩；章尾禁…温情泄压…纯感慨收束"
  ("stop on an urgent or longing hook; no warm release or pure reflection at the end") (`ws/novel-chapter-beat-generate.ts:164-217`).
  Beat weights 2: [.4,.6]; 3: [.20,.45,.35]; 4: [.15,.25,.40,.20]; 5: [.12,.18,.35,.22,.13]
  (`ws/novel-chapter-beat-budget.ts:40-55`).
- **Design (duties).** `scene_draft_prompt` (`prompts/drafting.py:159-172`) gains `chapter_first: bool`,
  `story_first: bool`:
  - story's first scene: "Đoạn đầu tiên mở bằng một lời thoại hoặc một hành động va chạm; tả cảnh tối đa một câu;
    không mở bằng giới thiệu hoàn cảnh hay hồi tưởng."
  - first scene of a later chapter: "Câu đầu nối ngay sau điều vừa xảy ra cuối chương trước (nói rõ thời gian đã trôi
    nếu có), không kể lại; câu thứ hai vào xung đột hoặc lời thoại."
  - last scene of a non-final chapter (replaces `:163-164`): "Dừng ở một câu hỏi chưa có lời đáp hoặc một nguy cơ sắp
    tới; không kết bằng cảm xúc lắng xuống, không tổng kết, không suy ngẫm." (with F4: the closing-hook line).
- **Design (weights).** Not with the current window: 3 scenes × 1 000 is already the per-chapter target. Needs a
  per-scene `SceneLengthWindow` (target ± 40 %) and a water-filling split that keeps the chapter sum; measure length
  findings on a fixture first.
- **Tests.** Each duty appears only at its position; no duty text leaks into prose (`META_LEAK` covers labels in
  brackets; HUO saw task labels leak, `cn/novel-emotion-beat-meta-strip.ts:1-4`, so duties are written as plain
  sentences, never as tags).

### F6. Each character has a voice and a flaw — SAFE NOW, 0 calls

- **Donors.** SH: "铁律 — voice_profile 必填: 每个主要角色必须有说话风格指纹（speech_patterns, catchphrases,
  avoid_patterns）。没有声音指纹的配角说话都一个味" ("every major character must have a speech fingerprint; without
  one, supporting characters all sound the same", `skills/shenbi-character-design/SKILL.md:143`); foundation review
  scores "voice distinctness (≥3 main characters blind-distinguishable)", "independent motives", "real flaws that
  affect decisions" (`skills/shenbi-foundation-review/SKILL.md:198-203`). SH `a16216e`: catchphrase scoring is an
  exact substring, and "the live miss was a catchphrase one character off the card" — so do not score catchphrases
  in code for a 9B writer.
- **Design.** `SeedCharacter` (`prompts/schemas.py:222-242`) gains `voice: str | None = Field(None, max_length=120)`
  and `flaw: str | None = Field(None, max_length=120)`; `book.bound_seed` requires both for generated seeds (as
  `gender`); seed prompt (`prompts/planning.py:54-58`) adds: "voice: cách nhân vật nói (câu ngắn hay dài, từ hay
  dùng, cách xưng hô), tối đa 20 chữ; flaw: một tật xấu hoặc điểm yếu thật, ảnh hưởng tới quyết định của họ, tối đa
  20 chữ." `locked_line` appends "Cách nói: {voice}. Điểm yếu: {flaw}." only when present, so old seeds render
  byte-identical (the bible input and canon stay stable for resumed runs). Volume `new_characters` gets the same.
- **Tests.** Old seed JSON validates and `locked_line` is unchanged; new grammar requires both; CHARACTER audit
  facts contain the voice.
- **Cost.** 0 calls; ~30 more output tokens on the seed.

### F7. Foundation check on the seed — deterministic SAFE NOW; judged review later (+1, +1 on failure)

- **Donors.** SH foundation review: total ≥ 80/100, core conflict < 15/25 fails outright; core-conflict items:
  "冲突清晰度（对抗双方+赌注明确）8 / 冲突推动力（冲突驱动主角行动而非被动卷入）7 / 私人关联 6 / 三级递进 4"
  ("two sides and stakes clear / the conflict drives the protagonist's action rather than sweeping them along /
  personal stake / three layers", `skills/shenbi-foundation-review/SKILL.md:78-82,173-180`). SH `19f192e`:
  "seed structural validation … reports every problem at once" before the pipeline starts.
- **Design.** `cast_checks.py` `seed_problems(seed) -> list[str]`: exactly one character whose
  `relation_to_protagonist` says "chính là nhân vật chính" (the prompt's own phrase, `prompts/planning.py:55`);
  `central_conflict` and `ending_direction` content-word Jaccard < 0.8 against `premise`; with F6 every character
  has `voice` and `flaw` and no two voices have Jaccard ≥ 0.6. Problems trigger the existing one-time seed redraw
  path (`driver.py:670-681`), merged with missing idea names. The judged review (Vietnamese version of the four
  core-conflict items plus "các nhân vật có giọng và mục tiêu riêng") waits for F14: a writer judging its own seed
  adds little (INFER).
- **Tests.** Each problem fires on a constructed seed; a good seed passes; redraw happens once.
- **Cost.** 0 calls, +1 when the seed fails.

### F8. Review-driven repair sees the scene's plan and keeps earlier fixes — SAFE NOW, 0 calls

- **Donors.** SH `0cdc218`: "single-round feedback makes the model drop constraints round by round (planning failed
  3 times, drafting 4 times in a row)"; fix: the current round's items in full plus a "防回退令" (anti-regression
  order) section listing every family named in earlier rounds (latest message per family); "the 4th dispatch passed
  first try". SH `3900bb8` T4: repair feedback in three parts: the dropped lines verbatim, the base instruction,
  a minimal positive example; and the length repair is "scene-granular … no whole-chapter rewrite".
- **Design.**
  - `driver.py:1669-1671`: replace `facts` by `repair_context(story, chapter, scene)`: the locked facts, then
    "[Cảnh này]" (summary, beats in plan order, emotional turn from `story.plans`), the chapter's withheld cards and
    do-not items, the scene's required changes if it is the last scene, and F1's voice block.
  - Persist kept fixes in the scene head: `{**scene_head, "prose": repaired, "fixed": [...]}` (`driver.py:1674-1676`),
    each entry `"{code}: “{quote[:80]}”"`; readers only use `h["prose"]`, so extra keys are backward compatible.
  - `repair.py` `span_repair` gains `kept_fixed: Sequence[str] = ()`, rendered "[Đã sửa ở vòng trước — giữ nguyên,
    không làm hỏng lại]"; the existing "[Các lần sửa trước chưa đạt]" stays for failed attempts.
  - `_no_worse` (`driver.py:1721-1729`) also rejects a repair that re-introduces a quote listed in `fixed`.
- **Tests.** Review repair prompt contains the beats; a second cycle's prompt lists the first cycle's fix; a patch
  that restores a fixed quote is rejected; old heads without `fixed` work.

### F9. A title that passes the prompt's own rules — SAFE NOW, +1 call only when all fail

- **Donors.** HUO bans "文艺空洞：云与梦、时光、岁月、彼岸、无题、随笔 … 只有抽象词或成语堆砌，看不出故事卖点"
  ("hollow literary words … only abstract words or idioms, no visible selling point"), one line only, length floor
  in code (`ws/novel-writing.ts:186-193,224-226`).
- **Design.** `prompts/packaging.py` `title_problems(title, cast_names) -> list[str]`: 2–6 syllables
  (`checks.count_syllables`), every token `checks.is_vietnamese_syllable` or a cast name, no syllable repeated
  (casefold), not only a character name, not made only of words in a short hollow list ("thời gian", "năm tháng",
  "kỷ niệm", "giấc mơ", "bến bờ", "vô đề", "tâm tư"). `_packaging` (`driver.py:1875-1891`): the second draw also
  happens when no title passes, with the problems appended; titles sorted passing-first; export and book title
  (`driver.py:1094,2019`) take the first passing one, else `working_title`.
- **Tests.** Each rule; packaging with only bad titles redraws once; export uses a passing title.

### F10. A floor on what autopilot publishes — F10a SAFE NOW (inside the driver); F10b needs an ADR and a sponsor decision

- **Donors.** SH closure ends at a Human checkpoint (`src/shenbi/pipeline/closure.py:1-12`); retries are capped at
  3 then escalate (`state.py:63-64`). No donor auto-publishes an unresolved ending.
- **Design.**
  - **F10a (driver):** when `NO_ENDING` is still confirmed after the `ENDING_NOTE` rewrite (`driver.py:1815-1821`),
    replan the last chapter once (`add_intent` on `chapter_plan(last)` with the critic's quote and
    `story.outline.ending`, then `_Restart(plan_node)`, as the MEMO replans at `driver.py:1684-1700`). Count it with
    a new `ENDING_REPLANS = 1` in `run_call_bound` (one chapter's plans, scenes and reviews).
  - **F10b (authority):** `narrative_authority._recorded_findings` (`:150-174`) refuses automatic approval when the
    quality record holds an escalated `NO_ENDING`, a hard `STORY_LENGTH`, or a confirmed blocking-at-birth MEMO
    finding of the last chapter. For a no-Human product this means the story waits; whether that is acceptable is a
    product decision (publish unresolved vs wait), so it needs the sponsor and an ADR.
- **Cost.** F10a: when it fires, ~one chapter (~40–50 calls, ~1–1.3 h). F10b: 0 calls.

### F11. Merge the anti-AI judge into the craft judge with injected counts — FIXTURE FIRST (A/B)

- **Donors.** SH merged seven serial auditors into domain groups (`chapter_loop.py:136-137`) and precomputes
  deterministic anti-AI values into the checklist so the judge reads numbers instead of counting
  (`review_checklist.py:277-300`); `1d35be2`: count on the narrative body only, otherwise the self-check's own
  banned-word list produced "4 BLOCKING marker hits that existed only in the META block".
- **Design.** `audits.py`: CRAFT instruction gets a "[Số đo máy]" block (stock phrases, not-but, paragraph CV,
  genre fatigue counts from `anti_ai_findings`/`fatigue_findings`, computed on prose only); drop `ANTI_AI` from
  `CHAPTER_DIMENSIONS`; keep `humanize_targets` on deterministic codes. Saves 1 call per chapter cycle (3–9 per short
  story). A/B on two real stories: count of quoted voice findings and humanize repairs per chapter.

### F12. Remove self-contradicting instructions — SAFE NOW, hours

- `prompts/planning.py:143`: render the number from `PLAN_LIST_MAX` ("tối đa {PLAN_LIST_MAX} mục") so prompt and
  grammar cannot drift again (SH `3900bb8` T1: "enum constants single-sourced … gate/lint/context consumers read one
  base").
- `prompts/drafting.py:98-101`: drop the "[Nhịp bắt buộc]" block (the beats are already in plan order at `:178`);
  the pack keeps them for the contract (V9).
- `server/production_run/story_adapter.py:7-8`: say what `_recorded_findings` accepts.
- Tests: prompt shows "2"; rendered context has no sorted beat block; prompt keeps plan order including duplicates.

### F13. Carry-over invariants — FIXTURE FIRST, 0 calls each

Order by false-positive risk, lowest first. All start STYLISTIC (recorded), promoted only after a real-run fixture
shows no false positive (SH `c586cb3` "false-positive deadlock"; FM row 13).

1. **POV person.** SH derives POV from narration with dialogue stripped; 我 vs 他/她 counts, "我" if first > 2×third
   (`src/shenbi/gates/g4/cross_chapter.py:239-255`); `f10cd69`: "a side character's 我-heavy lines flipped a
   third-person chapter to mixed" until quotes were stripped. ArcReel: reuse `cast_checks._narration`
   (`cast_checks.py:32-34`, already strips dash lines and quotes); count standalone "tôi" in narration per scene;
   seed `pov` containing "thứ ba" and ≥ 3 narration "tôi" → `POV_PERSON`; "thứ nhất" and 0 "tôi" in a scene of ≥ 600
   syllables → `POV_PERSON`.
2. **Next-chapter leak.** HUO `next_chapter_beat_leak` (FM row 10). ArcReel: content-word overlap of the next outline
   chapter's `turning_point` with the current chapter's last scene ≥ τ → stylistic.
3. **Age.** HUO stable cast facts (FM row 7). `SeedCharacter.age: int | None = None`; "N tuổi" within the sentence
   naming the character, ±1.
4. **Life status.** `CharacterNow.status: Literal["sống", "đã mất", "mất tích"] | None = None` in book digests;
   plan-time: a dead character in a scene's `characters` must be marked as memory.
5. **Time anchor.** SH monotonic anchors (`cross_chapter.py:813-828`) produced four false-positive fixes from count
   words read as dates (`4fa6092`, `0905b4e`, `0cdc218`(c) "加护卫二十三；" read as day 23, `6eb94b5`(a) "第二十三根"
   read as day 23). For Vietnamese, only explicit forms ("ngày mùng …", "ngày … tháng …", "sáng hôm sau") count;
   a number followed by a counter word (người, cái, con, đồng, lần, năm tuổi) never does.

### F14 (new). An independent judge route — needs a route decision and a measurement

- **Fact.** Production reviews are the writer judging itself (V12). HUO warns against same-family judging
  (inventory B3); SH requires an independent agent for every scoring skill (`skills/shenbi-foundation-review/SKILL.md:80`).
- **Design.** The brief already supports `judge_selection` (`driver.py:225,240-242`; `service.py:225-247`). The
  adapter passes the project's judge route when one is configured. Options: a cloud judge (when cloud is allowed),
  or a second local model of another family. UNKNOWN: Ollama model-swap time on the GPU per judge call; measure
  before choosing the local option.

## 5. Fixes mined from donor history (not covered by F1–F14 or ADR-0125–0127)

"Same weakness?" cites ArcReel at `99934cb6d`. H-rows are new guards.

| # | Donor failure (FACT) | Donor fix (FACT) | ArcReel same weakness? | Recommended guard | Class |
|---|---|---|---|---|---|
| H1 | SH `5b517c3`(2), `32adb2c`: retry feedback was "the generic fallback string — nothing actionable across 3 attempts" | Failure message carries measured values (window char count + excerpt) and a rewrite direction | Yes: `REGENERATE_NOTE` has no numbers (`driver.py:170-173`) | Put the measured syllables, the target and the paragraph count into the note ("bản trước {n} chữ, cần khoảng {target} chữ, đúng {k} đoạn") | SAFE NOW |
| H2 | SH `a16216e`: repeated failures because messages did not show legal values; "inline the legal values, a copyable template and a live example" | Verbatim templates in gate messages | Partly: plan replan notes quote findings (`driver.py:1692`); MEMO scene notes quote (`:1654-1658`) | For MEMO rewrite notes, add the plan's exact `required_changes_by_end` item the scene must reach | SAFE NOW |
| H3 | SH spec #96 (`9c61842`): style rewrites dropped claims; "打破段落等长 / 打破句式规律 / 整段自然重述 … 最易丢 claim" | Six-dimension fact conservation for any humanize rewrite: agent, time, condition, scope, negation, attribution, plus certainty | Yes: humanize uses the continuity patch prompt (`repair.py:202-210`; `driver.py:2201-2216`) | Add to `PATCH_SYSTEM`: "Không đổi ai làm, khi nào, điều kiện, phạm vi, phủ định, lời của ai; điều nhân vật đoán không được thành điều họ biết." | SAFE NOW |
| H4 | SH spec #96 §0.4: tells adopted from a generic list misfired; "repeated sentence openings: 62 hits, mostly the legitimate follow-shot form → revoked" | Measure every candidate tell on the real corpus before adopting | Risk: `opening_findings`, `REPETITION`, `STOCK_PHRASES` were set without a Vietnamese corpus measurement (`craft_checks.py:75-117`, `audits.py:559-561`) | Before adding H5/H6, count them on ≥ 3 real stories; record the hit rate in the test fixture | process |
| H5 | SH drafting rule "转折词密度 ≤ 1/3000字 — 然/不过/此时/突然/终于/于是" (`skills/shenbi-chapter-drafting/SKILL.md:109`); `5fdc333` transition-word gate | Deterministic count, injected into the craft judge | Yes: no transition-word guard; "bỗng nhiên/đột nhiên" absent from every list (grep of `server/story_authoring`) | `TRANSITION_DENSITY` stylistic: "bỗng nhiên, đột nhiên, bỗng, chợt, lúc này, thế là, cuối cùng" > 1 per ~700 syllables per scene; joins `HUMANIZE_CODES` | FIXTURE FIRST (H4) |
| H6 | SH spec #77 (`6859ad4`): question-mark density in dialogue too high across chapter windows ("ch1-2/ch5-6 consecutive WARN, true positives") | WARN on a 3-chapter window | UNKNOWN for the 9B writer | Measure; if high, a stylistic `QUESTION_DENSITY` | FIXTURE FIRST |
| H7 | SH `02d3381`: over-executed anti-monologue rule → "190 paragraphs, median 6 chars" | A paragraph floor: any 8 consecutive paragraphs ≥100 chars with ≥4 carrying dialogue or action | Not today (280-char floor); becomes a risk with F2 | `natural_paragraphs` merges orphans and never emits more than 2 consecutive one-sentence narration paragraphs | built into F2 |
| H8 | SH spec #82 (`21fa61c`), `_spec82_hook_rotation` (`chapter_drafting.py:500-545`): same chapter-ending type two chapters running; same closing archetype three in a row | Seven hook types, "连续两章不得同型" (no two consecutive chapters of one type) | Yes for books: endings are not compared (only openings, `craft_checks.py:75`) | With F4: a `hook_type` enum on the plan (câu hỏi / nguy cơ / bí mật / đảo chiều / cảm xúc) and a stylistic finding when two consecutive chapters repeat it | book: SAFE NOW as prompt; check FIXTURE FIRST |
| H9 | SH `a4b0bbf`: chapters without a declared payoff read flat; emotion tone monotone across chapters | Plan declares `emotion_tone` (悲/喜/怒/惧/平) and a payoff beat ("none + reason" legal) | Yes: plan has `emotional_turn` per scene, no chapter payoff | With F4: optional `payoff` ("người đọc được gì ở chương này") on outline rows; a stylistic monotone-tone check for books | SAFE NOW (prompt) |
| H10 | HUO `f104b85` `cn/novel-deadline-day-lock.ts:1-4`: a deadline stated as N days is restated with another number later | Lock to the first stated value unless an explicit change word | Yes, unguarded; model CONTINUITY only (`audits.py:121-126`) | Deterministic: "N ngày/N tháng" deadlines tied to the same noun ("hạn", "thời hạn") must agree within a chapter unless "gia hạn/rút ngắn" appears; stylistic | FIXTURE FIRST |
| H11 | HUO `cn/novel-kinship-address-strip.ts:1-4`: outsiders/antagonists in dialogue address family members with in-family kin terms | Rewrite in-quote kin terms when an outsider speaks | Partly: narration address is locked per character (ADR-0126); dialogue address is model-judged (`audits.py:125`) | Add to the CHARACTER audit instruction: "người ngoài gọi nhân vật bằng từ xưng hô chỉ người trong nhà dùng"; no code check (Vietnamese xưng hô is relational) | SAFE NOW (prompt) |
| H12 | HUO `cn/novel-replacement-char.ts:1-4`: U+FFFD in prose from gateways | Dictionary fix + short model repair | UNKNOWN: local Ollama emits valid UTF-8; `foreign_words` may not flag U+FFFD (`checks.py:203`) | Add U+FFFD to the integrity check as HARD_INTEGRITY (cheap, no false positives) | SAFE NOW |
| H13 | HUO `ws/novel-stakes-restatement.ts:1-6`: the same amount + deadline + evidence cluster repeated within a chapter | Strip later restatements | Partly: `NEAR_DUPLICATE`, `CROSS_SCENE_REPLAY`, trigram `REPETITION` (`checks.py:822-835`) catch verbatim, not paraphrased restatement | Leave to CRAFT judge; measure first | FIXTURE FIRST |
| H14 | SH `1d35be2`: counters run on bytes that include self-check text | Count on the narrative body only | No: ArcReel prose has no meta block; counts run on prose | none | — |
| H15 | SH `a2ca684`, `8ac5881`, capacity-wall fixes | Thinking off for evaluators; resend once on empty content | Covered (`lib/text_backends/ollama.py:134`; RETRYABLE `driver.py:187-195`) | none | — |
| H16 | SH `ed6bad8`: a 3-character floor killed real 2-character names | Exempt short real names | Yes: `near_name` skips names under 3 letters (`checks.py:704-707`), so "An", "Ba" are never repaired | Allow 2-letter names when the allowed set has exactly one candidate within one letter | FIXTURE FIRST |
| H17 | SH `5716a19`: genesis artifacts produced "three contradictory chronologies" | Every world artifact reads the volume map and is checked against chapter numbers | Partly: bible `forbidden_contradictions` exist but nobody reads them (V1) | F1 carries them to the writer; add them to the CONTINUITY audit's facts | SAFE NOW (with F1) |
| H18 | SH `5fdc333` T4: retries oscillate between full rewrites | "streak_monitor_rewinds durable counter + targeted-edit mode switch" | Covered: scene repairs are span patches inside a cap with best-version fallback (`driver.py:1497-1542`) | none | — |
| H19 | SH `2f5b18c`: regeneration lost content | `verify_preservation` retention check | Partly: `_no_worse` compares findings only (`driver.py:1721-1729`); compression floor 0.7 (`repair.py:53`) | With F8, also reject a review repair that removes a beat's content words entirely | FIXTURE FIRST |
| H20 | SH `0cdc218`(b), `6eb94b5`(a): count words misread as entities or dates | Exclude numeral + counter-word forms | Relevant to F13.5 and H10 | Encode the counter-word exclusion from day one | design rule |

History coverage note: SH's 2026-09-28 → 2026-11-09 commits are mostly pipeline, truth-file and dispatch plumbing for
a 1 400-chapter novel; they were read for the failure they name and skipped when the failure was infrastructure only.
HUO has no history beyond the commit file lists; `f104b85` is the only commit whose modules name concrete prose
failures (H10–H13).

## 6. Re-ranked plan (old and new), by product-quality gain per cost for a 9B local writer

Gain is INFER; cost is engineering time plus model calls. "Safe" means shippable without a real-run fixture.

| Rank | Fix | Gain (why) | Cost | Ship |
|---|---|---|---|---|
| 1 | **F12** prompt/grammar alignment, drop sorted beat block, stale docstring | removes two contradictions the writer sees on every plan and scene | hours, 0 calls | SAFE NOW |
| 2 | **F1** voice block to writer and humanize repair (+H17) | tone, POV person and dialogue style stop resting on 9B defaults; three planning calls stop being wasted | <1 day, 0 calls | SAFE NOW (measure beat coverage once) |
| 3 | **F8** review repair with scene plan, voice and kept fixes | stops repairs breaking beats and oscillating (SH `0cdc218`) | <1 day, 0 calls | SAFE NOW |
| 4 | **F3** short-story digests + "[Cần tránh]" + CONTINUITY sees what was written; book `time_place` | the only source of "what happened" for writer and continuity judge | 1 day, +3 calls (~5 min) | SAFE NOW |
| 5 | **F2** natural paragraphs at export (+H7) | the most visible reading-quality defect; dialogue lines | 1 day, 0 calls | SAFE NOW at export; scene heads after a fixture |
| 6 | **F5 duties** (opening conflict, seam, open-question ending) | openings and chapter pull, cited by both donors | hours, 0 calls | SAFE NOW |
| 7 | **F4** drama fields + `closing_hook` in plan and duty (+H8 hook type, +H9 payoff as prompt) | concrete choices and a declared hook instead of "end on a hook" | ~1 day, 0 calls | prompt/schema SAFE NOW; hook check FIXTURE FIRST |
| 8 | **F6** voice and flaw per character | distinct voices; CHARACTER audit gets a reference | hours, 0 calls | SAFE NOW |
| 9 | **H1, H2, H3, H11, H12, V4 fix** (actionable retry notes, MEMO notes with exact item, humanize fact conservation, outsider address in CHARACTER audit, U+FFFD, inline dialogue count) | fewer wasted retries, fewer meaning changes, fewer false `NO_DIALOGUE` | hours each, 0 calls | SAFE NOW |
| 10 | **F9** title filter | the published title obeys its rules | hours, +1 call only on failure | SAFE NOW |
| 11 | **F10a** last-chapter replan when the ending stays unresolved | avoids publishing an unresolved ending | <1 day; ~45 calls only when it fires | SAFE NOW (deterministic trigger already exists) |
| 12 | **F7** deterministic seed problems | catches weak seeds before 300+ calls | hours, +1 on failure | SAFE NOW; judged part after F14 |
| 13 | **F14** independent judge route | every review today is self-judged; confirmation is weakest where it matters (endings) | config + measurement | needs route decision and swap-time measurement |
| 14 | **F11** merge anti-AI into craft | saves 3–9 calls per story | <1 day | FIXTURE FIRST (A/B) |
| 15 | **F13.1** POV person, then **F13.2** next-chapter leak | rare but ruinous drifts | <1 day each | FIXTURE FIRST |
| 16 | **H5, H6, H10, H13, H16, H19** (transition density, question density, deadline lock, restated stakes, short names, beat retention) | prose polish and small continuity | hours each | FIXTURE FIRST (measure per H4) |
| 17 | **F5 weights** | turn scene gets room | 1 day; needs per-scene windows | FIXTURE FIRST |
| 18 | **F13.3–5** age, life status, time anchors | book-scale continuity | 1 day each | FIXTURE FIRST |
| 19 | **F10b** authority floor | no unresolved story published without a person | ADR | sponsor decision |

Fixtures to collect first (one real 3-chapter story and one book part from the next run, read by the main agent from
the run state): the scenes' raw prose (F2, H5, H6, H16), the plans and final reviews (F4 τ, F13.2), and the
manuscript review record (F10a, F14).

## 7. Facts, inferences, unknowns

- **FACT** (cited above): V1–V15; the export is the only hand-off input; the beat order is sorted by the R2 contract;
  the pattern admits `\n`; critic issues other than `NO_ENDING` are never repaired; production reviews are
  self-judged; every donor mechanism quoted in sections 4–5.
- **INFER**: the gain ranking; that a 9B writer follows a ~700-character voice block; that export-side
  re-paragraphing reads better to Vietnamese readers; that a self-judged seed review adds little.
- **UNKNOWN**: how the current 9B prose lays out dialogue (no real prose was available to this research); hit rates
  of H5/H6/H10 in Vietnamese; how often `NO_ENDING` survives the rewrite in production; local model-swap time for a
  second judge.
