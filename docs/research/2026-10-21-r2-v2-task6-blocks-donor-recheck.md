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
