---
status: proposed
---

# ProductionBinding has one versioned authority and carries an exact spatial constraint reference

ADR-0095 stopped M8-C promotion because R2 has a `ProductionBinding` contract but no persistent authority. This ADR chooses the full promotion path over a candidate-only amendment. It is a design candidate until the review and acceptance gates below pass. It does not release the stopped M8-C implementation.

## Evidence and decision boundary

The [binding research](../research/2026-09-30-r2-m8c-production-binding-authority.md) and [consumer comparison](../research/2026-09-30-r2-m8c-consumer-options.md) establish that current bindings and `SceneSpec`/`ShotSpec` are fixture or pure values in the inspected R2 runtime, M8-A refuses the binding target, and no live generation path reads spatial constraints. The bounded searches cover `r2`, `lib`, and `server` at the stated worktree HEAD; they do not prove global absence. The graph index is for another checkout and predates these M8 files.

The accepted M8 design assigns `SpatialCandidate` to `PRODUCTION_BINDING`. A candidate-only packet would leave C2's promotion and M8-D's dependency unsatisfied. A binding store with no typed spatial value or consumer would accept data without a production effect. The selected design supplies all three, in dependency order: target and binding authority, spatial representation and read path, then M8 promotion. This is an inference and design choice from the cited evidence, not a claim that those components already exist.

## Decision

1. **Production Preparation owns binding writes.** A project-scoped PostgreSQL head keyed by `(user_id, project_name, binding_id)` points to immutable binding versions. Each version stores a v1 `ProductionBinding` body, its canonical digest, optional exact spatial constraint ID and digest, actor, command key and provenance. The v1 schema and existing fixture serialization stay intact; a spatial update increments the body's `version` and the version envelope carries the new spatial reference. A single writer performs expected-version CAS, command replay validation, append and head advance in one transaction. M8 calls this authority through a narrow port inside its promotion transaction; Canvas, M7 master slots, asset rows and manifests are never independent binding writers.
2. **Targets have checked identities.** A production binding may reference only an exact, approved, project-scoped `SceneSpec` or `ShotSpec` version registered by Production Preparation. Since the inspected host has no such persistent registry, the first authority packet includes an explicit target registration and exact-version reader. An opaque client `target_id` or a Golden fixture cannot stand in for this check. Binding creation requires a separate Production Preparation command with typed semantic, production, role and asset identities; M8 spatial promotion can only update an existing `LOCATION` binding and cannot create one or replace its core refs. An approved reference claim needs an exact content digest and custody proof from its owning authority. The mutable global asset row alone is insufficient.
3. **Spatial evidence stays separate from production facts.** A typed immutable `SpatialConstraintSet` selects assertion IDs from one exact `SpatialCandidate` revision. It records source media authority identity/digest, source spans, observed view, semantic relation, seam and direction locks, duplicate exclusions, normalizer version and provenance. A production constraint is derived only from explicitly selected `VISIBLE` assertions whose source identity and spans resolve exactly. `INFERRED`, `GAP`, unknown source, and conflicting assertions remain in the candidate and preview as evidence; they cannot be promoted as facts. The original candidate revision is never rewritten. No donor free text is accepted as a binding identity.
4. **One exact snapshot drives readers.** The binding authority returns a snapshot ID over ordered binding IDs, versions and envelope digests. Readiness and content fingerprinting use that same snapshot; a changed binding head invalidates stale readiness. A typed spatial resolver reads the constraint set through the exact binding version and passes its permitted constraints into R2 `PromptPlanner`/compiler output. The selected donor consumer is only a behavior comparison; R2 must test its own prompt effect on the same fixture and preserve visible/inferred/gap boundaries. The legacy M7 provider submitter is not given an unreviewed spatial wire change.
5. **Promotion is preview-bound and atomic.** The M8 preview carries the exact candidate revision/digest, selected assertion IDs, typed constraint-set proposal/digest, existing binding ID/version/envelope digest, target version/digest, source media digests, actor scope, impact and expiry. Authorization names its preview digest. Promotion locks command key, candidate head, preview, binding head and referenced target/source identities in a fixed documented order. It revalidates all bound identities and selected evidence, then writes the constraint set, binding version, authorization, promotion receipt and command receipt in one transaction. Exact replay returns the stored receipt; changed body with the same command key fails. Stale, corrupt, unauthorized or expired inputs commit none of those rows.

## Interface consequences

- The current M8 preview request has only candidate, revision, target and command ID. It needs a typed spatial proposal or a separately persisted digest-bound proposal. The untyped `impact` field cannot carry a client-authored binding body.
- The production snapshot and spatial resolver are new contracts. Existing Golden fixtures remain offline values unless explicitly registered; no backfill silently turns them into production authority.
- A binding version may attach a spatial constraint while preserving the v1 field schema. Its version changes; snapshot fingerprints must include the envelope digest so a spatial change cannot masquerade as the previous production input.
- The source media references must resolve to immutable, exact M7 authority objects or another independently reviewed custody seam. Asset URLs and mutable asset rows are not sufficient.

## Alternatives rejected

- **Candidate-only M8-C and roadmap amendment:** safe as an interim milestone but does not satisfy the accepted C2 promotion target or M8-D release dependency. It remains the behavior while this authority is absent, not the completion criterion.
- **Put spatial prose in `ProductionBinding.production_ref` or `asset_refs`:** destroys the identity meaning of those fields and loses typed seam/gap provenance.
- **Promote through an M7 artifact slot:** a master artifact is not a semantic-to-production binding and ADR-0095 already rejects that substitution.
- **Create a binding from donor JSON:** generic spatial relations lack the typed target, semantic, production and approved asset identities. This would turn inference into authority.
- **Extend the v1 binding body directly:** adds new serialized fields to a frozen contract and changes existing fixture/content hashes without a migration need. A version envelope gives exact spatial identity while preserving the v1 schema.

## Required acceptance sequence

1. Review and accept this ADR and a concrete design spec for target registration, binding CAS, immutable constraint storage, digest domains, reference custody, authorization and transaction order. Confirm that the new target registration is the minimum necessary authority and that no existing owner can be reused.
2. Implement and independently accept target/binding authority with corruption, stale-head, cross-project, replay, rollback and snapshot-reader tests. Then implement the typed spatial resolver and same-fixture prompt-consumer proof. The authority must be useful and checked before M8 writes to it.
3. Execute M8-C C1 candidate normalization and C2 bounded execution independently of the blocked promotion step. Only after step 2 may C2 add preview/authorization/promotion. Reseal donor differential parity, exact integrated HEAD, required skips and independent review under R2-DEC-031. M8-D starts only after the complete M8-C packet is accepted.

Until these gates pass, `PRODUCTION_BINDING` preview/promotion continues to fail closed with `M8_REQUIRED_EVIDENCE_MISSING` at the packet level and `m8_promotion_target_unavailable` at the API boundary. No candidate-only result is reported as M8-C acceptance.
