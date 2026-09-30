# R2 M8-C ProductionBinding authority and spatial promotion design candidate

Status: **proposed**. Depends on ADR-0102 review and acceptance. This packet extends the accepted M8 spec only at the missing `PRODUCTION_BINDING` authority seam; it does not redefine M8-A's artifact-slot path or release M8-C C2.

## Why this packet exists

The frozen domain model makes `ProductionBinding` the semantic-to-production bridge. The accepted M8 spec targets that bridge for `SpatialCandidate`, and ADR-0095 requires a persistent CAS writer before promotion. The inspected R2 source has only in-memory binding and target values; the M8 preview API rejects the binding target; the prompt planner has no typed spatial input. [Source inventory](../../research/2026-09-30-r2-m8c-production-binding-authority.md) and [consumer comparison](../../research/2026-09-30-r2-m8c-consumer-options.md) record the bounded evidence.

## Authority model

| Object | Owning write path | Identity and immutable content | Read rule |
| --- | --- | --- | --- |
| Production target | Production Preparation | project, `SCENE`/`SHOT`, ID, version, canonical `SceneSpec`/`ShotSpec` digest, approval state and lineage | Exact approved version; a shot also resolves its scene in the same project |
| Production binding | Production Preparation | project, binding ID, monotonic version, exact v1 body digest, optional spatial-set ID/digest, envelope digest | Head for admission, exact version for snapshot/readiness |
| Spatial constraint set | Production Preparation via M8 authorized promotion only | immutable ID, digest, exact candidate revision/digest, selected visible assertion IDs, source media IDs/digests and source spans | Exact set only through a binding version |
| M8 candidate/preview/authorization/receipt | M8-A authority | existing IDs and digests plus typed spatial proposal and binding expected head | Exact revision and preview, same transaction as binding update |

Target registration is necessary because a binding's `target_id` otherwise has no checked production identity in the inspected host. Registration is an explicit Production Preparation command, not implicit fixture import. A target version's approval and lineage must be verified against the owning scene/shot authority when one exists; if no live approval authority can be identified, the first packet must define and review its registration admission instead of fabricating an approval flag. Target and binding creation stay outside M8 promotion.

The binding version envelope preserves the v1 `ProductionBinding` field schema and does not change existing fixture serialization. It adds only spatial-set identity and digests around that body. `LOCATION` is the only role eligible for the first M8-C spatial update. An update increments the body's `version` and copies every other v1 field unchanged; it cannot change the target, semantic/production refs, role or asset refs. Other binding edits use a separate Production Preparation command and their own typed validation.

Every stored digest uses a named domain and canonical JSON version. Digests cover all identity and content fields, including source media references, source spans, assertion IDs, classifications, locks and normalizer version. The snapshot digest covers ordered `(binding_id, version, envelope_digest)` tuples and the exact target-version digests. Digest input and bytes must be fixed in a test vector before schema implementation. A reader rehashes stored bodies rather than trusting a digest column.

## Spatial evidence and mapping

A validated candidate revision retains the donor-derived visible/inferred/gap distinction, overlap deduplication, seam topology, direction exclusions, source references and normalizer version. The current `SpatialAssertion` has generic `relation` and `subject_refs`; it requires explicit source media identity, visible source span and assertion ID in the candidate schema before promotion. A span must identify a bounded region or timestamp in an exact immutable source; an empty or unresolvable span fails closed. The provider/model result is evidence only.

The typed preview proposal names an existing binding, selected assertion IDs and a constrained spatial mapping. It cannot supply a new `ProductionBinding` body. The adapter validates every selected assertion as `VISIBLE`, resolves its exact media digest and span, rejects contradictory direction/seam constraints and records omitted `INFERRED`/`GAP` rows in the impact view. The proposal's canonical digest is part of the preview. The human authorization binds that digest and an expiry. The resulting immutable set carries structured constraints and provenance, not a prose prompt fragment. Source image URL or mutable asset ID alone is never a custody proof.

The candidate normalizer and its donor differential can be implemented before this authority. The exact selected donor behavior is spatial normalization in `scene_spatial_contract.py`; the donor 360 builder is a consumer comparison, not automatically part of the selected parity surface. The parity contract must state this boundary and run same-fixture donor/R2 behavior for every selected material row under R2-DEC-031. A donor correction needs a failing donor fixture and stronger R2 expected result.

## Write and replay protocol

The Preparation writer uses one database transaction. It scopes every query by user and project, verifies the actor and project access before writing, locks the command key, locks the binding head, revalidates exact target/media content and expected head version, appends one immutable version and advances the head. A request with expected version zero can create a binding only through the separate Preparation create command. M8 always requires an existing positive head.

For M8 promotion, lock order is command key → candidate head → preview → binding head → target/source authority rows. The transaction checks authorization scope, candidate revision/body digest, selected assertion classifications, preview digest/expiry, binding version/envelope digest, target version/digest, source media digests and the constraint proposal digest under those locks. It stages the immutable constraint set and binding version, authorization, promotion receipt and command receipt, then commits once. An exact command replay returns its stored result before currentness checks; the same command ID with a different body fails. Storage failure rolls back all staged rows. Lock acquisition and transaction ownership must be shared with the existing M8 promotion adapter rather than nested commits.

The preview read is non-mutating. It binds the exact expected head and names effects on readiness/fingerprints and the prompt consumer. The current untyped `impact` field remains explanatory only. Promotion may not turn a gap or an inferred claim into a visible production fact.

## Read and consumer protocol

The snapshot resolver returns exact binding versions and verifies envelope, v1 body, spatial set and target digests. ProductionReadiness evaluates this resolved set and records the snapshot ID. Content fingerprinting includes the snapshot digest so a spatial-only update changes the fingerprint. A stale readiness snapshot cannot authorize later use. Existing pure Golden fixtures continue to work as offline fixture inputs; they are explicitly tagged as such and cannot be used as live authority reads.

The first production consumer is the R2 prompt planning/compilation seam. It takes a typed resolved spatial set from an exact `LOCATION` binding, emits only supported visible constraints, and records the binding snapshot in the prompt plan/fingerprint. An inferred region or gap is represented as a coverage warning, never as a positive scene fact. Same-fixture tests must show that the binding changes the compiled semantic prompt, that omission of the binding does not invent topology, and that stale or corrupt binding reads fail before a provider request. The current M7 video submitter is not changed by this packet; a future live route must explicitly thread the compiled plan and snapshot through its reviewed request contract. This limits the initial consumer proof to the R2 path rather than claiming live production deployment.

## Packet and acceptance order

1. **Design gate:** review ADR-0102 and this spec against frozen R2 decisions, current source and exact target/source custody seams. Resolve approval admission and digest vectors; publish a reviewed implementation plan and allowlist. No acceptance claim follows from author self-review.
2. **Authority gate:** implement target registration, binding create/update, CAS storage and exact snapshot resolver. Test cross-project access, stale head, changed replay body, partial transaction failure, row corruption, target mismatch, source custody and concurrent updates in PostgreSQL. Independently review exact HEAD.
3. **Consumer gate:** implement immutable typed spatial set and the R2 prompt consumer; prove readiness/fingerprint invalidation and same-fixture prompt effect. Independently review exact HEAD.
4. **M8-C gate:** implement C1 normalizer and candidate append/execution; then typed preview and atomic C2 promotion through the accepted authority. Run donor differential, fault/replay and affected-domain gates, seal exact integrated HEAD and independent review. M8-D remains gated on full M8-C acceptance.

Open design items for gate 1: locate or define live scene/shot approval custody; identify exact M7 source-media authority/variant path for both reference views; freeze canonical digest test vectors and database lock order with existing M8 rows; confirm the eligible mapping from selected visible spatial relations to typed constraints. These are required design work, not waivers.
