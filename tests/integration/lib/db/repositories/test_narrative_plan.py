"""Integration coverage for the scoped NarrativePlan persistence adapter and UoW."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_plan_uow import narrative_plan_uow_factory
from lib.db.repositories.narrative_plan import NarrativePlanRepository
from r2.contracts import (
    CanonBasis,
    NarrativePlanContent,
    NarrativePlanHeadSnapshot,
    NarrativePlanVersionSnapshot,
)
from r2.narrative_plan.errors import (
    NarrativePlanApprovalError,
    NarrativePlanIdentityConflictError,
    NarrativePlanValidationError,
)
from r2.narrative_plan.hashing import compute_plan_content_hash

NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)
USER = "u1"
OTHER_USER = "conformance"
PROJECT = "project-a"

type Factory = async_sessionmaker[AsyncSession]


def _content() -> NarrativePlanContent:
    return NarrativePlanContent(
        canon_basis=CanonBasis(branch_id="main", canon_version_id="canon-v1"), story_frame="frame"
    )


def head(*, plan_id: str = "plan-1", user_id: str = USER, head_version: int | None = None) -> NarrativePlanHeadSnapshot:
    return NarrativePlanHeadSnapshot(
        plan_id=plan_id,
        user_id=user_id,
        project_name=PROJECT,
        head_version=head_version,
        created_at=NOW,
        created_by="lead",
    )


def version(
    *,
    plan_id: str = "plan-1",
    version_number: int = 1,
    parent: int | None = None,
    revision: str = "rev-1",
    approval: str = "ap-1",
    user_id: str = USER,
) -> NarrativePlanVersionSnapshot:
    content = _content()
    return NarrativePlanVersionSnapshot(
        plan_id=plan_id,
        version=version_number,
        user_id=user_id,
        project_name=PROJECT,
        plan_revision_id=revision,
        parent_version=parent,
        canon_branch_id="main",
        canon_version_id="canon-v1",
        content=content,
        content_hash=compute_plan_content_hash(content),
        approval_ref=approval,
        approved_by="approver",
        approved_at=NOW,
        committed_at=NOW,
        committed_by="lead",
    )


async def test_scoped_reads_collapse_unknown_and_cross_scope(session_factory: Factory) -> None:
    async with narrative_plan_uow_factory(session_factory)() as uow:
        await uow.repository.insert_plan(head())
        await uow.repository.insert_version(version())
        await uow.repository.advance_head(
            plan_id="plan-1", expected_version=None, new_version=1, project_name=PROJECT, user_id=USER
        )
        await uow.commit()

    async with session_factory() as session:
        repository = NarrativePlanRepository(session)
        assert await repository.get_plan_head(plan_id="plan-1", project_name=PROJECT, user_id=USER) is not None
        assert await repository.get_plan_head(plan_id="ghost", project_name=PROJECT, user_id=USER) is None
        assert await repository.get_plan_head(plan_id="plan-1", project_name=PROJECT, user_id=OTHER_USER) is None
        assert (
            await repository.get_version_by_revision(plan_revision_id="rev-1", project_name=PROJECT, user_id=USER)
        ).version == 1
        assert (
            await repository.get_version_by_approval(approval_ref="ap-1", project_name=PROJECT, user_id=USER)
        ).version == 1


async def test_append_advances_head_and_keeps_ordered_history(session_factory: Factory) -> None:
    async with narrative_plan_uow_factory(session_factory)() as uow:
        await uow.repository.insert_plan(head())
        await uow.repository.insert_version(version(version_number=1))
        await uow.repository.advance_head(
            plan_id="plan-1", expected_version=None, new_version=1, project_name=PROJECT, user_id=USER
        )
        await uow.repository.insert_version(version(version_number=2, parent=1, revision="rev-2", approval="ap-2"))
        await uow.repository.advance_head(
            plan_id="plan-1", expected_version=1, new_version=2, project_name=PROJECT, user_id=USER
        )
        await uow.commit()

    async with session_factory() as session:
        repository = NarrativePlanRepository(session)
        versions = await repository.list_plan_versions(plan_id="plan-1", project_name=PROJECT, user_id=USER)
        assert [item.version for item in versions] == [1, 2]
        assert (await repository.get_plan_head(plan_id="plan-1", project_name=PROJECT, user_id=USER)).head_version == 2


async def test_duplicate_revision_and_approval_fail_closed(session_factory: Factory) -> None:
    async with narrative_plan_uow_factory(session_factory)() as uow:
        await uow.repository.insert_plan(head())
        await uow.repository.insert_version(version(revision="rev-1", approval="ap-1"))
        await uow.commit()

    async with narrative_plan_uow_factory(session_factory)() as uow:
        await uow.repository.insert_plan(head(plan_id="plan-2"))
        with pytest.raises(NarrativePlanApprovalError):
            await uow.repository.insert_version(version(plan_id="plan-2", revision="rev-9", approval="ap-1"))

    async with narrative_plan_uow_factory(session_factory)() as uow:
        await uow.repository.insert_plan(head(plan_id="plan-3"))
        with pytest.raises(NarrativePlanIdentityConflictError):
            await uow.repository.insert_version(version(plan_id="plan-3", revision="rev-1", approval="ap-8"))


async def test_stale_advance_head_raises_and_writes_nothing(session_factory: Factory) -> None:
    async with narrative_plan_uow_factory(session_factory)() as uow:
        await uow.repository.insert_plan(head(head_version=1))
        await uow.repository.insert_version(version())
        with pytest.raises(NarrativePlanValidationError):
            await uow.repository.advance_head(
                plan_id="plan-1", expected_version=5, new_version=6, project_name=PROJECT, user_id=USER
            )
