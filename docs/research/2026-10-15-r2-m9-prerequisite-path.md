# R2 M9: the prerequisite path on the V2 lineage

**Date:** 2026-10-15. **Base:** `23cf146a`, the M8 implementation acceptance on `impl/r2-m8f-utility`. That
branch is not yet merged into `r2-v2/main`. **Branch:** `design/r2-m9-v2-revalidation`.
**Sponsor direction:** after M8, go straight on to M9.

## Facts

1. **The M9 design set is proposed, not accepted, and it lives outside V2.** It consists of ADR-0081, the
   design spec, the umbrella plan, the M9-A packet, the execution contract, the design-acceptance
   contract, the two schemas, the verifier with its tests, and the research and validation notes. All of
   them are committed only on `design/r2-m5b-narrative-context` (`8ce1ad67`, `d42e9a49`, `f4d3b0d8`).
   The 2026-09-15 handoff records that no blind design review was ever sealed.
2. **The M9 execution contract** requires four acceptances before any M9 code:
   - `M9_DESIGN_ACCEPTED`;
   - `M8_IMPLEMENTATION_ACCEPTED`, now met at `23cf146a`;
   - `FACTUAL_AUTHORITY_IMPLEMENTATION_ACCEPTED`;
   - a combined-base acceptance.
3. **No durable Factual Authority exists.**
   - Only the contracts exist (`r2/contracts/factual.py`: `SourceRecord`, `EvidenceRecord`, `Claim`,
     `ClaimLedger`) plus the M3 fixture.
   - There is no ORM model, repository, service or route.
   - The frozen M0–M8 roadmap never assigned that implementation. ADR-0080 calls it "existing", which
     is not true. No packet owns it.
4. **Only M9-D consumes the Factual port.** M9-D is the Greenlight + M8 Canvas seed + Factual bridge
   packet, in umbrella plan Task D. M9-A, the foundation and cohort profiles, imports only the existing
   factual contracts (packet A1.5). M9-B and M9-C do not call the port.
5. **The V2 seams changed after the M9 design was written:**
   - ADR-0105: lineage v2 binds the admitted M6 profile.
   - ADR-0106: scoped M7 candidate ids.
   - ADR-0107: client Canvas appends must carry a server-resolved lineage.
   - M8 acceptance itself.

   `M8CanvasSeedPort` and `M8LearningReadPort` are still unimplemented. The M9 spec defines them as M9-side
   adapters over accepted M8 services.
6. **M9 design acceptance** requires "two distinct author-independent mutually blind reviewers"
   (`required_acceptance_properties`). ADR-0108 changed the review rule for M8 acceptance only.

## Inference

- **Factual Authority is the critical-path blocker,** but only for M9-D. Requiring its acceptance before
  M9-A blocks three packets (A–C) that do not use it.
- **The design must be revalidated before it is accepted.** Accepting the proposed design as written
  would bind hashes to text that predates the V2 seams.

## Decisions (agent, by sponsor delegation of technical choices)

- **DEC-M9-1: port the design set unchanged.** The design set moves onto this branch byte for byte, as a
  docs-only commit, so the recorded hashes stay comparable.
- **DEC-M9-2: revalidate against `23cf146a` in one revision commit, before design acceptance.** The
  revision:
  - (a) updates the seams for ADR-0105, ADR-0106 and ADR-0107: an M9 Canvas seed is created server-side
    under the server-resolved lineage, never through the client append route;
  - (b) moves the Factual Authority acceptance from the M9-A release gate to the M9-D release gate. M9-A
    to M9-C then start from accepted M8 plus the accepted M9 design;
  - (c) recomputes the contract hashes.

  The design is still proposed, so this is a revision, not an amendment of an accepted contract.
- **DEC-M9-3: Factual Authority gets its own prerequisite packet (FA-1) before M9-D.** Its minimum scope
  is what M9 consumes:
  - durable `SourceRecord`/`EvidenceRecord` submission with command-id replay and qualified lookup;
  - invalidation with receipts.

  ResearchPack and Claim review remain later work. FA-1 runs its own research, spec, plan, review and
  acceptance.
- **DEC-M9-4: design acceptance uses the existing M9 verifier and schemas,** with the reviewer kind
  decided by the sponsor (see Unknowns).

## Unknowns

- **U1 (sponsor):** who reviews the M9 design? The contract requires two author-independent, mutually
  blind reviewers. Two options:
  - qualified humans;
  - an ADR-0108-style amendment to two fresh blind model agents.
- **U2:** whether the merge of M8 into `r2-v2/main` happens before the M9 combined-base acceptance. The
  combined base must descend from the accepted M8 commit; the merge itself is the sponsor's call.

## Order

```text
port design set -> revalidation revision (seams, Factual gate moved to M9-D, hashes)
 -> M9 design blind reviews + acceptance -> combined base (M8 + M9 design)
 -> M9-A ... M9-C   |   FA-1 research/spec/plan/impl/acceptance (parallel track, before M9-D)
 -> M9-D (needs FA-1) -> M9-E -> M9-F
```
