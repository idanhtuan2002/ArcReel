# M8-C consumer gate, packet 1: typed spatial constraint set, snapshot read, fingerprint, prompt consumer

**Basis:**
- ADR-0102 (accepted 2026-10-13 by sponsor decision): decisions 3 and 4.
- Spec `2026-09-30-r2-m8c-binding-authority-design.md`: "Spatial evidence and mapping", "Spatial wire and persistence arm" and "Read and consumer protocol".

**Goal:** make one exact LOCATION binding version able to carry a typed, immutable spatial constraint set, and make readers and the prompt consumer verify and use it.

**Out of scope:**
- The binding write that attaches a set. That is the typed promotion in packet 3.
- The shot generation route and task (packet 2).

## Decisions

1. **Contract** in `r2/contracts/spatial_constraint.py`. It holds only facts derived on the server.
   - `SpatialConstraintV1`:
     - fields: `assertion_id`, `relation_kind`, `subject_ref`, `wall`, `source_spans`;
     - `PRESERVE_ON_WALL` requires `front`/`back`;
     - `SHARED_SIDE_ANCHOR` requires `left`/`right` and spans from both views.
   - `SpatialSourceBindingV1`: the frame and parent identity fields listed in the spec's V2 wire.
   - `SpatialCoverageWarningV1`: `assertion_id`, `evidence_class` (`INFERRED`/`GAP`), `relation`. These are carried as warnings, never as facts.
   - `SpatialConstraintSetV1`:
     - identity: `schema_version="1"`, user and project scope, `binding_id`;
     - candidate identity: `candidate_id`, `candidate_revision`, `candidate_payload_digest`;
     - content: `constraints` (at least one, assertion ids unique), `coverage_warnings`, `seam_locks`, `direction_locks`, `duplicate_warnings` (all copied from the exact revision), `normalizer_version`;
     - pair identity: `pair_id`, `pair_version`, `pair_decision_digest`;
     - `ordered_sources`: MASTER then REVERSE.
   - Every span's `(view, source_digest)` must match the source with the same view.
2. **Digest:** domain `r2.m8.spatial.constraint_set.v1`, canonical version `1`, the same envelope rule as `r2/production_binding/digests.py`. The set ID is `m8s:` plus the hex digest. A fixed byte/digest vector is frozen first (`tests/fixtures/r2/m8c_spatial_constraint_set_vector.json`).
3. **Derivation:** `derive_spatial_constraint_set(...)` is pure. It takes one exact SPATIAL `ExplorationRevision`, the ordered selected assertion IDs, the binding ID, the pair identity and the two source bindings. It fails closed on:
   - an empty, duplicate or unknown selection;
   - a non-VISIBLE selection;
   - a selection that does not have exactly one subject;
   - a missing server-stamped wall;
   - an unsupported wall/kind;
   - a span that does not resolve to the given sources.

   Every non-selected INFERRED or GAP assertion becomes a coverage warning. Non-selected VISIBLE rows are omitted.
4. **Binding envelope:** `BindingEnvelopeV1.spatial_set_id` and `spatial_set_digest` widen from `None` to an optional `m8s:` ID and digest. They must be both null or both set. An existing envelope serializes to the same bytes, so its digest is unchanged.
5. **Storage:** an immutable table `m8_spatial_constraint_sets`, scoped by `(user_id, project_name, set_id)`. It stores:
   - `binding_id`;
   - `body_json`;
   - `set_digest`;
   - `created_at`.

   The repository's `stage` validates the digest and the ID. `get_verified` rehashes on read. A tampered row is unavailable.

   The new migration follows the branch head `911c4a0e0001`.
6. **Snapshot read:** when the current envelope names a set, `CurrentLocationBindingSnapshotReader` loads it in the same session. It verifies:
   - ID, digest and scope;
   - `binding_id`;
   - that every ordered source's frame receipt ID and digest equal the envelope's claims.

   It returns the verified set with the snapshot. A missing or mismatched set fails closed. `BindingSnapshotV1` already covers the envelope digest, so a spatial change changes the snapshot digest.
7. **Fingerprint:** a new versioned `compute_content_fingerprint_v2` binds `binding_snapshot_digest` and the ordered spatial set digests next to the v1 inputs. It has its own domain envelope. v1 is unchanged.
8. **Prompt consumer:** `apply_spatial_constraints(plan, constraint_set)` returns a new `PromptPlan`.
   - Each constraint becomes one deterministic `environment_intent` line, in selection order.
   - `output_requirements["spatial_constraint_set"]` carries the set ID and digest.
   - `output_requirements["spatial_coverage_warnings"]` lists the warnings.
   - INFERRED and GAP never enter `environment_intent`.

   Same-fixture tests show that:
   - the set changes the compiled plan;
   - without a set the plan is byte-identical;
   - nothing invents topology.

## Steps and gates

1. Contract, digest, frozen vector and derivation, with pure tests.
2. Envelope widening, fingerprint v2 and prompt consumer, with pure tests (existing envelope digests unchanged).
3. Migration, repository and snapshot reader integration, with PostgreSQL 18 tests:
   - corruption;
   - cross-project;
   - mismatched set;
   - an absent set keeping the current behaviour.
4. Static gates and the affected selection.

Review is by the sponsor's choice of reviewer. Self-review limits are recorded at the packet end.
