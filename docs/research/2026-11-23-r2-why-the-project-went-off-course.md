# Why R2 went off course, and how it stays on course

Date: 2026-11-23. Asked by the sponsor after the episode 2 run blocked: "we have gone too far from the original
expectation; stop current work, research the whole project, find why it went wrong and how never to go wrong again."
All current work is stopped (no watcher, no job; run 010a7912 left blocked). Labels: **FACT** (with source),
**INFER**. Companions: [donor ports](2026-11-23-r2-why-donor-units-were-not-ported.md),
[resource waste](2026-11-23-r2-resource-waste-audit.md).

## 1. What was expected, in the sponsor's words over time (FACT)

| Date | Source | Expectation |
|---|---|---|
| 2026-09-07 | `docs/research/r2-origin/00_PRODUCT_VISION.md` §1 | idea → story → finished media through a **reuse-first**, hybrid, model-agnostic pipeline; humans hold four approval gates (§5); "not zero-human at start" |
| 2026-10-18 | memory `v2-release-story-authoring-intent` | V2 = V1 + story authoring: integrate the existing parts, commercial quality, to production |
| 2026-10-21 | session transcript | "tận dụng những gì có sẵn, kể cả áp dụng toàn bộ từ các donor, hạn chế xây dựng mới" |
| 2026-11-01 / 11-02 | memories `autonomous-production-delegation`, `local-models-for-plumbing-cloud-for-quality` | fully automatic idea → export, no mandatory human step; cloud models for quality; compare with donors |
| 2026-11-15 | memory `content-forms-coverage-goal` | every genre and form the donors support |
| 2026-11-22 / 11-23 | transcripts, ADR-0169 | "app của chúng ta là lấy những phần tốt nhất và giống với các donor nhất"; best parts taken whole, quality equal or better |

The expectation moved from **a governed production OS with human gates** to **an automatic app assembled from the
donors' best parts at commercial quality**.

## 2. What was built (FACT)

- **Foundation frozen on 2026-09-06** (`docs/r2/R2_01_FROZEN_ARCHITECTURE.md`, `R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md`,
  "Human Showrunner approved"):
  - roadmap §1 "Implementation proceeds by executable vertical milestones, **not by wholesale donor merge**";
    invariant 6.3 "**Do not merge donor repositories wholesale**";
  - architecture §26: donors get a *role* (DramaClaw: "Creative Canvas, Visual Workbench, optional DC-Media
    transport"); "**R2 custom core**: Authority, lineage, context, transactions, routing, learning";
  - §28.1–2: no donor becomes a core authority, no donor store becomes authoritative; §28.7 "**Broad donor research
    is closed**".
- **Neither frozen document has changed since** (`git log -- docs/r2/R2_01_FROZEN_ARCHITECTURE.md
  docs/r2/R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md` shows only the 09-06 import). No architecture-change approval was
  recorded after any of the expectation changes in §1.
- **Where the work went** (1 981 commits since 2026-09-06 on `impl/r2-film-quality`):
  764 docs-only (39 %); 726 whose subject is governance, authority, custody, grants, fences, attestation, lineage,
  Canon, acceptance, review, evidence or qualification; 152 touching media, film, render, video, TTS or storyboards.
  Code: `r2/` 45 198 lines + `server/production_run/` 12 763; tests 344 965 lines; docs 30 MB (162 ADRs,
  147 research notes, 301 evidence files).
- **Milestones**: M0–M7 and V1 by 09-29; October on M8–M12 authority packets (frame custody, exact-byte review
  proofs, grants, Canon branches). The **first automatic film** came on 2026-11-08 (run 6de90785, REWORK).
  11-10 … 11-23: 91 releases, 44 % repairing the run-governance layer and reviewer qualification.
- **A reset was already tried.** `docs/r2/R2_DELIVERY_RESET_2026-10-06.md` found that "slow visible progress comes
  from treating many internal custody and authority increments as separate completion points", and changed the
  workflow — but stated that it "changes the delivery workflow, **not the frozen architecture, authority contracts,
  release gates**". The cause it found was left in place.
- **Today's state**: after 2.5 months of R2, a 28-second drama episode with a missing second character, identity
  drift and REWORK verdicts; the first ported donor unit ran on its first try, then was fed by our own stages and
  produced an empty appearance and Chinese identity names (run 010a7912).

## 3. Why it went wrong (INFER, each from the facts above)

1. **The expectation changed; the foundation did not.** Every later instruction (reuse whole, automatic, like the
   donors) contradicts a frozen invariant (no wholesale merge, custom core owns authority, human gates). Agents are
   told to respect frozen authority boundaries (AGENTS.md "Reuse-first … authority 边界"), so each instruction was
   absorbed *inside* the old foundation: automation became grants, preflight, qualification and fences around human
   gates; donor reuse became "study the mechanism, rewrite it into our contracts". Nobody — the agent included —
   raised the conflict and asked to reopen the freeze.
2. **The foundation optimised for governance, not for the product.** The custom core (authority, lineage,
   transactions, evidence, custody) is the part no donor has; it is 45 k+ lines with 345 k lines of tests, and every
   real run meets its edges (44 % of recent releases). The donors that already make films (DramaClaw, OpenMontage,
   huohuo-drama) were kept as reference roles.
3. **Progress was measured by internal gates, not by films.** Milestones closed on acceptance packets, independent
   reviews and evidence files (39 % of commits are docs). The first measure of the actual product — an automatic
   film — came two months in; quality has been measured only since.
4. **Research was used to justify rewriting.** Donor studies ended in mechanism and gap tables; ADRs then
   re-implemented. The rule "Broad donor research is closed" stopped the question "should we take this whole?".
5. **Agreements lived in chat.** The 10-21 instruction never reached a rule; compactions dropped it; the agent
   (me) repeatedly skipped research-first, codebase-memory and donor rules until hooks were added today.
6. **Each fix was local.** Blocks were fixed one instance at a time (same roots fixed twice), and each new stage was
   wired with our own glue (today: identity planner fed by a cast that never registered the second character).

## 4. What keeps it from happening again

Mechanisms (not intentions). Items 1–3 need no product decision and are proposed for the rules now; item 4 is the
decision the sponsor has to take, after the research it names.

1. **Intent register over frozen documents.** `docs/r2/SPONSOR_INTENT.md` lists the sponsor's current goals with
   dates and quotes, newest first. Rule: a sponsor intent newer than a frozen document **supersedes it where they
   conflict**; the agent must name the conflicting frozen clause in its reply the same day and propose reopening it.
   No work may proceed under a clause the register contradicts.
2. **Outcome before ceremony.** Each work item names the film-level outcome it improves (a run that succeeds, a
   reviewer verdict, a defect seen by eye) and the run that proves it. Docs-only and governance work stays below a
   share the sponsor sets; the waste audit's classes (G/Q/C/F/U) are counted per week in the block ledger.
3. **Hooks, ledger and port lists** (in place today): codebase-memory first; `Donor:`/`Consumers:` in code commits;
   the per-turn rule reminder; the run block ledger; donor research ends in a port list.
4. **Re-foundation decision (sponsor).** Research the options with evidence before choosing, for example:
   (a) keep the R2 core and port donor units into it (today's path); (b) take a donor pipeline whole as the engine
   per form — DramaClaw for drama, OpenMontage for non-fiction, huohuo for novels — with ArcReel/R2 reduced to the
   shell, settings, accounts and the run panel; (c) a mix. Criteria: time to a PASS-quality film per form, recurring
   cost, how much of our custom core each keeps. Until decided, no new governance or core mechanism is built.
