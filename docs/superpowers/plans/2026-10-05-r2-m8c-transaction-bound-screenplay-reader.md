# M8-C Transaction-Bound Screenplay Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The repository's stricter one-background-agent budget and main-agent authority rules still apply.

**Goal:** Let a future Take target-registration transaction verify the exact current screenplay admission through its own `AsyncSession` without duplicating the existing reader's checks or opening a second transaction.

**Architecture:** Extract the admission-row, locked-head, decision-fold and screenplay-hash checks from `ApprovedScreenplayReader` into one repository-level function. Keep the public reader as a UoW-owning wrapper; add a reader implementing `ApprovedScreenplayReaderPort` over a caller-owned repository. Neither the shared function nor the bound reader commits or closes the caller's session.

**Tech Stack:** Python 3.13, FastAPI service library, SQLAlchemy 2 async, Pydantic v2, pytest, PostgreSQL 16.

**Spec:** `docs/superpowers/specs/2026-09-30-r2-m8c-binding-authority-design.md` (proposed §Authority model and §Write and replay protocol); source seam in `docs/research/2026-10-05-r2-m8c-target-registration-transaction-seam.md`.

## Global Constraints

- Preserve the existing `ApprovedScreenplayReader.get_exact_admitted` signature, result and error behavior for every caller.
- The bound reader receives an already active repository backed by the registration session; it never creates a UoW, commits, rolls back or closes.
- Preserve exact `(user_id, project_name, screenplay_ref, admission_ref)` scoping, locked admission-head fold and screenplay content-hash check.
- Keep all repository calls sequential within one `AsyncSession` and one task. No provider call, schema change, route or production activation belongs to this packet.
- A later target registry must acquire the admission-head lock before scene/shot target-head locks, in the same transaction.

## Review Focus

- A foreign project/user admission ref must fail identically through public and bound readers; Task 1 pins this.
- A stale admission ref after a newer admission must fail through both readers; Task 1 pins this.
- A corrupt decision fold or screenplay content hash must fail through both readers; Task 1 pins this.
- A concurrent re-admission must wait while the bound reader's caller holds its transaction open; Task 2 pins this on PostgreSQL.
- The bound reader must not commit or close the caller's session, including on error; Task 2 pins this.

---

### Task 1: Share the Exact-Admission Check

**Files:**
- Modify: `r2/adaptation/screenplay_reader.py`
- Test: `tests/integration/r2/adaptation/test_screenplay_admission.py`

**Interfaces:**
- Produce `resolve_exact_admitted(repository: AdaptationRepositoryPort, *, user_id: str, project_name: str, screenplay_ref: ArtifactVersionRef, admission_ref: DecisionRef) -> ScreenplayArtifactV2` as an async function in `r2/adaptation/screenplay_reader.py`.
- Preserve `ApprovedScreenplayReader.get_exact_admitted(...) -> ScreenplayArtifactV2`; its UoW calls the shared function with `uow.repository`.

- [ ] Write a test using the existing persisted two-admission fixture: compare the public reader with the shared function called on `AdaptationRepository(session)` for the current ref; assert both reject wrong scope and stale ref with the same exception class. Add one corrupt-fold or content-hash case using the existing adversarial test setup.
- [ ] Run that selected test before extraction and confirm it fails because `resolve_exact_admitted` is absent.
- [ ] Extract the current checks without changing their order, exceptions or UoW lifetime; make the public reader delegate.
- [ ] Run the selected test and the entire `tests/integration/r2/adaptation/test_screenplay_admission.py` file with a real database. Require nonzero selection and all relevant tests passing.
- [ ] Commit only this task's source and tests.

### Task 2: Bind the Reader to the Caller Transaction

**Files:**
- Modify: `r2/adaptation/screenplay_reader.py`
- Test: `tests/integration/r2/adaptation/test_screenplay_admission.py`
- Test: `tests/integration/r2/adaptation/test_screenplay_reader_locking.py` (new PostgreSQL interleaving file)

**Interfaces:**
- Produce `TransactionBoundApprovedScreenplayReader(repository: AdaptationRepositoryPort)` with the same `get_exact_admitted(...) -> ScreenplayArtifactV2` signature as `ApprovedScreenplayReaderPort`. Its method delegates to `resolve_exact_admitted` and has no UoW methods.
- A future registration writer constructs it from `AdaptationRepository(its_active_session)` and passes it to `TakeDirectorAdapter`.

- [ ] Write a test that constructs the bound reader over the caller's session, derives the same scene/shot bundle through `TakeDirectorAdapter`, and proves the session remains in its transaction after both success and a stale-ref error.
- [ ] Write a PostgreSQL forced interleaving: after the bound reader resolves the current ref, hold its caller transaction; start a second real admission for the same screenplay and identify that writer's backend PID or test-owned barrier; assert it waits on this test's admission-head row, release the first transaction, then assert admission completes and the old ref is refused. A sleep or unscoped `pg_stat_activity` query alone is insufficient.
- [ ] Run both tests RED before adding the bound class. Implement the class with no commit, rollback, close or new session creation.
- [ ] Run the whole affected adaptation test file on SQLite and PostgreSQL; run the PostgreSQL interleaving with `-n 4 --dist loadfile`. Run repository Ruff, changed-file format, basedpyright, import contracts, deptry and test audit; record exact HEAD and outputs.
- [ ] Commit only this task's source and tests. Do not claim target-registry acceptance: its schema, CAS writer, canonical version digest and independent exact-HEAD review are separate gates.

## Plan Self-Review

This packet covers only the reusable admission reader seam. It intentionally does not create target registry schema, version/head writer, command receipts, binding authority, pair admission or promotion. Those require the proposed ADR-0102 design gate and a separate plan with real target-version digest vectors and cross-writer lock tests. The two tasks share one method signature, keep current callers intact and have distinct test gates. The five review-focus risks map to tests above.
