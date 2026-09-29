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

## V2-02 research (2026-09-29, at `c8eec594`)

### The M7 design intent (spec 2026-09-12, §6)

- **Promotion.** It CASes exactly one master head. In one PostgreSQL transaction it appends the
  head version, the receipt and the event. "A manifest/version projection is updated after the
  authority commit through an idempotent projector."
- **Reads.** "All authoritative master reads go through one `MasterResolver` that compares the
  database head with the compatibility manifest/version projection and fails with
  `M7_MASTER_DIVERGED`." The projection "may remain for compatibility; it cannot remain an
  unguarded authority."

**Conclusion:** V2-02 is the unfinished wiring of M7-B. It needs no new architecture.

### Pieces that exist but are uncomposed

| Piece | Where | Production caller |
|---|---|---|
| `prepare_candidate` (immutable object, digest and probe, idempotent replay when the final path exists) | `lib/candidate_store.py:83` | none (tests only) |
| `CandidateObjectRepository.insert/get_exact` | `lib/db/repositories/host_hardening.py:805-861` | none |
| `AtomicPromotionService.promote` | `r2/host_hardening/promotion.py:83` | none |
| `MasterAuthorityRepository` (optimistic CAS) | `lib/db/repositories/host_hardening.py:864` | none |
| `DatabaseMasterResolver` + `LegacyMasterProjection` protocol | `r2/host_hardening/master_resolver.py` | none; there is no projection implementation |

### The live path

- **The writer.** Gate C (`server/routers/gates.py`, final-cut) calls
  `GoldenAHostIntegration.stage_candidate`, then `.approve`, and `approve` calls
  `ProductionApprovalService.promote`. That writes `approved_master` into the R2 manifest
  metadata and restores the selected host version as the current file, through
  `ArcReelVersionRestorePromoter`. The route then appends a `FinalCutReceipt`.
- **The only other writer** is `GoldenARunner.run` (`r2/m3/golden_a.py:309`), an offline M3
  harness with no database or user scope (`scripts/r2/run_m3_golden_a.py`).
- **Readers of the file master:**
  - `r2/m3/deliverables.py`: `ApprovedMasterResolver`, the export copy, the deliverable listing
    and the download;
  - `r2/m3/composition.py`: the composite source masters;
  - `r2/m3/golden_a.py`: the offline runner;
  - the Gate C route.

  Each checks the current file's digest against the selected version, so a generic ArcReel
  version restore that changes the current file fails closed.
- **Candidate ids.** A candidate id is `CAND-{target_ref}-V{n}` (`host_integration.py:315`).
  It is unique per artifact but can repeat across episodes of one project, while M7
  `candidate_objects` are unique per `(user, project, candidate_id)`.
- **Version files.** No route deletes a version file at this HEAD. The `unlink` calls in
  `lib/version_manager.py` clean up failed appends, and `server/routers/versions.py` deletes
  thumbnails only (bounded grep). A host version file is therefore immutable once written.

### Unknowns resolved

- **Mapping candidates to `VerifiedCandidateObject`.** Yes, without loss. The object is the
  staged host version file: `object_ref` is its path, `content_digest` its sha256, and
  `media_probe_digest` is the ffprobe stream-summary digest. `prepare_candidate`'s
  existing-final-path branch verifies it without copying.
- **Backfill.** An operator-run idempotent command registers each artifact's selected version
  file and promotes it with a deterministic command id. It is required because the resolver
  treats "file master present, database head absent" as divergence.
- **Gate C receipt.** It stays the Gate C audit record (ADR-0090). The DB master head is the
  authority, and the receipt carries the approval context.
