# M8-C Signed Grant Contract Implementation Plan

> **For agentic workers:** Implement this plan task by task with test-first checks. This plan covers only the pure signed-event boundary; no database, route or production activation.

**Goal:** Parse and verify a canonical, bounded Governance Showrunner event with a pinned Ed25519 public key.

**Architecture:** `r2/contracts/showrunner_grant.py` owns strict event shape and canonical byte parsing. `r2/governance/grant_signature.py` owns signature verification against an explicit public key; the importer will later own sequence, scope and ledger transactions. No runtime key loader or grant issuer is introduced.

**Tech Stack:** Python 3.12, Pydantic, `lib.content_digest`, `cryptography`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-06-r2-m8c-grant-and-review-evidence-design.md`

## Global Constraints

- One pinned Ed25519 public key supplied by a caller; no embedded test or production key.
- Canonical UTF-8 JSON, 65,536-byte maximum, exact schema and fields, UTC seconds timestamps, `sha256:` event digest.
- V1 spatial pair contracts and digest vectors stay unchanged.
- No database, route, migration or production grant adapter in this packet.

## Review Focus

- Duplicate JSON keys, noncanonical whitespace/field order, invalid UTF-8 and oversized bytes deny.
- Wrong key ID, changed signed field, bad signature encoding and invalid signature deny.
- Boolean sequence, invalid predecessor shape, impossible ISSUE window and REVOKE carrying window fields deny.
- Errors do not echo submitted event or signature.
- Valid ISSUE and REVOKE fixed vectors verify against an ephemeral test key.

## Task 1: Canonical event contract

- [x] Add failing tests in `tests/unit/r2/governance/test_signed_grant_contract.py` for strict parsing and valid ISSUE/REVOKE bodies.
- [x] Implement `parse_grant_event(raw: bytes) -> ParsedGrantEventV1` in `r2/contracts/showrunner_grant.py`, returning typed body, signature bytes, canonical signed bytes and event digest. Reject duplicate keys and noncanonical serialization before Pydantic validation.
- [x] Run the focused tests and Ruff check/format for changed files.

## Task 2: Pinned-key signature verification

- [x] Add failing tests using a fixed test-only Ed25519 key for valid signatures, wrong key ID, tampered body/signature, wrong key and sanitized failures.
- [x] Add `cryptography` as a direct runtime dependency without upgrading unrelated pins.
- [x] Implement `verify_grant_event(raw: bytes, *, key_id: str, public_key: bytes) -> VerifiedGrantEventV1` in `r2/governance/grant_signature.py`; call Task 1 parser, require the exact signer ID and 32-byte public key, and verify Ed25519 over canonical signed bytes.
- [x] Run focused tests, `scripts/audit_tests.py --check`, Ruff, basedpyright, lint-imports and deptry. Update M8-C handoff with exact HEAD and result; commit only this packet.
