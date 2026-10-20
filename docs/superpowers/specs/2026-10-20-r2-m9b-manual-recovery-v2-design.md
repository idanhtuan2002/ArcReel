# M9-B manual admission recovery — amendment specification

Status: WRITTEN_SPEC_FOR_REVIEW. Direction: proposal revision 2, advanced by Human instruction “tiep tuc sang buoc tiep theo”. This authorizes preparing this artifact; it is not a claim that the successor contract, implementation plan or release ceremony has been approved.

Baseline: `4c4861e9ae6fe74ca6828d676791ae203252e139`; predecessor A `04b1b92184a5d5b0643256be533332de6ed8b009`; original B release `5b7a4be9f4b083f1d00db8005b49d7ba664658b8`. Original B plan/fixture approval remains effective. This specification does not alter those immutable artifacts.

## 1. Intent and selection

Close the same-upload/different-bytes gap during manual host reconstruction, recover original admitted material without another source dispatch, and give an expired uncertain attempt a truthful public terminal outcome. Preserve original clocks, data-class restrictions, possible quota consumption, exact legacy replay and future E closure dependencies.

Recommended direction: independently authenticated erasable admission plus a versioned public expiry contract. Compared with keeping checkpoint-only recovery, this closes the seven reviewed requirements but adds a custody authority, publication reconciliation and successor serialization. A separate general-purpose upload registry release remains an alternative; this amendment defines only the scoped manual admission claim needed by B, not a general ingestion product. Checkpoint-only recovery remains the actual runtime behavior until the amendment is qualified.

Normative requirements below use MUST. They describe the proposed extension, not existing capabilities. The reviewed proposal remains supporting rationale: `RECOVERY-DESIGN-PROPOSAL-2026-10-20.md` revision 2.

## 2. Verified baseline and reuse limits

| Current source at baseline | Finding and consequence |
|---|---|
| `r2/contracts/opportunity.py:145,707,1404` | Six V1 attempt states; attempt/receipt use the frozen enum. Add successor models; do not widen this enum in place. |
| `lib/db/repositories/opportunity_acquisition.py:327,483` | Reader terminal checks and transition CAS explicitly recognize SUCCEEDED/FAILED. A new enum alone cannot close the lifecycle. |
| Same repository `:1174,1189,1215` | Current receipt replay/staging requires an existing snapshot and V1 terminal state. Expiry before checkpoint needs an explicitly snapshot-free successor receipt. Never synthesize an empty successful snapshot to pass this check. |
| `r2/opportunity/digests.py:64` | Result domain is `m9.command-result.v1`. Preserve legacy calculation; successor receipts require an explicit domain/version selector. |
| `r2/opportunity/ports.py:79,117` | Source fetch and store put/read/delete exist; immutable host binding, upload-claim authority and header-only receipt lookup are new internal seams. |
| `r2/opportunity/manual_import.py:110` | Fetch returns constructor-held bytes, not a filesystem read. Qualify reconstruction from admitted refs and pinned normalization; paths are never recovery authority. |
| `server/services/m9_evidence_store.py:161,239` | Attempt-scoped publication, co-located unkeyed hashes. Reuse I/O durability/conditional-write primitives only after fixture qualification; they do not prove authenticity against the filesystem owner. |
| `r2/governance/ceremony.py:178` | `sign_grant_event` signs ISSUE/REVOKE showrunner-role events with sequence/previous-event lineage. Its call surface cannot issue an upload claim. No key or grant authority reuse is selected. |
| `server/services/governance_attestation.py:146` | Startup challenge preflights an operator archive and returns public archive digests. This is not an upload-material signer or immutable upload registry. |
| `scripts/r2/verify_m9b_scope.py:29` | Verifier pins the original release blob, owned paths and migration chain. An edited release JSON or extra file cannot silently authorize itself. |

Evidence method: Tier 2 graph project `r2-m9b`, generation `2026-10-20T00:39:00Z`; exact snippets for attempt/receipt/grant signing and a depth-1 receipt trace found repository reconstruction and service finalization. Relevant application files have metadata-match/no recorded gap. Docs/scripts are excluded and were read directly. Graph evidence is best-effort, not an exhaustive donor search. No external signer/library/donor has been selected or qualified by this spec. The existing owner-write probe remains evidence of a current limitation, not a successful repair.

## 3. Authority and identities

MUST distinguish four principals: deployment configuration authority registers measured bindings; ingest custodian validates and seals original material; publication service writes erasable objects; scoped acquisition/reconciliation host consumes them. Project users, HTTP callers and interactive operators cannot select implementations/keys/roots or overwrite published objects. Object-writer credentials MUST NOT confer custodian signing/claim-replacement authority.

The trusted database and independent original-claim authority are security anchors. Store-owner replacement without that authority must be detected. Joint compromise of the authoritative DB and custodian is outside this guarantee. Fixture acceptance names its exact principals and isolation; it does not establish production provisioning.

Identity rules:

- Existing command identity `(user_id, actor_id, acquire, command_id)` remains the one dispatch/replay guard across projects. A matching key with another project/request conflicts; successor protocol version is included in the successor request binding, never used to allocate a second attempt under the same key.
- Stable upload claim identity is `(owner, project, source_kind, source_contract_version, opaque_upload_id, upload_version)`. It MUST be unique across attempts and processes. Original bytes/provenance/classes are immutable; differing claims conflict. An erased version remains spent and cannot acquire replacement content. New content needs a new upload version and command.
- Command publication identity additionally binds command, request/query closure, attempt/version and frozen host descriptor. It names one durable receipt; repeated equal publication returns the original refs, never a new capture timestamp.
- Opaque identities MUST be random/non-content-derived where retention forbids a content proof. Do not hide content hashes in keys, filenames, logs, metadata fingerprints, signatures or tombstones.

PLANNED preparation MUST freeze binding ID/version, scope, implementation and dependency measurements, normalizer/decoder definitions, non-secret configuration fingerprint, resolver/store namespace and independent verification-key identity before admission port calls. Every subsequent resolution uses this descriptor. Actual measurements MUST match; a label alone is insufficient. Missing old configuration records BINDING_UNAVAILABLE and stops automatic work. New default configuration cannot rebase the old command.

## 4. Persisted objects and retention

The SQL admission record MUST contain typed/versioned metadata: full command/request/query bindings; attempt/version; frozen descriptor; publication key/phase/version; original paired payload/integrity/authenticity refs; class/clock metadata; immutable first DB admission anchor; dispatch claim metadata; recovery disposition; cleanup/closure identity. Each metadata digest MUST be recomputed from the whole typed object on read and mutation. It is not a substitute for original-content authenticity.

The erasable attestation MUST bind material digest and actual bytes to upload claim, scope, command/request/query, attempt/version, frozen descriptor, classes and provenance. Its issuance MUST enforce one original upload-version claim, not merely sign arbitrary caller-supplied digests. SQL retains content proof only when every class permits it; otherwise digest/seal stay solely inside erasable objects. SQL retains only opaque refs, verifier identity and allowed metadata. Erasure covers attestations, receipt/index copies and claim comparison material as well as raw bytes.

An orphan-discovery receipt/header MUST be separate from the current inline-content JSON bundle. Header-only lookup by publication key MUST not read raw bytes, native IDs, forbidden proof, attestation content or the old bundle. It returns original opaque refs and permitted metadata or explicit absent/unverifiable state. Store-owner forged headers cannot establish READY; attachment still requires independent authentication while content access remains permitted. Expired publications can be located for exact cleanup without authenticating/reading expired content.

No automatic claim reissuance, re-signing or backfill from the current upload path is permitted for an old attempt lacking original authority. Existing checkpoint-only attempts remain legacy; no retroactive admission is invented.

## 5. SQL and I/O protocol

All source/store/capability/custodian I/O MUST occur outside SQL transactions. SQL mutations use existing command, policy, capability, cohort, query and attempt guard ordering; new shared-upload/publication guards require an explicit total order and native PostgreSQL interleaving proof before implementation acceptance. This spec does not assume current locking already covers new identities.

| Step | Durable boundary | Permitted next operation |
|---|---|---|
| Prepare | PLANNED with immutable descriptor under full command guard | CAS RUNNING; no source dispatch |
| Reserve | RUNNING + RESERVED intent committed | Scoped local claim/publication outside SQL |
| Publish | Independent claim/seal and durable exact store receipt | Verify actual original material outside SQL, while clocks permit |
| Attach | READY envelope + first DB admission anchor committed by version CAS | Compete for original dispatch claim |
| Claim | One durable dispatch owner under attempt/version guard | Revalidate original policy/clocks/binding, then one original fetch |
| Accept | Response matches original claim/bytes; durable page checkpoint | Normalize verified original bytes; finalize snapshot/observations/event/receipt atomically |

Capture anchor MUST be the first successful READY transaction's database admission time, no earlier than started_at. An ACK-lost commit retains that value. Copying/attachment/recovery MUST NOT extend any upstream custody, retention, refresh or operational deadline; effective access uses the earliest applicable deadline. Response time/provider observed time and local admission time remain distinct. If frozen snapshot clock invariants cannot represent this truth, the successor contract must specify the changed field before implementation.

Publication phases: RESERVED → READY or CLEANUP_PENDING; durable publication with no SQL attachment is the PUBLISHED_UNATTACHED fact discoverable from the receipt, even if the row still says RESERVED. READY cannot return to RESERVED. Cleanup proceeds CLEANUP_PENDING → ERASED only with exact deletion receipts and SQL closure confirmation. No READY-before-publication transition exists.

Commit ACK loss MUST be resolved by reading retained authoritative state, not rerunning writes or dispatch. Publication-before-attach crash MUST recover the same receipt/refs from intent or clean them up. Material loss after READY MUST record MATERIAL_UNAVAILABLE and block content use; no replacement publication. Shared-upload leases MUST prevent one orphan cleanup from erasing another live admission. No unfenced age/directory sweep is allowed.

A dispatch claim proves ownership, not source delivery. Any restart after a claim without proven response preserves uncertainty and never dispatches again. A retained READY envelope without a claim does not authorize a retry endpoint to dispatch; explicit reconciliation reconstructs only admitted local material. Same-command API replay returns current retained state before all port calls.

## 6. Recovery and public expiry successor

Manual no-checkpoint reconciliation MUST verify the original envelope, clocks, current scope/policy and exact binding; then verify original bytes/seal and use pinned decoder/normalizer. It MUST NOT call fetch_page, consult current upload/path mappings or treat a new ManualImportSource construction as original evidence. Recovered snapshots identify local-admission reconstruction honestly; they do not assert a provider response was observed. Required provenance/projection fields belong to the successor inventory before coding.

All content reads revalidate original clocks immediately before the read. Finalization rechecks original clocks/policy under authoritative SQL guards after I/O. If expiry wins during verification/normalization, discard uncommitted content-derived work and close recovery without publishing operational evidence. Exact boundary is DB now >= effective deadline. Erasure fencing wins against reading/finalization and never refreshes clocks.

Proposed public protocol identifier: `m9.acquisition.v2`. It introduces separate `AttemptStateV2`, `AcquisitionAttemptV2`, `AcquisitionReceiptV2` and versioned projection/digest handling in successor files. V1 imports, serialized bytes and digest algorithm MUST remain unchanged. New result domain: `m9.command-result.v2`; canonical body binds protocol/schema version, operation, request digest and receipt excluding result_digest. Version routing MUST be explicit; no parse-failure downgrade or ambiguous enum union.

New state `EXPIRED_UNRECOVERABLE` is terminal for the attempt lifecycle and retains unknown provider outcome. It MUST carry outcome_reason RESPONSE_OUTCOME_UNKNOWN plus a typed recovery disposition (retention expired or operational evidence stale), original deadline, closure DB time and resolver identity/version. `completed_at` means local lifecycle closure only. It MUST preserve original request/provider identity and possible consumed quota, and MUST have no outgoing transitions, clock renewal, refund or same-command redispatch.

| Original state | Expiry action in successor protocol | Authority |
|---|---|---|
| RUNNING, call may have occurred | Record OUTCOME_UNKNOWN with original uncertainty, then terminal expiry; transitions may be committed atomically with an audit record of both | Scoped expiry resolver + expected-version CAS + original deadline metadata + DB time |
| OUTCOME_UNKNOWN | EXPIRED_UNRECOVERABLE | Same resolver; no expired-content reads |
| NEEDS_OPERATOR | EXPIRED_UNRECOVERABLE solely for objective policy closure, preserving uncertainty | Explicit narrow exception proposed by this amendment; it grants no provider-outcome resolution or other operator powers |
| SUCCEEDED / FAILED / EXPIRED_UNRECOVERABLE | Exact retained replay | No transition |
| Proven no dispatch and known refusal | Existing separately qualified FAILED path with truthful partial coverage | Positive retained pre-dispatch proof, never absence of response |

The NEEDS_OPERATOR exception is an explicit change to frozen spec §10, not a claim that the existing qualified-operator rule allows it. If this exception is rejected, that transition remains unavailable and item 3 is partial for those attempts. Missing/unverifiable deadline metadata is a custody failure, not proof of expiry; preserve non-retryable operator disposition and report the closure gap honestly.

The successor receipt MUST allow zero snapshots only for EXPIRED_UNRECOVERABLE with the required closure metadata. Existing verified checkpoints/snapshots, if any, remain referenced without implying operational usability; no expired-content reads are needed to return their permitted metadata. Closure atomically stores attempt version/state, recovery disposition and immutable receipt. Concurrent expiry/finalization has one version winner; the loser rereads authoritative retained state. Lost closure ACK returns that exact receipt. Old terminal receipts replay with exactly their original V1 digest/bytes. V1 unresolved attempts MUST NOT silently upgrade or be parsed as V2; an independently authorized explicit migration would be needed.

## 7. Erasure dependency contract

One logical closure/job MUST include admission, publication/erase intents, stable claim/leases, headers, payload, identity, integrity and authenticity objects. SQL fence first; exact external deletion next; durable deletion receipts then SQL tombstone/phase finalization. Keep reads blocked throughout. Retain permitted opaque anchors until required deletions are confirmed.

Material-first/DB-failure MUST resume the same fenced closure and idempotent delete; it cannot recreate evidence or report COMPLETE. Envelope-first removal MUST be rejected while material may exist. Injected envelope loss MUST be recoverable through independent retained intent/receipt, otherwise remain unresolved custody failure. Shared object deletion requires the whole dependency closure. B qualifies isolated admission-side behavior; E must later qualify its actual global guards, traversal, shared dependencies and deadlines before integrated erasure acceptance.

## 8. Review traceability and qualification gates

| Human item | Binding spec requirement | Required observable evidence |
|---|---|---|
| 1 | §3 immutable per-command descriptor | Binding/config/key change before dispatch and after reconstruction refuses old-command substitution; new command does not replace old upload version |
| 2 | §3–4 unique stable claim + independent seal | Cross-process equal/different claim race; same refs + changed bytes + recomputed ordinary hashes rejected after READY and before response/finalization |
| 3 | §6 successor terminal state/receipt | Exact-deadline zero-content-read closure; zero-snapshot receipt; unknown quota/outcome retained; concurrent resolver/finalizer; V1 exact replay; operator exception denied outside expiry |
| 4 | §6 original refs + pinned normalization | Changed path, same path/different bytes, changed decoder/config after actual host reconstruction never substitute or fetch again |
| 5 | §7 same logical closure | Both deletion orders, ACK loss, lost envelope anchors and shared references remain fenced until completion proven; E acceptance separately required |
| 6 | §5 durable intent/receipt phases | Publish-before-attach crash/orphan recovery; missing post-READY material; illegal READY-before-publication refusal; header lookup performs zero content reads |
| 7 | Restart inventory below | Real process IDs/exit points plus persisted fault and sample inventory, no unexecuted sample labeled PASS |

Mandatory actual fresh-process pairs: immediately before/after READY commit including lost ACK; both sides of dispatch claim and immediately before dispatch; publication durable but SQL attachment absent. Deterministic faults MUST cover all other named boundaries, including source response/checkpoint/finalization and both erase orders. Additional real restarts sample those latter boundaries using persisted seed `m9-manual-recovery-restarts.v1`; any changed sampled boundary becomes mandatory real-process coverage. The seed value, selected cases and unselected cases MUST be recorded before execution.

Acceptance also requires actual native PostgreSQL uniqueness/CAS/lock races; process-safe filesystem publication/reopen; class-proof and upstream-deadline cases; sanitized exceptions; migration upgrade/downgrade; affected-domain/static gates; exact candidate tree/source hashes. The previous 752-case PASS is baseline evidence only and cannot qualify any extension requirement. This document has no executed extension PASS.

## 9. Proposed release inventory and decisions before implementation

The existing B verifier cannot accept this expansion unchanged. A new immutable amendment record MUST reference the original release and exact predecessor/candidate SHA, the approved spec/plan hashes, new fixture/protocol versions, complete create/modify paths and migration strategy. A separately reviewed successor verifier MUST preserve the original A/B authority checks and validate the additive amendment; editing the pinned release blob or weakening the old verifier is forbidden.

| Inventory area | Existing owned path or proposed addition | Required treatment |
|---|---|---|
| Successor public contracts/ports/digests | NEW successor files beside frozen A contracts/ports; exact filenames to be fixed in implementation plan | Additive release ownership and explicit reader/version routing; frozen files remain byte-identical |
| Admission domain, host publication/authority adapter | NEW internal modules beside `r2/opportunity/` and `server/services/` | Exact paths, trust principal and call surface must be released; not assumed to fit old owned map |
| Attempt/admission/intent persistence | Existing B model/repository + proposed schema changes | Fix exact schema/constraints and total lock order after authority qualification; no unapproved tables |
| Migration | Existing B revision is already used by disposable tests | Plan must explicitly choose a new linear successor revision and migration-head verifier amendment; do not silently rewrite applied schema |
| Acquisition host/service | Existing B owned domain and host-factory paths | V1 replay isolated from V2 routing, no endpoint-controlled port binding |
| HTTP/readers/locales | Remaining B5 owned paths | Public V2 request/receipt negotiation and localized expiry semantics required before exposure |
| Tests/evidence/verifiers | Existing B fixtures/tests plus new custody/restart/amendment files | List exact paths; preserve one independent acceptance pass / one repair maximum, no automatic rereview |
| E handoff | New explicit dependency/phase fixture inventory | Does not release or accept E implementation |

Before an executable implementation plan can select a custody mechanism, research MUST qualify its actual primary-source implementation/version, pinned external donor if reused, real signing/verification/claim call surface, same synthetic fixture behavior, erasability and authority separation. Current grant signer/startup attestor are inspected non-matches, not a completed exhaustive reuse search. No signer, new dependency, production credential or general registry is selected here. License work remains outside scope.

Requested design decision: approve the independently authenticated admission direction and explicit V2 expiry/zero-snapshot receipt/operator-exception semantics above. This enables the bounded custody/source qualification and exact implementation/release-amendment plan; it does not activate a provider, grant production rights, mutate accepted A, or approve an as-yet unwritten plan. If the V2 semantic expansion is declined, retain V1 checkpoint-only recovery and report the remaining public-terminal requirement as unmet.

## 10. Self-review and scope

Self-review checked seven-item traceability, same-command at-most-once behavior, expiry without content reads, terminal receipt without fabricated snapshot, original clocks, orphan discovery without raw reads, both erasure orders, legacy compatibility and release pinning. Unresolved implementation choices are explicitly gated research inputs rather than assumed capabilities. This is an architecture-level specification, not an executable plan or acceptance report.

This file stays in the ignored durable handoff directory because the original immutable B release does not own a new tracked design artifact. On amendment approval, its exact bytes/hash must be incorporated by the additive release ceremony. Do not force-add it or edit the original release to make the existing gate green.
