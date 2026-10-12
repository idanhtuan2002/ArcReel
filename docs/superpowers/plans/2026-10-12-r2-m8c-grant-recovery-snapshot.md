# M8-C Grant Recovery Snapshot Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify that every local signed grant chain exactly matches one externally supplied signed checkpoint under the recovery scan fence.

**Architecture:** Add an internal `GovernanceGrantRecoveryScanner` beside the existing `_GrantLedger` in `server/services/governance_grants.py`, reusing `_current_locked` for complete event-chain validation. It takes an async checkpoint-byte loader so loading happens after the exclusive fence is acquired. It verifies those bytes with the pure checkpoint verifier and explicit trusted keys, then compares sorted database scopes and exact heads. No file loader or startup caller is added.

**Tech Stack:** Python 3.13, SQLAlchemy async, PostgreSQL 16, Ed25519, pytest.

**Spec:** `docs/superpowers/specs/2026-10-12-r2-m8c-governance-checkpoint-custody-design.md`; fence prerequisite: `docs/research/2026-10-12-r2-m8c-grant-import-recovery-scan-fence.md`.

## Global Constraints

- Acquire the exclusive PostgreSQL transaction fence before calling the checkpoint loader or enumerating scopes.
- Verify the checkpoint signature and deployment ID with explicit caller-pinned key material; never trust the signed key ID to select an untrusted key.
- Enumerate all scopes in sorted exact identity order; reject a missing/extra scope, empty committed head, sequence/digest mismatch or any broken signed event chain.
- Recompute every stored event digest from signed body bytes through the existing `_GrantLedger._current_locked` path; do not trust digest columns alone.
- Treat a REVOKE head as valid recovery state, while a current-grant reader correctly denies it for approval.
- Scanner remains internal with no filesystem loader, startup hook, route, migration or production activation.

## Review Focus

- A matching empty genesis and matching ISSUE/REVOKE checkpoints pass.
- Pre-REVOKE database against post-REVOKE checkpoint denies as rollback; an older signed checkpoint against newer DB denies.
- Extra/missing checkpoint scope and corrupted stored event bytes/digest deny.
- A scanner that waits for an in-flight import loads the checkpoint only after the import commits and the exclusive fence is acquired.
- Unsupported database dialect and malformed/unavailable loader output deny without starting workers.

---

### Task 1: Internal full-chain recovery scanner

**Files:**
- Modify: `server/services/governance_grants.py`
- Create: `tests/integration/r2/governance/test_grant_recovery_snapshot.py`

**Interfaces:**
- `GovernanceGrantRecoveryScanner(session_factory, *, grant_key_id: str, grant_public_key: bytes, deployment_id: str, checkpoint_key_id: str, checkpoint_public_key: bytes)`.
- `verify(load_checkpoint: Callable[[], Awaitable[bytes]]) -> VerifiedGrantCheckpointV1` loads only after the exclusive fence, then compares all DB scopes and complete chains.
- Invalid content/DB state raises sanitized `GrantRecoveryUnavailable`; unsupported dialect remains `GrantRecoveryFenceUnavailable`.

- [x] **Step 1: Write failing source-backed tests.** Use deterministic test-only Ed25519 keys and real imported ISSUE/REVOKE chains. Pin empty/matching success, rollback and changed signed checkpoint, extra/missing scope, corrupt event, loader failure, and a forced import-first load-order schedule on disposable PostgreSQL. Assert no scanner success on SQLite.
- [x] **Step 2: Run RED.** The new test module must fail import at absent scanner API.
- [x] **Step 3: Implement the internal scanner.** Use existing `_current_locked` under sorted row locks; compare the exact `(sequence, digest)` to each checkpoint record and verify set equality. Map malformed checkpoint and chain errors to sanitized recovery-unavailable errors.
- [x] **Step 4: Run GREEN and affected gates.** Run complete grant/review PostgreSQL selection, affected SQLite/unit tests, Ruff check/format, targeted basedpyright, lint-imports, deptry, test audit and diff check.
- [x] **Step 5: Update the durable M8-C handoff and commit.** Record exact HEAD/tests and leave external key custody, startup wiring and production approval closed.

This scanner is a testable building block. A future deployment packet must own operator-key registry, atomic directory loader, Alembic/startup ordering, recovery restore drill, transaction-bound runtime equality and independent exact-HEAD acceptance review.
