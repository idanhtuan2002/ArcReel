# M8-C Signed Grant Checkpoint Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse and verify bounded, canonical, signed exact grant-head checkpoints without loading deployment keys or enabling Governance-backed routes.

**Architecture:** `r2/contracts/grant_checkpoint.py` owns strict wire shape, canonical bytes, scope ordering and digest. `r2/governance/checkpoint_signature.py` verifies Ed25519 using an explicit caller-pinned key. Both follow the existing Showrunner grant event contract; no database, filesystem or signer is introduced.

**Tech Stack:** Python 3.13, Pydantic, `lib.content_digest`, `cryptography`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-12-r2-m8c-governance-checkpoint-custody-design.md`

## Global Constraints

- The body schema is `governance.grant_head_checkpoint.v1` and the envelope has exactly `body` and `signature`.
- Sign and hash `canonical_json_bytes(body, allow_nan=False)`; accept only canonical UTF-8 envelope bytes.
- The initial bounded contract accepts at most 4,194,304 bytes and 10,000 sorted unique scopes. These are implementation limits to validate against a representative deployment fixture before activation.
- An empty head list is valid; each present head has strict positive sequence and lowercase `sha256:` digest.
- `checkpoint_sequence` is positive; `previous_checkpoint_digest` is null exactly at sequence 1.
- `issued_at` uses strict UTC seconds. Identities and key ID are nonempty, unpadded and not `*`.
- No database, route, Compose edit, file loader, key registry, private key or runtime approval adapter in this packet.

## Review Focus

- A checkpoint with duplicate or out-of-order scope records must deny instead of silently selecting one record.
- A different deployment, key ID, body byte or signature must deny without echoing submitted data.
- Boolean numeric fields and noncanonical envelope bytes must deny.
- A 10,001st head or 4,194,305th byte must deny before unbounded parsing.
- A correctly signed empty genesis and a sorted two-scope successor must verify with fixed digest/signature vectors.

---

### Task 1: Canonical checkpoint body and parser

**Files:**
- Create: `r2/contracts/grant_checkpoint.py`
- Create: `tests/unit/r2/governance/test_signed_checkpoint_contract.py`

**Interfaces:**
- Produces: `CheckpointInvalid(category: str)`, `GrantHeadCheckpointBodyV1`, `ParsedGrantCheckpointV1`, and `parse_grant_checkpoint(raw: bytes) -> ParsedGrantCheckpointV1`.
- `ParsedGrantCheckpointV1` contains `body`, 64-byte `signature`, `signed_bytes`, and `checkpoint_digest`.

- [x] **Step 1: Write failing parser tests.** Pin exact canonical genesis/two-scope bodies, sorted order, duplicate scope, excess scope count/bytes, malformed/duplicate JSON, invalid UTF-8, Boolean sequence, timestamp, identity, digest and signature encoding. Verify sanitized `CheckpointInvalid.category`.
- [x] **Step 2: Run RED.** Run `python -m pytest tests/unit/r2/governance/test_signed_checkpoint_contract.py -q`; expect import failure before the implementation exists.
- [x] **Step 3: Implement the bounded parser.** Follow `r2/contracts/showrunner_grant.py` for duplicate-key detection, canonical round trip, strict Pydantic validation and unpadded base64url. Check byte length before JSON decode and head count before Pydantic conversion; reject any order other than strict lexicographic `(user_id, project_name, principal)`.
- [x] **Step 4: Run GREEN and static checks.** The focused pytest selection, Ruff check/format, targeted basedpyright, lint-imports and deptry must pass.
- [x] **Step 5: Commit only Task 1** with its test and handoff evidence.

### Task 2: Explicit-key signature verifier

**Files:**
- Create: `r2/governance/checkpoint_signature.py`
- Modify: `tests/unit/r2/governance/test_signed_checkpoint_contract.py`

**Interfaces:**
- Consumes: `parse_grant_checkpoint(raw: bytes) -> ParsedGrantCheckpointV1`.
- Produces: `VerifiedGrantCheckpointV1` and `verify_grant_checkpoint(raw: bytes, *, deployment_id: str, key_id: str, public_key: bytes) -> VerifiedGrantCheckpointV1`.
- A verified result must retain the canonical signed bytes/digest and an exact-scope lookup. The caller supplies the trusted deployment ID, key ID and public key; the envelope cannot choose trust material.

- [x] **Step 1: Write failing verifier tests.** Pin a deterministic Ed25519 key/vector, valid genesis and two-scope successor, wrong deployment/key ID/public key, changed body, changed signature and sanitized errors.
- [x] **Step 2: Run RED.** The new verifier tests must fail because the verifier is absent.
- [x] **Step 3: Implement only the explicit-key verification adapter.** Reuse `cryptography` and the exception handling pattern in `r2/governance/grant_signature.py`; construct the scope lookup only after signature validation.
- [x] **Step 4: Run GREEN and affected gates.** Run the checkpoint/grant unit directory, test audit, Ruff check/format, targeted basedpyright, lint-imports, deptry and diff check. Record exact outputs and any unavailable checks.
- [x] **Step 5: Update the durable M8-C handoff and commit.** State that neither the file loader nor runtime/recovery equality gate is implemented, so no production approval is enabled.

The later registry/publication, startup recovery and transaction-bound gates are independent plans under the same spec. They require an operator custody design, disposable PostgreSQL/Compose drill, complete affected checks and independent exact-HEAD review before activation.
