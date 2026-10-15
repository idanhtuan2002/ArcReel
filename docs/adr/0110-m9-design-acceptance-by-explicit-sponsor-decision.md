---
status: accepted
---

# M9 design acceptance records an explicit sponsor decision for one candidate

On 2026-10-15 the sponsor said: `chap nhan m9 roi sang buoc tiep theo luon` after the agent identified
`24fa05e0610efa6fb60db50d1b22b10de48f2786` as the revised M9 design and reported the missing independent
reviews. This directly accepts that design and authorizes proceeding to Task P0.

The sponsor decision replaces the two-fresh-reviewer acceptance condition of
ADR-0080 and the M9 design review contract **only for this exact candidate**.
ADR-0081 changes status only. No reviewer PASS is created: the earlier FAIL and
unavailable second review stay historical evidence, and the revised candidate
has not received two independent reviews.

The decision is recorded as `M9_DESIGN_ACCEPTED` with
`acceptance_mode=EXPLICIT_SPONSOR_DECISION` in `R2_M9_DESIGN_ACCEPTANCE.json`,
validated against the dedicated sponsor schema. Its twelve artifact hashes
are recomputed from the accepted candidate Git objects, and its amendment,
status-only ADR transition and exact acceptance changed-path set are bound.
The old two-review schema/verifier remains unchanged and applies to that review
ceremony; its rejection of a sponsor-shaped record is not a passing review.
Task P0's verifier checks this explicit sponsor basis for the combined base.

The acceptance commit is the sole child of the accepted candidate and changes
only ADR-0081 status, this ADR, the sponsor record/schema and the M9 handoff.
This one-candidate exception changes no later packet review, prerequisite,
Factual Authority release, production activation or push requirement. In
particular, M9 implementation is not accepted: P0 must establish its combined
base before M9-A may begin, and FA-1 remains required before M9-D.
