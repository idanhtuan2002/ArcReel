# M8-C Frame Receipt Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve a pinned frame receipt to current approved parent lineage and exact verified PNG bytes for server-side spatial consumers.

**Architecture:** A standalone reader locks one parent through `serialized_artifacts` and delegates to a transaction-aware reader. The transaction-aware reader rechecks scoped receipt, current master projection, parent bytes, candidate metadata and a private PNG snapshot before returning immutable bytes; it does not decide pair suitability.

**Tech Stack:** Python 3.13, SQLAlchemy async sessions, FastAPI service layer, FFprobe, pytest, PostgreSQL 16.

**Spec:** `docs/superpowers/specs/2026-10-04-r2-m8c-frame-receipt-reader-design.md`

## Global Constraints

- Preserve the separate dirty `.worktrees/r2-m8c` C1 checkout and all unrelated work.
- No schema, provider submission, live migration, public route, pair decision or production activation in this packet.
- The caller supplies scoped receipt ID and its canonical receipt digest; server resolves all other authority fields.
- M8 locks precede sorted/distinct M7 master locks. `read_locked` never commits and must reject a receipt parent outside the caller's pinned locked key.
- The returned media is immutable bytes, bounded by `MAX_FRAME_BYTES`; never return a mutable pathname as the verified media result.

## Review Focus

- Receipt parent changes between standalone preflight and locked reread: reject before reading frame bytes.
- Approved parent advances while a standalone read is in progress: serialize through the master row lock, then either return the old verified snapshot before advance or reject the stale parent after advance.
- Frame file changes during read/probe: use one private snapshot and verify its size, digest and PNG probe.
- Candidate row has the correct frame ID but wrong artifact key, path, size or probe: reject.
- A consumer calls `read_locked` without the receipt's parent in its declared locked-key set: reject.

---

### Task 1: Verified frame media snapshot

**Files:**
- Modify: `server/services/spatial_source.py`
- Test: `tests/integration/server/routers/test_spatial_frame_registration.py`

**Interfaces:**
- Produces: `copy_frame_verified(source_path: Path, snapshot_path: Path, *, expected_digest: str, expected_size: int, expected_probe_digest: str) -> bytes`.
- Uses: existing bounded copy and `_probe_png` logic; accepts only a regular PNG within `MAX_FRAME_BYTES` and `MAX_FRAME_DIMENSION`.

- [ ] Add tests that mutate source bytes during the copy and probe boundary, and assert no verified bytes return for changed digest/probe.
- [ ] Run the focused tests to RED.
- [ ] Implement the snapshot helper so the returned bytes and probe are checked on the same private file.
- [ ] Run the focused tests to GREEN and commit only Task 1 files.

### Task 2: Scoped current receipt reader

**Files:**
- Create: `server/services/spatial_frame_reader.py`
- Modify: `server/services/spatial_source.py` only if sharing the existing parent verifier requires a public server helper.
- Test: `tests/integration/server/routers/test_spatial_frame_reader.py`

**Interfaces:**
- Produces: frozen `VerifiedSpatialFrame(receipt: FrameDerivationReceiptV1, receipt_digest: str, png_bytes: bytes)`.
- Produces: `SpatialFrameReader.read_locked(session: AsyncSession, *, user_id: str, project_name: str, receipt_id: str, expected_receipt_digest: str, expected_parent_artifact_key: str) -> VerifiedSpatialFrame`.
- Produces: `SpatialFrameReader.read_current(*, user_id: str, project_name: str, receipt_id: str, expected_receipt_digest: str) -> VerifiedSpatialFrame`.
- Consumes: `SpatialFrameReceiptRepository.get_exact`, canonical receipt digest, Gate C `verify_masters`, scoped candidate repository, current master repository, `serialized_artifacts`, and Task 1's snapshot helper.

- [ ] Add real Gate C plus frame-receipt tests for a valid read, wrong scope/digest/key, superseded parent, missing projection, candidate metadata mismatch and changed PNG bytes. Assert no media result on each refusal.
- [ ] Run the focused tests to RED.
- [ ] Implement `read_locked` without committing or taking independent locks; compare every receipt lineage field to the current head and candidate, require canonical frame path and exact candidate metadata, then return Task 1's bytes.
- [ ] Implement `read_current` with a preflight receipt lookup for the parent key, `serialized_artifacts` for that key, and a locked reread that requires the same key.
- [ ] Run the focused tests to GREEN and commit only Task 2 files.

### Task 3: PostgreSQL lock proof and checkpoint

**Files:**
- Modify: `tests/integration/server/routers/test_spatial_frame_reader.py`
- Modify: `docs/r2/evidence/R2_M8C_FRAME_CUSTODY_HANDOFF.md`

**Interfaces:**
- Consumes: Task 2's two reader methods.

- [ ] Add a forced PostgreSQL interleaving where a reader holds the parent lock while Gate C tries to advance it. Assert the approval waits and the reader returns bytes from the pinned head; after approval commits, the old receipt is refused.
- [ ] Add a caller transaction test that acquires sorted parent locks and invokes `read_locked` without ending that transaction.
- [ ] Run the PostgreSQL tests to RED before final fixes, then GREEN on a disposable database. Verify migration head and leave the container stopped/removed.
- [ ] Run affected SQLite tests, Ruff, basedpyright, lint-imports, deptry and test audit. Commit test/evidence files and record exact tested HEAD, dirty paths and skipped coverage.
- [ ] Obtain independent full-diff review on the exact integrated HEAD before calling the reader an accepted authority. Pair admission remains a separate plan.
