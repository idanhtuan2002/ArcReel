# M8-C source identity digest vectors

Status: proposed canonical contract examples, not persisted authority, source-media evidence or acceptance. Fixture: `tests/fixtures/r2/m8c_source_digest_vectors.json`; check: `tests/unit/r2/advanced_creative/test_m8c_source_digest_vectors.py`.

The fixture freezes six illustrative envelopes under canonical JSON version `1`: MASTER and REVERSE frame identities, their derivation receipts, and two versions of one pair decision (`APPROVE` followed by `REJECT`). Each case contains the full body, exact UTF-8 canonical JSON text and expected SHA-256 digest. The test compares those bytes with the current M8 canonical encoder, independently hashes the stored canonical bytes and checks that material parent, recipe and frame changes alter identity. Placeholder media/authorization/evidence digests are syntactically shaped values for serialization; they do **not** attest to real video, frame extraction, reviewer authorization or geometry.

| Domain | Bound fields in this proposed v1 body |
| --- | --- |
| `r2.m8.spatial.frame.identity.v1` | User/project, exact parent artifact key/master version/candidate/content digest, zero-based decoded frame index, recipe version, decoder identity, exact PNG content digest. |
| `r2.m8.spatial.frame.receipt.v1` | Complete frame identity, derived frame candidate ID, frame byte size/probe digest, creation time and command digest. |
| `r2.m8.spatial.pair.decision.v1` | User/project, pair ID/version, exact target version/digest, binding/core digest, ordered MASTER/REVERSE receipt IDs/digests, reviewed evidence refs **and digests**, reviewer identity/scope, authorization ref/digest, decision/time and command digest. |

`frame_candidate_id` is `m8f:` plus the complete 64-character lowercase SHA-256 hex of the frame identity envelope. The receipt ID in the initial schema equals that candidate ID, but its receipt digest is separate. The pair body carries no internal filesystem `object_ref`; a server reader resolves each opaque receipt/candidate ID in the caller's scope and rehashes its body and media bytes. The fixture's REJECT decision has the same pair/frame identities at version 2 with a distinct command and authorization; it demonstrates digest separation, not an implemented state transition.

The acceptance design must still freeze binding, target, spatial set, preview, receipt, snapshot and submit digest vectors, plus model validation and PostgreSQL constraints. No current table or service accepts the fixture bodies. An independent review of the exact design HEAD is required before implementation treats these examples as final wire authority.
