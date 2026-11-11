# Donor failure modes the story engine still lacks a guard for

Date 2026-11-11. Research only; nothing here is decided. Trigger: on today's production run (local writer
`qwen3.5-vimax:9b`, about 93 s per call) the male protagonist Minh was narrated as a woman for four chapters (fixed
by ADR-0126), the seed drifted from the user's idea, and chapter plans were replanned until the run stopped in
`BLOCKED_BUDGET` after chapter 4 of 5 (349 of 375 calls). This note looks for the other failure modes donors have
already hit and guarded.

## 1. Method and pins

- **AR** (ArcReel): worktree `/home/anhtuan/.codex/worktrees/9b89/content-production-os`, branch
  `impl/autonomous-production`, HEAD `5b5230fd4`. Paths below are relative to `server/story_authoring/` unless
  they say otherwise.
- **SH** (shenbi): clone at pin `10efa7cc` (1 176 commits). I read the gate code `src/shenbi/gates/g4/*`, the
  pipeline modules it names, and the `git log` messages matching fix/修复/实弹/regress/死循环/budget (about 120
  commits). The repo was read and never run.
- **HUO** (huohuo-drama): `/home/anhtuan/content-os-r1-8/work/huohuo-drama`, pin `f104b85`. Its 29 commit
  messages are terse ("fix novel bug"), so the evidence is the code: `workbench-server/src/services/novel/*`,
  `common/novel/*`, `agent-skills/novel_*`.
- **Baseline**: the two inventories from 2026-11-09 (`docs/research/2026-11-09-r2-donor-long-novel-and-skill-gaps.md`,
  `…-donor-writing-capabilities.md`) list the donors' mechanisms. This note does not repeat them. It is organised
  by **failure mode** and asks one question: is there a guard today? Where an inventory gap (for example B1, the
  cross-chapter invariants) is still unimplemented, the row says so.
- **Labels.** FACT means cited from source. INFER means my reasoning from those facts. UNKNOWN means not
  verifiable without the production run state (the production DB was out of scope).
- **Not checked.** Production run logs and plans (production services and the DB were off-limits). shenbi skills
  other than intent-management, foundation-review and chapter-planning were not re-read. The HUO frontend was not
  read.

## 2. Failure modes, donor guards, ArcReel status

Severity: **HIGH** = likely to ruin a commercial story or stop a run; **MEDIUM**; **LOW**.

| # | Failure mode | Donor evidence and guard (FACT) | ArcReel today (FACT) | Sev | Recommended guard for us (cost) |
|---|---|---|---|---|---|
| 1 | **Idea drift**: the seed or outline turns into a different story than the user's idea | SH `a440306` item 3: "genesis auto-mode … confabulated a complete foreign story into truth/author_intent.md"; the fix grounds intent on `novel.json` and `story_frame`. `skills/shenbi-intent-management/SKILL.md:56,59`: the author dictates intent, the AI only tidies it; intent "must be anchored to this book, never invented". HUO re-sends the premise verbatim into every outline call (`services/novel/novel-writing.ts:401`, `:453` `premise.slice(0,1200)`) | The idea reaches **only** the seed prompt (`driver.py:641`, `prompts/planning.py:45-65`). The bible, outline, plans and drafts see only the seed. The seed has no review. The outline review checks fidelity to the **seed**, not to the idea (`prompts/outline.py:60`). The seed chooses its own genre from a menu when the brief has none (`prompts/planning.py:42`) | HIGH | (a) Carry the idea verbatim as `[Ý tưởng gốc]` into the bible, outline, outline-review and chapter-plan prompts (0 calls). (b) Change outline-review point 6 to "faithful to the idea **and** the seed" (0 extra calls; the review call already exists). (c) A deterministic seed check: every proper name the idea gives must be a seed character name, and the idea's content-syllable bigrams must overlap the seed's `premise + central_conflict` above a floor, otherwise regenerate the seed once (0 calls, 1 on failure). See section 4.1 |
| 2 | **Self-contradicting chapter plan** (required changes vs withheld cards vs do-not items) that is found only after drafting | SH checks plans at planning time, deterministically, before drafting. `gates/g4/chapter_planning.py:609` ("planning 时点拦截", stop it at planning time) and `:644` (real run: "the model left the budget section out of two bundles in a row"). Hook ids are checked against the registry (`:590`, "the ch3 memo invented MH11/MH12 … two human reject rounds … still shipped"). "无"/N/A is legal for do-not (`skills/shenbi-chapter-planning/SKILL.md:172`). A goal-source priority chain with an explicit conflict note (`SKILL.md:145-154`). HUO checks mechanically that outline beats are covered (`novel-outline-compliance.ts:1-7,22-39`) | Plan consistency is checked by one **model** judge plus one revision (`driver.py:1203-1219`, `prompts/planning.py:162-177`). The revised plan is not re-checked. Contradictions surface only at the chapter seal, as `MEMO_COMPLIANCE` blocking findings. Those trigger a full replan (`driver.py:1636-1648`) that throws away the chapter's drafted scenes and reviews | HIGH | A **deterministic plan precheck** before any scene is drafted (0 calls; 1 regeneration on failure). (i) A `required_changes_by_end` item whose content bigrams overlap a `do_not`/`withheld_cards` item, with negation words removed, is a contradiction. (ii) A withheld card's bigrams in `chapter_goal`, a scene `summary` or a beat is a leak. (iii) Every required change must have bigram cover in some scene's beats (HUO `outlineBeatCoveredIn`). (iv) Cap `withheld_cards` and `do_not` at 2 items each, empty allowed. Calibrate (i)-(iii) on today's failing plans first (section 4.2) |
| 3 | **Retry oscillation**: each retry fixes one problem and regresses another, so the retry budget is spent | SH `0cdc218` (#291): single-round feedback "makes the model drop constraints round by round" ("planning failed 3 times, drafting 4 times in a row"). The fix accumulates failure families with an anti-regression section, and the 4th dispatch passed first try. Code: `pipeline/chapter_loop.py:1225-1265` (`accumulate_retry_feedback`), cap of 16 families at `:1184` | The plan revision sees only the current problems (`prompts/planning.py:172-177`). An audit-driven replan regenerates from the base prompt plus the note **without the failed plan** (`driver.py:1149-1166`), so the 9B writer can draw a new plan with new contradictions | HIGH | Replan with the failed plan and the accumulated findings: "keep everything not named; these problems from all earlier rounds must stay fixed" (0 extra calls, a longer prompt). Use the same accumulation for scene repair notes |
| 4 | **Budget runaway, and a block that cannot be recovered** | SH: per-step caps `max_revision_retries=3`, `max_audit_retries=3` (`pipeline/state.py:63-64`), then an escalation checkpoint a human resolves, and the run resumes at that step (`15202d0` keeps memory of finished steps on resume). HUO aborts a rewrite after a stagnant-hash streak (`novel-chapter-pipeline.ts:721,810-815,895-900`; `novel-continuity-errors.ts:6`) | Node caps and a worst-case run bound (`driver.py:2054-2077`). There is no check that the remaining budget covers the remaining chapters. **Retry does not raise the limits**: `retry` only calls `reopen_unconverged` (`service.py:756-764`, `runtime.py:432-440`), while `reserve` compares cumulative usage with the same `limits` (`runtime.py:238-248`). INFER: a run in `BLOCKED_BUDGET` re-blocks on its first call after a retry, so the ~349 calls (~9 h) already spent cannot be finished | HIGH | (a) A **feasibility guard**: before a replan, or before starting chapter c, compare the remaining calls with the minimum cost of the remaining chapters (scenes + 6 audits + plan + digest each). If a replan would make the remainder infeasible, escalate the `MEMO_COMPLIANCE` finding (it is already escalable, `checks.py:62-63`) instead of replanning (0 calls). (b) Let a Showrunner retry from `BLOCKED_BUDGET` add a bounded top-up to the limits, for example the bound of the unfinished chapters (0 calls). (c) Per-chapter sub-budgets, so early chapters cannot starve later ones |
| 5 | **Protagonist or name drift** (Minh becomes Mạnh; an old alias returns in the narration) | SH cross-chapter invariant 2 (reserved-name binding and hijack, `gates/g4/cross_chapter.py:699-711`, real-run wound "ch7 井台女") and F15 narration-name scan: dialogue stripped, any alias in the narration is a violation, flashback exempt by declaration (`:595-631`) | `UNKNOWN_NAME` exists but is **STYLISTIC** (`checks.py:690-720,810`), and STYLISTIC is not repairable (`driver.py:187`). A wrong name for a bible character is therefore recorded, never fixed | HIGH | Promote `UNKNOWN_NAME` to NARRATIVE_CRITICAL when the unknown name is within edit distance 1-2 (diacritics folded) of a cast name, or takes a cast member's role. That is a likely misnaming, repaired by span patch (0 calls to detect) |
| 6 | **A dead character reappears**, or a major state is invented (pregnancy, marriage, injury healed overnight) | HUO deterministic prechecks: unprompted major life state against a grounding corpus (`novel-continuity-precheck.ts:66-90`, comment example: a pregnancy invented in a famine scene); severe injury to healed without recovery (`:424-475`). SH settles state into append-only truth rows (inventory row 21) | Only the model CONTINUITY audit (`audits.py:120-128`). `CharacterNow.state` in the book digest is free text (`book.py:141-143`); no structured alive/dead status | HIGH for books, MEDIUM for 3-chapter stories | Add `status: sống/đã mất/mất tích` to `CharacterNow`. A **plan-time** check rejects a scene whose `characters` include a dead character unless the scene is marked as memory (0 calls). A Vietnamese cue list (mang thai, có bầu, cưới, chết…) checked against the grounding text (seed, bible, plans, digests) gives a NARRATIVE_CRITICAL finding (0 calls) |
| 7 | **Age contradictions** | HUO extracts stable cast facts (age) from the outline and checks hard against stated ages in the prose (`novel-stable-cast-facts.ts:82,235-310`) | `SeedCharacter` has **no age field** (`prompts/schemas.py:23-44`); age lives only in the free-text description. The seed prompt asks to keep ages (`prompts/planning.py:60`), but nothing checks it | MEDIUM | `age: int | None` on the seed character, part of `locked_line()`. A deterministic "<Name> … N tuổi" check against age (+ elapsed years in a book) (0 calls) |
| 8 | **Timeline runs backwards** across chapters | SH invariant 3, monotonic time anchors, with a declared flashback exempt (`cross_chapter.py:813-828`). The commits show its false positives, each fixed with a real-run fixture: `4fa6092`, `0905b4e`, `0cdc218`(c), `6eb94b5`(a) | Model CONTINUITY only (`audits.py:126`). The digest's `time_place` is free text (`book.py:157`) | MEDIUM | A structured `time_anchor` (day index or date) in the digest and the plan. A deterministic check that the next chapter's plan does not start before the last digest anchor without `flashback` (0 calls) |
| 9 | **POV person drift** (first person ↔ third person) | SH invariant 1: POV derived from narration with dialogue stripped; a change needs a declaration (`cross_chapter.py:242-255,800-811`; `f10cd69` fixed a false positive from dialogue spans) | The scene POV *character* is an enum (`prompts/schemas.py:139-141`). The person (tôi vs third) is not checked; the seed `pov` is free text (`prompts/schemas.py:56`) | MEDIUM | Count narration "tôi/mình" outside quotes per scene against the seed POV ("ngôi thứ nhất" vs "ngôi thứ ba"); finding when the mode flips (0 calls) |
| 10 | **Chapter overshoot**: it writes the next chapter's events or resolves a pending state early ("story finished in chapter 3") | HUO codes `outline_endpoint_overshoot` and `next_chapter_beat_leak` (`novel-outline-compliance.ts:29-30,442,531,557,657`), `brief_pending_overshoot` (`novel-brief-compliance.ts:62-115`), and a strip with a catastrophic-ratio floor of 0.65 (`novel-outline-poison-strip.ts:29-30`) | A prompt rule "do not resolve the central conflict before the last chapter" (`prompts/planning.py:122`) and the model MEMO audit | MEDIUM (HIGH for books) | A deterministic leak check: the **next** chapter's outline `core_task`/`turning_point` bigrams in the current chapter's last scene give a finding (0 calls) |
| 11 | **Presence teleport**: a character who left acts in the scene without a bridge, or acts in a scene they are not planned in | HUO `intra_cast_teleport` (`novel-presence-phase.ts:145-170`) | Model CONTINUITY only ("nhân vật xuất hiện khi không thể có mặt", `audits.py:125`) | LOW-MEDIUM | A cast character named as speaker or actor in a scene whose plan `characters` list excludes them gives a stylistic, then narrative-critical, finding (0 calls) |
| 12 | **Object, money or prop continuity** | SH invariants 4 (prop owner chain) and 6 (asset balance with event reconciliation) (`cross_chapter.py:718-797,830-865`). HUO stakes restatement and common-sense amount checks (`novel-stakes-restatement.ts`, `novel-stakes-common-sense.ts:154-186`) | Model CONTINUITY only (`audits.py:126`) | LOW (short) / MEDIUM (book) | Defer until book digests carry items; a check would read the digest, not regex the prose |
| 13 | **False-positive deterministic gates cause redispatch deadlocks** | SH `c586cb3` ("H4 false-positive deadlock"), `cross_chapter.py:723-727` ("otherwise the follower's true declaration is killed — deterministic redispatch dead loop"), plus a series of anchor false positives (row 8). Each is fixed with a real-run fixture | ADR-0126's `CAST_GENDER` is narrative-critical, so it is repaired, then recorded, never blocking (`docs/adr/0126-characters-keep-their-gender.md` item 3) | MEDIUM (process risk for rows 2, 5-11) | Every new deterministic check: (a) severity NARRATIVE_CRITICAL or STYLISTIC, never blocking; (b) a regression fixture from a real run; (c) its repair counted against the existing caps |
| 14 | **Empty or truncated output; thinking leak** | SH `8ac5881` (empty content with billed reasoning tokens, one resend), `a2ca684` (thinking off for evaluators), max_tokens "capacity wall" fixes (`c7f3d8a`, `fb624f2`, `a66ff8e`). HUO `assertValidNovelCreativeOutput` (empty, thinking leak, too short; `common/novel/novel-creative-output.ts:87-112`) | Covered: `think: False` (`lib/text_backends/ollama.py:134`); `done_reason == "length"` is a failure (`generation.py:328-331`); counted input must equal reported input (`generation.py:5-8`); unterminated tail trimmed (`checks.py:676-684`); meta leaks (`checks.py:644-675`) | — | None needed |
| 15 | **Silent shrink or loss in repair** | SH `33c98f0`: a WARN on a section shrink below 50% after a 43% silent compaction | Compression floor 0.7 (`repair.py:53-55`), near-duplicate strip refuses a half-text removal (`checks.py:542-560`), `_no_worse` (`driver.py:1669`) | — | None |
| 16 | **Repetition and looping across chapters; same openings** | SH long-span n-gram rate (inventory B7). HUO intra-chapter dedupe | Covered: `long_span_findings` 12% four-word reuse (`craft_checks.py:45`), `opening_findings` (`craft_checks.py:75`), near-duplicate and replay (`checks.py:533-631`), degenerate judge text (`audits.py:254`) | — | None (calibration only) |
| 17 | **Invented hook ids / hook payoff misses** | SH `chapter_planning.py:590` (MH11/MH12 invented, see row 2) | Covered for ids: digest hook ops are an enum of known hooks (`book.py:220-228`). Open hooks are paid in the last part (ADR-0117) | LOW | None now |
| 18 | **Crash or restart** | SH emergency snapshots (`pipeline/crash_recovery.py:1-6`), step resume memory (`15202d0`) | Covered: fingerprinted nodes resume without regenerating (`driver.py:1-6`); epochs fence late results (`runtime.py:432-440`) | — | None (but see row 4 on budget) |
| 19 | **Cliché / AI voice; dialogue attribution** | Inventory B2/B3/B6 (prompt and score-heavy at both donors) | Partly covered: stock phrases, not-but pattern, paragraph CV (`audits.py:563-590`), humanize repair (`driver.py:2146-2160`), CHARACTER voice audit (`audits.py:135-139`) | LOW | No new gate. Dialogue attribution stays model-judged |

## 3. Top 10 to implement next (ranked)

Ranking: severity first, then how cheap the guard is (no model calls first), then how directly it explains today's
failures.

1. **Idea anchoring** (row 1): pass the idea verbatim to the bible, outline, review and plan prompts; make outline
   review point 6 check against the idea; add a deterministic seed-vs-idea name and overlap check. 0 calls (1 on
   regeneration).
2. **Deterministic plan precheck before drafting** (row 2): find contradictions, leaks and uncovered required
   changes; cap withheld and do-not at 2 each, empty allowed. 0 calls. This removes the most expensive path
   (draft, review, then replan).
3. **Replan with the failed plan and accumulated findings** (row 3): SH's anti-regression feedback. 0 extra calls.
4. **Budget feasibility guard plus escalate-instead-of-replan** (row 4a): when the remaining calls cannot pay for a
   replan plus the remaining chapters, record the MEMO finding as an escalated exception and continue. 0 calls.
5. **Recoverable `BLOCKED_BUDGET`** (row 4b): a Showrunner retry adds a bounded top-up to the limits. Without it, a
   budget block throws away hours of local-writer work. Code only.
6. **Name drift is repairable** (row 5): a cast-like unknown name becomes NARRATIVE_CRITICAL and gets a span patch.
   0 calls to detect.
7. **Life status** (row 6): a structured `status` in `CharacterNow`, a plan-time dead-character check, and an
   invented-major-state cue check. 0 calls.
8. **Age as a locked fact** (row 7): an `age` field, `locked_line`, and a deterministic stated-age check. 0 calls.
9. **Chapter overshoot / next-chapter leak** (row 10): bigram check of the next outline row against the current
   last scene. 0 calls.
10. **POV person and time-anchor checks** (rows 8-9): deterministic and declaration-exempt, following SH
    invariants 1 and 3. Bring in SH's false-positive lessons (row 13) from the start.

Process rule for items 2 and 6-10 (row 13): never blocking, a fixture from a real run per check, and repairs inside
the existing caps.

## 4. The three observed problems

### 4.1 Idea fidelity (Minh coveting other men's wives became an artist and ghost-wife story)

- FACT: the idea is used once, in the seed prompt (`driver.py:641`), next to a "stay close to the author's idea"
  rule (`prompts/planning.py:60`). Every later stage is built from the seed (`prompts/planning.py:68-89`,
  `prompts/outline.py:23-37`). The only fidelity review compares outline with seed (`prompts/outline.py:60`). So a
  seed that drifts locks the drift in for the whole run, and no stage can see it.
- FACT: a brief without a genre lets the seed choose one from the genre menu (`prompts/planning.py:42`), and that
  genre pack then shapes later prompts (`genre_packs.py`).
- Donor FACT: SH hit the same class ("confabulated a complete foreign story", `a440306`) and fixed it by grounding
  and an "intent must be anchored, never invented" rule (`skills/shenbi-intent-management/SKILL.md:59`). HUO keeps
  the premise in every outline prompt (`novel-writing.ts:401,453`).
- INFER: a 9B writer under "write a three-chapter seed" picks the nearest familiar template (a ghost-wife romance)
  when the idea is morally edgy (coveting married women, a wish-granting power). The model may also soften an
  edgy premise on its own. UNKNOWN whether the safety level or the drawn idea (ADR-0125) contributed; that needs the
  run's seed and brief.
- Guard (no new calls): the idea is carried verbatim to the bible, outline, review and plans, and outline review
  point 6 becomes "faithful to the idea". A deterministic seed check covers (a) the idea's capitalised names, which
  must be seed character names with the protagonist among them, and (b) the content bigrams of the idea's
  premise-bearing nouns and verbs, which must appear in `premise ∪ central_conflict ∪ protagonist goal`. One seed
  regeneration names what was lost. A seed review call (+1 call) is possible later if the deterministic check
  proves too weak.

### 4.2 Plan contradictions and the replan budget burn

- FACT: the plan schema asks the 9B writer for up to 3 withheld cards, 1-3 required changes and up to 4 do-not
  items per chapter (`prompts/schemas.py:125-131`). The only consistency check is a model judge plus one revision
  that is not re-checked (`driver.py:1203-1219`).
- FACT: an unsatisfiable plan shows up only after its scenes are drafted and the chapter is reviewed and repaired
  across `REVIEW_CYCLES = 2` (`driver.py:144`). Then, if every blocking finding is MEMO_COMPLIANCE, the plan gets
  a note and the driver raises `_Restart` (`driver.py:1636-1648`). That regenerates the plan without showing it
  its failed version (`driver.py:1149-1166`), and the chapter's scenes are drafted and reviewed again. Each plan
  is replanned at most once; on the second failure the finding is escalated or the chapter blocks
  (`driver.py:1638`, `checks.py:62-63`).
- INFER, with my estimate of the cost: one such cycle for a 5-scene chapter costs about 4 plan calls, 5 × 3 × 2
  scene calls and 2 × 3 × (6 audits + 3 confirmations), which is roughly 90 calls. At 93 s per call that is about
  2.3 h per chapter that fails its contract. Two or three such chapters exhaust a 375-call cap. That fits the
  observed 349/375 after chapter 4.
- Donor FACT: SH stops this class at planning time with deterministic gates (`chapter_planning.py:609,644`). It
  accumulates failure families so retries converge (`chapter_loop.py:1225-1265`, "4th dispatch passed first-try"),
  and allows an empty do-not (`SKILL.md:172`).
- Guard: items 2, 3 and 4 of the top 10. The precheck needs fixtures: take today's failing plans and their
  `MEMO_COMPLIANCE` findings from the run state (the main agent can read them; this research could not). Measure
  how many the bigram rules would have caught before choosing thresholds.

### 4.3 Budget sizing for a slow local writer

- FACT: the cap is a worst-case call bound (`driver.py:2054-2077`). Limits are derived from it: wall clock =
  calls × `SECONDS_PER_CALL = 120` (`service.py:97-105,167-178`). At HEAD, `run_call_bound()` = 334 for a 3-chapter
  story and `run_call_bound(5)` = 546 without book memory (computed with `uv run python`). UNKNOWN why production
  reported 375: it may be a different release tag or a part with fewer scenes per chapter, so check against the
  deployed tag.
- FACT: the bound assumes "each chapter replanned once". Nothing reserves budget for later chapters, so one
  expensive early chapter can starve the rest. A `BLOCKED_BUDGET` cannot be retried into completion, because the
  limits never grow (row 4).
- FACT: every generate call is preceded by a COUNT probe (`generation.py:5-8`), counted separately
  (`runtime.py:239-240`). UNKNOWN how much wall time the probe adds on the 9B model when the prompt cache is cold.
- Recommendation, no extra quality cost:
  1. Size the run as a forecast plus a reserve, not only a cap. Nominal cost per chapter is plan 3 + scenes + 6
     audits + about 3 confirmations + digest. Show the expected wall time (calls × measured seconds per call)
     before the autopilot starts a part.
  2. Give each chapter a sub-budget. When a chapter exceeds it, escalate (finding recorded, run continues) instead
     of replanning.
  3. Allow a bounded top-up when a Showrunner retries a budget block, so finished chapters are never lost.
  4. Measure seconds per call per node kind from the attempt ledger. If the COUNT probe is a material share, cache
     counts by prompt digest. INFER: the same prompt is often re-counted on retries.

## 5. Unknowns

- What today's failing plans and MEMO findings say, and why the cap was 375. Both need the production run state,
  which was not read.
- Whether the edgy premise was softened by the model, by the safety level (ADR-0121) or by the drawn profile
  (ADR-0125).
- How well bigram-overlap rules work on Vietnamese plans, in false positives and misses. Fixtures are needed
  before thresholds are chosen (row 13).
