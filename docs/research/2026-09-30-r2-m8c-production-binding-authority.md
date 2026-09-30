# R2 M8-C ProductionBinding authority and spatial donor facts

## Scope and evidence point

This is a factual research note for the M8-C binding-authority prerequisite. It
does not select a storage design, define an authority interface, or authorize a
promotion implementation.

The inspected M8-C design worktree was at `8d4328d63f98bd8bf6e3baf02cbb05ad98300f37`.
The accepted M8-B base supplied for this research is `774952b2`. The donor
inspection was local-only at DramaClaw commit
`b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83`; the inspected source file is
`src/novelvideo/director_world/scene_spatial_contract.py`, SHA-256
`975e634cdd99500be5e29901da4930db14d5b81b1d14e6616e7e2e71081f1c92`.

## Observed R2 facts

1. `ProductionBinding` is a Pydantic contract with target, semantic and
   production references, a role, asset references, and optional variant/state
   references. Its only mutating behavior is in-memory canonicalization of
   `asset_refs`; the class has no persistence operation
   ([`r2/contracts/preparation.py:20`](../../r2/contracts/preparation.py#L20)-[`34`](../../r2/contracts/preparation.py#L34)).

2. The checked-in Golden A preparation flow constructs a `ProductionBinding`
   in memory when a reused asset is supplied, returns it in a frozen prepared
   shot, and uses its identifier to satisfy a readiness requirement. This flow
   contains no repository or transaction call
   ([`r2/m3/preparation.py:27`](../../r2/m3/preparation.py#L27)-[`32`](../../r2/m3/preparation.py#L32),
   [`53`](../../r2/m3/preparation.py#L53)-[`101`](../../r2/m3/preparation.py#L101)).

3. The recorded M8-A seam check says the `PRODUCTION_BINDING` target had no
   existing atomic authority seam: it found only the contract class and no ORM
   model, repository, service, or transaction writer. That receipt identifies
   its checked paths and command scope, so it is evidence for the specified
   bounded search rather than a general proof about all future code
   ([`docs/r2/evidence/R2_M8_A_STOP_2026-09-29.json:8`](../r2/evidence/R2_M8_A_STOP_2026-09-29.json#L8)-[`18`](../r2/evidence/R2_M8_A_STOP_2026-09-29.json#L18)).

4. The current exploration service performs its replay and candidate lookups,
   then raises `PromotionTargetUnavailableError` for a
   `PRODUCTION_BINDING` target before the later promotion-preview path
   ([`r2/advanced_creative/exploration.py:250`](../../r2/advanced_creative/exploration.py#L250)-[`269`](../../r2/advanced_creative/exploration.py#L269)).
   A unit test asserts that this category of unavailable target does not commit
   ([`tests/unit/r2/advanced_creative/test_exploration.py:192`](../../tests/unit/r2/advanced_creative/test_exploration.py#L192)-[`205`](../../tests/unit/r2/advanced_creative/test_exploration.py#L205));
   the PostgreSQL integration test observes only the two append receipts after
   rejected canvas, manifest, and binding previews
   ([`tests/integration/r2/advanced_creative/test_promotion_atomicity.py:349`](../../tests/integration/r2/advanced_creative/test_promotion_atomicity.py#L349)-[`361`](../../tests/integration/r2/advanced_creative/test_promotion_atomicity.py#L361)).

5. ADR-0095 records that a persistent ProductionBinding authority with an
   atomic CAS-versioned writer and its own design/ADR is a prerequisite for
   `SpatialCandidate` promotion. It separately permits validation and append
   of SpatialCandidate revisions without that writer, and records M8-C
   promotion as blocked until the authority is accepted
   ([`docs/adr/0095-m8a-defers-the-production-binding-promotion-target.md:37`](../adr/0095-m8a-defers-the-production-binding-promotion-target.md#L37)-[`49`](../adr/0095-m8a-defers-the-production-binding-promotion-target.md#L49),
   [`62`](../adr/0095-m8a-defers-the-production-binding-promotion-target.md#L62)-[`68`](../adr/0095-m8a-defers-the-production-binding-promotion-target.md#L68)).

6. The M8-C implementation plan has the same bounded authority line: it
   requires no direct ProductionBinding or master write and says to stop at a
   clean M8-C evidence HEAD
   ([`docs/superpowers/plans/2026-09-13-r2-m8c-spatial-candidates.md:13`](../superpowers/plans/2026-09-13-r2-m8c-spatial-candidates.md#L13)-[`18`](../superpowers/plans/2026-09-13-r2-m8c-spatial-candidates.md#L18)).

7. The current `ProductionBinding` body has no spatial assertion, seam, direction,
   gap or source-span field. `SpatialCandidate` has these evidence categories but
   only generic `relation`/`subject_refs` for each assertion. The preview request
   carries a candidate, revision, target and command ID, not a typed binding
   proposal ([`r2/contracts/preparation.py:20`](../../r2/contracts/preparation.py#L20),
   [`r2/contracts/advanced_creative.py:275`](../../r2/contracts/advanced_creative.py#L275),
   [`server/routers/advanced_creative.py:50`](../../server/routers/advanced_creative.py#L50)).

8. The inspected global `AssetRepository` updates and deletes assets, while its
   ORM row has no approval state or content digest. It cannot itself prove an
   immutable approved reference for a binding. This is a bounded observation
   about that repository/model, not an absence claim about every possible host
   asset path ([`lib/db/repositories/asset_repo.py:70`](../../lib/db/repositories/asset_repo.py#L70),
   [`lib/db/repositories/asset_repo.py:79`](../../lib/db/repositories/asset_repo.py#L79),
   [`lib/db/models/asset.py:19`](../../lib/db/models/asset.py#L19)).

## Observed DramaClaw spatial behavior and fixture shape

1. The donor prompt accepts two reference views from one camera point and
   explicitly distinguishes direct observation from inference and coverage
   gaps. Its JSON shape includes coverage gaps, front/back/side walls,
   must-preserve fixtures, inferred fill, side joins, forbidden transforms, and
   direction-exclusion locks
   (`b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83:src/novelvideo/director_world/scene_spatial_contract.py:181-290`).

2. The prompt fixes the spatial mapping used by its fixture-shaped data: master
   front at raw `x=25%`, the right-side join at `x=50%`, reverse back center at
   `x=75%`, and the low-detail seam at `x=0%/100%`. It tells the model to put
   insufficiently visible areas in `coverage_gaps` and `inferred_fill` rather
   than assert a confident wall
   (`b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83:src/novelvideo/director_world/scene_spatial_contract.py:189-206,274-289`).

3. Given overlap-analysis input, the donor admits only selected unique side
   anchors to `merge_once`/`do_not_duplicate`; it keeps other overlap names as
   smooth continuation. It moves a representative anchor from front/back
   preservation into the corresponding side-wall shared-overlap list, avoiding
   duplicate copies
   (`b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83:src/novelvideo/director_world/scene_spatial_contract.py:694-777,780-812`).

4. The donor derives direction locks only for eligible visible front/back
   fixtures and excludes inferred or both-view items. It emits a required
   direction and panorama zone, plus forbidden zones, for each generated lock
   (`b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83:src/novelvideo/director_world/scene_spatial_contract.py:815-899`).

5. The generated contract is consumed as a prompt insert by the donor 360
   builder. In automatic mode it rejects a missing, stale, malformed, or
   schema-version-mismatched contract; it then returns only
   `pano_prompt_insert` for the builder's use
   (`b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83:src/novelvideo/director_world/scene_360_builder.py:718-751,894-915`).
   The contract writer itself parses the model response, applies overlap and
   direction normalization, synthesizes this insert, and writes a JSON
   artifact beside its input references
   (`b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83:src/novelvideo/director_world/scene_spatial_contract.py:1040-1094`).

## Inferences bounded by the observations

- The donor source provides a useful normalization vocabulary and behavioral
  fixture axes: visible versus inferred versus gap, source direction, seam
  position, shared-overlap de-duplication, and forbidden direction migration.
  This follows from the donor's prompt schema and normalizers above. It does
  not establish that donor-generated JSON is production truth.

- Since the active R2 path rejects the binding target before a preview commit,
  an M8-C spatial revision can exist without a ProductionBinding write, but a
  promotion cannot complete through that target at this evidence point. This
  is consistent with both ADR-0095 and the current tests.

## Unknowns and limits

- This note does not determine the persistent authority's data model, CAS
  identity, transaction boundary, migration, authorization, or receipt shape.
  Those are authority-design questions outside this research scope.

- No runtime donor execution, network/provider call, or donor test suite was
  run. The donor facts are static-source observations at the pinned commit.

- A versioned binding store alone cannot specify which spatial information is
  production data, how a spatial constraint is represented by a binding, or
  which authority proves its referenced asset. Those choices require an
  explicit design before M8-C promotion can be implemented.

- The donor's script writes artifacts to its own filesystem paths. This note
  records that behavior as donor evidence only; it does not establish an R2
  storage or promotion mechanism.
