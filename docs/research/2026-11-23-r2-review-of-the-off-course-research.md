# Review of the off-course research (rounds 1–3) and of the proposals

Date: 2026-11-23, round 4. The sponsor asked for a further round on all earlier findings and proposals. This note
checks rounds 1–3 ([1–2](2026-11-23-r2-why-the-project-went-off-course.md),
[3](2026-11-23-r2-operating-model-vs-large-organisations.md), [waste audit](2026-11-23-r2-resource-waste-audit.md))
for wrong or overstated claims, bias, untested assumptions and proposals that would repeat the failure.
Labels: **FACT** (with source), **INFER**.

## 1. Corrections

| Claim (round) | Check | Correction |
|---|---|---|
| "The first validation of the product came on 11-08"; "validation missing for 2 months" (3, row 1) | Golden A media evidence exists from 09-06 (`R2_M3_GOLDEN_A_EVIDENCE.json`), Golden B 96 s films and the V1 operator cycle with real films by 09-29 (`R2_V1_OPERATOR_CYCLE_1_RECORD_2026-09-29.md`) | Films existed from September. What was missing was **validation against the sponsor's expectation**: no film was compared with a donor's output or judged at commercial quality before November. 11-08 is the first *automatic* film |
| "~58 k-line governance core" (1–3) | `r2/` by package: contracts 10 080, narrative_lifecycle 5 414, host_hardening 5 122, narrative 3 392, adaptation 3 284, production_intelligence 2 781, quality 2 766, advanced_creative 2 618, m3 2 415, governance 1 674, learning 1 324 … | `r2/` is not all governance: narrative, adaptation and quality are product code. Governance/authority proper (governance, host_hardening, contracts in part, automation, target_registry, production_binding) is roughly 10–17 k lines plus `server/production_run/` (12.8 k) — still large for one operator, but not 58 k |
| 726 "governance" commits; 44 % of releases on own governance (1, waste audit) | Keyword match on subjects ("review", "accept", "canon" also match product work such as script review); release classes were assigned by the main agent | Both are **estimates with a classification bias**; the direction holds (docs-only 39 % is exact), the exact shares do not. The weekly metrics should classify from changed paths, not subjects |
| "The goal never changed" (2) | 09-07 … 11-23 messages state the reuse/quality goal throughout; but on 09-06 the sponsor approved the freeze with four human gates, and on 11-01/11-02 asked for full automation | The **core goal** (assemble the donors' best parts, quality ≥ donor, one operator) is constant; the **level of automation** did change (human gates → fully automatic). Round 1 over-weighted change, round 2 under-weighted it |
| "DramaClaw, a complete drama pipeline, was assigned Creative Canvas" (2, cause 6) | The R1.8 evaluation packages (`~/content-os-r1-8/content_production_os_r1_8_*`) contain no DramaClaw run; the revision used now, `b299bfd`, is dated 2026-09-07 — after the 09-06 freeze — and was cloned on 09-29 | The role was assigned **without a hands-on evaluation** and on an earlier DramaClaw; the evaluated donors were ArcReel, OpenMontage and take. Cause 6 is sharper than stated: a donor was ranked by description |
| "Nobody raised reopening the freeze" (2) | Search of assistant messages (Codex 09–11, Claude 10–11) for freeze/frozen next to change/reopen/supersede/amend together with donor/reuse: 0 hits | Holds, within the limits of a text search |

## 2. Blind spots in rounds 1–3

1. **Survivorship of the critique.** The rounds count what went wrong and not what the governance bought: the V1
   operator cycle and restore drills (09-27/28), recovery from an unplanned power loss with the orphan story run
   requeued (11-12), 11 SUCCEEDED production runs, a stable deploy/backup path. A re-foundation that drops the core
   must keep these properties or decide to lose them.
2. **The donor is assumed to be better.** No donor film has been made here. DramaClaw needs a newAPI gateway, a Cognee
   graph and dozens of model settings (`.env.example`: `IDENTITY_PLANNER_*`, `SCENE_BUILD_MODEL`,
   `NEWAPI_IMAGE_MODEL`, …), mostly paid cloud models; its language detection knows only Chinese and English, and its
   identity planner gave Chinese identity names to a Vietnamese story (run 010a7912). huohuo-drama's prompts are
   Chinese. **Whether a donor makes a better Vietnamese film on our free tiers is unknown** — it is the first thing
   to measure, not a premise.
3. **The sponsor's side of the process.** Rounds 2–3 note the relays (≈185 messages) but propose only agent-side
   fixes. Three AI roles with the sponsor routing between them is a process the sponsor also chose; the fix needs a
   decision from the sponsor (one owner agent), not only a rule for agents.
4. **Rules reach only Claude Code.** The hooks are Claude Code hooks; Codex sessions (still the independent reviewer
   by memory `independent-review-via-codex`) read AGENTS.md only. A rule that must hold for every agent belongs in
   AGENTS.md, and the hooks are an extra layer for one agent.
5. **The research itself costs.** Four rounds in one day; each round re-read large documents. Research needs a time
   and quota box like any stage.

## 3. Do the proposals repeat the failure?

Round 3 proposes eight elements (charter + PR/FAQ per form, staged lifecycle, gate records, tolerances, weekly
metrics, COE documents, tailoring review, hooks). Measured against round 3's own finding — R2 over-built control
documents — **several of them are more control documents** for a one-operator project (PRINCE2 "tailor to suit").
Keep what changes decisions; drop what only records them:

| Element | Keep / change | Why |
|---|---|---|
| Charter (`docs/GOAL.md`) | **keep, one page**, PR/FAQ lines and tolerances inside it, no separate PR/FAQ files | It is the missing authority (cause 1) |
| Charter supremacy + direction-question rule + sponsor decides product only | **keep, in AGENTS.md** (all agents), hook reminder as extra | Causes 1, 3, 4 |
| Donor baseline before building | **keep, as a time-boxed discovery spike** with a stop condition | Tests the premise in §2.2 |
| Stage lifecycle and gate records | **merge into the tracker**: a stage is one line with the film, verdicts, Go/Kill | No new document type |
| Weekly metrics | **later, automated from git and the ledger** (paths, not subjects), no hand-written report | Avoids a new manual ritual |
| COE documents | **a ledger column** (repeat → root cause → action → checked) | Same effect, no new file kind |
| Tailoring review of governance | **part of the re-foundation decision**, not a separate exercise | One decision, one place |

## 4. Revised proposal (smallest set, in order, each with a stop condition)

1. **Charter, today.** `docs/GOAL.md` (one page): the sponsor's goal in the sponsor's words; per form one line of
   product and its acceptance (reviewers accept, the sponsor's eye, ≥ the donor baseline); tolerances the sponsor
   sets (days per stage, weekly quota share, share of non-product work). AGENTS.md gains three rules: the charter
   overrides any frozen document it contradicts (reported the same day); a question about direction or speed is
   answered with the frozen clauses involved and a Go/Kill/Hold/Recycle choice; the sponsor is asked product
   questions only, one owner agent runs research and reviews. *Stop*: the sponsor's approval of the charter text.
2. **Discovery spike for drama, time-boxed** (proposed: one working day, ≤ 10 % of the weekly quota): install
   DramaClaw at `b299bfd` in an isolated directory and make one episode of "Chiếc đồng hồ của ông" with the free or
   cheapest routes we have. Record: does it run, cost, time, Vietnamese quality, identity consistency, both
   reviewers' verdicts, and the sponsor's eye next to episode 1 of run b961dc0a. *Stop*: the box expires, or a
   blocker (a model we cannot get, no Vietnamese) is found — that is a result too.
3. **Re-foundation decision** with the spike's evidence: (a) keep the core and port units; (b) the donor pipeline as
   the engine for the form, our app as the shell, keeping the properties in §2.1 that the sponsor wants; (c) a mix.
   *Stop*: the sponsor's Go/Kill per option.
4. **Only then** the metrics script and any further rule.

Until step 3, no new governance mechanism, no new pipeline stage and no release except a fix for a production fault.
