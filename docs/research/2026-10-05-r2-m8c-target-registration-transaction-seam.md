# M8-C target registration transaction seam — source checkpoint

Status: bounded source finding for the next authority gate, not an accepted implementation design. Inspected code HEAD `88e568f242994a21049209adccc2bea75f351be4` on `impl/r2-m8c-frame-receipts`. The repository knowledge graph generation predates this worktree's new modules, so the cited sources were read directly.

## Observed source behavior

- `r2/adaptation/screenplay_reader.py` implements `ApprovedScreenplayReader.get_exact_admitted` through its own `AdaptationUnitOfWorkFactory`. It checks the exact admission row, locks the screenplay admission head, folds its decisions, compares the effective decision and selected artifact, and verifies screenplay content hash before returning the screenplay.
- `lib/db/adaptation_uow.py` creates a fresh `AsyncSession` per reader call and rolls back and closes that transaction on exit. `lib/db/repositories/adaptation.py` takes a PostgreSQL row lock in `prepare_or_lock_head`.
- `r2/production_intelligence/take_director.py` accepts a structural `ApprovedScreenplayReaderPort`; `TakeDirectorAdapter.direct` calls it once and derives scene and shot values. Its first Take bodies stamp `version=1`. The existing two-admission probe in `tests/integration/r2/adaptation/test_screenplay_admission.py` confirms a changed admitted screenplay can retain the same target ID and body version while changing the target content.
- ADR-0102 and `docs/superpowers/specs/2026-09-30-r2-m8c-binding-authority-design.md` require target registration to re-read current admission and append/advance target registry authority in one transaction. Calling the existing reader and then writing the target in a separate session would leave an admission-advance interval between check and commit.

## Next design check

Design a transaction-bound screenplay reader port using the same `AsyncSession` and existing `AdaptationRepository` checks, while preserving the public `ApprovedScreenplayReader` path for its current callers. Pass that port into the existing `TakeDirectorAdapter` so target derivation reuses its behavior. Define and verify the cross-family lock order for admission head, target head and binding head before schema or writer implementation. Prove with a forced PostgreSQL interleaving that admission advance cannot slip between target proof and registry commit; also test exact replay and two admissions with the same target ID but different canonical digests. This is an implementation direction to evaluate, not an accepted authority decision.
