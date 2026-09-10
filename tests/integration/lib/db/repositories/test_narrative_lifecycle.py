"""Integration coverage for the scoped Narrative-lifecycle evidence adapter and UoW."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_lifecycle_uow import narrative_lifecycle_uow_factory
from lib.db.repositories.narrative_lifecycle import NarrativeLifecycleRepository
from r2.contracts.narrative_lifecycle import ExtractionAttempt, ExtractionResult, NarrativeChangeSet, NarrativeWorkScope
from r2.narrative_lifecycle.errors import (
    NarrativeAttemptGenerationConflict,
    NarrativeEvidenceIdentityConflictError,
    NarrativeEvidenceIntegrityError,
)
from tests.factories import (
    make_draft_candidate,
    make_extraction_attempt,
    make_extraction_result,
    make_narrative_change_set,
    make_narrative_revision,
    make_narrative_work_scope,
)

USER = "u1"
OTHER_USER = "conformance"
PROJECT = "project-a"

type Factory = async_sessionmaker[AsyncSession]


def _scope(*, user_id: str = USER) -> NarrativeWorkScope:
    return make_narrative_work_scope(user_id=user_id, project_name=PROJECT)


def _candidate(*, candidate_id: str = "cand-1", user_id: str = USER):
    return make_draft_candidate(candidate_id=candidate_id, work_scope=_scope(user_id=user_id))


def _revision(*, revision_id: str = "rev-1", candidate_id: str = "cand-1", user_id: str = USER):
    return make_narrative_revision(
        revision_id=revision_id, base_candidate_id=candidate_id, work_scope=_scope(user_id=user_id)
    )


def _attempt(*, attempt_id: str = "att-1", generation: int = 0, revision_id: str = "rev-1") -> ExtractionAttempt:
    return make_extraction_attempt(attempt_id=attempt_id, generation=generation, revision_id=revision_id)


def _result(
    *,
    result_id: str = "res-1",
    attempt_id: str = "att-1",
    generation: int = 0,
    outcome: str = "ABSTAINED",
    change_set_ids: tuple[str, ...] = (),
) -> ExtractionResult:
    return make_extraction_result(
        result_id=result_id,
        attempt_id=attempt_id,
        generation=generation,
        outcome=outcome,
        change_set_ids=change_set_ids,
    )


def _change_set(*, change_set_id: str, attempt_id: str = "att-1", generation: int = 0) -> NarrativeChangeSet:
    return make_narrative_change_set(
        change_set_id=change_set_id, extraction_attempt_id=attempt_id, extraction_generation=generation
    )


async def _seed_attempt(session_factory: Factory, *, generation: int = 0) -> None:
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_candidate())
        await uow.repository.insert_revision(_revision())
        await uow.repository.insert_extraction_attempt(_attempt(generation=generation))
        await uow.commit()


async def test_scoped_reads_collapse_unknown_and_cross_scope(session_factory: Factory) -> None:
    await _seed_attempt(session_factory)
    async with session_factory() as session:
        repo = NarrativeLifecycleRepository(session)
        assert await repo.get_exact_draft_candidate(candidate_id="cand-1", project_name=PROJECT, user_id=USER)
        assert await repo.get_exact_draft_candidate(candidate_id="ghost", project_name=PROJECT, user_id=USER) is None
        assert (
            await repo.get_exact_draft_candidate(candidate_id="cand-1", project_name=PROJECT, user_id=OTHER_USER)
        ) is None
        assert await repo.get_exact_revision(revision_id="rev-1", project_name="other", user_id=USER) is None
        assert await repo.get_exact_extraction_attempt(attempt_id="att-1", project_name=PROJECT, user_id=USER)


async def test_result_is_uniquely_bound_to_one_attempt_generation(session_factory: Factory) -> None:
    await _seed_attempt(session_factory, generation=0)
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_non_successful_extraction(
            _result(result_id="res-1", generation=0, outcome="FAILED")
        )
        await uow.commit()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        with pytest.raises(NarrativeAttemptGenerationConflict):
            await uow.repository.insert_non_successful_extraction(
                _result(result_id="res-2", generation=0, outcome="ABSTAINED")
            )


async def test_successful_bundle_stores_ordered_membership(session_factory: Factory) -> None:
    await _seed_attempt(session_factory)
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_successful_extraction(
            _result(outcome="SUCCEEDED", change_set_ids=("cs-2", "cs-1")),
            (_change_set(change_set_id="cs-2"), _change_set(change_set_id="cs-1")),
        )
        await uow.commit()
    async with session_factory() as session:
        repo = NarrativeLifecycleRepository(session)
        loaded = await repo.get_exact_extraction_result(
            attempt_id="att-1", generation=0, project_name=PROJECT, user_id=USER
        )
        assert loaded is not None
        assert tuple(loaded.change_set_ids) == ("cs-2", "cs-1")  # association order, not sorted
        assert await repo.get_exact_change_set(change_set_id="cs-1", project_name=PROJECT, user_id=USER) is not None


async def test_successful_bundle_with_mismatched_ids_writes_nothing(session_factory: Factory) -> None:
    await _seed_attempt(session_factory)
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        with pytest.raises(NarrativeEvidenceIntegrityError):
            await uow.repository.insert_successful_extraction(
                _result(outcome="SUCCEEDED", change_set_ids=("cs-1", "cs-9")),
                (_change_set(change_set_id="cs-1"),),
            )
        await uow.commit()
    async with session_factory() as session:
        repo = NarrativeLifecycleRepository(session)
        assert (
            await repo.get_exact_extraction_result(attempt_id="att-1", generation=0, project_name=PROJECT, user_id=USER)
        ) is None
        assert await repo.get_exact_change_set(change_set_id="cs-1", project_name=PROJECT, user_id=USER) is None


async def test_non_success_result_rejects_declared_change_sets(session_factory: Factory) -> None:
    await _seed_attempt(session_factory)
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        with pytest.raises(NarrativeEvidenceIntegrityError):
            await uow.repository.insert_non_successful_extraction(
                _result(outcome="SUCCEEDED", change_set_ids=("cs-1",))
            )


async def test_duplicate_candidate_id_fails_closed(session_factory: Factory) -> None:
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_candidate(candidate_id="cand-1"))
        await uow.commit()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        with pytest.raises(NarrativeEvidenceIdentityConflictError):
            await uow.repository.insert_draft_candidate(_candidate(candidate_id="cand-1"))


async def test_uow_rollback_leaves_no_partial_evidence(session_factory: Factory) -> None:
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_candidate())
        # exit without commit -> rollback
    async with session_factory() as session:
        repo = NarrativeLifecycleRepository(session)
        assert await repo.get_exact_draft_candidate(candidate_id="cand-1", project_name=PROJECT, user_id=USER) is None


async def test_composite_basis_fk_rejects_an_incompatible_revision_link(session_factory: Factory) -> None:
    async with session_factory() as probe:
        if probe.bind.dialect.name == "sqlite":
            pytest.skip("the SQLite test engine runs with foreign keys disabled")

    await _seed_attempt(session_factory)  # revision rev-1 has base_canon_version_id 'cv-1'
    mismatched = _attempt(attempt_id="att-2").model_copy(update={"base_canon_version_id": "cv-DIFFERENT"})
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        with pytest.raises((IntegrityError, NarrativeEvidenceIdentityConflictError, NarrativeEvidenceIntegrityError)):
            await uow.repository.insert_extraction_attempt(mismatched)
