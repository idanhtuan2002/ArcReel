"""Integration coverage for the M5C-3 compilation attempt/result/compiled-delta
repository methods (Task 22): admission, the SUCCEEDED <-> compiled-delta one-to-one
invariant, and lossless round-trip of the embedded M5A ``CanonDelta`` payload.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_lifecycle_uow import SqlAlchemyNarrativeLifecycleUnitOfWork, narrative_lifecycle_uow_factory
from r2.narrative_lifecycle.acceptance import NarrativeAcceptanceService
from r2.narrative_lifecycle.errors import NarrativeEvidenceIdentityConflictError, NarrativeEvidenceIntegrityError
from tests.factories import (
    make_change_set_review_command,
    make_compilation_attempt,
    make_compilation_result,
    make_compiled_canon_delta_evidence,
    make_draft_candidate,
    make_extraction_attempt,
    make_extraction_result,
    make_narrative_change_set,
    make_narrative_revision,
    make_revision_acceptance_command,
)
from tests.integration.r2.narrative_lifecycle._fakes import SHOWRUNNER

type Factory = async_sessionmaker[AsyncSession]


@pytest.fixture
async def seeded_change_set(session_factory: Factory, acceptance_service: NarrativeAcceptanceService) -> None:
    """Seeds exactly the object graph ``make_compilation_attempt``'s defaults name: an
    accepted revision (``d-1`` selects ``rev-1``) and an accepted change-set review
    (``d-2`` selects ``cs-1`` under ``d-1``)."""
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(make_draft_candidate())
        await uow.repository.insert_revision(make_narrative_revision())
        await uow.repository.insert_extraction_attempt(make_extraction_attempt())
        await uow.repository.insert_successful_extraction(
            make_extraction_result(outcome="SUCCEEDED", change_set_ids=("cs-1",)),
            (make_narrative_change_set(change_set_id="cs-1"),),
        )
        await uow.commit()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", action="ACCEPT"), authenticated_principal=SHOWRUNNER
    )
    await acceptance_service.review_change_set(
        make_change_set_review_command(decision_id="d-2", action="ACCEPT"), authenticated_principal=SHOWRUNNER
    )


async def test_a_compilation_attempt_round_trips_exactly(session_factory: Factory, seeded_change_set: None) -> None:
    attempt = make_compilation_attempt()
    async with SqlAlchemyNarrativeLifecycleUnitOfWork(session_factory) as uow:
        await uow.repository.insert_compilation_attempt(attempt)
        await uow.commit()
    async with SqlAlchemyNarrativeLifecycleUnitOfWork(session_factory) as uow:
        loaded = await uow.repository.get_exact_compilation_attempt(
            attempt_id=attempt.attempt_id,
            project_name=attempt.work_scope.project_name,
            user_id=attempt.work_scope.user_id,
        )
    assert loaded == attempt


async def _reinsert(session_factory: Factory, attempt) -> None:
    async with SqlAlchemyNarrativeLifecycleUnitOfWork(session_factory) as uow:
        await uow.repository.insert_compilation_attempt(attempt)
        await uow.commit()


async def test_duplicate_attempt_id_is_an_identity_conflict(session_factory: Factory, seeded_change_set: None) -> None:
    attempt = make_compilation_attempt()
    async with SqlAlchemyNarrativeLifecycleUnitOfWork(session_factory) as uow:
        await uow.repository.insert_compilation_attempt(attempt)
        await uow.commit()
    with pytest.raises(NarrativeEvidenceIdentityConflictError):
        await _reinsert(session_factory, attempt)


async def test_successful_compilation_persists_the_lossless_canon_delta_payload(
    session_factory: Factory, seeded_change_set: None
) -> None:
    attempt = make_compilation_attempt()
    evidence = make_compiled_canon_delta_evidence()
    result = make_compilation_result(
        outcome="SUCCEEDED",
        canon_delta_id=evidence.canon_delta.canon_delta_id,
        canon_delta_payload_hash=evidence.canon_delta_payload_hash,
    )
    async with SqlAlchemyNarrativeLifecycleUnitOfWork(session_factory) as uow:
        await uow.repository.insert_compilation_attempt(attempt)
        await uow.repository.insert_successful_compilation(result, evidence)
        await uow.commit()
    async with SqlAlchemyNarrativeLifecycleUnitOfWork(session_factory) as uow:
        loaded_result = await uow.repository.get_exact_compilation_result(
            attempt_id=attempt.attempt_id,
            generation=attempt.generation,
            project_name=attempt.work_scope.project_name,
            user_id=attempt.work_scope.user_id,
        )
        loaded_evidence = await uow.repository.get_exact_compiled_canon_delta(
            compilation_result_id=result.result_id,
            project_name=attempt.work_scope.project_name,
            user_id=attempt.work_scope.user_id,
        )
    assert loaded_result == result
    assert loaded_evidence == evidence
    assert loaded_evidence.canon_delta.payload_hash == evidence.canon_delta.payload_hash


async def test_non_successful_compilation_persists_no_delta_row(
    session_factory: Factory, seeded_change_set: None
) -> None:
    attempt = make_compilation_attempt()
    result = make_compilation_result(outcome="NO_CANON_MUTATION")
    async with SqlAlchemyNarrativeLifecycleUnitOfWork(session_factory) as uow:
        await uow.repository.insert_compilation_attempt(attempt)
        await uow.repository.insert_non_successful_compilation(result)
        await uow.commit()
    async with SqlAlchemyNarrativeLifecycleUnitOfWork(session_factory) as uow:
        loaded_evidence = await uow.repository.get_exact_compiled_canon_delta(
            compilation_result_id=result.result_id,
            project_name=attempt.work_scope.project_name,
            user_id=attempt.work_scope.user_id,
        )
    assert loaded_evidence is None


async def test_insert_successful_compilation_rejects_a_non_succeeded_result(
    session_factory: Factory, seeded_change_set: None
) -> None:
    attempt = make_compilation_attempt()
    evidence = make_compiled_canon_delta_evidence()
    non_succeeded = make_compilation_result(outcome="ABSTAINED")
    async with SqlAlchemyNarrativeLifecycleUnitOfWork(session_factory) as uow:
        await uow.repository.insert_compilation_attempt(attempt)
        with pytest.raises(NarrativeEvidenceIntegrityError):
            await uow.repository.insert_successful_compilation(non_succeeded, evidence)


async def test_insert_non_successful_compilation_rejects_a_succeeded_result(
    session_factory: Factory, seeded_change_set: None
) -> None:
    attempt = make_compilation_attempt()
    evidence = make_compiled_canon_delta_evidence()
    succeeded = make_compilation_result(
        outcome="SUCCEEDED",
        canon_delta_id=evidence.canon_delta.canon_delta_id,
        canon_delta_payload_hash=evidence.canon_delta_payload_hash,
    )
    async with SqlAlchemyNarrativeLifecycleUnitOfWork(session_factory) as uow:
        await uow.repository.insert_compilation_attempt(attempt)
        with pytest.raises(NarrativeEvidenceIntegrityError):
            await uow.repository.insert_non_successful_compilation(succeeded)


async def test_insert_successful_compilation_rejects_evidence_naming_a_different_result(
    session_factory: Factory, seeded_change_set: None
) -> None:
    attempt = make_compilation_attempt()
    evidence = make_compiled_canon_delta_evidence(compilation_result_id="some-other-result")
    result = make_compilation_result(
        outcome="SUCCEEDED",
        canon_delta_id=evidence.canon_delta.canon_delta_id,
        canon_delta_payload_hash=evidence.canon_delta_payload_hash,
    )
    async with SqlAlchemyNarrativeLifecycleUnitOfWork(session_factory) as uow:
        await uow.repository.insert_compilation_attempt(attempt)
        with pytest.raises(NarrativeEvidenceIntegrityError):
            await uow.repository.insert_successful_compilation(result, evidence)
