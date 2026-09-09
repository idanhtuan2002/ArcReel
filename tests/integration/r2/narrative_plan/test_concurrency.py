"""Same-plan serialization and different-plan concurrency for NarrativePlanService.

On PostgreSQL the ``lock_plan`` row lock is the concurrency authority; on SQLite the
UoW's ``BEGIN IMMEDIATE`` serializes. Either way exactly one racer wins an append and
the other sees a version conflict.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_plan_uow import narrative_plan_uow_factory
from r2.contracts import (
    CanonBasis,
    CanonContent,
    NarrativePlanApproval,
    NarrativePlanContent,
    NarrativePlanRevisionProposal,
)
from r2.narrative.canon_state import ResolvedCanonView
from r2.narrative.hashing import compute_canon_content_hash
from r2.narrative_plan.errors import NarrativePlanVersionConflict
from r2.narrative_plan.hashing import compute_plan_content_hash
from r2.narrative_plan.service import NarrativePlanService

NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)
USER = "u1"
PROJECT = "project-a"

type Factory = async_sessionmaker[AsyncSession]


class _Reader:
    async def get_exact(
        self, *, branch_id: str, canon_version_id: str, project_name: str, user_id: str
    ) -> ResolvedCanonView | None:
        _ = (branch_id, project_name, user_id)
        content = CanonContent(entities_by_id={}, facts_by_id={}, events_by_id={})
        return ResolvedCanonView(
            canon_version_id=canon_version_id,
            branch_id="main",
            content_hash=compute_canon_content_hash(content, schema_version="r2-canon-schema-v2"),
            content_schema_version="r2-canon-schema-v2",
            content=content,
        )


def _content(frame: str, parent_version: int | None = None) -> NarrativePlanContent:
    return NarrativePlanContent(
        parent_version=parent_version,
        canon_basis=CanonBasis(branch_id="main", canon_version_id="canon-v1"),
        story_frame=frame,
    )


def _proposal(plan_id: str, expected: int | None, revision: str, frame: str) -> NarrativePlanRevisionProposal:
    content = _content(frame, parent_version=expected)
    return NarrativePlanRevisionProposal(
        plan_revision_id=revision,
        plan_id=plan_id,
        expected_version=expected,
        proposed_content=content,
        content_hash=compute_plan_content_hash(content),
        created_at=NOW,
        created_by="lead",
    )


def _approval(proposal: NarrativePlanRevisionProposal, ref: str) -> NarrativePlanApproval:
    return NarrativePlanApproval(
        approval_ref=ref,
        plan_revision_id=proposal.plan_revision_id,
        plan_id=proposal.plan_id,
        expected_version=proposal.expected_version,
        content_hash=proposal.content_hash,
        project_name=PROJECT,
        user_id=USER,
        approved_by="approver",
        approved_at=NOW,
    )


def _service(factory: Factory) -> NarrativePlanService:
    return NarrativePlanService(narrative_plan_uow_factory(factory), _Reader())


async def _commit(factory: Factory, proposal: NarrativePlanRevisionProposal, ref: str) -> object:
    try:
        return await _service(factory).commit_revision(
            proposal=proposal, approval=_approval(proposal, ref), project_name=PROJECT, user_id=USER, now=NOW
        )
    except NarrativePlanVersionConflict as exc:
        return exc


async def test_two_same_plan_appends_yield_one_winner_and_one_conflict(
    concurrent_session_factory: Factory,
) -> None:
    genesis = _proposal("plan-1", None, "rev-1", "frame-1")
    await _commit(concurrent_session_factory, genesis, "ap-1")

    start = asyncio.Event()

    async def race(revision: str, frame: str, ref: str) -> object:
        await start.wait()
        return await _commit(concurrent_session_factory, _proposal("plan-1", 1, revision, frame), ref)

    tasks = [
        asyncio.create_task(race("rev-a", "frame-a", "ap-a")),
        asyncio.create_task(race("rev-b", "frame-b", "ap-b")),
    ]
    start.set()
    outcomes = await asyncio.gather(*tasks)

    conflicts = [item for item in outcomes if isinstance(item, NarrativePlanVersionConflict)]
    winners = [item for item in outcomes if not isinstance(item, NarrativePlanVersionConflict)]
    assert len(conflicts) == 1
    assert len(winners) == 1
    assert winners[0].plan.version == 2


async def test_two_different_plans_commit_independently(concurrent_session_factory: Factory) -> None:
    start = asyncio.Event()

    async def genesis(plan_id: str, revision: str, ref: str) -> object:
        await start.wait()
        return await _commit(concurrent_session_factory, _proposal(plan_id, None, revision, "frame"), ref)

    tasks = [
        asyncio.create_task(genesis("plan-x", "rev-x", "ap-x")),
        asyncio.create_task(genesis("plan-y", "rev-y", "ap-y")),
    ]
    start.set()
    outcomes = await asyncio.gather(*tasks)
    assert all(not isinstance(item, NarrativePlanVersionConflict) for item in outcomes)
    assert {item.plan.plan_id for item in outcomes} == {"plan-x", "plan-y"}
