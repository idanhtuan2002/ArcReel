"""Integration coverage for the scoped Narrative-lifecycle evidence adapter and UoW."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_lifecycle_uow import narrative_lifecycle_uow_factory
from lib.db.repositories.narrative_lifecycle import NarrativeLifecycleRepository, head_lock_sort_key
from r2.contracts.narrative_lifecycle import (
    ConflictResolutionLineage,
    ConflictSubject,
    ExtractionAttempt,
    ExtractionResult,
    NarrativeChangeSet,
    NarrativeWorkScope,
    SourceSpan,
)
from r2.narrative_lifecycle.errors import (
    NarrativeAttemptGenerationConflict,
    NarrativeDecisionIdentityConflictError,
    NarrativeDecisionPredecessorConflict,
    NarrativeEvidenceIdentityConflictError,
    NarrativeEvidenceIntegrityError,
)
from tests.factories import (
    make_change_set_review_command,
    make_conflict_resolution_command,
    make_draft_candidate,
    make_extraction_attempt,
    make_extraction_result,
    make_narrative_change_set,
    make_narrative_decision_authorization,
    make_narrative_revision,
    make_narrative_work_scope,
    make_revision_acceptance_command,
)

_STORED_AT = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)

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


# --- M5C-2 decision authority: identity registry, typed decisions, lineage, heads ---


async def _insert_genesis_revision_decision(
    repo: NarrativeLifecycleRepository, *, decision_id: str, work_scope: NarrativeWorkScope, action: str = "ACCEPT"
) -> None:
    await repo.lock_or_insert_revision_head(work_scope)
    command = make_revision_acceptance_command(decision_id=decision_id, work_scope=work_scope, action=action)
    authorization = make_narrative_decision_authorization(
        decision_id=decision_id, user_id=work_scope.user_id, project_name=work_scope.project_name, action=action
    )
    await repo.insert_identity_and_decision(
        command,
        authorization,
        canonical_identity_hash=f"dci:{decision_id}",
        decision_generation=1,
        stored_at=_STORED_AT,
    )
    await repo.advance_revision_head(
        work_scope,
        expected_latest_decision_id=None,
        expected_effective_decision_id=None,
        new_latest_decision_id=decision_id,
        new_decision_generation=1,
        new_effective_decision_id=decision_id if action == "ACCEPT" else None,
        new_effective_generation=1 if action == "ACCEPT" else 0,
    )


async def test_global_decision_id_cannot_collide_across_typed_tables(session_factory: Factory) -> None:
    scope = _scope()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await _insert_genesis_revision_decision(uow.repository, decision_id="d-1", work_scope=scope)
        await uow.commit()

    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        review_command = make_change_set_review_command(decision_id="d-1", work_scope=scope)
        review_authorization = make_narrative_decision_authorization(
            decision_id="d-1",
            user_id=scope.user_id,
            project_name=scope.project_name,
            decision_family="CHANGE_SET_REVIEW",
        )
        with pytest.raises(NarrativeDecisionIdentityConflictError):
            await uow.repository.insert_identity_and_decision(
                review_command,
                review_authorization,
                canonical_identity_hash="dci:other",
                decision_generation=1,
                stored_at=_STORED_AT,
            )


async def test_get_decision_by_id_round_trips_the_exact_command_and_authorization(session_factory: Factory) -> None:
    scope = _scope()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await _insert_genesis_revision_decision(uow.repository, decision_id="d-1", work_scope=scope)
        await uow.commit()

    async with session_factory() as session:
        repo = NarrativeLifecycleRepository(session)
        stored = await repo.get_decision_by_id("d-1", user_id=scope.user_id, project_name=scope.project_name)
        assert stored is not None
        command, authorization, generation = stored
        assert command == make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT")
        assert authorization.decision_id == "d-1"
        assert generation == 1
        assert (await repo.get_decision_by_id("d-1", user_id="other-user", project_name=scope.project_name)) is None
        assert (await repo.get_decision_by_id("ghost", user_id=scope.user_id, project_name=scope.project_name)) is None


async def test_lock_or_insert_revision_head_is_idempotent(session_factory: Factory) -> None:
    scope = _scope()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        first = await uow.repository.lock_or_insert_revision_head(scope)
        second = await uow.repository.lock_or_insert_revision_head(scope)
        await uow.commit()
    assert first == second
    assert first.latest_decision_id is None
    assert first.decision_generation == 0
    assert first.effective_decision_id is None
    assert first.effective_generation == 0


async def test_advance_revision_head_rejects_a_stale_expected_predecessor(session_factory: Factory) -> None:
    scope = _scope()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await _insert_genesis_revision_decision(uow.repository, decision_id="d-1", work_scope=scope)
        await uow.commit()

    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        with pytest.raises(NarrativeDecisionPredecessorConflict):
            await uow.repository.advance_revision_head(
                scope,
                expected_latest_decision_id=None,  # stale: the head already advanced to "d-1"
                expected_effective_decision_id=None,
                new_latest_decision_id="d-2",
                new_decision_generation=2,
                new_effective_decision_id="d-2",
                new_effective_generation=2,
            )


async def test_advance_revision_head_supersede_updates_both_pointers(session_factory: Factory) -> None:
    scope = _scope()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await _insert_genesis_revision_decision(uow.repository, decision_id="d-1", work_scope=scope)
        await uow.commit()

    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        repo = uow.repository
        command = make_revision_acceptance_command(
            decision_id="d-2",
            work_scope=scope,
            action="SUPERSEDE",
            expected_latest_decision_id="d-1",
            expected_effective_decision_id="d-1",
            selected_revision_id="rev-2",
        )
        authorization = make_narrative_decision_authorization(
            decision_id="d-2", user_id=scope.user_id, project_name=scope.project_name, action="SUPERSEDE"
        )
        await repo.insert_identity_and_decision(
            command, authorization, canonical_identity_hash="dci:d-2", decision_generation=2, stored_at=_STORED_AT
        )
        await repo.advance_revision_head(
            scope,
            expected_latest_decision_id="d-1",
            expected_effective_decision_id="d-1",
            new_latest_decision_id="d-2",
            new_decision_generation=2,
            new_effective_decision_id="d-2",
            new_effective_generation=2,
        )
        await uow.commit()

    async with session_factory() as session:
        head = await NarrativeLifecycleRepository(session).lock_or_insert_revision_head(scope)
    assert head.latest_decision_id == "d-2"
    assert head.decision_generation == 2
    assert head.effective_decision_id == "d-2"
    assert head.effective_generation == 2


async def test_reject_preserves_the_effective_pointer(session_factory: Factory) -> None:
    scope = _scope()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await _insert_genesis_revision_decision(uow.repository, decision_id="d-1", work_scope=scope)
        await uow.commit()

    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        repo = uow.repository
        command = make_revision_acceptance_command(
            decision_id="d-2",
            work_scope=scope,
            action="REJECT",
            expected_latest_decision_id="d-1",
            expected_effective_decision_id="d-1",
            selected_revision_id="rev-2",
        )
        authorization = make_narrative_decision_authorization(
            decision_id="d-2", user_id=scope.user_id, project_name=scope.project_name, action="REJECT"
        )
        await repo.insert_identity_and_decision(
            command, authorization, canonical_identity_hash="dci:d-2", decision_generation=2, stored_at=_STORED_AT
        )
        # REJECT advances latest/decision_generation only; the effective pointer is
        # untouched, so the expected effective predecessor passed here is the unchanged one.
        await repo.advance_revision_head(
            scope,
            expected_latest_decision_id="d-1",
            expected_effective_decision_id="d-1",
            new_latest_decision_id="d-2",
            new_decision_generation=2,
            new_effective_decision_id="d-1",
            new_effective_generation=1,
        )
        await uow.commit()

    async with session_factory() as session:
        head = await NarrativeLifecycleRepository(session).lock_or_insert_revision_head(scope)
    assert head.latest_decision_id == "d-2"
    assert head.decision_generation == 2
    assert head.effective_decision_id == "d-1"
    assert head.effective_generation == 1


async def test_change_set_review_and_conflict_resolution_heads_lock_and_advance(session_factory: Factory) -> None:
    scope = _scope()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        repo = uow.repository
        await _insert_genesis_revision_decision(repo, decision_id="d-1", work_scope=scope)

        # The conflict-resolution decision below names two competing change sets and
        # their review decisions by real FK, so both must exist first.
        await repo.insert_draft_candidate(_candidate())
        await repo.insert_revision(_revision())
        await repo.insert_extraction_attempt(_attempt())
        await repo.insert_successful_extraction(
            _result(outcome="SUCCEEDED", change_set_ids=("cs-1", "cs-2")),
            (_change_set(change_set_id="cs-1"), _change_set(change_set_id="cs-2")),
        )

        review_head = await repo.lock_or_insert_change_set_review_head(
            revision_acceptance_decision_id="d-1",
            change_set_lineage_id="lin-cs-1",
            user_id=scope.user_id,
            project_name=scope.project_name,
        )
        assert review_head.decision_generation == 0
        review_command = make_change_set_review_command(
            decision_id="d-2", work_scope=scope, action="ACCEPT", selected_change_set_id="cs-1"
        )
        review_authorization = make_narrative_decision_authorization(
            decision_id="d-2",
            user_id=scope.user_id,
            project_name=scope.project_name,
            decision_family="CHANGE_SET_REVIEW",
        )
        await repo.insert_identity_and_decision(
            review_command,
            review_authorization,
            canonical_identity_hash="dci:d-2",
            decision_generation=1,
            stored_at=_STORED_AT,
        )
        await repo.advance_change_set_review_head(
            revision_acceptance_decision_id="d-1",
            change_set_lineage_id="lin-cs-1",
            expected_latest_decision_id=None,
            expected_effective_decision_id=None,
            new_latest_decision_id="d-2",
            new_decision_generation=1,
            new_effective_decision_id="d-2",
            new_effective_generation=1,
        )

        # A second reviewed change set + decision, for the second conflict competitor.
        await repo.lock_or_insert_change_set_review_head(
            revision_acceptance_decision_id="d-1",
            change_set_lineage_id="lin-cs-2",
            user_id=scope.user_id,
            project_name=scope.project_name,
        )
        second_review_command = make_change_set_review_command(
            decision_id="d-2b",
            work_scope=scope,
            action="ACCEPT",
            change_set_lineage_id="lin-cs-2",
            selected_change_set_id="cs-2",
        )
        second_review_authorization = make_narrative_decision_authorization(
            decision_id="d-2b",
            user_id=scope.user_id,
            project_name=scope.project_name,
            decision_family="CHANGE_SET_REVIEW",
        )
        await repo.insert_identity_and_decision(
            second_review_command,
            second_review_authorization,
            canonical_identity_hash="dci:d-2b",
            decision_generation=1,
            stored_at=_STORED_AT,
        )
        await repo.advance_change_set_review_head(
            revision_acceptance_decision_id="d-1",
            change_set_lineage_id="lin-cs-2",
            expected_latest_decision_id=None,
            expected_effective_decision_id=None,
            new_latest_decision_id="d-2b",
            new_decision_generation=1,
            new_effective_decision_id="d-2b",
            new_effective_generation=1,
        )

        lineage = ConflictResolutionLineage(
            conflict_resolution_lineage_id="lin-conflict-1",
            revision_acceptance_decision_id="d-1",
            conflict_subject=ConflictSubject(coverage=(SourceSpan(start=0, end=4),), effect_key_subjects=("hero",)),
            conflict_subject_fingerprint="csf:lin-conflict-1",
            created_at=_STORED_AT,
            created_by="showrunner-1",
        )
        await repo.insert_conflict_lineage(lineage, user_id=scope.user_id, project_name=scope.project_name)

        conflict_head = await repo.lock_or_insert_conflict_resolution_head(
            revision_acceptance_decision_id="d-1",
            conflict_resolution_lineage_id="lin-conflict-1",
            user_id=scope.user_id,
            project_name=scope.project_name,
        )
        assert conflict_head.decision_generation == 0
        conflict_command = make_conflict_resolution_command(decision_id="d-3", work_scope=scope, action="RESOLVE")
        conflict_authorization = make_narrative_decision_authorization(
            decision_id="d-3",
            user_id=scope.user_id,
            project_name=scope.project_name,
            decision_family="CONFLICT_RESOLUTION",
            action="RESOLVE",
        )
        await repo.insert_identity_and_decision(
            conflict_command,
            conflict_authorization,
            canonical_identity_hash="dci:d-3",
            decision_generation=1,
            stored_at=_STORED_AT,
        )
        await repo.advance_conflict_resolution_head(
            revision_acceptance_decision_id="d-1",
            conflict_resolution_lineage_id="lin-conflict-1",
            expected_latest_decision_id=None,
            expected_effective_decision_id=None,
            new_latest_decision_id="d-3",
            new_decision_generation=1,
            new_effective_decision_id="d-3",
            new_effective_generation=1,
        )
        await uow.commit()

    async with session_factory() as session:
        repo = NarrativeLifecycleRepository(session)
        stored_review = await repo.get_decision_by_id("d-2", user_id=scope.user_id, project_name=scope.project_name)
        assert stored_review is not None
        assert stored_review[2] == 1
        stored_conflict = await repo.get_decision_by_id("d-3", user_id=scope.user_id, project_name=scope.project_name)
        assert stored_conflict is not None
        conflict_command_round_trip, _, _ = stored_conflict
        assert conflict_command_round_trip.competing_change_set_ids == ("cs-1", "cs-2")
        assert conflict_command_round_trip.competing_review_decision_ids == ("d-2", "d-2b")


async def test_insert_conflict_lineage_converges_on_one_winner(session_factory: Factory) -> None:
    scope = _scope()
    subject = ConflictSubject(coverage=(SourceSpan(start=0, end=10),), effect_key_subjects=("hero",))
    first = ConflictResolutionLineage(
        conflict_resolution_lineage_id="lin-a",
        revision_acceptance_decision_id="d-1",
        conflict_subject=subject,
        conflict_subject_fingerprint="csf:same-subject",
        created_at=_STORED_AT,
        created_by="showrunner-1",
    )
    second = first.model_copy(update={"conflict_resolution_lineage_id": "lin-b"})

    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await _insert_genesis_revision_decision(uow.repository, decision_id="d-1", work_scope=scope)
        winner_a = await uow.repository.insert_conflict_lineage(
            first, user_id=scope.user_id, project_name=scope.project_name
        )
        winner_b = await uow.repository.insert_conflict_lineage(
            second, user_id=scope.user_id, project_name=scope.project_name
        )
        await uow.commit()

    assert winner_a.conflict_resolution_lineage_id == "lin-a"
    assert (
        winner_b.conflict_resolution_lineage_id == "lin-a"
    )  # the second insert lost the race and reads back the first


async def test_head_pointer_fk_rejects_a_decision_from_another_subject(session_factory: Factory) -> None:
    async with session_factory() as probe:
        if probe.bind.dialect.name == "sqlite":
            pytest.skip("the SQLite test engine runs with foreign keys disabled")

    scope_a = _scope(user_id="u1")
    scope_b = _scope(user_id="conformance")
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await _insert_genesis_revision_decision(uow.repository, decision_id="d-a", work_scope=scope_a)
        await _insert_genesis_revision_decision(uow.repository, decision_id="d-b", work_scope=scope_b)
        await uow.commit()

    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        with pytest.raises(IntegrityError):
            # head A's own key, but the effective pointer names head B's decision --
            # the composite FK requires the pointed-to decision to share this exact subject.
            await uow.repository.advance_revision_head(
                scope_a,
                expected_latest_decision_id="d-a",
                expected_effective_decision_id="d-a",
                new_latest_decision_id="d-a",
                new_decision_generation=1,
                new_effective_decision_id="d-b",
                new_effective_generation=1,
            )


def test_head_lock_sort_key_orders_by_family_then_scope_then_logical_key() -> None:
    revision_key = head_lock_sort_key("REVISION_ACCEPTANCE", user_id="u1", project_name="p", logical_key=("a",))
    review_key = head_lock_sort_key("CHANGE_SET_REVIEW", user_id="u1", project_name="p", logical_key=("a",))
    conflict_key = head_lock_sort_key("CONFLICT_RESOLUTION", user_id="u1", project_name="p", logical_key=("a",))
    assert revision_key < review_key < conflict_key
