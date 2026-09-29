---
status: accepted
---

# V2 makes the M7 database master head the sole master authority; the manifest master is its projection

M7-B built an atomic database master authority but never composed it into the host. Live
approval still writes the file manifest's `approved_master` through `ProductionApprovalService`.
That leaves two master stores, one of them unreachable, and it stopped M8-A
(`docs/r2/evidence/R2_M8_A_STOP_2_2026-09-29.json`). The research is
`docs/research/2026-09-29-r2-m8a-master-authority-seam.md` (V2-02 section). The sponsor
delegated the choice.

**Decision: complete M7-B's specified wiring (option U1).**

1. **Authority.** For every R2 artifact served by the host, the master is the M7 master head
   (`master_authorities` / `master_head_versions`). It is written only by
   `AtomicPromotionService.promote`.
2. **Candidate objects.**
   - **What the object is.** A promoted candidate's object is its immutable host version file,
     registered through `prepare_candidate` (verify-in-place) and `CandidateObjectRepository`.
   - **Its id.** The M7 `candidate_id` is `m7c:` followed by the first 40 hex digits of
     `sha256(artifact_key + "\n" + generation_candidate_id)`.
3. **Gate C.** The final-cut route runs these steps in order:
   1. stage the host version (unchanged);
   2. in one transaction, register the candidate object and promote the master head, with
      `command_id` equal to the route's operation id. The promotion writes its receipt and
      the promoted event;
   3. project the file manifest through the existing `ProductionApprovalService`, which is
      idempotent;
   4. write the export copy, then the Gate C receipt.

   A failure after step 2 is retried by the same `approval_record`: every step replays.
4. **Projection and reads.**
   - `FileMasterProjection` implements `LegacyMasterProjection` from the manifest's
     `approved_master`, mapped through the same candidate-id function.
   - Every server route that consumes a master first calls `DatabaseMasterResolver.get_exact`
     for each artifact it reads, and refuses a divergence with 409 `master_diverged`. The
     routes are Gate C composite dependencies, publish approval, deliverable listing and
     download.
   - The file checks already in `r2/m3/deliverables.py` stay as a second line.
5. **Backfill.** `scripts/r2/backfill_master_authority.py` promotes every existing file master
   that has no database head. It is operator-run, idempotent, and uses the deterministic command
   `backfill:<artifact_key>:<candidate_id>`.
   - It is a release step for existing deployments.
   - Offline `GoldenARunner` output stays file-only until it is backfilled.
6. **Enforcement.** An architecture test rejects any call to `ProductionApprovalService` or
   `GoldenAHostIntegration.approve` outside the projector and the offline runner. It also
   rejects any construction of `AtomicPromotionService` outside the host composition.

## Considered options

- **M8 promotes through `ProductionApprovalService` (U2).** Rejected. It is a file-based,
  non-CAS writer with no receipt, so the seam is non-atomic, and the M8 contract forbids
  substituting an authority.
- **Leave M7 uncomposed and let M8 write to it (U3).** Rejected. The promotions would be
  invisible to production, and the host would have two live masters.
- **Make the Gate C receipt table the authority.** Rejected. It records approvals; it has no
  master version CAS, candidate object or retention.

## Consequences

- **Stores.** One master authority, with the manifest as its guarded projection. M8-A resumes at
  A0 unchanged.
- **Release step.** Existing projects (the operator trial, restore drill targets) must be
  backfilled before readers accept them. The runbook gains the step.
- **The restore drill** adds a check that the database head equals the projected manifest
  master for each product.
