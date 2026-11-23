# R2 independent round C — What could make the assembly fail (pre-mortem)

Date: 2026-11-23. Reviewer: independent read-only agent (Opus). Brief: section C + common context of
`docs/r2/evidence/assembly-research-briefs.md`.

## Method

1. Read GOAL, ADR-0170, ASSEMBLY_PLAN, ASSEMBLY_ACCEPTANCE, the verification round, and the 2026-11-23 off-course
   research, its review, the waste audit and the operating-model note.
2. Read pinned donor code (DramaClaw b299bfd, huohuo f104b85, OpenMontage 08e2151) where a risk depends on it.
3. Pre-mortem: assume the assembly failed by 2027-02-23; write failure stories; then a risk register.
4. Labels: FACT (file:line) = verified in the file at that line; INFER = my reasoning. No docker, no network.

Findings are appended as they are found (the session may be cut off).

