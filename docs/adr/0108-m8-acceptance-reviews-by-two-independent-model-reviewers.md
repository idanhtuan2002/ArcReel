---
status: accepted
---

# M8 acceptance takes two independent model reviewers instead of two qualified human reviewers

**Sponsor decision (2026-10-15):** after the Codex review refused M8 acceptance because spec §9's
"at least two blind qualified reviews" was unmet, the sponsor was offered three options. The sponsor
chose "Sửa yêu cầu, chỉ dùng mô hình": amend the requirement and use model reviewers only.

## Context

Spec §9 requires at least two blind, qualified reviews per artifact, with disagreement retained, and
a reviewer qualification record: language/cultural cohort, calibration, role and conflict. M8-F first
named the sponsor as the single reviewer (DEC-F-3). The sponsor then delegated that review to the
implementing agent. A recorded deviation cannot make an unmet frozen requirement pass, so the sponsor
amended the requirement. The amendment is prospective: the evaluation is registered again (protocol
v2) and run again under it.

## Decision

1. **Reviewers.** For M8 acceptance, the blind reviews of the M8-F artifacts come from two independent
   model reviewers:
   - Reviewer A is the implementing agent, Claude (`claude-opus-5-5`).
   - Reviewer B is Codex, run as a separate agent. Codex does not see reviewer A's verdicts or the
     label key, and forms its own measurements.
2. **Calibration and disagreement.** Each reviewer passes the calibration item before its cohort
   verdicts count. Disagreements are retained item by item. A material disagreement blocks acceptance
   until it is adjudicated, and the adjudication is recorded.
3. **Qualification records.** Each record states that the reviewer is a model, its model identity, its
   role, and its conflicts. Reviewer A implemented the code under review; reviewer B did not.
4. **No human review.** M8 acceptance states plainly that no human reviewed the M8-F artifacts.
   Nothing here weakens a human gate (Gate A–D) or any later milestone's review rule.

## Consequences

- Protocol v2 (`R2_M8_EVALUATION_PROTOCOL_V2.json`) replaces v1's roster, deviations and determinism
  definition before any v2 result exists. The v1 results remain historical evidence and do not count
  toward acceptance.
- M8 acceptance is weaker evidence of perceptual quality than human review. The corpus is synthetic,
  so the reviews check that the artifacts are faithful to their sources and to the pinned fixture.

## Rejected

- **Two qualified humans:** not available to the sponsor.
- **The sponsor plus Codex:** offered; the sponsor declined.

## Amendment 1 (2026-10-15, after the second Codex review)

The second Codex review found that reviewer A was not blind. Reviewer A was the implementing agent,
built the packet, and held the label key, and the reviewer prompt disclosed the expected calibration
verdicts. The sponsor's decision (model reviewers only, no human) stands. Blindness is enforced as
follows:

- **Who reviews.** The two reviewers are fresh model instances run as separate agents, neither of
  which implemented M8-F:
  - reviewer A is a new Claude agent with no conversation context;
  - reviewer B is a new Codex agent.

  The implementing agent only builds the packet and records the outcome.
- **What reviewers do not see.** Neither reviewer sees:
  - the label key;
  - which items are calibration items;
  - any expected verdict;
  - the other reviewer's output;
  - earlier review records.

  Calibration items are unlabelled. A reviewer passes calibration only if it independently fails the
  planted defect.
- **Fresh run.** Protocol v3 freezes this roster before a new run and new reviews. The v2 reviews do
  not count toward acceptance.
