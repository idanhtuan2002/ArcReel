# M8-C Transaction-Bound Screenplay Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The repository's stricter one-background-agent budget and main-agent authority rules still apply.

**Goal:** Let a future Take target-registration transaction verify the full current `AdmittedScreenplayRef`, including profile provenance, through its own `AsyncSession` without duplicating the existing reader's checks or opening a second transaction.

**Architecture:** Extract the admission-row, locked-head, decision-fold and screenplay-hash checks from `ApprovedScreenplayReader` into one repository-level function. Keep the public reader as a UoW-owning wrapper; add a reader implementing `ApprovedScreenplayReaderPort` over a caller-owned repository. Neither the shared function nor the bound reader commits or closes the caller's session.

**Tech Stack:** Python 3.13, FastAPI service library, SQLAlchemy 2 async, Pydantic v2, pytest, PostgreSQL 16.

**Spec:** `docs/superpowers/specs/2026-09-30-r2-m8c-binding-authority-design.md` (proposed §Authority model and §Write and replay protocol); source seam in `docs/research/2026-10-05-r2-m8c-target-registration-transaction-seam.md`.

## Global Constraints

- Preserve the existing `ApprovedScreenplayReader.get_exact_admitted` signature, result and error behavior for every caller.
- The bound reader receives an already active repository backed by the registration session; it never creates a UoW, commits, rolls back or closes.
- Preserve exact `(user_id, project_name, screenplay_ref, admission_ref)` scoping, locked admission-head fold and screenplay content-hash check. The new bound path additionally compares `profile_ref` with the stored admission projection; the existing public signature does not accept a profile ref.
- Keep all repository calls sequential within one `AsyncSession` and one task. No provider call, schema change, route or production activation belongs to this packet.
- A later target registry must acquire the admission-head lock before scene/shot target-head locks, in the same transaction.

## Review Focus

- A foreign project/user or stale admission ref must fail identically through public and bound readers; Task 1 pins both cases.
- A caller-supplied profile ref that differs from the stored admission projection must fail through the bound reader; Task 2 pins this.
- A corrupt decision fold or screenplay content hash must fail through both readers; Task 1 pins this.
- A concurrent re-admission must wait while the bound reader's caller holds its transaction open; Task 2 pins this on PostgreSQL.
- The bound reader must not commit or close the caller's session, including on error; Task 2 pins this.

---

### Task 1: Share the Exact-Admission Check

**Files:**
- Modify: `r2/adaptation/screenplay_reader.py`
- Test: `tests/integration/r2/adaptation/test_screenplay_admission.py`

**Interfaces:**
- Produce `resolve_exact_admitted(repository: AdaptationRepositoryPort, *, user_id: str, project_name: str, screenplay_ref: ArtifactVersionRef, admission_ref: DecisionRef, expected_profile_ref: AdaptationProfileRef | None = None) -> ScreenplayArtifactV2` as an async function in `r2/adaptation/screenplay_reader.py`. If supplied, the profile must equal the stored admission projection before any screenplay is returned.
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
- Produce `TransactionBoundApprovedScreenplayReader(repository: AdaptationRepositoryPort, *, expected_admission: AdmittedScreenplayRef)` with the same `get_exact_admitted(...) -> ScreenplayArtifactV2` signature as `ApprovedScreenplayReaderPort`. Its method requires its screenplay and decision arguments to equal `expected_admission` and delegates to `resolve_exact_admitted` with `expected_profile_ref=expected_admission.profile_ref`; it has no UoW methods.
- A future registration writer constructs it from `AdaptationRepository(its_active_session)` and the command's full `AdmittedScreenplayRef`, then passes it to `TakeDirectorAdapter`.

- [ ] Write a test that constructs the bound reader over the caller's session, derives the same scene/shot bundle through `TakeDirectorAdapter`, and proves the session remains in its transaction after both success and a stale-ref error. Change only the requested `profile_ref` while keeping screenplay and decision refs exact; the bound reader must reject it using the stored admission projection.
- [ ] Write a PostgreSQL forced interleaving: after the bound reader resolves the current ref, hold its caller transaction; start a second real admission for the same screenplay and identify that writer's backend PID or test-owned barrier; assert it waits on this test's admission-head row, release the first transaction, then assert admission completes and the old ref is refused. A sleep or unscoped `pg_stat_activity` query alone is insufficient.
- [ ] Run both tests RED before adding the bound class. Implement the class with no commit, rollback, close or new session creation.
- [ ] Run the whole affected adaptation test file on SQLite and PostgreSQL; run the PostgreSQL interleaving with `-n 4 --dist loadfile`. Run repository Ruff, changed-file format, basedpyright, import contracts, deptry and test audit; record exact HEAD and outputs.
- [ ] Commit only this task's source and tests. Do not claim target-registry acceptance: its schema, CAS writer, canonical version digest and independent exact-HEAD review are separate gates.

## Plan Self-Review

This packet covers only the reusable admission reader seam. It intentionally does not create target registry schema, version/head writer, command receipts, binding authority, pair admission or promotion. Those require the proposed ADR-0102 design gate and a separate plan with real target-version digest vectors and cross-writer lock tests. The two tasks share one method signature, keep current callers intact and have distinct test gates. The five review-focus risks map to tests above.
