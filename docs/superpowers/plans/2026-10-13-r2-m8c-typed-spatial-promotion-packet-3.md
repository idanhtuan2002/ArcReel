# M8-C packet 3: typed spatial promotion into a LOCATION binding version

**Basis:**
- ADR-0102 decision 5 and ADR-0103, both accepted by the sponsor on 2026-10-13.
- Spec `2026-09-30-r2-m8c-binding-authority-design.md`, sections "Spatial wire and persistence arm" and "Write and replay protocol".
- Packets 1–2: the constraint set, its storage and the snapshot read.

## Facts established before deciding

- **Pair approvals bind one binding version.** `verify_stored_pair_decision` requires the approval's `expected_binding_version`, envelope digest and core digest to equal the current binding's. A promotion that appends binding version N+1 therefore leaves the version-N approval historical.
- **The V2 approval reader needs a current Showrunner grant.** `CurrentApprovedSpatialPairReaderV2.read_current_locked` locks the target, binding, pair, parent masters and frames, and checks a current grant from `CurrentShowrunnerGrantReader`. Under ADR-0103 the grant issuer is an operator activation step. Until that step, a real deployment has no grant and promotion is denied.
- **Existing promotion code.**
  - `ExplorationPromotion.promote` handles only artifact slots.
  - `ExplorationService.create_preview` refuses `PRODUCTION_BINDING`.
  - The `m8_promotion_previews` and `m8_promotion_receipts` rows already accept a `PRODUCTION_BINDING` target with a null master.
- **Binding repository.** It can append and advance only binding version 1 (`append_first_version`, `advance_first_head`).

## Decisions

1. **New binding version.** Promotion appends binding version N+1:
   - The v1 body is identical except `version`.
   - The envelope keeps the same scene, target and claims, and carries `binding_version=N+1`, the new body digest, and the `spatial_set_id`/`spatial_set_digest`.
   - The head advances by CAS from N to N+1.
   - The core digest is unchanged, as the existing vector proves.
2. **Pair currentness is checked once.** At promotion the V2 approval must be current for version N, read under its locks. The stored set records the pair ID, version and decision digest.
   - Generation (packet 2) trusts the current binding version and its verified set. It does not recheck pair currentness, because by design the approval names the previous version.
   - A later promotion needs a fresh approval of the then-current version.
   - This closes packet 2 open item 2.
3. **Preview request.** `POST /projects/{p}/m8/spatial/promotion-previews` takes `(candidate_id, candidate_revision, target_id, expected_binding_version, selected_assertion_ids, command_id)`. The server derives everything else; no client digest or relation text is accepted.
   - The base preview row has `target=PRODUCTION_BINDING(target_ref=binding_id, expected_target_version=N)` and a null master.
   - Sources come from the approved pair's views: the MASTER view is `Image 1`.
4. **Sidecars.**
   - `m8_spatial_preview_bindings`, keyed by the scoped `preview_id`, holds the proposed set body and digest, the binding version and envelope digest, the target ref, the pair identity and the V2 preview digest.
   - `m8_spatial_promotion_results`, keyed by the scoped `receipt_id`, holds the binding version, envelope digest, set ID and digest, and the V2 receipt digest.
   - **Coupling.**
     - Application readers require exactly one sidecar for a binding target and none for a slot.
     - PostgreSQL adds deferred constraint triggers that enforce the same rule at commit.
     - SQLite relies on the application check, and the tests run the trigger cases on PostgreSQL.
5. **Digests.** Both use the canonical envelope rule:
   - `r2.m8.spatial.preview.v2` over the base preview plus the sidecar body;
   - `r2.m8.spatial.receipt.v2` over the base receipt plus the result sidecar body.

   For a binding target, `PromotionAuthorization.preview_digest` must equal the V2 preview digest. The receipt has:
   - `result_artifact_ref` = `"<binding_id>@<N+1>"`;
   - `result_digest` = the new envelope digest;
   - `result_master_id` = null.
6. **Promotion arm.** `ExplorationPromotion.promote` delegates a `PRODUCTION_BINDING` preview to a `SpatialBindingAuthority` port, implemented by the host.
   - The port works under the order: M8 command key → candidate head → preview → target/admission → binding head → pair head → M7 masters and frames.
   - It revalidates the authorization, expiry, revision digest, re-derived set, binding version and envelope, and the current pair approval.
   - It then stages, in one transaction, the constraint set, the binding version N+1 and head CAS, the authorization, the base receipt with its result sidecar, and the command receipt.
   - An exact replay returns the stored receipt; a changed body conflicts.
7. **Out of scope.**
   - Live grants (ADR-0103 activation).
   - Any promotion into other binding roles.
   - Changing the artifact-slot arm, whose bytes and digests stay unchanged.

## Slices

- **3a.** V2 preview and receipt contracts, digests and frozen vectors.
- **3b.** Migration `913c4a0e0001`: the two sidecars, the PostgreSQL deferred coupling triggers, and the repository with rehash-on-read.
- **3c.** Binding repository: append version N+1 with the spatial set, and advance the head by CAS.
- **3d.** Preview service and route.
- **3e.** Promotion arm with the host `SpatialBindingAuthority`, wired into the existing promotion route.
- **3f.** Tests on PostgreSQL:
  - happy path, replay and changed body;
  - stale binding, pair or revision;
  - expired preview and wrong digest;
  - storage failure rolling back every row;
  - a concurrent pair, binding or promotion write;
  - coupling triggers.

  A generation snapshot after promotion must carry the set.
