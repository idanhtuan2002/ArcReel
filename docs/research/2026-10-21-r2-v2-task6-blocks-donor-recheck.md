# R2 V2 Task6 blocks — donor re-check (2026-10-21)

Trigger: Task6 on T = `0b7f869f`. Every run that reached its end stopped at `BLOCKED_QUALITY` before touchpoint 2
(`accept-restart`, `accept-kill`, `accept-clean`); the clean case therefore fails. The Human stopped the remaining
cases and asked for a donor re-check first, with reuse (including whole donor behaviour) preferred over new design.

Sources: Shenbi `65ddfc261f4e491b07c36e548f78de36109be218`, Novel Studio `9b690ae2e2f6921f9bd2782b42cef53c1662ad3b`
(both fetched at their pins), Huohuo `f104b853b3563e124d9cde25f9331d323fb483b9` (local checkout). Evidence:
`~/arcreel-v2-story-accept/evidence/accept-{clean,kill,restart-before-kill}.json`.

## 1. The blocks

| Run | Block | Reading of the evidence |
|---|---|---|
| clean | `chapter_plan[3]: names outside the bible: Lũ trẻ` | The idea is about "lời hứa với lũ trẻ"; the seed cast (2–5 named people) has no entry for the children, so the plan's `characters` list names a collective the bible lacks. One reprompt, then block. |
| kill | `MEMO_COMPLIANCE:withheld_card_revealed scene_draft[1,2]` | True positive: "con bác thì đã chết giữa biển khơi" states the chapter's withheld fact. The judge proposed a one-sentence replacement. Before the block: the scene was regenerated with an editor note, the chapter plan was regenerated once, and `chapter_review[1]` used 32 calls. |
| restart | 3 × `MEMO_COMPLIANCE` on `scene_draft[2,3]` | Mostly over-reading: "vẫn giữ kín lý do cụ thể" reveals nothing; one sentence ("kỷ niệm của người mẹ đã khuất") is a narrator disclosure to the reader. All three survived the second (confirming) reading on the same judge model. |

## 2. Facts from the donors

### Cast and names

- **Novel Studio** — `SceneBeatSchema.involved_character_names` is free text (`src/lib/ai/schemas.ts`). Context
  building resolves only names that match a known character or alias and silently ignores the rest
  (`resolveCharacterIdsByNames`, `src/lib/context/contextPack.ts`). New people found in a chapter are registered
  after drafting as tier-D characters (`ensureCharacterByName`, `MemoryExtractionSchema.new_characters`). No path
  blocks on an unknown name.
- **Shenbi** — the short-story outline allows up to 8 main characters (`skills/shenbi-short-outline/SKILL.md`,
  "角色数 ≤ 8"); chapter planning may introduce a new character (`skills/shenbi-chapter-planning/SKILL.md` L104).
  No check blocks on an unknown name.
- **R2 itself** — Canon genesis already drops participants that do not resolve
  (`server/story_authoring/driver.py`, `participants=tuple(k for k in ... if k)`); only the scene's POV and location
  must resolve to a bible key. The block at `driver.py:569–582` is therefore stricter than both donors and than
  what Canon needs.

### Audit surface provenance

- 15 Shenbi skills carry `DEPRECATED`; among them 10 of the 12 specialist audits pinned in
  `R2_STORY_DONOR_BASELINE.json` S06 (memo-compliance, character, motivation, dialogue, pov, pacing, texture,
  reader-pull, anti-ai, continuity). They are superseded by four grouped audits — `shenbi-review-group-plan`,
  `-group-character`, `-group-factual`, `-group-craft` — each "supersedes the deprecated …" dimension by dimension.
- The memo-compliance rules in `group-plan` Dimension 1 are the same five rules as the deprecated skill (task
  delivered, held hooks not revealed, end-of-chapter changes present, hook ledger, prohibitions avoided). R2 already
  runs grouped L2 calls (`CHAPTER_DIMENSIONS` = continuity, memo compliance, character, anti-AI). The deprecation is
  a provenance error in S06, not a behavioural gap.

### What happens after a blocking audit finding

- **Shenbi** — `src/shenbi/pipeline/revision_router.py`: BLOCKING → revision → re-audit, at most 3 rounds, then an
  escalation checkpoint. `skills/shenbi-chapter-revision/SKILL.md`: local issues → **spot-fix** (patches), structural
  issues → rewrite; a revision is accepted only if blocking/critical/AI-tell counts do not increase; after 3 failed
  revisions the chapter **falls back to the best version** (fewest weighted findings) and is marked for the human.
  `skills/shenbi-escalation-review/SKILL.md` offers the human: (1) accept as is and continue, (2) roll back to a
  snapshot and revise by hand, (3) revise the current output by hand.
- **Huohuo** — `novel-chapter-pipeline.ts`: span-local patch first, regenerate on stagnation, and in strict mode a
  hard reject (`ContinuityRewriteAbortError`, `hard_reject: true`) after the rewrite budget. It blocks, like R2.
- **R2 at T** — memo-contract findings always **regenerate the whole scene** with a note (commit `2b3b118f`: a span
  patch "cannot add a missing change"), then replan the chapter once (`a3b3e956`), then end the run at
  `BLOCKED_QUALITY`. In `BLOCKED_QUALITY` the Human may revise, retry or discard, but cannot accept the finding.

## 3. Inferences

1. The `2b3b118f` reason holds for `required_change_missing` only. `withheld_card_revealed`/`_broken` and a
   violated `do_not` are *excess* sentences that the finding quotes; that is Shenbi's spot-fix case and Huohuo's
   span-patch case, which R2 already implements (`repair.span_repair`, S07). Regeneration re-exposes the writer to
   the same plan, so a small model leaks the same fact again (kill run).
2. Without Shenbi's "no worsening / keep the best version" rule, a later regeneration can replace a scene that had
   fewer findings.
3. Judge-based memo findings on a 12B local judge include over-reading (restart run) that a second reading on the same
   model confirms. Ending the run on them is Huohuo's strict behaviour; Shenbi hands the same situation to the human
   with "accept as is". R2's touchpoint 2 already offers Approve (bound to open findings and exceptions), Revise and
   Discard — the same three options.

## 4. Unknowns

- How often the changed loop reaches touchpoint 2 on `qwen3.5-vimax:9b` + `gemma3:12b`; only new runs show it.
- Whether 8 seed characters fit the 9B planner's context and grammar budget (Shenbi's limit targets larger models).

## 5. Decisions

Technical choices made under the Human's delegation (design choices after research):

- **N1 — names (Novel Studio + Canon behaviour).** A scene participant that does not resolve is kept in the plan as a
  minor or collective character and dropped from Canon participants, as Canon genesis already does. Only an
  unresolved POV or location is a contract failure, and both are constrained at generation time by an `enum` of
  bible names in the per-call JSON schema (the grammar path qualified in Task1), so the model cannot emit them.
  The seed cast limit stays at 5 (unknown above).
- **N2 — repair routing (Shenbi spot-fix / Huohuo patch).** Memo findings that quote an excess sentence
  (`withheld_card_*`, `do_not_*`) go to `span_repair`; `required_change_missing` keeps scene regeneration.
- **N3 — no worsening, best version (Shenbi chapter-revision).** A scene revision is kept only if the chapter's
  blocking count does not increase; otherwise the previous head stays.
- **N4 — provenance.** S06 is re-pinned to the four grouped Shenbi audits; prompts are unchanged because the rules
  are the same. Recorded in the donor parity contract.

Needs the Human (changes the approved severity policy, Change G):

- **N5 — escalation instead of a terminal block (Shenbi escalation-review).** When the repair budget of a chapter is
  spent, memo-compliance findings that survived the second reading become narrative-critical exceptions carried to
  touchpoint 2 on the best version, where Approve / Revise / Discard map to Shenbi's accept / manual revision /
  rollback. Hard integrity (CJK, truncation, over-context, unresolved POV or location) stays blocking with no manual
  exception. Without N5, runs still end at `BLOCKED_QUALITY` whenever the judge holds a memo finding, as Huohuo does.

Any of N1–N5 changes code after T, so Task6 restarts on a new T with all eleven cases.

**Human decision (2026-10-21):** N5 approved, following Shenbi. The Human also asked for a full review of every stop
case, the errors that can occur and how the donors handle each (§6–§9).

## 6. How each donor ends a step that keeps failing (facts)

| Donor | Rule | Source |
|---|---|---|
| Shenbi | Dispatch/gate failure: 2 retries, then an escalation checkpoint (pipeline paused, Human decides). Audit BLOCKING: at most 3 revision rounds, then escalation. Short-story drafting: a chapter still failing after 3 rounds **falls back to its best version, is marked "回退" in the batch summary, and drafting continues**; the summary goes to the Human. Packaging: the Human picks title and blurb (Step 6). Quality never ends a run. | `src/shenbi/pipeline/error_handler.py` header; `revision_router.py`; `skills/shenbi-short-drafting/SKILL.md` §铁律 3, §修订规则, summary table; `skills/shenbi-short-packaging/SKILL.md` Step 6; `skills/shenbi-escalation-review/SKILL.md` |
| Novel Studio | No automatic repair loop. A model call is tried twice (`client.ts`, `attempt <= 2`). A chapter cannot be accepted into memory while the latest continuity report has a `high`/`critical` issue; the Human edits the text (`finalText`) or regenerates, then re-checks. | `src/lib/ai/client.ts`; `src/lib/memory/memoryService.ts` `getChapterAcceptanceGate`; accept route (409) |
| Huohuo | Strict mode: span patch, regenerate on stagnation, then `ContinuityRewriteAbortError` on `max_attempts` or `stagnant_rewrite`; the batch stops at that chapter (`mustAbortBatchOnContinuityError`) and shows the conflicts. Outline hard rejects deliver no content. | `novel-chapter-pipeline.ts` L795–L900; `services/batch/batch-generation.ts` L516–L539; `novel-continuity-errors.ts` |

Summary: Shenbi escalates to the Human with the best version; Novel Studio leaves repair to the Human; Huohuo stops.
None of the three ends on a model-judged quality claim without a Human path to accept, edit or redo.

## 7. Live-run history (facts)

`R2_STORY_AUTHORING_QUALIFICATION.md` runs 1–11 plus Task6: 14 runs, every one ended `BLOCKED_QUALITY` on its first
pass; only run 11 reached touchpoint 2, after an operator Retry on a fixed critic. Causes in order: scene cap per epoch
(1), copied passages (2), self-contradicting plan (3), quote read as truncation (4), required dialogue breaking a
do-not item (5), length/paragraph floor and `OUTPUT_TRUNCATED` (6, 7), wrong memo claims (8, 10, Task6 restart),
truncated audit (9), wrong `NO_ENDING` (11), true memo reveal (Task6 kill), names (Task6 clean). Each fix moved the
stop to the next judge-dependent gate. Run 11 also carried reader-visible defects no gate stopped: kinship drift,
meta narration ("khép lại chương ba"), a broken do-not line, 7 of 11 scenes without dialogue.

## 8. Every stop point in R2 at T, against the donors

| # | Stop (code site at T) | Kind | Donor behaviour | Decision |
|---|---|---|---|---|
| B1 | `BLOCKED_PROPAGATION` — convergence passes exhausted (`driver.run`) | R2 integrity | none comparable | keep |
| B2 | `MODEL_UNAVAILABLE` / `PROVIDER_ERROR` | transport | Shenbi pause + resume; NS 2 tries then error; Huohuo error | keep (typed, Retry) — parity |
| B3 | other `StoryStepError` (over-context, over-limit, not qualified, selection changed) | integrity | Shenbi escalation (pause) | keep — hard integrity, Retry/Revise/Discard |
| B4 | node call cap reached without a valid output (invalid JSON, truncated, CJK) | output integrity | Shenbi 2 retries → escalation | keep; caps (3–12) already exceed Shenbi's 3 attempts |
| B5 | outline: deterministic problems after one revision (not 3 chapters, empty task, no ending, duplicate tasks) | structure | Shenbi generate → 6-point review → revise, then escalation | keep — later nodes cannot be built without it |
| B6 | chapter plan: names outside the bible | structure | NS ignores unknown names; Shenbi allows new characters | **N1** |
| B7a | scene L1 after cap: `CJK`, `UNTERMINATED`, `PARAGRAPH_CUT`, `META_LEAK`, `MARKUP` | output integrity | Shenbi output-integrity → retry → escalation | keep (zero-CJK and no cut prose are release invariants) |
| B7b | scene L1 after cap: `SCENE_TOO_SHORT`, `LENGTH_HARD` | quality (deterministic) | Shenbi length-normalizing, then best version recorded and continue | **N7** |
| B8 | chapter review final: memo-compliance `HARD_STRUCTURAL` after scene repair and one replan | quality (judged) | Shenbi best version + escalation; Huohuo stop | **N5 (approved)** with N2, N3 |
| B9 | manuscript review: `NO_ENDING` confirmed after one ending rewrite | quality (judged) | Shenbi best version + Human | **N6** |
| B10 | packaging: fewer than 3 selling points quote the manuscript after 2 tries | quality (deterministic) | Shenbi Human selects | **N8** |
| B11 | manifest: `STORY_LENGTH` outside the hard bounds | quality (deterministic) | Shenbi records under-floor chapters in the summary | **N7** |
| B12 | `BLOCKED_BUDGET` | R2 safety cap | none | keep |
| B13 | `BLOCKED_BINDING_MISMATCH`, `COMMIT_BLOCKED`, `RECOVERY_INCONSISTENT` | authority / commit integrity | none (R2-owned) | keep |

Proposed extensions of the approved N5 principle (need the Human, same policy change class):

- **N6** — `NO_ENDING` after the ending rewrite and the confirming reading: the best version goes to touchpoint 2 with
  the claim as a narrative-critical exception; the Human reads the ending.
- **N7** — `SCENE_TOO_SHORT`/`LENGTH_HARD` after the scene cap and `STORY_LENGTH` at the manifest: the best version goes on
  with a narrative-critical exception stating the measured length and the bound.
- **N8** — packaging with fewer than 3 verified selling points after its tries: keep the best attempt, drop unverified
  points, carry an exception; the Human sees titles, blurbs and points before Approve.

Kept hard in every case: CJK, cut or unterminated prose, meta/markup in prose, over-context/truncation, unresolved POV
or location, transport, budget, authority and commit integrity.

## 9. Planned failure rows not implemented at T (facts) and donor coverage

| Row | Planned | At T | Donor | Decision |
|---|---|---|---|---|
| F62 | best-version fallback | absent | Shenbi chapter-revision (no worsening, best version) | **N3**, implement now |
| F43 | meta text | headings/labels only; narration such as "khép lại chương ba" passes | Shenbi `llm_output_integrity.check_prose_leakage` (pattern detection) | extend the detector's patterns with chapter/story self-reference; keep `META_LEAK` hard |
| F34 | POV audit | no POV dimension | Shenbi `group-character` Dimension 4 | defer: one more judge call per chapter on a 5–7 tok/s judge; recorded as open |
| F22 | xưng hô matrix in the bible | prompt rule + continuity audit only | no donor (Huohuo: prompt rules only) | defer: Vietnamese-specific design; local-model limit until the cloud model |
| F30/F31 | deterministic age/time checks | continuity audit only | Huohuo `novel-stable-cast-facts.ts` (Chinese numerals) | defer: needs a Vietnamese port |
| F42 | premature closure | absent | Huohuo `novel-brief-compliance.ts` (unfinished-state markers) | defer |
| F71 | chapter seam replay | `CROSS_SCENE_REPLAY` covers copied sentences across scenes | Huohuo `novel-chapter-seam.ts` | covered for copies; structure part deferred |

Deferred rows remain reader-visible risks that the Human sees at touchpoint 2; they are not gates in V2.
