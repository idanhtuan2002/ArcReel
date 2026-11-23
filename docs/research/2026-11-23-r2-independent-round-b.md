# R2 independent round B — What the assembly will produce (2026-11-23)

Reviewer: independent read-only agent (Opus), brief B + common context of
`docs/r2/evidence/assembly-research-briefs.md`. No edits outside this file, no docker, no network, DramaClaw untouched.

## Method

1. Read common context (GOAL, ADR-0170, ASSEMBLY_PLAN, ASSEMBLY_ACCEPTANCE, verification round) and B-specific docs
   (cloud-free quota registry, donor stage mechanisms 2026-11-08, craft quality program incl. smoke run b961dc0a).
2. Walk one story through each step, reading the pinned donor code/prompts (DramaClaw b299bfd, huohuo f104b85,
   OpenMontage 08e2151) to predict the output with the stated models.
3. Count model calls per episode vs quotas; compare with GOAL's quality bar and the old app's films.
4. Every claim labelled FACT (file:line) or INFER. Findings appended as found.

## Findings (appended in order)

