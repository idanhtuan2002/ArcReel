# M9-B Acquisition and Observations Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` inline, task by task. Do not dispatch per-task implementers/reviewers. The Human's bounded review budget takes precedence over generic skill review loops.

**Status:** DRAFT_FOR_HUMAN_REVIEW; not released for runtime implementation.
**Goal:** Declare capability-bound queries and acquire manual-import evidence into immutable, scoped snapshots and lossless observations, with explicit recovery, retention and erasure references.
**Architecture:** Keep M9 authority in its PostgreSQL application unit-of-work. Source capability evidence comes from the host, raw bytes/identities live behind `SnapshotEvidenceStore`, and external I/O happens between DB transactions. Existing A profiles/contracts/digests remain the predecessor; disabled providers refuse before credentials or network access.
**Tech Stack:** Existing Python3.13/Pydantic2/FastAPI/SQLAlchemy/Alembic/PostgreSQL18 environment and native filesystem; no new dependency is planned.
**Spec:** `docs/superpowers/specs/2026-09-14-r2-m9-opportunity-research-intelligence-design.md`, particularly sections5,7-11,14-16,18-20; umbrella TaskB; ADR0111 only for its A-scoped historical decision.
**Research:** `docs/research/2026-10-16-r2-m9b-native-reuse.md`.

## Immutable predecessor and release gate

- Accepted A commit: `04b1b92184a5d5b0643256be533332de6ed8b009`.
- Its sole parent is candidate `912abc3bedf5cf2f5965284919f11acc3a3c7593`, tested code `fd9543de6053c5b21a17605c5ea13b967a6ff638`.
- Acceptance record: `docs/r2/evidence/R2_M9_A_IMPLEMENTATION_ACCEPTANCE.json`; independent report verdict `PASS_M9_A_FOUNDATION`, zero Critical/Important defects. The historical candidate JSON stays unchanged.
- B migration: `9b9c4a0e0001`, exact `down_revision='9a9c4a0e0001'`. A migration bytes are immutable.
- Human input still required: the exact proposed synthetic fixture in `docs/r2/evidence/R2_M9_B_MANUAL_IMPORT_FIXTURE_PROPOSAL.json`. Its status remains PROPOSED_NOT_APPROVED; an unanswered text question is not approval.
- After Human approval of this plan/fixture, create a separate `R2_M9_B_PACKET_RELEASE.json` binding the exact plan, fixture, readiness inventory and A acceptance/review hashes; record the actual approval and pin its commit before B0. A draft alone is never release authority.
- Continue on an `impl/r2-m9b-acquisition-observations` branch derived from the approved packet. Do not implement on the design branch. Preserve the A worktree and unrelated root changes.

## Global constraints

- Authority scope is authenticated owner/project/actor, never an independently supplied actor. V1 manual-import mutation routes require an interactive Human; reads preserve the existing authenticated-read convention.
- Source grants are host evidence. M9 consumes and validates them; it does not issue permissions, discover credentials or interpret an unresolved CONDITIONAL grant as executable.
- Every command uses the existing `(user_id,actor_id,operation,command_id)` advisory guard and immutable request/result digests. Cross-project UUID reuse conflicts without disclosure.
- Lock rank: command guard/receipt, consumed capability/evaluation IDs, cohort-profile head, query head, attempt, snapshot/correction identity, observation heads; sort IDs inside a rank. Reuse accepted host creative-policy serialization before locking the profile head. No transaction spans any port/filesystem I/O.
- Canonical parameters64KiB;20pages;1000records;2MiB/page;40MiB/snapshot. Enforce declared ceilings before I/O and returned-byte limits before metadata admission.
- Page/class anchors are the DB timestamp at first successful page acceptance after I/O. Provider timestamps never anchor retention; replay never renews it. Minimum non-null deadlines govern shared objects.
- At `now >= refresh_due_at`, operational use refuses stale evidence. At `now >= retention_due_at`, payload access refuses before store dereference. Missing rules are forbidden; explicit null intervals mean no imposed elapsed interval.
- Raw bytes, native IDs, native values and non-retainable proof digests stay outside ORM rows. Native values are erasable canonical objects with paired integrity refs. No scoring, ratios, category inference or opportunity derivation during normalization.
- B consumes no future E tables, exposes no invalidation/sweep worker, and cannot claim E's final integrated erasure guarantee. E owns those additions.
- The A-only foundation inventory exception does not extend to B. Any actually consumed donor runtime behavior needs its exact-pin paired offline harness. Inventory-only evidence must never say runtime parity PASS.
- No live provider, real credential, production migration, deployment or push. Qualified production host capabilities remain separate from offline fixture authority.

## Exact owned file map

Create:
- `alembic/versions/9b9c4a0e0001_add_m9_acquisition_observations.py`
- `lib/db/models/opportunity_acquisition.py`
- `lib/db/repositories/opportunity_acquisition.py`
- `r2/opportunity/capabilities.py`
- `r2/opportunity/acquisition.py`
- `r2/opportunity/normalization.py`
- `r2/opportunity/manual_import.py`
- `server/services/m9_evidence_store.py`
- `server/routers/opportunity_acquisition.py`
- `scripts/r2/verify_m9b_scope.py`
- `scripts/r2/verify_m9b_evidence.py`
- `docs/r2/evidence/schemas/R2_M9_B_ACQUISITION.schema.json`
- `docs/r2/evidence/R2_M9_B_ACQUISITION.json`
- `tests/fixtures/r2/opportunity/manual_import.json`
- `tests/fixtures/r2/opportunity/source_capabilities.json`
- `tests/unit/r2/opportunity/test_capabilities.py`
- `tests/unit/r2/opportunity/test_acquisition.py`
- `tests/unit/r2/opportunity/test_normalization.py`
- `tests/unit/r2/opportunity/test_manual_import.py`
- `tests/unit/scripts/r2/test_verify_m9b_scope.py`
- `tests/unit/scripts/r2/test_verify_m9b_evidence.py`
- `tests/unit/server/routers/test_opportunity_acquisition_router.py`
- `tests/integration/lib/db/migrations/test_alembic_m9_acquisition.py`
- `tests/integration/lib/db/repositories/test_opportunity_acquisition.py`
- `tests/integration/r2/opportunity/test_acquisition_concurrency.py`
- `tests/integration/server/services/test_m9_evidence_store.py`

Modify only these accepted composition/export seams:
- `lib/db/models/__init__.py`
- `lib/db/repositories/__init__.py`
- `server/services/opportunity.py`
- `server/app.py`
- `lib/i18n/en/errors.py`, `lib/i18n/vi/errors.py`, `lib/i18n/zh/errors.py`
- `tests/unit/scripts/r2/test_verify_m9_scope.py` (pin its historical A fixture to accepted A bytes, not mutable current exports)
- `tests/integration/lib/db/migrations/test_alembic_m8_exploration.py`
- `tests/integration/lib/db/migrations/test_format_projections.py`
- `tests/integration/lib/db/migrations/test_learning_observations.py`
- `tests/integration/lib/db/migrations/test_production_binding_authority.py`
- `tests/integration/lib/db/migrations/test_production_target_registry.py`
- `tests/integration/lib/db/migrations/test_spatial_constraint_sets.py`
- `tests/integration/lib/db/migrations/test_spatial_execution_evidence.py`
- `tests/integration/lib/db/migrations/test_spatial_frame_receipts.py`
- `tests/integration/lib/db/migrations/test_spatial_pair_authority.py`
- `tests/integration/lib/db/migrations/test_spatial_pair_v2_custody.py`
- `tests/integration/lib/db/migrations/test_spatial_promotion_sidecars.py`
- `tests/integration/lib/db/migrations/test_spatial_review_custody.py`
- `tests/integration/lib/db/migrations/test_alembic_m9_foundation.py`

Planning/release artifacts are this plan, the native-reuse research, B readiness and fixture proposal, and `R2_M9_B_PACKET_RELEASE.json`. B0 must use this explicit map, never widen A's old verifier or edit frozen A baseline/amendments to make later code appear A-owned. Do not alter frozen public contract/port fields; report a concrete contract gap instead.

## Reuse decisions and native gaps

Reuse A canonicalizers, M9 digest functions, typed contracts, verified profile reader, command-key domain, DB-time/CAS patterns and authenticated host scope. Profile receipt reconstruction is specifically COHORT_PROFILE, so B needs typed query/acquisition receipt reconstruction over the existing receipt table, not a generic caller-selected ORM/model.

The inspected artifact manifest removes manifest metadata, not raw payloads/identity/integrity objects. The inspected CandidateObjectStore has get/insert for verified production candidates and no erase operation. Neither is a compatible SnapshotEvidenceStore implementation. Reuse `lib.json_io.atomic_write_bytes` only as a fsynced temporary-byte primitive; it replaces targets and is not an immutable put-if-absent primitive.

B owns a scoped native file-store adapter with immutable publication, paired integrity validation, persistent opaque refs, and exact deletion. Its root is a trusted host directory outside project-controlled upload paths; callers cannot select roots or filesystem paths. Scope/attempt/page/kind identify idempotent puts; raw content/native identifiers never become filenames or retained identity hashes. Random opaque source-identity mappings remain in erasable host storage. Conditional final publication must reject concurrent different bytes without overwriting a committed object. Corrupt, cross-scope, symlink and missing objects fail closed. These are new B behaviors requiring the integration tests below, not claimed existing donor parity.

SourceCapabilityPort implementations used in acceptance are explicit host fixtures built from the approved policy input, not production issuers. The host composition accepts configured trusted ports; missing ports fail `M9_SOURCE_CAPABILITY_UNAVAILABLE`. No M9 endpoint creates a source grant. A real provider adapter or production permission issuer is not activated by this packet.

## Review focus and owning regression

1. Concurrent first acquire after an uncertain call must not dispatch twice: B3 race/restart tests.
2. A clock or host grant changes while a page is outside the DB transaction: B1/B3 exact-boundary, between-page and finalize tests.
3. A mixed-class raw page contains a class that forbids retained proof: B1/B2/B4 digest/erasure tests.
4. A syntactically valid provider grant has the wrong purpose/account/qualification: B1/B5 dormant/ineligible fixture tests with zero credential/network calls.
5. Native retrieval metadata, units or an absent value silently change correction identity: B4 raw-field/window/missingness/identity tests.

## Task B0: Freeze and verify the released packet

**Files:** scope verifier/tests; approved planning/release documents.
**Consumes:** exact A acceptance/review/candidate refs, Human fixture decision and this owned map.
**Produces:** `verify_m9b_scope(repo: Path, release: Mapping[str,object]) -> list[str]`, a read-only gate.

- [ ] Write tests refusing absent/tampered A acceptance/report, wrong candidate parent, non-PASS review, modified A native source before B starts, changed fixture hash, unapproved input, dirty/outside paths, wrong branch/head and non-disposable DB.
- [ ] Run `uv run python -m pytest tests/unit/scripts/r2/test_verify_m9b_scope.py -q`; observe real RED for the missing verifier.
- [ ] Implement with existing Git readers/unique JSON parsing; pin the actual A acceptance commit and exact approval/release bytes. Return `M9_REQUIRED_EVIDENCE_MISSING` for unresolved inputs, `POST_M8_BASE_SEAM_CHANGED` for outside ownership, and `M9_SCHEMA_CHANGE_REQUIRED` for an incompatible accepted migration. No file writes, migration or fetching in this gate.
- [ ] Run GREEN and execute the gate against the actual clean released packet/disposable target. Non-zero selection or any required skip blocks.
- [ ] Commit only B0 paths after the gate passes.

## Task B1: Capability, clock and native page policy

**Files:** `capabilities.py`, its unit tests and approved capability fixtures.
**Consumes:** SourceCapabilityGrant, EffectiveCapabilityEvaluation, CapabilityEvaluationRequest, SourceDataRule and existing digest functions.
**Produces:** `validate_capability(grant, evaluation, request, *, now: datetime) -> None`; `page_clocks(page: SourcePageResult, grant: SourceCapabilityGrant, *, captured_at: datetime) -> tuple[EvidenceDataClassClock,...]`.

- [ ] RED-test exact scope/actor/source/schema/operation/purpose/account and digest bindings; forbidden/disabled/expired/revoked/unavailable grants; incomplete/unknown condition proof; unresolved CONDITIONAL permission; duplicate/missing data rules; expired policy/evaluation/refresh; credential material refusal.
- [ ] RED-test DB-capture anchor, provider timestamp independence, before/at/after deadlines, null-rule semantics, mixed-class minima and no replay renewal. For approved proposed rules, assert raw-page offsets30/90s, metadata observation60/120s and excerpt30/90s; both classes delete on revoke and excerpt never retains proof.
- [ ] Run `uv run python -m pytest tests/unit/r2/opportunity/test_capabilities.py -q`, observe RED, implement pure folds and run GREEN. No policy grant is manufactured or mutated by the fold.
- [ ] Commit B1 paths.

## Task B2: Scoped erasable host evidence store

**Files:** `server/services/m9_evidence_store.py`, integration tests.
**Consumes:** exact SnapshotEvidenceStore contract and ErasableEvidencePayload/PayloadRef/DeletionRequest/DeletionResult; existing fsynced byte-write primitive.
**Produces:** `FileSnapshotEvidenceStore(root: Path, *, user_id: str, project_name: str)` implementing the three frozen async port methods. Instance scope is mandatory because read takes opaque refs rather than caller scope.

- [ ] RED-test actual temporary-filesystem puts, byte-equal replay, concurrent equal/different puts, interrupted publication, reopen in a fresh process, exact bytes and paired integrity reads, scope substitution, path traversal/symlink/corruption refusal and absence equivalence.
- [ ] RED-test erased payload/value/raw-ID/integrity refs cannot be resolved after reopening, unrelated objects survive, repeated exact deletion is idempotent and only explicitly permitted proofs remain. Keep identities/secret-like native data out of paths, logs and exception strings; prove with a canary.
- [ ] Run `uv run python -m pytest tests/integration/server/services/test_m9_evidence_store.py -q`, observe RED, implement immutable conditional publication and GREEN. An atomic replace alone must not satisfy the concurrent immutable-put tests.
- [ ] Commit B2 paths. The B service performs clock/permission refusal before calling this port; the store does not grant permission or query future E tables.

## Task B3: Persistence, query declaration and acquisition recovery

**Files:** B migration/models/repository/UoW, `acquisition.py`, repository/concurrency/migration/unit tests and model/repository exports.
**Consumes:** accepted profiles/host policy, B1 folds, B2/store port, MarketSourcePort and frozen query/attempt/snapshot/receipt contracts.
**Produces:** `OpportunityAcquisitionService` scoped to owner/project/actor with exact `declare_query(DeclareSourceQuery)->QueryReceipt`, `acquire(AcquireSourceQuery)->AcquisitionReceipt`; typed repositories for capability evidence, query, attempt, snapshot and observation, sharing one application-owned session/UoW. Recovery consumes retained page checkpoints, provider request identities and qualified host operator evidence; it never resets terminal/uncertain attempts for blind replay.

- [ ] RED-test migration upgrade/downgrade/upgrade to the exact predecessor; scoped PK/FK/uniqueness/parent rules; no deletion or rewrite of A tables. B table families are `m9_consumed_capability_grants`, `m9_capability_evaluations`, `m9_source_queries`, `m9_source_query_heads`, `m9_acquisition_attempts`, `m9_snapshot_pages`, `m9_source_snapshots`, `m9_source_observations`, `m9_observation_heads`. Snapshot currentness is derived from stored immutable revisions; do not invent an unapproved snapshot-head table or future E table.
- [ ] Maintain the thirteen enumerated legacy migration tests: their current singleton tip changes9a→9b, while historical migration revision/down_revision assertions stay exact. The M8 aggregate downgrade expected-removal set adds exactly the nine B tables. For the A five-table round trip, downgrade B in the test fixture before exercising A, then restore B; never weaken A's exact five-table/preservation assertions or alter A migration bytes. Pin `AmendmentSource` fixture data in `test_verify_m9_scope.py` to accepted tested A code `fd9543de6053c5b21a17605c5ea13b967a6ff638`; current B composition/legacy expectations must not masquerade as historical A artifact bytes. Keep all authority-drift tests and A foundation rejection tests intact.
- [ ] RED-test scoped immutable query/CAS/receipt reconstruction; command UUID project conflicts; equal/divergent concurrent genesis/acquire; advisory collision; rollback after each staged write; stored digest corruption; foreign/unknown equivalence.
- [ ] RED-test prepare commits one PLANNED attempt under the full command key before I/O. Same-key retry in RUNNING/OUTCOME_UNKNOWN/NEEDS_OPERATOR returns current state without calling a provider. Only permitted monotonic transitions occur; unknown outcomes require stable provider reconciliation or a qualified host operator receipt.
- [ ] RED-test no open DB transaction during every source/store/capability call; profile/policy supersession and revoke-between-pages; missing/mutated payload; duplicate/cursor-loop/page-order drift; quota/record/page/per-page/aggregate byte limits; exact partial coverage on failure.
- [ ] RED-test page checkpoint DB timestamp at first acceptance, no clock renewal on service restart/replay, no duplicate external call after I/O-before-finalize interruption, and final snapshot/observations/event/receipt atomicity. Persist page checkpoints against the attempt before the final snapshot; snapshot pages are reconstructed by exact attempt/ordinal. Every successful B acquire creates one immutable snapshot; a known failure preserves explicit partial evidence.
- [ ] Run `uv run python -m pytest tests/unit/r2/opportunity/test_acquisition.py tests/integration/lib/db/migrations/test_alembic_m9_acquisition.py tests/integration/lib/db/repositories/test_opportunity_acquisition.py tests/integration/r2/opportunity/test_acquisition_concurrency.py -q`, observe RED, implement minimal typed aggregates, run GREEN on disposable PostgreSQL.
- [ ] Commit B3 paths. Repositories flush but never commit or perform port I/O. Do not change A's profile or receipt implementation to accommodate B.

## Task B4: Manual import and lossless native observations

**Files:** `manual_import.py`, `normalization.py`, their unit tests and approved raw fixture.
**Consumes:** SourcePageRequest/Result, host-approved immutable manual-upload reference/origin/uploader policy, B1 grant/clock proofs and the store port.
**Produces:** `ManualImportSource.fetch_page(SourcePageRequest)->SourcePageResult`; `normalize_manual_page(page: SourcePageResult)->tuple[dict[str,object],...]` with exact native field descriptors/values, for B3 to stamp into NormalizedSourceObservation only after integrity verification. These drafts remain internal and never cross HTTP or become ORM inline values.

- [ ] RED-test manual import uses the same attempt/snapshot route with null credential; immutable uploaded bytes/digest and qualified Human uploader/origin come from the host, never mere filesystem existence or caller labels. Every raw field maps to one native observation with its exact definition/version, unit/window/missingness and opaque source identity.
- [ ] RED-test unknown/ambiguous definitions, non-finite values, unit coercion, invented categories/ratios, dropped fields and changed query scope are rejected; zero stays zero, missing stays explicit, retrieval metadata is not stable content identity, and corrections never rewrite a prior snapshot/observation.
- [ ] RED-test canonical value objects resolve only through paired store refs, no inline native values/raw IDs/unretained proof digest enters ORM rows, and mixed-class proof retention follows each exact rule. A raw page containing excerpt has no retained page-content proof; metadata-only value proof can exist only when its own rule permits it.
- [ ] Run `uv run python -m pytest tests/unit/r2/opportunity/test_manual_import.py tests/unit/r2/opportunity/test_normalization.py tests/unit/r2/learning/test_adapters.py -q`, observe new tests RED, implement and GREEN. Existing M8 tests are semantic regression references; their LearningObservation adapter is not substituted for M9 snapshots/erasable refs.
- [ ] Commit B4 paths.

## Task B5: Authenticated host composition and readers

**Files:** new B router, accepted `server/services/opportunity.py`/`server/app.py` composition, router tests and all three backend locale catalogs.
**Consumes:** B3 service, configured trusted capability/source/store ports, accepted auth dependencies and policy-lock adapter.
**Produces:** under existing `/projects/{project_name}/m9/opportunity` prefix: POST`/queries`, GET`/queries/{query_id}`, POST`/acquisitions`, GET`/capabilities`, GET`/snapshots?query_id=...`, GET`/snapshots/{snapshot_id}`. JSON request models omit independent owner/project/actor; host builds frozen application commands from authenticated scope and validated host evidence.

- [ ] RED-test interactive-only manual mutations, authenticated/API-key reads, foreign/unknown equivalence, independent scope injection, exact same-command replay, migration refusal and missing host port refusal. No endpoint issues a source grant or exposes source/evidence-port internal objects.
- [ ] RED-test `get_query`, `list_capabilities`, `list_snapshots`, `get_snapshot` exact frozen reader signatures; verify stored hashes and clock/known-revocation state. Metadata history may be STALE, but retention-expired content is refused before a store read. No CURRENT projection from an expired/missing authority object.
- [ ] Register `manual-import.v1`; YouTube Data and Commercial Content remain DISABLED/dormant, Trends alpha and TikTok Research UNAVAILABLE, YouTube derived analytics DISABLED. Their refusal tests assert zero source/credential/network calls, including a format-valid but ineligible research grant. Do not invent enabled grants to list adapter descriptors.
- [ ] RED-test every new stop-code translation and exception/redaction path; update en/vi/zh catalogs together. Run `uv run python -m pytest tests/unit/server/routers/test_opportunity_acquisition_router.py tests/unit/server/routers/test_opportunity_router.py tests/unit/lib/i18n/test_i18n_consistency.py -q`, observe RED then GREEN.
- [ ] Commit B5 paths. E routes/workers and F UI are not introduced here.

## Task B6: Candidate evidence and stop

**Files:** B evidence verifier/schema/tests and candidate JSON.
**Consumes:** immutable approved release/predecessor, all actual B gate outputs, source-derived test inventory and graph coverage.
**Produces:** read-only `verify_m9b_evidence`, clean `M9_B_CANDIDATE` evidence, no independent approval assertion.

- [ ] RED-test unknown/missing fields, stale HEAD, fake/nonmatching exit/count/log/JUnit, omitted owned test/function, wrong migration/fixture/approval SHA, altered A acceptance and false donor-runtime claims. Bind the exact command argv/output, source hashes, all applicable fault cases and current graph generation/fallback ranges. Required skips and material unknowns must be empty.
- [ ] Run all affected B tests explicitly (the test paths in this owned map), the complete migration-test directory, A contract/digest/profile/router tests, A scope/parity/evidence verifier unit modules and existing M8 adapter regressions. Run Ruff check/format-check, basedpyright, lint-imports, deptry, audit_tests and git diff-check. PostgreSQL concurrency/migration and native filesystem recovery tests must actually pass. Expand a zero-test selection; never count collection or an interrupted run as PASS.
- [ ] Reuse the accepted A baseline only where exact dependency/source equality proves applicability; retain its actual historical SHA and limits. Do not replay unrelated M6 real-media suites or relabel old results. A new full-backend run needs a concrete change/failure justification per CONTRIBUTING; final full utility closure belongs to F.
- [ ] Record actual donor applicability. Execute paired pinned harnesses for every B-consumed donor behavior, if any; default fail closed on an absent harness or unknown classification. Never reuse A's foundation-only exception as a B runtime-parity PASS.
- [ ] Refresh graph coverage for every changed path and directly read missed/excluded/stale source. After GREEN on clean code, write candidate evidence as its sole evidence/schema child and run the strict verifier on that clean child.
- [ ] Stop at `M9_B_CANDIDATE`; one subsequent bounded independent acceptance pass at most, one evidence-driven repair pass, no automatic re-review loop. Do not open C, push, activate providers or migrate production.

## Execution ledger and human handoff

All steps are unchecked because this is a plan, not execution evidence. No B runtime/migration/test file has been authored. Planning validation covers file paths, accepted lineage, JSON/model validity and source reuse only; it is not a B runtime pass.

The pending Human decision covers the exact fixture proposal and this written packet. Preserve inline execution once approved. If the approved policy values differ, revise and hash the concrete input before release; never infer consent from a default selection or silence.
