# M8-C Grant Import and Recovery Scan Fence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fence new grant scopes across processes while a future recovery scanner enumerates exact grant heads.

**Architecture:** A small `server/services/governance_grant_fence.py` module reserves one two-integer PostgreSQL transaction advisory key and exposes shared/import and exclusive/scan acquisitions. `GovernanceGrantImporter.import_event` takes shared before its first head insert. The exclusive API is internal and has no startup caller until the full scanner exists.

**Tech Stack:** Python 3.13, SQLAlchemy async, PostgreSQL 16, pytest.

**Spec:** `docs/superpowers/specs/2026-10-12-r2-m8c-governance-checkpoint-custody-design.md`; bounded lock research: `docs/research/2026-10-12-r2-m8c-grant-import-recovery-scan-fence.md`.

## Global Constraints

- Reserved key is the two-integer pair `(0x4D384743, 1)`; do not use the existing one-bigint hashed-text namespace.
- Import shared fence precedes any scope-head insert or row lock in the same transaction.
- Scan exclusive fence precedes any scope enumeration and lasts through its transaction; non-PostgreSQL scan acquisition denies.
- A SQLite importer remains available for existing isolated unit tests, but SQLite supplies no cross-process recovery acceptance.
- Normal current-grant readers do not take the global fence; keep target/binding/pair/parent/grant/review lock order.
- No startup scanner, external key loader, production route or activation in this packet.

## Review Focus

- An import after scanner exclusive acquisition waits before any head insert.
- Scanner exclusive acquisition after an importer shared lock waits, then sees the committed new scope.
- Two different-scope imports may share the fence concurrently.
- A failed import releases its fence and leaves no committed empty head.
- A reader holding its scoped head must not deadlock with a waiting importer/scanner.

---

### Task 1: Shared/exclusive fence and importer integration

**Files:**
- Create: `server/services/governance_grant_fence.py`
- Modify: `server/services/governance_grants.py`
- Modify: `tests/integration/r2/governance/test_grant_importer.py`

**Interfaces:**
- `acquire_grant_import_fence(session: AsyncSession) -> None`: PostgreSQL shared transaction lock; SQLite test path is a no-op.
- `acquire_grant_recovery_scan_fence(session: AsyncSession) -> None`: PostgreSQL exclusive transaction lock; other dialects raise a sanitized `GrantRecoveryFenceUnavailable`.

- [ ] **Step 1: Write failing forced PostgreSQL tests.** Use two backend PIDs and `pg_blocking_pids` for scanner-first and import-first schedules. Scanner-first asserts zero head rows while blocked; import-first enumerates the new scope only after the import commits. Add a concurrent different-scope shared-lock check and rollback-release check. Keep task cleanup in `finally`.
- [ ] **Step 2: Run RED.** The tests must fail at the absent fence module or show an importer continuing past an exclusive scanner lock.
- [ ] **Step 3: Implement the two small fence functions and insert shared acquisition as the import transaction's first DB action.** Use `pg_advisory_xact_lock_shared(:namespace, :version)` and `pg_advisory_xact_lock(:namespace, :version)` with the reserved constants. No session-level advisory lock.
- [ ] **Step 4: Run GREEN.** Execute complete affected grant/review tests on disposable PostgreSQL, affected SQLite/unit selection, Ruff check/format, targeted basedpyright, lint-imports, deptry, test audit and diff check. Record exact outputs and skipped tests.
- [ ] **Step 5: Update M8-C handoff and commit only this fence slice.** Keep scanner/startup and production approval closed.

The future recovery scanner must validate every chain and exact checkpoint scope/head equality while holding the exclusive fence. This plan does not count the fence helper alone as recovery acceptance.
