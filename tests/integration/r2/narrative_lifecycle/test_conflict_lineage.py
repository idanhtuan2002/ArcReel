"""Integration coverage for ``NarrativeAcceptanceService.resolve_change_set_conflict``
and conflict-lineage genesis (Task 19, spec §6.7/§7.2 conflict-genesis order).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_lifecycle_uow import narrative_lifecycle_uow_factory
from r2.contracts.narrative_lifecycle import (
    ConflictResolutionCommand,
    NarrativeWorkScope,
    SourceSpan,
)
from r2.narrative_lifecycle.acceptance import NarrativeAcceptanceService
from r2.narrative_lifecycle.errors import (
    NarrativeConflictCoverageError,
    NarrativeConflictLineageConflict,
    NarrativeDecisionApplicabilityError,
    NarrativeDecisionPredecessorConflict,
)
from tests.factories import (
    make_canon_mutation_effect_key,
    make_change_set_review_command,
    make_narrative_change_set,
    make_narrative_work_scope,
    make_revision_acceptance_command,
)
from tests.integration.r2.narrative_lifecycle.test_acceptance_decisions import SHOWRUNNER, _FakeShowrunnerAuthorityPort
from tests.integration.r2.narrative_lifecycle.test_evidence_service import _attempt, _candidate, _result, _revision

type Factory = async_sessionmaker[AsyncSession]


def _scope() -> NarrativeWorkScope:
    return make_narrative_work_scope()


@pytest.fixture
def fake_showrunner() -> _FakeShowrunnerAuthorityPort:
    return _FakeShowrunnerAuthorityPort()


@pytest.fixture
def acceptance_service(
    session_factory: Factory, fake_showrunner: _FakeShowrunnerAuthorityPort
) -> NarrativeAcceptanceService:
    return NarrativeAcceptanceService(narrative_lifecycle_uow_factory(session_factory), fake_showrunner)


async def _seed_two_competing_reviews(
    acceptance_service: NarrativeAcceptanceService,
    session_factory: Factory,
    *,
    cs_a_overrides: dict[str, object] | None = None,
    cs_b_overrides: dict[str, object] | None = None,
) -> None:
    """d-1 accepts a revision; cs-a / cs-b are extracted from it; d-2 / d-3 each accept
    one of them under their own (auto-derived) lineage."""
    scope = _scope()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_candidate())
        await uow.repository.insert_revision(_revision())
        await uow.repository.insert_extraction_attempt(_attempt())
        await uow.repository.insert_successful_extraction(
            _result(outcome="SUCCEEDED", change_set_ids=("cs-a", "cs-b")),
            [
                make_narrative_change_set(change_set_id="cs-a", **(cs_a_overrides or {})),
                make_narrative_change_set(change_set_id="cs-b", **(cs_b_overrides or {})),
            ],
        )
        await uow.commit()

    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.review_change_set(
        make_change_set_review_command(
            decision_id="d-2",
            work_scope=scope,
            action="ACCEPT",
            change_set_lineage_id="lin-cs-a",
            selected_change_set_id="cs-a",
        ),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.review_change_set(
        make_change_set_review_command(
            decision_id="d-3",
            work_scope=scope,
            action="ACCEPT",
            change_set_lineage_id="lin-cs-b",
            selected_change_set_id="cs-b",
        ),
        authenticated_principal=SHOWRUNNER,
    )


def _genesis_command(*, decision_id: str = "d-4", lineage_id: str = "lin-conflict-1") -> ConflictResolutionCommand:
    return ConflictResolutionCommand(
        decision_id=decision_id,
        action="RESOLVE",
        work_scope=_scope(),
        revision_acceptance_decision_id="d-1",
        conflict_resolution_lineage_id=lineage_id,
        competing_change_set_ids=("cs-a", "cs-b"),
        competing_review_decision_ids=("d-2", "d-3"),
        chosen_resolution="keep cs-a",
        expected_latest_decision_id=None,
        expected_effective_decision_id=None,
        base_canon_version_id="cv-1",
        plan_version=2,
        scene_contract_version=1,
        context_pack_id="ctx-1",
        actor_id=SHOWRUNNER,
    )


async def test_conflict_genesis_creates_the_lineage_head_and_first_decision(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_two_competing_reviews(acceptance_service, session_factory)
    receipt = await acceptance_service.resolve_change_set_conflict(
        _genesis_command(), authenticated_principal=SHOWRUNNER
    )

    assert receipt.decision_id == "d-4"
    assert receipt.decision_generation == 1
    assert receipt.effective_decision_id == "d-4"
    assert receipt.effective_generation == 1

    head = await acceptance_service.get_current_conflict_resolution(
        "d-1", "lin-conflict-1", user_id=_scope().user_id, project_name=_scope().project_name
    )
    assert head is not None
    assert head.latest_decision_id == "d-4"
    assert head.effective_decision_id == "d-4"


async def test_same_revision_and_canonical_subject_cannot_create_two_lineages(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_two_competing_reviews(acceptance_service, session_factory)
    await acceptance_service.resolve_change_set_conflict(
        _genesis_command(decision_id="d-4", lineage_id="L-1"), authenticated_principal=SHOWRUNNER
    )
    with pytest.raises(NarrativeConflictLineageConflict):
        await acceptance_service.resolve_change_set_conflict(
            _genesis_command(decision_id="d-5", lineage_id="L-2"), authenticated_principal=SHOWRUNNER
        )
    # the losing attempt wrote no decision under its own proposed id
    assert (
        await acceptance_service.verify_exact_current_selection(
            "d-5", user_id=_scope().user_id, project_name=_scope().project_name
        )
    ) is False


async def test_non_overlapping_competitors_are_rejected_before_any_write(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    far_span = SourceSpan(start=100, end=104)
    other_subject_key = make_canon_mutation_effect_key(subject_ref="villain")
    await _seed_two_competing_reviews(
        acceptance_service,
        session_factory,
        cs_b_overrides={"span": far_span, "key": other_subject_key},
    )
    with pytest.raises(NarrativeConflictCoverageError):
        await acceptance_service.resolve_change_set_conflict(_genesis_command(), authenticated_principal=SHOWRUNNER)

    assert (
        await acceptance_service.get_current_conflict_resolution(
            "d-1", "lin-conflict-1", user_id=_scope().user_id, project_name=_scope().project_name
        )
    ) is None
    assert (
        await acceptance_service.verify_exact_current_selection(
            "d-4", user_id=_scope().user_id, project_name=_scope().project_name
        )
    ) is False


async def test_a_resolution_naming_a_change_set_outside_the_selection_fails_closed(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_two_competing_reviews(acceptance_service, session_factory)
    mismatched = _genesis_command().model_copy(update={"competing_change_set_ids": ("cs-a", "cs-a")})
    with pytest.raises(NarrativeDecisionApplicabilityError):
        await acceptance_service.resolve_change_set_conflict(mismatched, authenticated_principal=SHOWRUNNER)


async def test_reject_in_a_conflict_lineage_advances_latest_and_preserves_effective(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_two_competing_reviews(acceptance_service, session_factory)
    await acceptance_service.resolve_change_set_conflict(_genesis_command(), authenticated_principal=SHOWRUNNER)

    reject = _genesis_command(decision_id="d-5").model_copy(
        update={"action": "REJECT", "expected_latest_decision_id": "d-4", "expected_effective_decision_id": "d-4"}
    )
    receipt = await acceptance_service.resolve_change_set_conflict(reject, authenticated_principal=SHOWRUNNER)
    assert receipt.decision_generation == 2
    assert receipt.effective_decision_id == "d-4"
    assert receipt.effective_generation == 1

    head = await acceptance_service.get_current_conflict_resolution(
        "d-1", "lin-conflict-1", user_id=_scope().user_id, project_name=_scope().project_name
    )
    assert head is not None
    assert head.latest_decision_id == "d-5"
    assert head.decision_generation == 2
    assert head.effective_decision_id == "d-4"
    assert head.effective_generation == 1


async def test_stale_predecessor_on_an_existing_lineage_is_rejected(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_two_competing_reviews(acceptance_service, session_factory)
    await acceptance_service.resolve_change_set_conflict(_genesis_command(), authenticated_principal=SHOWRUNNER)

    stale = _genesis_command(decision_id="d-5").model_copy(
        update={"expected_latest_decision_id": "wrong-id", "expected_effective_decision_id": "d-4"}
    )
    with pytest.raises(NarrativeDecisionPredecessorConflict):
        await acceptance_service.resolve_change_set_conflict(stale, authenticated_principal=SHOWRUNNER)


async def test_superseding_a_named_review_makes_the_resolution_inapplicable(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_two_competing_reviews(acceptance_service, session_factory)
    await acceptance_service.resolve_change_set_conflict(_genesis_command(), authenticated_principal=SHOWRUNNER)
    scope = _scope()
    assert (
        await acceptance_service.is_conflict_resolution_applicable(
            "d-4", user_id=scope.user_id, project_name=scope.project_name
        )
        is True
    )

    await acceptance_service.review_change_set(
        make_change_set_review_command(
            decision_id="d-6",
            work_scope=scope,
            action="SUPERSEDE",
            change_set_lineage_id="lin-cs-a",
            selected_change_set_id="cs-a",
            expected_latest_decision_id="d-2",
            expected_effective_decision_id="d-2",
        ),
        authenticated_principal=SHOWRUNNER,
    )

    assert (
        await acceptance_service.is_conflict_resolution_applicable(
            "d-4", user_id=scope.user_id, project_name=scope.project_name
        )
        is False
    )
