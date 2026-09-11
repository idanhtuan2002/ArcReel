"""Integration coverage for ``NarrativeLifecycleIntegrityChecker`` (Task 20, partial —
rebuild only; Task 30 completes it with the read-side currentness wiring).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_lifecycle_uow import narrative_lifecycle_uow_factory
from r2.contracts.narrative_lifecycle import NarrativeWorkScope
from r2.narrative_lifecycle.acceptance import NarrativeAcceptanceService
from r2.narrative_lifecycle.errors import NarrativeAuthorityIntegrityError
from r2.narrative_lifecycle.integrity import NarrativeLifecycleIntegrityChecker
from tests.factories import make_change_set_review_command, make_narrative_work_scope, make_revision_acceptance_command
from tests.integration.r2.narrative_lifecycle._fakes import SHOWRUNNER

type Factory = async_sessionmaker[AsyncSession]


def _scope() -> NarrativeWorkScope:
    return make_narrative_work_scope()


@pytest.fixture
def integrity_checker(session_factory: Factory) -> NarrativeLifecycleIntegrityChecker:
    return NarrativeLifecycleIntegrityChecker(narrative_lifecycle_uow_factory(session_factory))


async def test_rebuild_matches_the_stored_head_after_accept_supersede_reject(
    acceptance_service: NarrativeAcceptanceService, integrity_checker: NarrativeLifecycleIntegrityChecker
) -> None:
    scope = _scope()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
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
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(
            decision_id="d-3",
            work_scope=scope,
            action="REJECT",
            selected_revision_id="rev-3",
            expected_latest_decision_id="d-2",
            expected_effective_decision_id="d-2",
        ),
        authenticated_principal=SHOWRUNNER,
    )

    verified = await integrity_checker.verify_revision_head(scope)
    assert verified.latest_decision_id == "d-3"
    assert verified.decision_generation == 3
    assert verified.effective_decision_id == "d-2"
    assert verified.effective_generation == 2

    stored = await acceptance_service.get_current_revision_selection(scope)
    assert stored == verified


async def test_reject_does_not_advance_effective_generation_on_rebuild(
    acceptance_service: NarrativeAcceptanceService, integrity_checker: NarrativeLifecycleIntegrityChecker
) -> None:
    scope = _scope()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(
            decision_id="d-2",
            work_scope=scope,
            action="REJECT",
            selected_revision_id="rev-2",
            expected_latest_decision_id="d-1",
            expected_effective_decision_id="d-1",
        ),
        authenticated_principal=SHOWRUNNER,
    )

    rebuilt = await integrity_checker.rebuild_revision_head(scope)
    assert rebuilt.effective_generation == 1
    assert rebuilt.decision_generation == 2
    assert rebuilt.effective_decision_id == "d-1"
    assert rebuilt.latest_decision_id == "d-2"


async def test_rebuild_on_an_untouched_scope_is_the_null_head(
    integrity_checker: NarrativeLifecycleIntegrityChecker,
) -> None:
    rebuilt = await integrity_checker.rebuild_revision_head(_scope())
    assert rebuilt.latest_decision_id is None
    assert rebuilt.decision_generation == 0
    assert rebuilt.effective_decision_id is None
    assert rebuilt.effective_generation == 0
    # verify_revision_head must not treat "nothing ever happened" as corruption
    verified = await integrity_checker.verify_revision_head(_scope())
    assert verified == rebuilt


async def test_verify_revision_head_raises_when_the_stored_head_disagrees(
    acceptance_service: NarrativeAcceptanceService,
    integrity_checker: NarrativeLifecycleIntegrityChecker,
    session_factory: Factory,
) -> None:
    scope = _scope()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )

    # Corrupt the mutable head directly -- the authoritative decision chain still says
    # decision_generation=1, but the stored projection now (wrongly) claims 2.
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE revision_acceptance_heads SET decision_generation = 2 "
                "WHERE user_id = :user_id AND project_name = :project_name"
            ),
            {"user_id": scope.user_id, "project_name": scope.project_name},
        )
        await session.commit()

    with pytest.raises(NarrativeAuthorityIntegrityError):
        await integrity_checker.verify_revision_head(scope)


async def test_change_set_review_and_conflict_resolution_heads_also_rebuild(
    acceptance_service: NarrativeAcceptanceService, integrity_checker: NarrativeLifecycleIntegrityChecker
) -> None:
    scope = _scope()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.review_change_set(
        make_change_set_review_command(decision_id="d-2", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )

    verified = await integrity_checker.verify_change_set_review_head(
        revision_acceptance_decision_id="d-1",
        change_set_lineage_id="lin-cs-1",
        user_id=scope.user_id,
        project_name=scope.project_name,
    )
    assert verified.latest_decision_id == "d-2"
    assert verified.effective_decision_id == "d-2"

    empty_conflict = await integrity_checker.rebuild_conflict_resolution_head(
        revision_acceptance_decision_id="d-1", conflict_resolution_lineage_id="lin-ghost"
    )
    assert empty_conflict.latest_decision_id is None
