"""PostgreSQL-only concurrency coverage for ``AdaptationAuthorityService.decide_map``
(plan Task 7).

Two genuinely independent connections race the same or different ``MAP_APPROVAL``
heads, synchronized with ``asyncio.Barrier`` so both reach the serialization point
before either proceeds — never ``time.sleep``, never implicit ordering. Skipped on
SQLite: the StaticPool test engine shares one connection and SQLite has no real
row-level locking, so there is nothing to race against. Mirrors
``tests/integration/r2/narrative_lifecycle/test_lifecycle_concurrency.py``'s own
"subclass the concrete unit of work, override the one method that serializes the race"
pattern exactly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.adaptation_uow import SqlAlchemyAdaptationUnitOfWork, adaptation_uow_factory
from lib.db.repositories.adaptation import AdaptationRepository
from r2.adaptation.authority import AdaptationAuthorityService
from r2.adaptation.evidence import AdaptationEvidenceService
from r2.contracts.adaptation import AdaptationAuthorityFamily, AdaptationHead
from tests.integration.r2.adaptation._fakes import FakeAuthority
from tests.integration.r2.adaptation.test_map_approval import (
    _PRINCIPAL,
    PROJECT,
    USER,
    _approve_command,
    _branch,
    _branch_ref,
    _map,
    _map_ref,
)

type Factory = async_sessionmaker[AsyncSession]

_DEADLOCK_TIMEOUT_S = 10.0


async def _skip_unless_postgres(session_factory: Factory) -> None:
    async with session_factory() as probe:
        if probe.bind.dialect.name == "sqlite":
            pytest.skip("concurrency races need real row-level locking (PostgreSQL only)")


def _outcome_type(value: object) -> str:
    return type(value).__name__


async def _run_capturing(coro: Coroutine[Any, Any, object]) -> object:
    try:
        return await coro
    except Exception as exc:
        return exc


class _BarrierBeforeHeadLockRepository(AdaptationRepository):
    def __init__(self, session: AsyncSession, barrier: asyncio.Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    async def prepare_or_lock_head(
        self, *, user_id: str, project_name: str, family: AdaptationAuthorityFamily, head_key: str
    ) -> AdaptationHead | None:
        await self._barrier.wait()
        return await super().prepare_or_lock_head(
            user_id=user_id, project_name=project_name, family=family, head_key=head_key
        )


class _BarrierBeforeHeadLockUnitOfWork(SqlAlchemyAdaptationUnitOfWork):
    def __init__(self, session_factory: Factory, barrier: asyncio.Barrier) -> None:
        super().__init__(session_factory)
        self._barrier = barrier

    async def __aenter__(self) -> _BarrierBeforeHeadLockUnitOfWork:
        await super().__aenter__()
        self.repository = _BarrierBeforeHeadLockRepository(self.session, self._barrier)
        return self


async def _seed_branch_and_map(session_factory: Factory, *, branch_id: str, map_id: str):
    evidence = AdaptationEvidenceService(adaptation_uow_factory(session_factory))
    branch = await evidence.create_branch(_branch(branch_id=branch_id), user_id=USER, project_name=PROJECT)
    map_ = await evidence.append_map(
        _map(adaptation_map_id=map_id, branch_ref=_branch_ref(branch)), user_id=USER, project_name=PROJECT
    )
    return branch, map_


async def test_two_concurrent_genesis_map_approvals_on_one_branch_yield_one_winner(
    concurrent_session_factory: Factory,
) -> None:
    await _skip_unless_postgres(concurrent_session_factory)
    branch, map_ = await _seed_branch_and_map(concurrent_session_factory, branch_id="branch-race", map_id="map-race")

    barrier = asyncio.Barrier(2)
    service = AdaptationAuthorityService(
        lambda: _BarrierBeforeHeadLockUnitOfWork(concurrent_session_factory, barrier), FakeAuthority()
    )

    async def run(decision_id: str) -> object:
        command = _approve_command(
            decision_id=decision_id, branch_id=branch.branch_id, map_ref=_map_ref(map_), profile_ref=branch.profile_ref
        )
        return await service.decide_map(command, authenticated_principal=_PRINCIPAL)

    a, b = await asyncio.wait_for(
        asyncio.gather(_run_capturing(run("d-a")), _run_capturing(run("d-b"))), timeout=_DEADLOCK_TIMEOUT_S
    )
    outcomes = sorted(_outcome_type(x) for x in (a, b))
    assert outcomes == ["AdaptationDecisionReceipt", "AdaptationStaleHeadError"]

    async with adaptation_uow_factory(concurrent_session_factory)() as uow:
        decisions = await uow.repository.list_decisions_for_locked_head(
            user_id=USER, project_name=PROJECT, family=AdaptationAuthorityFamily.MAP_APPROVAL, head_key=branch.branch_id
        )
        assert len(decisions) == 1


async def test_two_concurrent_genesis_map_approvals_on_distinct_branches_do_not_block_each_other(
    concurrent_session_factory: Factory,
) -> None:
    await _skip_unless_postgres(concurrent_session_factory)
    branch_a, map_a = await _seed_branch_and_map(concurrent_session_factory, branch_id="branch-a", map_id="map-a")
    branch_b, map_b = await _seed_branch_and_map(concurrent_session_factory, branch_id="branch-b", map_id="map-b")

    barrier = asyncio.Barrier(2)
    service = AdaptationAuthorityService(
        lambda: _BarrierBeforeHeadLockUnitOfWork(concurrent_session_factory, barrier), FakeAuthority()
    )

    async def run(decision_id: str, branch, map_) -> object:
        command = _approve_command(
            decision_id=decision_id, branch_id=branch.branch_id, map_ref=_map_ref(map_), profile_ref=branch.profile_ref
        )
        return await service.decide_map(command, authenticated_principal=_PRINCIPAL)

    a, b = await asyncio.wait_for(
        asyncio.gather(_run_capturing(run("d-a", branch_a, map_a)), _run_capturing(run("d-b", branch_b, map_b))),
        timeout=_DEADLOCK_TIMEOUT_S,
    )
    outcomes = sorted(_outcome_type(x) for x in (a, b))
    assert outcomes == ["AdaptationDecisionReceipt", "AdaptationDecisionReceipt"]

    async with adaptation_uow_factory(concurrent_session_factory)() as uow:
        for branch in (branch_a, branch_b):
            decisions = await uow.repository.list_decisions_for_locked_head(
                user_id=USER,
                project_name=PROJECT,
                family=AdaptationAuthorityFamily.MAP_APPROVAL,
                head_key=branch.branch_id,
            )
            assert len(decisions) == 1
