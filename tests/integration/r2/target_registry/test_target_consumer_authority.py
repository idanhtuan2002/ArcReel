"""A target-ID consumer proves upstream admission before trusting the current target."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.adaptation_uow import SqlAlchemyAdaptationUnitOfWork
from lib.db.models.production_target import ProductionTargetHeadModel, ProductionTargetVersionModel
from lib.db.repositories.production_target import ProductionTargetIntegrityError, ProductionTargetRepository
from r2.adaptation.evaluation import report_ref_of
from r2.adaptation.screenplay_reader import TransactionBoundApprovedScreenplayReader
from r2.contracts.adaptation import AdaptationDecisionAction
from r2.target_registry import service as target_service_module
from r2.target_registry.resolver import TransactionBoundTargetAuthorityResolver
from r2.target_registry.service import TakeTargetRegistrationService
from tests.integration.r2.adaptation.test_screenplay_admission import _admit_command
from tests.integration.r2.target_registry.test_take_registration import _admit, _command

type Factory = async_sessionmaker[AsyncSession]


async def test_target_id_consumer_resolves_current_scene_and_shot(session_factory: Factory) -> None:
    admission, *_ = await _admit(session_factory)
    result = await TakeTargetRegistrationService(session_factory).register(_command(admission))
    async with session_factory() as session:
        resolver = TransactionBoundTargetAuthorityResolver(session)
        for ref in (*result.scene_targets, *result.shot_targets):
            current = await resolver.resolve_current(
                user_id="u1", project_name="project-a", target_type=ref.target_type, target_id=ref.target_id
            )
            assert current is not None
            assert current.ref == ref
            assert current.admitted_screenplay_ref == admission
        assert (
            await resolver.resolve_current(
                user_id="u1", project_name="other", target_type="SHOT", target_id=result.shot_targets[0].target_id
            )
            is None
        )
        assert (
            await resolver.resolve_current(
                user_id="foreign",
                project_name="project-a",
                target_type="SHOT",
                target_id=result.shot_targets[0].target_id,
            )
            is None
        )


async def test_changed_untrusted_hint_fails_after_authority_read(
    session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    admission, *_ = await _admit(session_factory)
    result = await TakeTargetRegistrationService(session_factory).register(_command(admission))
    original = ProductionTargetRepository.peek_current_admission_hint

    async def changed_hint(self, **kwargs):
        hint = await original(self, **kwargs)
        assert hint is not None
        return replace(hint, ref=hint.ref.model_copy(update={"version_digest": "sha256:" + "f" * 64}))

    monkeypatch.setattr(ProductionTargetRepository, "peek_current_admission_hint", changed_hint)
    async with session_factory() as session:
        with pytest.raises(ProductionTargetIntegrityError, match="hint"):
            await TransactionBoundTargetAuthorityResolver(session).resolve_current(
                user_id="u1", project_name="project-a", target_type="SHOT", target_id=result.shot_targets[0].target_id
            )


async def test_committed_genesis_and_forged_profile_hint_are_not_authority(session_factory: Factory) -> None:
    admission, *_ = await _admit(session_factory)
    async with session_factory() as session:
        session.add(
            ProductionTargetHeadModel(
                user_id="u1",
                project_name="project-a",
                target_type="SCENE",
                target_id="stray-scene",
                current_version=None,
                current_version_digest=None,
            )
        )
        await session.commit()
    async with session_factory() as session:
        with pytest.raises(ProductionTargetIntegrityError, match="hint"):
            await TransactionBoundTargetAuthorityResolver(session).resolve_current(
                user_id="u1", project_name="project-a", target_type="SCENE", target_id="stray-scene"
            )
    result = await TakeTargetRegistrationService(session_factory).register(_command(admission))
    async with session_factory() as session:
        version = await session.get(
            ProductionTargetVersionModel, ("u1", "project-a", "SCENE", result.scene_targets[0].target_id, 1)
        )
        assert version is not None
        version.admitted_screenplay_ref_json = version.admitted_screenplay_ref_json | {
            "profile_ref": version.admitted_screenplay_ref_json["profile_ref"]
            | {"policy_pack_digest": "sha256:" + "f" * 64}
        }
        await session.commit()
    async with session_factory() as session:
        with pytest.raises(ProductionTargetIntegrityError, match="hint is stale"):
            await TransactionBoundTargetAuthorityResolver(session).resolve_current(
                user_id="u1", project_name="project-a", target_type="SCENE", target_id=result.scene_targets[0].target_id
            )


async def test_postgres_target_advance_between_hint_and_admission_lock_fails(
    concurrent_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with concurrent_session_factory() as probe:
        if probe.bind.dialect.name != "postgresql":
            pytest.skip("forced hint/lock interleaving requires PostgreSQL")
    admission, *_ = await _admit(concurrent_session_factory)
    service = TakeTargetRegistrationService(concurrent_session_factory)
    first = await service.register(_command(admission))
    hint_read = asyncio.Event()
    release = asyncio.Event()
    original_peek = ProductionTargetRepository.peek_current_admission_hint

    async def pause_after_hint(self, **kwargs):
        hint = await original_peek(self, **kwargs)
        hint_read.set()
        await release.wait()
        return hint

    monkeypatch.setattr(ProductionTargetRepository, "peek_current_admission_hint", pause_after_hint)

    async def resolve():
        async with concurrent_session_factory() as session:
            return await TransactionBoundTargetAuthorityResolver(session).resolve_current(
                user_id="u1", project_name="project-a", target_type="SHOT", target_id=first.shot_targets[0].target_id
            )

    reader = asyncio.create_task(resolve())
    try:
        await asyncio.wait_for(hint_read.wait(), timeout=15)
        monkeypatch.setattr(target_service_module, "TAKE_DERIVATION_VERSION", "r2-take-director-v2-test")
        changed = await asyncio.wait_for(service.register(_command(admission, command_id="take-next-derivation")), 15)
        assert changed.scene_targets[0].registry_version == 2
        assert changed.shot_targets[0].registry_version == 2
    finally:
        release.set()
    with pytest.raises(ProductionTargetIntegrityError, match="hint changed"):
        await asyncio.wait_for(reader, timeout=15)


async def test_postgres_readmission_between_hint_and_lock_fails(
    concurrent_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with concurrent_session_factory() as probe:
        if probe.bind.dialect.name != "postgresql":
            pytest.skip("forced hint/lock interleaving requires PostgreSQL")
    admission, branch, map_receipt, proposal, admit, _, authority, _, report = await _admit(concurrent_session_factory)
    result = await TakeTargetRegistrationService(concurrent_session_factory).register(_command(admission))
    hint_read = asyncio.Event()
    release = asyncio.Event()
    original_peek = ProductionTargetRepository.peek_current_admission_hint

    async def pause_after_hint(self, **kwargs):
        hint = await original_peek(self, **kwargs)
        hint_read.set()
        await release.wait()
        return hint

    monkeypatch.setattr(ProductionTargetRepository, "peek_current_admission_hint", pause_after_hint)

    async def resolve():
        async with concurrent_session_factory() as session:
            return await TransactionBoundTargetAuthorityResolver(session).resolve_current(
                user_id="u1", project_name="project-a", target_type="SHOT", target_id=result.shot_targets[0].target_id
            )

    reader = asyncio.create_task(resolve())
    try:
        await asyncio.wait_for(hint_read.wait(), timeout=15)
        revoke = _admit_command(
            decision_id="d-admit-consumer-revoke",
            proposal=proposal,
            profile_ref=branch.profile_ref,
            effective_map_approval_ref=map_receipt.decision_ref,
            report_refs=[report_ref_of(report)],
            expected_predecessor_id=admit.decision_id,
            action=AdaptationDecisionAction.REVOKE,
        )
        await asyncio.wait_for(
            authority.admit_screenplay_for_direction(revoke, authenticated_principal="human:anhtuan"), 15
        )
    finally:
        release.set()
    with pytest.raises(ProductionTargetIntegrityError, match="hint is stale"):
        await asyncio.wait_for(reader, timeout=15)


async def test_postgres_consumer_locks_admission_before_scene_and_shot(concurrent_session_factory: Factory) -> None:
    async with concurrent_session_factory() as probe:
        if probe.bind.dialect.name != "postgresql":
            pytest.skip("FOR UPDATE order is PostgreSQL-specific")
    admission, *_ = await _admit(concurrent_session_factory)
    result = await TakeTargetRegistrationService(concurrent_session_factory).register(_command(admission))
    async with concurrent_session_factory() as session:
        statements: list[tuple[str, object]] = []

        def capture(_connection, _cursor, statement, parameters, _context, _many):
            statements.append((statement, parameters))

        event.listen(session.bind.sync_engine, "before_cursor_execute", capture)
        try:
            current = await TransactionBoundTargetAuthorityResolver(session).resolve_current(
                user_id="u1", project_name="project-a", target_type="SHOT", target_id=result.shot_targets[0].target_id
            )
        finally:
            event.remove(session.bind.sync_engine, "before_cursor_execute", capture)
        assert current is not None
        assert "production_target_heads" in statements[0][0]
        assert "FOR UPDATE" not in statements[0][0].upper()
        locks = [(statement, parameters) for statement, parameters in statements if "FOR UPDATE" in statement.upper()]
        assert len(locks) >= 3
        assert "adaptation_heads" in locks[0][0]
        assert "production_target_heads" in locks[1][0]
        assert "production_target_heads" in locks[2][0]
        scene_parameters = locks[1][1]
        shot_parameters = locks[2][1]
        assert isinstance(scene_parameters, Mapping | tuple | list)
        assert isinstance(shot_parameters, Mapping | tuple | list)
        assert "SCENE" in (scene_parameters.values() if isinstance(scene_parameters, Mapping) else scene_parameters)
        assert "SHOT" in (shot_parameters.values() if isinstance(shot_parameters, Mapping) else shot_parameters)


async def test_postgres_target_writer_waits_for_consumer_admission_lock(
    concurrent_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with concurrent_session_factory() as probe:
        if probe.bind.dialect.name != "postgresql":
            pytest.skip("row-lock interleaving requires PostgreSQL")
    admission, *_ = await _admit(concurrent_session_factory)
    first = await TakeTargetRegistrationService(concurrent_session_factory).register(_command(admission))
    consumer_locked = asyncio.Event()
    release_consumer = asyncio.Event()
    consumer_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    writer_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    original_read = TransactionBoundApprovedScreenplayReader.get_exact_admitted
    original_enter = SqlAlchemyAdaptationUnitOfWork.__aenter__
    original_target_lock = ProductionTargetRepository.lock_target_head
    target_lock_attempted = False

    async def hold_after_admission_read(self, **kwargs):
        artifact = await original_read(self, **kwargs)
        if not consumer_pid.done():
            pid = await self._repository.session.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            consumer_pid.set_result(pid)
            consumer_locked.set()
            await release_consumer.wait()
        return artifact

    async def track_writer_pid(self):
        uow = await original_enter(self)
        pid = await self.session.scalar(text("SELECT pg_backend_pid()"))
        assert isinstance(pid, int)
        writer_pid.set_result(pid)
        return uow

    async def track_target_lock(self, **kwargs):
        nonlocal target_lock_attempted
        target_lock_attempted = True
        return await original_target_lock(self, **kwargs)

    monkeypatch.setattr(TransactionBoundApprovedScreenplayReader, "get_exact_admitted", hold_after_admission_read)
    monkeypatch.setattr(SqlAlchemyAdaptationUnitOfWork, "__aenter__", track_writer_pid)
    monkeypatch.setattr(ProductionTargetRepository, "lock_target_head", track_target_lock)

    async def resolve():
        async with concurrent_session_factory() as session:
            return await TransactionBoundTargetAuthorityResolver(session).resolve_current(
                user_id="u1", project_name="project-a", target_type="SHOT", target_id=first.shot_targets[0].target_id
            )

    consumer = asyncio.create_task(resolve())
    writer = None
    try:
        await asyncio.wait_for(consumer_locked.wait(), timeout=15)
        writer = asyncio.create_task(
            TakeTargetRegistrationService(concurrent_session_factory).register(
                _command(admission, command_id="take-after-consumer")
            )
        )
        waiting_pid = await asyncio.wait_for(writer_pid, timeout=15)
        holding_pid = await asyncio.wait_for(consumer_pid, timeout=15)

        async def blocked_by_consumer() -> bool:
            async with concurrent_session_factory() as probe:
                blockers = await probe.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiting_pid})
                return isinstance(blockers, list) and holding_pid in blockers

        async with asyncio.timeout(15):
            while not await blocked_by_consumer():
                assert not writer.done()
                await asyncio.sleep(0.02)
        assert not target_lock_attempted
    finally:
        release_consumer.set()
    current = await asyncio.wait_for(consumer, timeout=15)
    assert current is not None
    assert current.ref == first.shot_targets[0]
    assert writer is not None
    second = await asyncio.wait_for(writer, timeout=15)
    assert second.scene_targets == first.scene_targets
    assert second.shot_targets == first.shot_targets
    assert target_lock_attempted
