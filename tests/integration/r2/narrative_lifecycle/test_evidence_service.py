"""Integration coverage for ``NarrativeLifecycleEvidenceService``.

The extraction-admission path is exercised only for its fail-closed behaviour. Attempt
rows are seeded directly through the repository by a test-only fixture.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_lifecycle_uow import SqlAlchemyNarrativeLifecycleUnitOfWork, narrative_lifecycle_uow_factory
from r2.contracts.narrative_lifecycle import ExtractionAttempt, ExtractionResult, NarrativeChangeSet, NarrativeWorkScope
from r2.narrative_lifecycle.errors import (
    NarrativeAttemptGenerationConflict,
    NarrativeAuthorityUnavailableError,
    NarrativeEvidenceIdentityConflictError,
    NarrativeEvidenceIntegrityError,
)
from r2.narrative_lifecycle.evidence import ExtractionAdmissionCommand, NarrativeLifecycleEvidenceService
from tests.factories import (
    make_draft_candidate,
    make_extraction_attempt,
    make_extraction_result,
    make_narrative_change_set,
    make_narrative_revision,
    make_narrative_work_scope,
)

USER = "u1"
PROJECT = "project-a"

type Factory = async_sessionmaker[AsyncSession]


def _scope(*, user_id: str = USER, project_name: str = PROJECT) -> NarrativeWorkScope:
    return make_narrative_work_scope(user_id=user_id, project_name=project_name)


def _candidate(*, candidate_id: str = "cand-1", scope: NarrativeWorkScope | None = None):
    return make_draft_candidate(candidate_id=candidate_id, work_scope=scope or _scope())


def _revision(
    *,
    revision_id: str = "rev-1",
    candidate_id: str = "cand-1",
    predecessor: str | None = None,
    scope: NarrativeWorkScope | None = None,
):
    return make_narrative_revision(
        revision_id=revision_id,
        base_candidate_id=candidate_id,
        predecessor_revision_id=predecessor,
        work_scope=scope or _scope(),
    )


def _attempt(*, attempt_id: str = "att-1", generation: int = 0) -> ExtractionAttempt:
    return make_extraction_attempt(attempt_id=attempt_id, generation=generation)


def _result(
    *, result_id: str = "res-1", generation: int = 0, outcome: str = "ABSTAINED", change_set_ids: tuple[str, ...] = ()
) -> ExtractionResult:
    return make_extraction_result(
        result_id=result_id, generation=generation, outcome=outcome, change_set_ids=change_set_ids
    )


def _change_set(*, change_set_id: str) -> NarrativeChangeSet:
    return make_narrative_change_set(change_set_id=change_set_id)


@pytest.fixture
def evidence_service(session_factory: Factory) -> NarrativeLifecycleEvidenceService:
    return NarrativeLifecycleEvidenceService(narrative_lifecycle_uow_factory(session_factory))


class InjectedFault(RuntimeError):
    pass


class _FaultOnCommitUnitOfWork(SqlAlchemyNarrativeLifecycleUnitOfWork):
    """Flushes normally, then fails the commit — the transaction never reaches the DB."""

    async def commit(self) -> None:
        raise InjectedFault("injected fault before commit")


@pytest.fixture
def fault_on_commit_service(session_factory: Factory) -> NarrativeLifecycleEvidenceService:
    return NarrativeLifecycleEvidenceService(lambda: _FaultOnCommitUnitOfWork(session_factory))


@pytest.fixture
def seed_attempt(session_factory: Factory) -> Callable[..., Awaitable[ExtractionAttempt]]:
    async def _seed(*, generation: int = 0) -> ExtractionAttempt:
        attempt = _attempt(generation=generation)
        async with narrative_lifecycle_uow_factory(session_factory)() as uow:
            await uow.repository.insert_draft_candidate(_candidate())
            await uow.repository.insert_revision(_revision())
            await uow.repository.insert_extraction_attempt(attempt)
            await uow.commit()
        return attempt

    return _seed


def _command(*, generation: int = 0) -> ExtractionAdmissionCommand:
    return ExtractionAdmissionCommand(
        work_scope=_scope(),
        revision_id="rev-1",
        generation=generation,
        revision_acceptance_decision_id="dec-1",
        extractor_kind="LOCAL",
        extractor_version="x-1",
        policy_ref="pol",
        policy_version="1",
        authenticated_principal="human:anhtuan",
    )


async def test_admit_extraction_fails_closed_before_the_authority_layer_exists(
    evidence_service: NarrativeLifecycleEvidenceService,
) -> None:
    with pytest.raises(NarrativeAuthorityUnavailableError):
        await evidence_service.admit_extraction(_command(generation=0))


async def test_outcome_unknown_is_terminal_and_late_success_is_rejected(
    evidence_service: NarrativeLifecycleEvidenceService,
    seed_attempt: Callable[..., Awaitable[ExtractionAttempt]],
) -> None:
    await seed_attempt(generation=0)
    await evidence_service.record_non_successful_extraction(_result(outcome="OUTCOME_UNKNOWN"))
    with pytest.raises(NarrativeAttemptGenerationConflict):
        await evidence_service.record_successful_extraction(
            _result(result_id="res-2", outcome="SUCCEEDED", change_set_ids=("cs-1",)),
            [_change_set(change_set_id="cs-1")],
        )
    assert (
        await evidence_service.get_exact_change_set(change_set_id="cs-1", project_name=PROJECT, user_id=USER)
    ) is None


async def test_successful_bundle_exact_retry_writes_nothing_new(
    evidence_service: NarrativeLifecycleEvidenceService,
    seed_attempt: Callable[..., Awaitable[ExtractionAttempt]],
) -> None:
    await seed_attempt(generation=0)
    result = _result(outcome="SUCCEEDED", change_set_ids=("cs-2", "cs-1"))
    change_sets = [_change_set(change_set_id="cs-2"), _change_set(change_set_id="cs-1")]
    await evidence_service.record_successful_extraction(result, change_sets)
    again = await evidence_service.record_successful_extraction(result, change_sets)
    assert tuple(again.change_set_ids) == ("cs-2", "cs-1")


async def test_mismatched_success_retry_fails_with_no_write(
    evidence_service: NarrativeLifecycleEvidenceService,
    seed_attempt: Callable[..., Awaitable[ExtractionAttempt]],
) -> None:
    await seed_attempt(generation=0)
    await evidence_service.record_successful_extraction(
        _result(outcome="SUCCEEDED", change_set_ids=("cs-1",)), [_change_set(change_set_id="cs-1")]
    )
    with pytest.raises(NarrativeAttemptGenerationConflict):
        await evidence_service.record_successful_extraction(
            _result(result_id="res-9", outcome="SUCCEEDED", change_set_ids=("cs-2",)),
            [_change_set(change_set_id="cs-2")],
        )
    assert await evidence_service.get_exact_change_set(change_set_id="cs-2", project_name=PROJECT, user_id=USER) is None


async def test_record_revision_rejects_a_missing_base_candidate(
    evidence_service: NarrativeLifecycleEvidenceService,
) -> None:
    with pytest.raises(NarrativeEvidenceIntegrityError):
        await evidence_service.record_revision(_revision(candidate_id="ghost"))


async def test_record_revision_rejects_a_predecessor_from_another_scope(
    evidence_service: NarrativeLifecycleEvidenceService, session_factory: Factory
) -> None:
    other = _scope(user_id="conformance")
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_candidate(candidate_id="c-other", scope=other))
        await uow.repository.insert_revision(_revision(revision_id="rev-other", candidate_id="c-other", scope=other))
        await uow.commit()
    await evidence_service.record_draft_candidate(_candidate())
    with pytest.raises(NarrativeEvidenceIntegrityError):
        await evidence_service.record_revision(_revision(predecessor="rev-other"))


async def test_exact_retry_of_draft_and_non_success_result_returns_the_original(
    evidence_service: NarrativeLifecycleEvidenceService,
    seed_attempt: Callable[..., Awaitable[ExtractionAttempt]],
) -> None:
    await seed_attempt(generation=0)
    candidate = _candidate(candidate_id="cand-1")
    assert await evidence_service.record_draft_candidate(candidate) == candidate  # already seeded -> exact retry
    with pytest.raises(NarrativeEvidenceIdentityConflictError):
        await evidence_service.record_draft_candidate(
            _candidate(candidate_id="cand-1", scope=_scope()).model_copy(update={"content_hash": "pch:different"})
        )
    failed = _result(outcome="FAILED")
    await evidence_service.record_non_successful_extraction(failed)
    assert await evidence_service.record_non_successful_extraction(failed) == failed


async def test_record_non_successful_extraction_rejects_succeeded_or_declared_change_sets(
    evidence_service: NarrativeLifecycleEvidenceService,
    seed_attempt: Callable[..., Awaitable[ExtractionAttempt]],
) -> None:
    await seed_attempt(generation=0)
    with pytest.raises(NarrativeEvidenceIntegrityError):
        await evidence_service.record_non_successful_extraction(_result(outcome="SUCCEEDED", change_set_ids=("cs-1",)))


async def test_successful_bundle_is_atomic_when_the_commit_faults(
    evidence_service: NarrativeLifecycleEvidenceService,
    fault_on_commit_service: NarrativeLifecycleEvidenceService,
    seed_attempt: Callable[..., Awaitable[ExtractionAttempt]],
) -> None:
    await seed_attempt(generation=0)
    with pytest.raises(InjectedFault):
        await fault_on_commit_service.record_successful_extraction(
            _result(outcome="SUCCEEDED", change_set_ids=("cs-1",)), [_change_set(change_set_id="cs-1")]
        )
    # Neither the result nor its proposal evidence is observable after the fault.
    assert (
        await evidence_service.get_exact_extraction_result(
            attempt_id="att-1", generation=0, project_name=PROJECT, user_id=USER
        )
    ) is None
    assert await evidence_service.get_exact_change_set(change_set_id="cs-1", project_name=PROJECT, user_id=USER) is None
    # The independently-committed attempt row seeded before the fault is still durable.
    assert await evidence_service.get_exact_extraction_attempt(attempt_id="att-1", project_name=PROJECT, user_id=USER)
