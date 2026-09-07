---
status: accepted
---

# Canon authority uses append-only deltas with rebuildable resolved projections

R2 Canon needs immutable history, auditable branch overlays, atomic commits, and deterministic reads without creating a second project authority. Store `CanonBranch`, immutable `CanonVersion`, and the accepted `CanonDelta` in the existing asynchronous ORM database. A branch pins an immutable parent version and records only its local deltas. `CanonTransactionService` is the only writer: it locks the branch head, verifies the caller's base version, validates the candidate resolved view, appends the delta and version, advances the head, and refreshes the resolved projection in one PostgreSQL transaction. The resolved projection is a disposable read optimization whose hash must match the authoritative version; it may be deleted and rebuilt by replaying the pinned parent lineage and local deltas.

## Considered options

- A complete snapshot as the authority for every version makes reads simple but duplicates parent Canon into each branch and weakens the distinction between an overlay and its resolved view.
- Fully normalized temporal tables make individual facts easy to query but spread one Canon commit across many validity joins and make branch resolution substantially harder before the M5 benchmark demonstrates that need.
- An append-only delta authority matches the frozen `CanonDelta → CanonVersion` contract directly. A rebuildable projection keeps ordinary reads simple without gaining commit authority.

## Consequences

- PostgreSQL is the production-development baseline; SQLite remains a supported focused-test dialect where the existing test suite uses it.
- Canon deltas and versions are immutable. Corrections append a new delta rather than updating history.
- A narrative branch remains pinned to its parent version until an explicit rebase operation is designed; parent advancement cannot silently change the branch.
- Projection loss or hash mismatch is recoverable by replay. Projection data must never be used as independent evidence that a Canon commit occurred.
- M5 starts with deterministic replay and one projection per committed version. More elaborate checkpoints or normalized query indexes require measured evidence from the 30-scene fixture.
