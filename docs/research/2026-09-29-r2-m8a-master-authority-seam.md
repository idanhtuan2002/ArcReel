# M8-A second seam stop — the M7 master authority has no production composition (2026-09-29)

This is research. It records a stop and the options for resolving it, with a recommendation.

## Facts at `e455ab05`

- **The M7 authority exists but is not composed.** `AtomicPromotionService.promote` is atomic:
  it checks the receipt, the candidate and the version with CAS, inserts the head version,
  advances the head, writes the receipt and the promoted event, and commits once. It is
  constructed only in unit tests, and no host module composes it. The same holds for
  `DatabaseMasterResolver`, `MasterAuthorityRepository` and `CandidateObjectRepository`.
- **No legacy projection is implemented.** `DatabaseMasterResolver` would fail closed with
  `MasterDivergedError` if a legacy projection disagreed. No such projection exists.
- **The live master authority is different.** Live approval runs through
  `ProductionApprovalService`, reached from `GoldenAHostIntegration.approve` and the Gate C route.
  It uses the M2 artifact bridge's file-based masters and writes the `gate_final_cut_receipts`
  table.
- **The bridge was deferred.** The P1 design deferred the `AtomicPromotionService` ⟷ M3/M4
  bridge. Its blocker was that M3/M4 candidates are `GenerationCandidate`s, while M7 promotes
  `VerifiedCandidateObject`s from `CandidateObjectPort.prepare_candidate`.
- **The M8 design assumed otherwise.** It assumes the M7 Production Authority is *the* production
  authority, with a compatibility projection owned by M7. Plan A3.5 says "Compatibility projection
  remains the M7 projector's responsibility". There is no projector.

**Inference:** if M8-A promoted into the M7 tables, its promotions would be invisible to
production. The host would also gain a second live master writer that no reader reconciles.
This is the duplicate-authority case the contract stops on.

## Options

| Option | Assessment |
|---|---|
| **U1: unify the master authority first** (a V2 packet before M8-A) | Route M3/M4 candidates through `prepare_candidate`. Make Gate C approval promote through `AtomicPromotionService`, the one writer. Implement the `LegacyMasterProjection` that projects DB heads to the file-based masters the renderer and export read, so `DatabaseMasterResolver` is the one read. M8-A then promotes into the real authority, as designed. This is the named deferred work. It touches Gate C, O2a export and the restore drill. |
| U2: M8-A promotes through `ProductionApprovalService` | That is substituting an authority, which the execution contract forbids. The service is also synchronous and file-based, with no CAS receipt, so the seam is non-atomic. |
| U3: M8-A writes to the uncomposed M7 tables | This follows the letter of the contract but has no production effect. It creates a second writer and defers the divergence. |

## Recommendation

**U1**, as its own packet (V2-02, master authority unification). It needs:

- research into the M2 bridge's master files and the readers of the O2a export and the
  restore drill;
- an ADR;
- a spec and plan;
- implementation;
- an independent review.

M8-A resumes at A0 once V2-02 is accepted, and needs no change to its design. Unknowns for V2-02
research:

- whether every M3/M4 candidate shape maps to `VerifiedCandidateObject` without loss;
- how existing projects' file-based masters are backfilled into DB heads;
- whether the Gate C receipt table becomes a projection or stays as the audit record.
