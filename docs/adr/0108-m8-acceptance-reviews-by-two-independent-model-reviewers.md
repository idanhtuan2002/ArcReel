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
