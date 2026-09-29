---
status: accepted
---

# M8-A promotes to artifact slots only; the ProductionBinding target waits for a binding authority

M8-A's step A0.2 stopped with `M8_BASE_SEAM_CHANGED`
(`docs/r2/evidence/R2_M8_A_STOP_2026-09-29.json`). The M8 design (spec §4) has two promotion
targets:

- `ARTIFACT_SLOT`, owned by the M7 Production Authority;
- `PRODUCTION_BINDING`, owned by "the existing R2 Production Binding authority".

It requires A0 to find that authority's atomic seam, or to stop.

**Facts at `27881800`:**

- **ProductionBinding is only a contract class.** It is `r2/contracts/preparation.py:20`, used by
  fingerprints and the production-intelligence fixture loader. No model, repository, service or
  transaction persists or writes it. The M4 spec names it as the owner of reference assets and
  semantic-to-production bindings, but no milestone built that store.
- **The ARTIFACT_SLOT seam is complete.** It consists of:
  - `AtomicPromotionService.promote`;
  - `DatabaseMasterResolver.get_exact`;
  - `CommandReceiptRepository`;
  - `MasterAuthorityRepository.append_promoted_event`.
- **Only one candidate kind needs the missing target.** `SpatialCandidate` is the only kind that
  targets `PRODUCTION_BINDING`, and it is produced by M8-C. `CanvasCandidate` and
  `FormatCandidate` target `ARTIFACT_SLOT`.
- **The error key already exists.** The M8-A plan defines `m8_promotion_target_unavailable` (409)
  for an unsupported target or seam.

The sponsor delegated the choice.

**Decision:**

- **What M8-A implements.** It implements the whole contract universe, both target kinds
  included, and the complete `ARTIFACT_SLOT` promotion.
- **How the missing target behaves.** A preview or promotion whose target is
  `PRODUCTION_BINDING` fails closed with `m8_promotion_target_unavailable`. It writes nothing:
  no preview row, no authorization and no receipt.
- **Why no substitute is used.** No other store stands in for the binding authority.
- **The new prerequisite.** A persistent ProductionBinding authority, with an atomic, CAS-versioned
  writer and its own design and ADR, is a prerequisite of SpatialCandidate *promotion* in M8-C.
- **What M8-C can still do without it.** It can still validate and append SpatialCandidate
  revisions, which need no binding writer.
- **The M8-A test obligation changes.** The A3 test "ProductionBinding translation rejecting
  `GAP` assertions" becomes "a `PRODUCTION_BINDING` target is refused as unavailable before any
  write".

## Considered options

- **Build the binding authority before M8-A.** Rejected for now. It creates a new production
  authority with no consumer until M8-C, and it needs a design of its own (M4 ownership of
  reference assets, CAS identity, migration of fixture bindings). Starting it now would put
  unreviewed authority design in front of the packet that needs none of it.
- **Remove `PRODUCTION_BINDING` from the universe.** Rejected. It discards a reviewed design
  intent that M8-C will need, and it changes the contract shape twice.
- **Promote spatial evidence through `ARTIFACT_SLOT`.** Rejected. That substitutes an authority,
  which the execution contract forbids.

## Consequences

- **The M8 execution contract.** Its second amendment
  (`R2_M8_EXECUTION_CONTRACT_AMENDMENT_2_2026-09-29.json`) records this decision and the new
  executor base.
- **M8-C.** Its promotion step is blocked, with `M8_REQUIRED_EVIDENCE_MISSING`, until an accepted
  ProductionBinding authority exists.
