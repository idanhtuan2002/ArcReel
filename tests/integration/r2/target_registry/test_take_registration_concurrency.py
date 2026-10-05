"""Forced PostgreSQL interleavings for scoped Take target registration."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.production_target import (
    ProductionTargetCommandModel,
    ProductionTargetHeadModel,
    ProductionTargetVersionModel,
)
from lib.db.repositories.production_target import ProductionTargetCommandConflictError
from r2.adaptation.authority import AdaptationAuthorityService
from r2.adaptation.evaluation import report_ref_of
from r2.contracts.adaptation import AdaptationDecisionAction
from r2.production_intelligence.take_director import TakeDirectorAdapter
from r2.target_registry.service import TakeTargetRegistrationService
from tests.integration.r2.adaptation._fakes import FakeAuthority
from tests.integration.r2.adaptation.test_screenplay_admission import _admit_command, _TrackedAdmissionUnitOfWork
from tests.integration.r2.target_registry.test_take_registration import _admit, _command

type Factory = async_sessionmaker[AsyncSession]


async def _two_admissions(factory: Factory):
    first, *_ = await _admit(factory)
    second, *_ = await _admit(
        factory,
        branch_id="branch-2",
        map_id="map-2",
        screenplay_id="sp-2",
        decision_id="d-admit-2",
    )
    return first, second


async def _postgres_only(factory: Factory) -> None:
    async with factory() as session:
        if session.bind.dialect.name != "postgresql":
            pytest.skip("forced row-lock interleavings require PostgreSQL")


def _barrier_after_derivation(monkeypatch: pytest.MonkeyPatch) -> None:
    barrier = asyncio.Barrier(2)
    original = TakeDirectorAdapter.direct

    async def direct_and_wait(self, artifact):
        result = await original(self, artifact)
        await asyncio.wait_for(barrier.wait(), timeout=15)
        return result

    monkeypatch.setattr(TakeDirectorAdapter, "direct", direct_and_wait)


async def test_two_first_writers_serialize_absent_heads(
    concurrent_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _postgres_only(concurrent_session_factory)
    first, second = await _two_admissions(concurrent_session_factory)
    _barrier_after_derivation(monkeypatch)
    service = TakeTargetRegistrationService(concurrent_session_factory)
    results = await asyncio.wait_for(
        asyncio.gather(
            service.register(_command(first, command_id="take-a")),
            service.register(_command(second, command_id="take-b")),
        ),
        timeout=30,
    )
    assert {result.scene_targets[0].registry_version for result in results} == {1, 2}
    assert {result.shot_targets[0].registry_version for result in results} == {1, 2}
    async with concurrent_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProductionTargetHeadModel)) == 2
        assert await session.scalar(select(func.count()).select_from(ProductionTargetVersionModel)) == 4
        assert await session.scalar(select(func.count()).select_from(ProductionTargetCommandModel)) == 2
        heads = (await session.scalars(select(ProductionTargetHeadModel))).all()
        assert all(head.current_version == 2 for head in heads)


async def test_identical_parallel_command_replays_one_receipt(concurrent_session_factory: Factory) -> None:
    await _postgres_only(concurrent_session_factory)
    ref, *_ = await _admit(concurrent_session_factory)
    service = TakeTargetRegistrationService(concurrent_session_factory)
    command = _command(ref)
    first, second = await asyncio.wait_for(
        asyncio.gather(service.register(command), service.register(command)), timeout=30
    )
    assert first == second
    async with concurrent_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProductionTargetHeadModel)) == 2
        assert await session.scalar(select(func.count()).select_from(ProductionTargetVersionModel)) == 2
        assert await session.scalar(select(func.count()).select_from(ProductionTargetCommandModel)) == 1


async def test_same_command_id_loser_rolls_back_whole_bundle(
    concurrent_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _postgres_only(concurrent_session_factory)
    first, second = await _two_admissions(concurrent_session_factory)
    _barrier_after_derivation(monkeypatch)
    service = TakeTargetRegistrationService(concurrent_session_factory)
    outcomes = await asyncio.wait_for(
        asyncio.gather(
            service.register(_command(first, command_id="same-command")),
            service.register(_command(second, command_id="same-command")),
            return_exceptions=True,
        ),
        timeout=30,
    )
    assert sum(isinstance(value, ProductionTargetCommandConflictError) for value in outcomes) == 1
    assert sum(not isinstance(value, BaseException) for value in outcomes) == 1
    async with concurrent_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProductionTargetHeadModel)) == 2
        assert await session.scalar(select(func.count()).select_from(ProductionTargetVersionModel)) == 2
        assert await session.scalar(select(func.count()).select_from(ProductionTargetCommandModel)) == 1
        heads = (await session.scalars(select(ProductionTargetHeadModel))).all()
        assert all(head.current_version == 1 for head in heads)


async def test_readmission_waits_for_registration_admission_lock(
    concurrent_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _postgres_only(concurrent_session_factory)
    ref, branch, map_receipt, proposal, admit, _, _, _, report = await _admit(concurrent_session_factory)
    entered = asyncio.Event()
    release = asyncio.Event()
    registration_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    original = TakeDirectorAdapter.direct

    async def direct_and_hold(self, artifact):
        result = await original(self, artifact)
        pid = await self._reader._repository.session.scalar(text("SELECT pg_backend_pid()"))
        assert isinstance(pid, int)
        registration_pid.set_result(pid)
        entered.set()
        await release.wait()
        return result

    monkeypatch.setattr(TakeDirectorAdapter, "direct", direct_and_hold)
    registration = asyncio.create_task(
        TakeTargetRegistrationService(concurrent_session_factory).register(_command(ref))
    )
    writer = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=15)
        revoke = _admit_command(
            decision_id="d-admit-revoke-after-target",
            proposal=proposal,
            profile_ref=branch.profile_ref,
            effective_map_approval_ref=map_receipt.decision_ref,
            report_refs=[report_ref_of(report)],
            expected_predecessor_id=admit.decision_id,
            action=AdaptationDecisionAction.REVOKE,
        )
        writer_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        authority = AdaptationAuthorityService(
            lambda: _TrackedAdmissionUnitOfWork(concurrent_session_factory, writer_pid), FakeAuthority()
        )
        writer = asyncio.create_task(
            authority.admit_screenplay_for_direction(revoke, authenticated_principal="human:anhtuan")
        )
        pid = await asyncio.wait_for(writer_pid, timeout=15)
        locked_by = await asyncio.wait_for(registration_pid, timeout=15)

        async def blocked() -> bool:
            async with concurrent_session_factory() as probe:
                blockers = await probe.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid})
                return isinstance(blockers, list) and locked_by in blockers

        async with asyncio.timeout(15):
            while not await blocked():
                assert not writer.done()
                await asyncio.sleep(0.02)
    finally:
        release.set()
    result = await asyncio.wait_for(registration, timeout=15)
    assert result.scene_targets[0].registry_version == 1
    assert writer is not None
    revoked = await asyncio.wait_for(writer, timeout=15)
    assert revoked.current_at_return is False
