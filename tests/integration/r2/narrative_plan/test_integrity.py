"""Executable NarrativePlan logical-head / lineage integrity over valid and corrupt fixtures."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.narrative_plan import NarrativePlanModel, NarrativePlanVersionModel
from lib.db.narrative_plan_uow import narrative_plan_uow_factory
from lib.db.repositories.narrative_plan import NarrativePlanRepository
from r2.contracts import CanonBasis, NarrativePlanContent, NarrativePlanHeadSnapshot, NarrativePlanVersionSnapshot
from r2.narrative_plan.hashing import compute_plan_content_hash
from r2.narrative_plan.integrity import NarrativePlanIntegrityChecker

NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)
USER = "u1"
PROJECT = "project-a"

type Factory = async_sessionmaker[AsyncSession]


def _content(parent_version: int | None = None) -> NarrativePlanContent:
    return NarrativePlanContent(
        parent_version=parent_version,
        canon_basis=CanonBasis(branch_id="main", canon_version_id="canon-v1"),
        story_frame="frame",
    )


def _version(number: int, parent: int | None) -> NarrativePlanVersionSnapshot:
    content = _content(parent_version=parent)
    return NarrativePlanVersionSnapshot(
        plan_id="plan-1",
        version=number,
        user_id=USER,
        project_name=PROJECT,
        plan_revision_id=f"rev-{number}",
        parent_version=parent,
        canon_branch_id="main",
        canon_version_id="canon-v1",
        content=content,
        content_hash=compute_plan_content_hash(content),
        approval_ref=f"ap-{number}",
        approved_by="approver",
        approved_at=NOW,
        committed_at=NOW,
        committed_by="lead",
    )


async def _seed_two_versions(factory: Factory) -> None:
    async with narrative_plan_uow_factory(factory)() as uow:
        await uow.repository.insert_plan(
            NarrativePlanHeadSnapshot(
                plan_id="plan-1",
                user_id=USER,
                project_name=PROJECT,
                head_version=None,
                created_at=NOW,
                created_by="lead",
            )
        )
        await uow.repository.insert_version(_version(1, None))
        await uow.repository.advance_head(
            plan_id="plan-1", expected_version=None, new_version=1, project_name=PROJECT, user_id=USER
        )
        await uow.repository.insert_version(_version(2, 1))
        await uow.repository.advance_head(
            plan_id="plan-1", expected_version=1, new_version=2, project_name=PROJECT, user_id=USER
        )
        await uow.commit()


async def _run(factory: Factory) -> list[str]:
    async with factory() as session:
        report = await NarrativePlanIntegrityChecker(NarrativePlanRepository(session)).check_plan(
            plan_id="plan-1", project_name=PROJECT, user_id=USER
        )
    return [finding.rule_id for finding in report.findings]


async def test_valid_plan_passes_every_rule(session_factory: Factory) -> None:
    await _seed_two_versions(session_factory)
    assert await _run(session_factory) == []


async def test_non_latest_head_is_reported(session_factory: Factory) -> None:
    await _seed_two_versions(session_factory)
    async with session_factory() as session:
        await session.execute(
            update(NarrativePlanModel).where(NarrativePlanModel.plan_id == "plan-1").values(head_version=1)
        )
        await session.commit()
    assert await _run(session_factory) == ["PLAN_HEAD_NOT_LATEST"]


async def test_null_head_with_versions_is_reported(session_factory: Factory) -> None:
    await _seed_two_versions(session_factory)
    async with session_factory() as session:
        await session.execute(
            update(NarrativePlanModel).where(NarrativePlanModel.plan_id == "plan-1").values(head_version=None)
        )
        await session.commit()
    assert await _run(session_factory) == ["PLAN_HEAD_NULL_WITH_VERSIONS"]


async def test_missing_head_version_is_reported(session_factory: Factory) -> None:
    await _seed_two_versions(session_factory)
    async with session_factory() as session:
        await session.execute(
            update(NarrativePlanModel).where(NarrativePlanModel.plan_id == "plan-1").values(head_version=9)
        )
        await session.commit()
    assert await _run(session_factory) == ["PLAN_HEAD_MISSING_OR_OUT_OF_SCOPE"]


async def test_broken_parent_lineage_is_reported(session_factory: Factory) -> None:
    await _seed_two_versions(session_factory)
    async with session_factory() as session:
        await session.execute(
            update(NarrativePlanVersionModel)
            .where(NarrativePlanVersionModel.plan_id == "plan-1", NarrativePlanVersionModel.version == 2)
            .values(parent_version=None)
        )
        await session.commit()
    assert await _run(session_factory) == ["PLAN_VERSION_PARENT_MISMATCH"]
