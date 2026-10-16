# M9-B preparation from the M9-A foundation candidate

Status: DRAFT_NOT_RELEASED. M9-A foundation acceptance is sealed at `04b1b92184a5d5b0643256be533332de6ed8b009`; M9-B runtime is not authored.
Source candidate: `912abc3bedf5cf2f5965284919f11acc3a3c7593`.
All source hashes are retained in `docs/r2/evidence/R2_M9_B_READINESS.json`; they must be refreshed if the predecessor changes.

## Required gates and authority

1. The execution contract `packet_inputs.M9-B` requires independently accepted M9-A and Human-approved manual-import data-class/retention fixtures. The immutable candidate retains its historical PENDING field. The subsequent M9-A acceptance record binds the actual independent PASS; it does not rewrite the candidate. The one acceptance pass found no Critical/Important defect. No review loop or automatic second reviewer is authorized.
2. `docs/r2/evidence/R2_M9_B_MANUAL_IMPORT_FIXTURE_PROPOSAL.json` is PROPOSED_NOT_APPROVED. A text question has been sent to the Human; no preselected option or elapsed time is approval. It proposes synthetic data only, metadata refresh/retention60/120s and excerpt30/90s, delete-on-revoke, no retained excerpt proof digest, DB admission anchors, exact-boundary and mixed-class cases. It issues no source capability grant and authorizes no production operation.
3. Freeze the accepted predecessor SHA, fixture decision/hash, owned paths, capability policy fixtures and migration predecessor before releasing the B implementation plan. Revision `9b9c4a0e0001` must descend from `9a9c4a0e0001` (umbrella migration sequence). Do not rewrite accepted A migration or frozen A artifacts.
4. Preserve root checkout's unrelated dirty work. Use an isolated B worktree for implementation after its gates are satisfied. Do not activate providers, use real credentials, deploy or push.

## Confirmed reuse surfaces

- `r2/contracts/opportunity.py`: frozen `SourceCapabilityGrant`, `EffectiveCapabilityEvaluation`, `SourceDataRule`, `SourceQueryDraft`, `DeclareSourceQuery`, `AcquireSourceQuery`, `SourceQuery`, `AcquisitionAttempt`, `SnapshotPage`, `EvidenceDataClassClock`, `SourceSnapshot`, `NormalizedSourceObservation`, `QueryReceipt`, `AcquisitionReceipt`, `SourcePageRequest`, `SourcePageResult` and erased-payload contracts. Candidate file SHA is pinned. The source-page proposal and both rule models were actually instantiated with these types; no B service behavior was executed by this probe.
- `r2/opportunity/ports.py`: exact methods `SourceCapabilityPort.resolve_grant(ref)` and `evaluate(CapabilityEvaluationRequest)`, `MarketSourcePort.fetch_page(SourcePageRequest)`, `SnapshotEvidenceStore.put_if_absent(ErasableEvidencePayload)`, `verify_and_read(payload_ref,integrity_ref)`, `delete_exact(PayloadDeletionRequest)`. These inspected definitions are Protocol seams, not qualified host implementations.
- `r2/opportunity/digests.py`: accepted `command_guard_key`, `digest_command_request`, `digest_command_result`, `digest_capability_grant`, `digest_capability_evaluation(actor_id=...)`, `digest_source_query`, `digest_source_snapshot` and observation digests. Existing implementation delegates canonical serialization to accepted M8 `canonical_json_bytes`/`digest_canonical`; do not introduce another canonicalizer.
- `lib/db/repositories/opportunity.py`: real command guard uses two signed32-bit SHA-derived integers in `pg_advisory_xact_lock`; `database_time()` reads PostgreSQL `clock_timestamp`; scoped fresh reads and CAS use explicit predicates and `populate_existing`. Reuse these established boundaries. Existing receipt reader/writer is specifically typed to `COHORT_PROFILE` and `CohortProfileReceipt`; it cannot be used unchanged for `QueryReceipt`/`AcquisitionReceipt`.
- `lib/db/models/opportunity.py`: command receipt uniqueness is `(user_id,actor_id,operation,command_id)` independently of project, with scoped project binding checked before replay disclosure. Existing `m9_events`/`m9_command_receipts` metadata exists; do not build a second incompatible command identity.
- `server/services/opportunity.py`: native host composition scopes owner/project/actor from authenticated `CurrentUserInfo`; accepted policy lookup locks adaptation heads including new-key phantoms. B must preserve full creative-policy tuple/profile revision currentness; never accept caller policy as authority.

## Existing adapter qualification probe and limits

At exact candidate912abc3b, native command:

`python -m pytest tests/unit/r2/learning/test_adapters.py -q --junitxml=/tmp/m9b-existing-adapters-912abc3b.xml`

Result:11passed,1existing SQLAlchemy expression-index reflection warning,1.55s. Raw log `/tmp/m9b-existing-adapters-912abc3b.log`. This is an M8 existing-behavior probe, not an M9-B implementation or donor-runtime test.

Public `r2.learning.adapters.observe_youtube_days` consumes explicit query scope, day rows, status and `LineageBinding`, produces `AdaptedRecord`/`LearningObservation`, preserves source units and distinguishes missingness/corrections. Graph both-direction trace returned2callers and14callees with no pagination; several generic `get`/`items` edges are heuristic and are not authority evidence. Source and fixtures confirm query scope identity, Pacific day windows, no minutes-to-seconds rewrite, finite values, duplicate/out-of-window rejection and correction lineage. That is a regression semantic reference. Its output contains M8 raw envelopes/digests and has no M9 snapshot/page/data-class clocks/erasable refs/capability authority. Do not substitute it directly for M9 normalization or label that substitution reusable production behavior.

No compatible concrete SourceCapabilityPort/SnapshotEvidenceStore implementation has yet been qualified by this investigation. This is a qualification gap, not an exhaustive assertion that no duck-typed implementation exists anywhere. The eventual B plan must identify and probe actual host implementations or explicitly own the missing implementations with fail-closed composition. M9 never issues/upgrades source permission or receives raw credential tokens. The spec explicitly allows initial ManualImportSource and a fixture InMemorySnapshotEvidenceStore; that fixture is not evidence of production durable storage or live activation.

## Frozen behavior checklist for B planning

- `declare_query`: exact adapter operation/schema, host grant/evaluation digest/actor/scope, full cohort/profile/policy tuple, intent/data classes, no token material, revision/head CAS and durable exact command replay.
- `acquire`: command guard before attempt lookup; one attempt per full command key; prepare/I/O/finalize, no transaction across ports; same-command retry returns current attempt state, no duplicate call; provider request identity or qualified-operator receipt for unknown-outcome reconciliation.
- Before every page: recheck grant/evaluation and exact profile revision; distinguish known refusal from unknown in-flight outcome. Keep coverage and partial pages explicit.
- Persist DB page admission and per-class clocks; mixed-class minima; exact retention boundary refuses use; replay never renews clocks; `None` intervals mean an explicit no-interval rule, not missing policy.
- Verify evidence-store integrity refs before authoritative metadata; raw source identities, values and unretained digests remain erasable. Normalization preserves native field/definition/version/value/unit/window/missingness with one exact raw-field lineage; no scores or derivation.
- V1 ceilings:64KiB canonical parameters,20pages,1000records,2MiB/page,40MiB/snapshot. Reject before I/O or before authoritative page acceptance at the correct boundary.
- Manual import uses Human uploader, declared origin/policy and same attempt/snapshot path, without a credential. External-provider descriptors remain dormant/unavailable with zero credential/network access on refusal. Do not refresh provider eligibility facts from old design notes into a claim of current access.
- B does not query future M9-E invalidation tables or activate invalidation routes/workers. E owns guard/coverage integration and erasure traversal. Final M9 acceptance remains sequence-gated through F.
- The A-only foundation inventory exception is not a blanket B parity waiver. Classify actual B donor consumption from inspected source/fixture reachability; any consumed donor runtime behavior requires its exact-pin paired offline harness. Never claim donor runtime or parity PASS from a source inventory.

## Qualified storage comparison and remaining host authority boundary

Inspected at the same native source revision: `lib/artifact_manifest.py` `ArtifactManifestAdapter`137-183 and `ProjectArtifactManifestAdapter.delete_entry`1134-1154 manage manifest entries; deletion removes the entry/empty manifest, not the underlying payload, raw identity mapping or integrity refs. `r2/host_hardening/master_authority.py` `CandidateObjectStore`121-128 owns typed verified candidate objects and has no erasure operation. Neither inspected API directly implements M9's erasable evidence-store contract. These are bounded interface comparisons, not claims of exhaustive absence across the repository.

`lib/json_io.atomic_write_bytes`72-96 writes a same-directory temporary, flushes/fsyncs and replaces its target. It is reusable as the byte-write primitive; it is not put-if-absent and must not overwrite a committed evidence object. The B plan owns the missing host adapter and tests conditional publication, scope, integrity, restart and exact erasure. Qualification of its new behavior remains a B task, not a claimed existing implementation.

Host SourceCapabilityPort remains the authority input: approved offline fixture implementations must prove the structured manual-uploader/origin/payload-policy conditions. Missing host authority always rejects; M9 may persist consumed evidence but never mint a grant. No fixture or local filesystem object activates a provider or grants rights over real data.

## Next concrete outputs after gates

The written B packet derives from accepted predecessor04b1b921. Its production-code steps remain blocked until the Human approves the concrete fixture proposal and packet. B0 pins that decision and all source hashes; no elapsed time or general continuation instruction is converted into a data-class/retention approval. The source-based plan is authored for review, not released for implementation. No additional reviewer is dispatched for this planning document.

## Verified migration/test maintenance impact

Literal head search in `tests/integration/lib/db/migrations` found exactly thirteen files expecting9a: the twelve legacy compatibility files plus A's migration wrapper. B's new tip will require9b in their tip assertions; the M8 aggregate downgrade set must add the nine B tables. A's direct five-table round trip currently starts from `Base.metadata` and must prepare the predecessor state by downgrading B before dropping A, then restore B. Historical revision and exact table assertions stay intact.

The A script-test `AmendmentSource` currently populates every simulated Git ref from mutable current filesystem bytes (`tests/unit/scripts/r2/test_verify_m9_scope.py`282-299). After legitimate B export/test changes, this would falsely represent B bytes as the frozen A fixture. The B plan pins this fixture's bytes to actual tested A commitfd9543de and reruns its scope/parity/evidence consumers. This changes test construction, never the accepted A verifier or historical sponsor bytes.
