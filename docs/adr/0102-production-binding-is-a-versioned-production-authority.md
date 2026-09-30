---
status: proposed
---

# ProductionBinding requires one versioned production authority before M8-C promotion

ADR-0095 deferred `PRODUCTION_BINDING` promotion because R2 has a binding contract but no persistent writer. The frozen domain contract names `ProductionBinding` as the semantic-to-production bridge; M8 spatial output is evidence, not that bridge. The factual basis is [the M8-C authority research](../research/2026-09-30-r2-m8c-production-binding-authority.md). The storage direction below is proposed, while the spatial representation is still undecided. This proposal does not release M8-C C2 or supersede ADR-0095 until independently reviewed and accepted.

## Proposed decision

1. Production Preparation owns a single project-scoped `ProductionBinding` authority in PostgreSQL. A binding head identifies `(user_id, project_name, binding_id)` and points to an immutable version containing the complete `ProductionBinding`, its canonical content digest, actor, command identity and provenance. A mutation supplies the expected head version (zero for an explicitly authorized creation), holds the head lock, checks it, appends one version and advances the head in one transaction. An exact command replay returns its stored receipt; a changed command body with the same key fails. No Canvas, Spatial, Canon, ShotSpec, manifest or M7 master row is a second binding writer.
2. A production read resolves an exact binding snapshot from this authority. The snapshot identifier commits to the ordered binding IDs, versions and content digests. Readiness and content fingerprints use that exact set; a later head change invalidates a prior readiness result. Existing in-memory Golden A bindings remain offline fixtures and are not silently treated as persisted heads.
3. `SpatialCandidate` remains non-authoritative. Its generic `relation` and `subject_refs` fields do not contain the typed `target_type`, `role`, `semantic_ref`, `production_ref` and asset identities needed for a `ProductionBinding`. A separate typed, human-selected change must name the spatial assertion IDs offered as evidence. Only `VISIBLE` assertions with source media identity and source spans can support a version-1 production change. `INFERRED` and `GAP` assertions remain visible in the preview as context but cannot supply a binding fact or asset reference. The system does not invent an asset or semantic identity from donor prose.
4. The M8 preview binds the exact candidate revision/digest, selected assertion IDs, typed binding change/digest, current binding head version/digest (or the explicit absent-head sentinel), actor scope, impact and expiry. Authorization names that preview digest. Promotion locks the command key, candidate head, preview and binding head in a fixed order, re-reads and validates every bound identity, then commits the binding version, M8 authorization, promotion receipt and command receipt together. It never writes a master. A failed validation, stale head, expired preview or replay mismatch writes none of those rows.
5. The public M8 preview request and persisted preview must acquire a typed production-change field or an equivalent separately persisted, digest-bound proposal. The current request has only `candidate_id`, `revision`, `target` and `command_id`, while `SpatialAssertion` has free-text relation and references. Implementation must not hide a client-authored binding body in the untyped `impact` field. The spec, schema, migration and execution contract must be amended before C2 resumes.

## Open spatial representation decision

`ProductionBinding` has no field for seams, direction locks, gaps or source spans, and the inspected global asset repository provides neither immutable content identity nor approval custody. A binding store alone therefore does not make spatial promotion meaningful or safe. Two concrete paths remain:

- **Recommended for the full M8-C goal:** add an immutable, typed `SpatialConstraintSet` built from selected visible assertions; extend a binding version with an exact `spatial_constraint_ref` and digest. Promotion updates an existing binding, preserves its production and asset references, and commits the constraint set and binding head together. Binding creation and asset replacement stay with a separate Production Preparation command. This needs a contract revision and a consumer that actually uses the spatial constraints.
- **Narrower interim scope:** finish spatial normalization and candidate revisions, leave promotion unavailable, and amend the roadmap so M8-D is not falsely described as starting from accepted M8-C. This does not deliver the current M8-C promotion requirement.

Neither path is accepted by this ADR draft. A sponsor decision and a checked consumer/read path are required before freezing the design or issuing an implementation plan.

## Alternatives considered

- **Let M8 write `ProductionBinding` directly.** This would create a second production authority and cannot provide one canonical snapshot to readiness and fingerprint consumers.
- **Infer a binding from donor spatial JSON.** Its topology and gap language lacks the required typed binding identities; automatic promotion could turn a gap or inference into a production fact.
- **Treat an M7 master slot as a binding.** A media master is an artifact authority, while a binding connects semantic and production identities. ADR-0095 already rejects this substitution.
- **Keep SpatialCandidate revisions only.** This remains the safe interim behavior, but it leaves the accepted M8-C promotion goal unfinished.

## Acceptance needed before implementation

- Review the target/role/asset validation rules, creation versus replacement semantics, and actor authorization with the M4 Production Preparation owner.
- Freeze the binding snapshot digest domain and its integration with readiness, fingerprints and existing fixture paths.
- Freeze the typed change and M8 preview/receipt wire contracts, CAS and lock order, migration/backfill policy, corruption tests and independent review gate.
- Keep the M8-C C2 promotion step stopped at `M8_REQUIRED_EVIDENCE_MISSING` until the authority implementation is independently accepted.
