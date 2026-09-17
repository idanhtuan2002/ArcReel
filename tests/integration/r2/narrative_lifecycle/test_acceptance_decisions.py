"""Integration coverage for ``NarrativeAcceptanceService.decide_revision`` /
``review_change_set`` (Task 18): authority-policy denial, ACCEPT/SUPERSEDE predecessor
enforcement, per-lineage head independence, and exact-retry stability — driven through
the real repository/UoW against SQLite, never a real ``NarrativeShowrunnerAuthorityPort``
adapter (that governance boundary is manual/fixture-only per spec §6.2).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_lifecycle_uow import narrative_lifecycle_uow_factory
from r2.contracts.narrative_lifecycle import ChangeSetReviewCommand, NarrativeWorkScope
from r2.narrative_lifecycle.acceptance import NarrativeAcceptanceService
from r2.narrative_lifecycle.errors import NarrativeDecisionAuthorizationError, NarrativeDecisionPredecessorConflict
from tests.factories import (
    make_change_set_review_command,
    make_narrative_decision_authorization,
    make_narrative_work_scope,
    make_revision_acceptance_command,
)
from tests.integration.r2.narrative_lifecycle._fakes import SHOWRUNNER, FakeShowrunnerAuthorityPort

type Factory = async_sessionmaker[AsyncSession]


def _scope() -> NarrativeWorkScope:
    return make_narrative_work_scope()


@pytest.mark.parametrize(
    "actor",
    [
        "delegated_reviewer",
        "human_author_no_capability",
        "agent",
        "extractor",
        "compiler",
        "provider",
        "orchestrator",
        "host_admin",
    ],
)
async def test_only_human_showrunner_may_decide(acceptance_service: NarrativeAcceptanceService, actor: str) -> None:
    command = make_revision_acceptance_command(decision_id="d-1", work_scope=_scope(), action="ACCEPT")
    with pytest.raises(NarrativeDecisionAuthorizationError):
        await acceptance_service.decide_revision(command, authenticated_principal=actor)


async def test_authorization_bound_to_another_family_is_rejected_by_the_service(
    acceptance_service: NarrativeAcceptanceService, fake_showrunner: FakeShowrunnerAuthorityPort
) -> None:
    scope = _scope()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    fake_showrunner.next_authorization = make_narrative_decision_authorization(
        decision_id="d-2",
        user_id=scope.user_id,
        project_name=scope.project_name,
        decision_family="REVISION_ACCEPTANCE",
        action="ACCEPT",
    )
    review_command = make_change_set_review_command(decision_id="d-2", work_scope=scope, action="ACCEPT")
    with pytest.raises(NarrativeDecisionAuthorizationError):
        await acceptance_service.review_change_set(review_command, authenticated_principal=SHOWRUNNER)


async def test_accept_with_an_existing_effective_selection_fails(
    acceptance_service: NarrativeAcceptanceService,
) -> None:
    scope = _scope()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    another_accept = make_revision_acceptance_command(
        decision_id="d-2",
        work_scope=scope,
        action="ACCEPT",
        selected_revision_id="rev-2",
        expected_latest_decision_id="d-1",
        expected_effective_decision_id=None,  # ACCEPT's own rule; the real effective is now "d-1"
    )
    with pytest.raises(NarrativeDecisionPredecessorConflict):
        await acceptance_service.decide_revision(another_accept, authenticated_principal=SHOWRUNNER)


async def test_supersede_replaces_only_its_exact_expected_effective_predecessor(
    acceptance_service: NarrativeAcceptanceService,
) -> None:
    scope = _scope()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    supersede_ok = make_revision_acceptance_command(
        decision_id="d-2",
        work_scope=scope,
        action="SUPERSEDE",
        selected_revision_id="rev-2",
        expected_latest_decision_id="d-1",
        expected_effective_decision_id="d-1",
    )
    receipt = await acceptance_service.decide_revision(supersede_ok, authenticated_principal=SHOWRUNNER)
    assert receipt.effective_decision_id == "d-2"

    stale_supersede = make_revision_acceptance_command(
        decision_id="d-3",
        work_scope=scope,
        action="SUPERSEDE",
        selected_revision_id="rev-3",
        expected_latest_decision_id="d-2",
        expected_effective_decision_id="d-1",  # stale: the real effective is now "d-2"
    )
    with pytest.raises(NarrativeDecisionPredecessorConflict):
        await acceptance_service.decide_revision(stale_supersede, authenticated_principal=SHOWRUNNER)


async def test_one_lineage_supersession_does_not_alter_another_non_overlapping_lineage(
    acceptance_service: NarrativeAcceptanceService,
) -> None:
    scope = _scope()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.review_change_set(
        make_change_set_review_command(
            decision_id="d-2",
            work_scope=scope,
            action="ACCEPT",
            change_set_lineage_id="lin-a",
            selected_change_set_id="cs-a",
        ),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.review_change_set(
        make_change_set_review_command(
            decision_id="d-3",
            work_scope=scope,
            action="ACCEPT",
            change_set_lineage_id="lin-b",
            selected_change_set_id="cs-b",
        ),
        authenticated_principal=SHOWRUNNER,
    )

    await acceptance_service.review_change_set(
        ChangeSetReviewCommand(
            decision_id="d-4",
            action="SUPERSEDE",
            work_scope=scope,
            revision_acceptance_decision_id="d-1",
            change_set_lineage_id="lin-a",
            selected_change_set_id="cs-a2",
            expected_latest_decision_id="d-2",
            expected_effective_decision_id="d-2",
            base_canon_version_id="cv-1",
            plan_version=2,
            scene_contract_version=1,
            context_pack_id="ctx-1",
            actor_id=SHOWRUNNER,
        ),
        authenticated_principal=SHOWRUNNER,
    )

    lineage_a = await acceptance_service.get_current_change_set_selection(
        "d-1", "lin-a", user_id=scope.user_id, project_name=scope.project_name
    )
    lineage_b = await acceptance_service.get_current_change_set_selection(
        "d-1", "lin-b", user_id=scope.user_id, project_name=scope.project_name
    )
    assert lineage_a is not None
    assert lineage_a.effective_decision_id == "d-4"
    assert lineage_b is not None
    assert lineage_b.effective_decision_id == "d-3"  # untouched by lineage a's supersession


async def test_a_new_revision_acceptance_does_not_inherit_prior_change_set_heads(
    acceptance_service: NarrativeAcceptanceService,
) -> None:
    scope = _scope()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.review_change_set(
        make_change_set_review_command(
            decision_id="d-2",
            work_scope=scope,
            action="ACCEPT",
            change_set_lineage_id="lin-x",
            selected_change_set_id="cs-x",
        ),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(
            decision_id="d-3",
            work_scope=scope,
            action="SUPERSEDE",
            selected_revision_id="rev-2",
            expected_latest_decision_id="d-1",
            expected_effective_decision_id="d-1",
        ),
        authenticated_principal=SHOWRUNNER,
    )

    old_lineage = await acceptance_service.get_current_change_set_selection(
        "d-1", "lin-x", user_id=scope.user_id, project_name=scope.project_name
    )
    new_lineage = await acceptance_service.get_current_change_set_selection(
        "d-3", "lin-x", user_id=scope.user_id, project_name=scope.project_name
    )
    assert old_lineage is not None
    assert old_lineage.effective_decision_id == "d-2"  # untouched, still under the old revision decision
    assert new_lineage is None  # the new revision acceptance starts with no change-set heads at all


async def test_exact_retry_after_later_head_movement_returns_the_original_decision_unchanged(
    acceptance_service: NarrativeAcceptanceService,
) -> None:
    scope = _scope()
    original = make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT")
    first_receipt = await acceptance_service.decide_revision(original, authenticated_principal=SHOWRUNNER)
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(
            decision_id="d-2",
            work_scope=scope,
            action="SUPERSEDE",
            selected_revision_id="rev-2",
            expected_latest_decision_id="d-1",
            expected_effective_decision_id="d-1",
        ),
        authenticated_principal=SHOWRUNNER,
    )

    retry_receipt = await acceptance_service.decide_revision(original, authenticated_principal=SHOWRUNNER)
    assert retry_receipt == first_receipt
    assert retry_receipt.effective_decision_id == "d-1"  # the original receipt, not "currently effective"

    current = await acceptance_service.get_current_revision_selection(scope)
    assert current is not None
    assert current.effective_decision_id == "d-2"  # the head moved on; the retry did not undo that


async def test_verify_exact_current_selection_reflects_supersession(
    acceptance_service: NarrativeAcceptanceService,
) -> None:
    scope = _scope()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    assert await acceptance_service.verify_exact_current_selection(
        "d-1", user_id=scope.user_id, project_name=scope.project_name
    )

    await acceptance_service.decide_revision(
        make_revision_acceptance_command(
            decision_id="d-2",
            work_scope=scope,
            action="SUPERSEDE",
            selected_revision_id="rev-2",
            expected_latest_decision_id="d-1",
            expected_effective_decision_id="d-1",
        ),
        authenticated_principal=SHOWRUNNER,
    )

    assert not await acceptance_service.verify_exact_current_selection(
        "d-1", user_id=scope.user_id, project_name=scope.project_name
    )
    assert await acceptance_service.verify_exact_current_selection(
        "d-2", user_id=scope.user_id, project_name=scope.project_name
    )
    assert not await acceptance_service.verify_exact_current_selection(
        "ghost", user_id=scope.user_id, project_name=scope.project_name
    )


def test_constructing_without_an_authority_adapter_denies_by_default(session_factory: Factory) -> None:
    with pytest.raises(ValueError, match="NarrativeShowrunnerAuthorityPort"):
        NarrativeAcceptanceService(narrative_lifecycle_uow_factory(session_factory), None)
