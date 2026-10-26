# M10 A0/A1 pure contract foundation implementation plan

> **For agentic workers:** Use superpowers:executing-plans serially, with test-driven-development. Do not start until the separate bounded design envelope passes its bootstrap.

**Goal:** Implement the M10-A scope guard and immutable contracts/digests without opening runtime authority.

**Architecture:** Reuse the released M7/M8 identity/canonical seams. A0 delegates structural custody to the accepted design-owned bootstrap and checks exact implementation scope/imports. A1 produces data/validation and digest helpers only. No host runtime adapter is composed.

**Tech Stack:** Python/Pydantic, existing M8 CanonicalJsonObject/canonical bytes, pytest, Git-object reads.

**Spec:** original2026-09-16 M10 design §4.1/§5.1 plus2026-10-25-r2-m10-contract-packet.md. The latter takes precedence only for this separately reviewed A0/A1 packet.

## Global constraints

- Only the exact nine paths in R2_M10_CONTRACT_PACKET_2026-10-25.json may change after acceptance. A new path requires a reviewed amendment.
- No database/ORM/migration, probe process, API, provider, credential, export, M9 edit or production activation.
- Original full M10 design/predecessor gate remains closed. Bounded success is CONTRACT_IMPLEMENTATION_ELIGIBLE only; it cannot release original A2-A7 or B.
- Entity models are frozen and recursively immutable; all extra fields forbidden, all checksums domain-separated with the exact accepted canonical bytes.
- Preserve all seven observations and typed requirements; no type constructor grants Human authority or asserts runtime currentness.
- Complete action-lease time pairs are positive and at most30seconds; final-disposition issued/expiry pairs at most7days; final WAIVE at most24hours. Absolute request expiry is aware/required in A1; remaining lifetime/policy caps are checked against locked DB admission time in A6. WAIVE cannot waive identity/integrity/authority/closure/currentness.
- Every command/receipt key includes user/project/actor/operation/command. Requests exclude command_id and their own request_digest from their semantic digest.
- Tests use deterministic fixtures, no provider/network calls, and no new source generator. This packet requires no database to exercise its contract behavior.

## Review focus

- Shallow frozen models must not retain mutable metadata/body aliases.
- Future authorization receipt/admission fields must not create a profile/request digest cycle.
- Directly comparable source-head/approval/edge mismatch must fail structural validation; host-generation to M7 candidate mapping is stateful A5 qualification, not A1 equality; an internally coherent subject must still not be called the current real master.
- B digest tags and operations cannot pass through an A prefix/default fallback.
- A scoped acceptance cannot open full-M10 code or runtime paths.

## A0: Implementation scope guard

Files: scripts/r2/verify_m10_scope.py and mirrored unit/integration tests.

- [ ] Bind the exact bounded acceptance commit SHA from the separate ceremony. Do not search for a success-shaped record or create one.
- [ ] Run `python scripts/r2/verify_m10_bootstrap.py --packet contracts --acceptance-ref <accepted-sha> --preflight`; require CONTRACT_IMPLEMENTATION_ELIGIBLE. On refusal create no product file.
- [ ] RED tests: absent/wrong acceptance, changed bootstrap/core source, dirty owned paths including index-only/ignored work, path outside the exact list, migration drift, forbidden DB/network/subprocess/Production Authority import and extra top-level side effects.
- [ ] Implement a read-only guard using the accepted GitRepository/load_json/verify(packet=contracts) seam. Revalidate accepted bootstrap runtime bytes and both endpoint HEADs. Require an explicit exact --acceptance-ref for descendants of acceptance; do not use current HEAD as the acceptance commit implicitly.
- [ ] Contract code imports only approved pure scalar/model/immutable/canonical/metadata/identity seams. The empty r2/quality/__init__.py may carry no behavior. Validate direct import/call policy with exact source inspection, not an assertion that an AST denylist is a general sandbox.
- [ ] GREEN real disposable-Git tests preserve complete repository snapshots, invoke from committed source and refuse an expanded scope. Run affected verifier tests, lint/type/test audit; commit only these three paths.

## A1: Immutable contracts and digest registry

Files: r2/contracts/quality.py, behavior-free r2/quality/__init__.py, r2/quality/digests.py, tests/unit/r2/contracts/test_quality.py, tests/unit/r2/quality/test_digests.py.

- [ ] RED field/roundtrip tests for every original A contract plus the explicitly patched draft/request/master/metadata/edge types. No B contract/type/operation may be exported.
- [ ] RED for mutable input aliases, extra fields, nonfinite values, naive time, wrong new-entity UUIDv7, normalized foreign identity, duplicate/unknown rule/requirement/slot IDs, invalid N_OF_M, missing/cyclic escalation and source edges, wrong metadata/head approval, wrong dependency raw-generation/host-version/media-fingerprint, master:A-to-childB aliasing even with equal bytes/version, noncanonical key encoding and cross-episode edges.
- [ ] RED profile parent/genesis consistency, complete run request/ObservationBinding roundtrips and every profile_id/profile_revision mutation, command/subject/draft scope mismatch, action confusion, lease bounds at0/30/>30seconds, mandatory aware request expiry, final-disposition WAIVE0/24h/>24h using explicit issued_at/expires_at pairs, and non-WAIVE waiver payloads. Do not claim a request-only constructor can compute remaining TTL; A6 tests enforce absolute expiry against DB-time admission.
- [ ] Implement frozen/extra-forbid models; use existing CanonicalJsonObject for stored metadata and temporary host metadata validation. Never store the mutable host model in a frozen public body.
- [ ] RED golden digest vectors for every original §5.1 A tag plus the five explicit added tags. Unknown and reserved B tags fail. Key order is invariant; each normative field mutation changes its applicable digest. Checksums' own cache fields never feed themselves; future lease/receipt fields never feed preflight subjects.
- [ ] Implement a closed exact-domain registry and verify-cache helpers using accepted M8 canonical bytes. Recompute cached body digests before declaring fixture validity; type constructors alone are not authority admission.
- [ ] Include valid master metadata/edge fixtures with distinct raw-generation and M7 candidate IDs, and rejected directly comparable mismatch fixtures. Mutate each candidate identity independently and require digest changes; do not claim stateful mapping refusal in A1. Document constructor coherence versus A5 resolver/store/currentness/byte verification.
- [ ] Run contract/digest tests twice and compare vectors; affected M8 canonical/contract regressions, relevant static gates and test audit. Commit only the five owned paths.

## Packet evidence and stop

- [ ] Create only docs/r2/evidence/R2_M10_A_CONTRACTS_CANDIDATE.json after both tasks' tests/gates pass, with exact clean source HEAD/parent, acceptance ref, file hashes, commands/results, zero tests skipped and explicit no-runtime boundaries.
- [ ] Run the scope guard against the committed candidate, independently review the bounded implementation and repair material findings with RED/GREEN before requesting its acceptance.
- [ ] Do not start A2/A3, create a migration, qualify a factual/custodian adapter, mark M10-A complete or deploy from this packet. Those require the original next-packet gates or a separately reviewed amendment.

## Pure dependency amendment before review

Use the contract packet's fixed released ancestor and separately fixed verified local implementation base. Consume only r2/artifact_identity.py and r2/contracts/artifact_metadata.py for identity/metadata. Preserve raw codec wire bytes; safe master refs use the separate leaf validator. Bootstrap pins the exact preparation evidence, checks its source parent/hashes and the observed pure import closure, and protects all consumed source/config/lock paths against dirty/hidden changes. Re-run affected verifier tests with adversarial source/base/evidence/closure cases and both live refusal modes before freezing a new normal single-parent review candidate. No product file or acceptance is created by this amendment.

## Normative repair after review63cc4e986

The candidate failed one high and two medium findings; reviewer B was not started. Existing host _metadata and artifact_key_for both derive identity from target_ref, so every root/dependency metadata snapshot now explicitly equates contract_ref.id to decoded key resource, and master children additionally equate it to shot_ref. No prior M10 waiver comparator exists; reuse the pinned canonical_json_bytes helper for full-binding byte sorting, with explicit null handling and duplicate logical-key refusal. Close the rule catalog across probe/freshness/slot/waiverable refs with per-collection uniqueness and freshness(rule_id,evidence_kind) keys. Required A1 refusal/permutation cases are in the packet; no product validator/test pass is claimed. Freeze another candidate and obtain two fresh independent reviews of the same bytes.

## Review be304aa58 repair

Retain the absolute-expiry request contract and explicitly split temporal obligations: A1 checks known time pairs on final records/leases and request expiry awareness; A6 alone validates request remaining lifetime/policy caps against locked DB time and stamps issued/admitted/expiry without clamping caller intent. This uses the review's allowed deferral alternative, not a weaker runtime TTL gate. All decoded root/dependency resource IDs must pass the existing safe-target leaf. Add exact host-characterization SHA/mode pins and dirty protection, including deliverables and package initializers, without allowing host imports in A1. RED13fail77pass demonstrated the missing host guards; new unit and disposable-Git cases cover them. Previous FAIL remains withdrawn, no product implementation or acceptance yet.

## Review14076 repair

Candidate14076 received A PASS and B FAIL; neither decision accepts a later candidate. Keep raw host generation IDs and statefully projected M7 candidate-object IDs separate. A1 binds both without computing their mapping; A5 must reuse the real scoped/legacy resolver and candidate store under qualified concurrency controls, including registration races. Pin the five additional owner/ADR characterizations without extending imports. Bootstrap now explicitly requires each fixed M7/M8 acceptance to precede the fixed released V2 base. A negative merge-DAG fixture reproduced acceptance by the old check; the repaired check and read-only disposable-Git policy test must refuse it. Obtain two fresh reviews on the same repaired candidate before A0/A1.
