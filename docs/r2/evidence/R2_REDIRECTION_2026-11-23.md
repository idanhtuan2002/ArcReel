# R2 redirection, 2026-11-23 — research trail and state

Durable index of the research and decisions of 2026-11-23 that changed the project's direction. Read this first when
resuming. Branch `impl/r2-film-quality` (pushed). Production: ArcReel `r2-v2.5.90`, frozen.

## Decision

[ADR-0170](../../adr/0170-assemble-the-donors-best-stages-whole.md): the product is an assembly of the donors' best
stages, taken whole — huohuo-drama `f104b85` writes the story (Chinese, ERNIE via OpenRouter), our existing story
translation makes it Vietnamese, DramaClaw `b299bfd` makes the film (its own docker-compose: api + NewAPI gateway +
web, only models substituted), OpenMontage `08e2151` later for non-fiction. Our code is the connector and the model
configuration. ArcReel/R2 is frozen and keeps serving production; no bake-off (sponsor).

## Research trail (in order)

1. [Why donor units were not ported](../../research/2026-11-23-r2-why-donor-units-were-not-ported.md) — research
   ended in gap tables, ADRs never had to justify rewriting.
2. [Resource waste audit](../../research/2026-11-23-r2-resource-waste-audit.md) — 91 releases in 14 days, mostly
   repairs of our own run governance; [run block ledger](R2_RUN_BLOCK_LEDGER.md).
3. [Donor shot timing and identity use](../../research/2026-11-23-r2-donor-shot-timing-and-identity-use.md).
4. [Why the project went off course](../../research/2026-11-23-r2-why-the-project-went-off-course.md) (rounds 1–2,
   from all 698 sponsor messages): the sponsor's goal — assemble the donors' best parts, quality ≥ donor, one
   operator — lived in chat; an authority-first architecture frozen on 09-06 ("do not merge donors wholesale")
   governed every decision and was never reopened.
5. [Operating model vs large organisations](../../research/2026-11-23-r2-operating-model-vs-large-organisations.md)
   (round 3): R2 had the verification half of large-organisation practice and lacked the direction half
   (validation, business case, go/kill, tolerances, single owner, simple skeleton, tailoring).
6. [Review of rounds 1–3](../../research/2026-11-23-r2-review-of-the-off-course-research.md) (round 4): corrections
   (films existed from September; `r2/` is not all governance; shares are estimates; DramaClaw's role was set without
   running it) and a smaller proposal.
7. [Assembly options](../../research/2026-11-23-r2-assembly-options.md) — A status quo, B one donor base, C stage
   assembly, D new repo, E strangler; the sponsor chose stage assembly without a bake-off.
8. [Old app vs new assembly](../../research/2026-11-23-r2-old-app-vs-assembly.md) — what the old app does well and
   carries over without changing direction.
9. [Coverage matrix](../../research/2026-11-23-r2-assembly-coverage-matrix.md) — the assembly must include the old app
   and every donor; gaps filled by a donor running whole, another donor's whole unit at an extension point, or the old
   app's unit as a connector feature or post-stage.

## Rules added on 2026-11-23

- AGENTS.md: "Donor 整体移植" with Port / Why-not-ported sections and port lists; "资源浪费防线" (class fixes, state
  sweeps, recurring-cost approval, run block ledger).
- Hooks (`.claude/hooks/`, installed for the main checkout via `settings.local.json`): codebase-memory before grep on
  source, `Donor:` / `Consumers:` in code commits, per-turn rule reminder.

## State to resume from

- Stopped and left as is: ArcReel drama run `010a7912` (episode 2, BLOCKED at SCRIPT, cast not registered); ADR-0168
  identity-planner port and its wiring (superseded by ADR-0170: DramaClaw runs its own planner).
- Unreleased on the branch: donor-sourced render values (`8f445ddbc`), hooks; not to be released unless a production
  fault needs it.
- Next: `docs/r2/ASSEMBLY_MODELS.md` (DramaClaw and huohuo model slots → substitutes), bring DramaClaw up, first film
  from the existing story "Chiếc đồng hồ của ông", then the huohuo story stage and the connector.
