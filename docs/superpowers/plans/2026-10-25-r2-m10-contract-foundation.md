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
- Separate action leases are positive and at most30seconds; dispositions at most7days; WAIVE at most24hours and cannot waive identity/integrity/authority/closure/currentness.
- Every command/receipt key includes user/project/actor/operation/command. Requests exclude command_id and their own request_digest from their semantic digest.
- Tests use deterministic fixtures, no provider/network calls, and no new source generator. This packet requires no database to exercise its contract behavior.

## Review focus

- Shallow frozen models must not retain mutable metadata/body aliases.
- Future authorization receipt/admission fields must not create a profile/request digest cycle.
- Source-head/approval/edge mismatch must fail structural validation; an internally coherent subject must still not be called the current real master.
- B digest tags and operations cannot pass through an A prefix/default fallback.
- A scoped acceptance cannot open full-M10 code or runtime paths.

## A0: Implementation scope guard

Files: scripts/r2/verify_m10_scope.py and mirrored unit/integration tests.

- [ ] Bind the exact bounded acceptance commit SHA from the separate ceremony. Do not search for a success-shaped record or create one.
- [ ] Run `python scripts/r2/verify_m10_bootstrap.py --packet contracts --acceptance-ref <accepted-sha> --preflight`; require CONTRACT_IMPLEMENTATION_ELIGIBLE. On refusal create no product file.
- [ ] RED tests: absent/wrong acceptance, changed bootstrap/core source, dirty owned paths including index-only/ignored work, path outside the exact list, migration drift, forbidden DB/network/subprocess/Production Authority import and extra top-level side effects.
- [ ] Implement a read-only guard using the accepted GitRepository/load_json/verify(packet=contracts) seam. Revalidate accepted bootstrap runtime bytes and both endpoint HEADs. Require an explicit exact --acceptance-ref for descendants of acceptance; do not use current HEAD as the acceptance commit implicitly.
- [ ] Contract code imports only approved pure scalar/model/immutable/canonical/metadata seams. The empty r2/quality/__init__.py may carry no behavior. Validate direct import/call policy with exact source inspection, not an assertion that an AST denylist is a general sandbox.
- [ ] GREEN real disposable-Git tests preserve complete repository snapshots, invoke from committed source and refuse an expanded scope. Run affected verifier tests, lint/type/test audit; commit only these three paths.

## A1: Immutable contracts and digest registry

Files: r2/contracts/quality.py, behavior-free r2/quality/__init__.py, r2/quality/digests.py, tests/unit/r2/contracts/test_quality.py, tests/unit/r2/quality/test_digests.py.

- [ ] RED field/roundtrip tests for every original A contract plus the explicitly patched draft/request/master/metadata/edge types. No B contract/type/operation may be exported.
- [ ] RED for mutable input aliases, extra fields, nonfinite values, naive time, wrong new-entity UUIDv7, normalized foreign identity, duplicate/unknown rule/requirement/slot IDs, invalid N_OF_M, missing/cyclic escalation and source edges, wrong metadata/head approval/candidate/version/fingerprint.
- [ ] RED profile parent/genesis consistency, command/subject/draft scope mismatch, action confusion, lease bounds at0/30/>30seconds, mandatory expiry, WAIVE0/24h/>24h and non-WAIVE waiver payloads.
- [ ] Implement frozen/extra-forbid models; use existing CanonicalJsonObject for stored metadata and temporary host metadata validation. Never store the mutable host model in a frozen public body.
- [ ] RED golden digest vectors for every original §5.1 A tag plus the four explicit added tags. Unknown and reserved B tags fail. Key order is invariant; each normative field mutation changes its applicable digest. Checksums' own cache fields never feed themselves; future lease/receipt fields never feed preflight subjects.
- [ ] Implement a closed exact-domain registry and verify-cache helpers using accepted M8 canonical bytes. Recompute cached body digests before declaring fixture validity; type constructors alone are not authority admission.
- [ ] Include valid master metadata/edge fixtures and rejected mismatch fixtures. Document constructor coherence versus A5 external currentness/byte verification.
- [ ] Run contract/digest tests twice and compare vectors; affected M8 canonical/contract regressions, relevant static gates and test audit. Commit only the five owned paths.

## Packet evidence and stop

- [ ] Create only docs/r2/evidence/R2_M10_A_CONTRACTS_CANDIDATE.json after both tasks' tests/gates pass, with exact clean source HEAD/parent, acceptance ref, file hashes, commands/results, zero tests skipped and explicit no-runtime boundaries.
- [ ] Run the scope guard against the committed candidate, independently review the bounded implementation and repair material findings with RED/GREEN before requesting its acceptance.
- [ ] Do not start A2/A3, create a migration, qualify a factual/custodian adapter, mark M10-A complete or deploy from this packet. Those require the original next-packet gates or a separately reviewed amendment.
