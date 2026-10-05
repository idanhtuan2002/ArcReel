"""One LOCATION binding uses registered Take targets and two current approved video frames."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.production_binding import (
    ProductionBindingCommandModel,
    ProductionBindingHeadModel,
    ProductionBindingVersionModel,
)
from lib.db.repositories.production_binding import (
    ProductionBindingAlreadyCurrentError,
    ProductionBindingIntegrityError,
    ProductionBindingRepository,
)
from lib.db.repositories.spatial_source import _receipt_digest
from r2.contracts.production_binding_authority import BindingCreateCommandV1
from r2.m3.host_integration import GoldenAHostIntegration
from r2.production_intelligence.take_director import TakeDirectorAdapter
from r2.target_registry import service as target_service_module
from r2.target_registry.service import TakeTargetRegistrationService
from server.services.location_binding import LocationBindingCreationService
from server.services.spatial_frame_reader import SpatialFrameReader
from server.services.spatial_source import FrameDerivationService, FrameSourceConflictError
from tests.integration.r2.adaptation import test_screenplay_admission as admission_helpers
from tests.integration.r2.target_registry import test_take_registration as target_helpers
from tests.integration.server.routers.test_gates_export import PROJECT, USER, _approve_shot

type Factory = async_sessionmaker[AsyncSession]


async def test_create_replays_exact_two_real_frames_and_current_take_shot(
    gate_export_client: AsyncClient,
    project_dir: Path,
    session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admission_helpers, "USER", USER.id)
    monkeypatch.setattr(admission_helpers, "PROJECT", PROJECT)
    admission, *_ = await target_helpers._admit(session_factory)
    original_direct = TakeDirectorAdapter.direct

    async def direct_with_location(self, ref):
        result = await original_direct(self, ref)
        return replace(
            result,
            scenes=tuple(scene.model_copy(update={"location_ref": "location:room-1"}) for scene in result.scenes),
        )

    monkeypatch.setattr(TakeDirectorAdapter, "direct", direct_with_location)
    registered = await TakeTargetRegistrationService(session_factory).register(
        target_helpers._command(admission, user_id=USER.id, project_name=PROJECT)
    )

    derived = []
    for shot, tag in (("SH01", b"binding-parent-a"), ("SH02", b"binding-parent-b")):
        await _approve_shot(gate_export_client, project_dir, shot, tag)
        key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for(shot)
        derived.append(
            await FrameDerivationService(session_factory=session_factory, project_dir=project_dir).derive(
                user_id=USER.id,
                project_name=PROJECT,
                parent_artifact_key=key,
                expected_master_version=1,
                decoded_frame_index=0,
                command_id=f"binding-frame-{shot}",
            )
        )
    derived.sort(key=lambda receipt: receipt.frame_candidate_id)
    command = BindingCreateCommandV1.model_validate(
        {
            "user_id": USER.id,
            "project_name": PROJECT,
            "principal": USER.sub,
            "command_id": "binding-location-1",
            "expected_target_ref": registered.shot_targets[0].model_dump(mode="json"),
            "ordered_frame_receipts": [
                {"receipt_id": receipt.frame_candidate_id, "receipt_digest": _receipt_digest(receipt)}
                for receipt in derived
            ],
        }
    )
    service = LocationBindingCreationService(session_factory=session_factory, project_dir=project_dir)
    original_record = ProductionBindingRepository.record_command

    async def fail_after_staged_version(_self, **_kwargs):
        raise RuntimeError("forced after binding version and head")

    monkeypatch.setattr(ProductionBindingRepository, "record_command", fail_after_staged_version)
    with pytest.raises(RuntimeError, match="forced after binding version and head"):
        await service.create(command)
    monkeypatch.setattr(ProductionBindingRepository, "record_command", original_record)
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProductionBindingHeadModel)) == 0
        assert await session.scalar(select(func.count()).select_from(ProductionBindingVersionModel)) == 0
        assert await session.scalar(select(func.count()).select_from(ProductionBindingCommandModel)) == 0

    async with session_factory() as probe:
        is_postgres = probe.get_bind().dialect.name == "postgresql"
    if is_postgres:
        original_get_receipt = ProductionBindingRepository.get_command_receipt
        both_absent = asyncio.Event()
        absent_reads = 0

        async def hold_both_first_readers(self, **kwargs):
            nonlocal absent_reads
            found = await original_get_receipt(self, **kwargs)
            if found is None and absent_reads < 2:
                absent_reads += 1
                if absent_reads == 2:
                    both_absent.set()
                await asyncio.wait_for(both_absent.wait(), timeout=15)
            return found

        monkeypatch.setattr(ProductionBindingRepository, "get_command_receipt", hold_both_first_readers)
        first, loser = await asyncio.wait_for(asyncio.gather(service.create(command), service.create(command)), 30)
        monkeypatch.setattr(ProductionBindingRepository, "get_command_receipt", original_get_receipt)
        assert absent_reads == 2
        assert loser == first
    else:
        first = await service.create(command)
    assert first.result.binding_version == 1
    assert first.result.target_ref == registered.shot_targets[0]
    assert await service.create(command) == first

    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProductionBindingHeadModel)) == 1
        assert await session.scalar(select(func.count()).select_from(ProductionBindingVersionModel)) == 1
        assert await session.scalar(select(func.count()).select_from(ProductionBindingCommandModel)) == 1
        version = (await session.execute(select(ProductionBindingVersionModel))).scalar_one()
        assert version.binding_body_json["semantic_ref"] == "location:room-1"
        assert version.binding_body_json["asset_refs"] == [receipt.frame_candidate_id for receipt in derived]
        assert version.envelope_json["spatial_set_id"] is None

    with pytest.raises(ProductionBindingIntegrityError, match="command ID has different input"):
        await service.create(
            command.model_copy(
                update={
                    "ordered_frame_receipts": (
                        command.ordered_frame_receipts[0].model_copy(update={"receipt_digest": "sha256:" + "f" * 64}),
                        command.ordered_frame_receipts[1],
                    )
                }
            )
        )
    with pytest.raises(ProductionBindingAlreadyCurrentError, match="already current"):
        await service.create(command.model_copy(update={"command_id": "binding-location-2"}))

    frame_path = project_dir / "spatial" / "frames" / f"{derived[0].frame_candidate_id}.png"
    original_frame = frame_path.read_bytes()
    frame_path.write_bytes(original_frame + b"changed")
    with pytest.raises(FrameSourceConflictError, match="frame bytes"):
        await service.create(command)
    frame_path.write_bytes(original_frame)

    if is_postgres:
        original_read_locked = SpatialFrameReader.read_locked
        first_frame_checked = asyncio.Event()
        release_reader = asyncio.Event()
        holder_pids: list[int] = []
        writer_pids: list[int] = []

        async def pause_after_checked_frame(self, session, **kwargs):
            verified = await original_read_locked(self, session, **kwargs)
            if not holder_pids:
                pid = await session.scalar(text("SELECT pg_backend_pid()"))
                assert isinstance(pid, int)
                holder_pids.append(pid)
                first_frame_checked.set()
                await asyncio.wait_for(release_reader.wait(), timeout=15)
            return verified

        def capture_writer(
            connection: Connection, _cursor: object, statement: str, _parameters: object, _context: object, _many: bool
        ) -> None:
            if not writer_pids and statement.lstrip().upper().startswith("UPDATE MASTER_AUTHORITIES"):
                writer_pids.append(connection.connection.driver_connection.get_server_pid())

        monkeypatch.setattr(SpatialFrameReader, "read_locked", pause_after_checked_frame)
        engine = session_factory.kw["bind"]
        replay = asyncio.create_task(service.create(command))
        writer = None
        listening = False
        observed_waits: Sequence[object] = ()
        try:
            await asyncio.wait_for(first_frame_checked.wait(), timeout=15)
            assert holder_pids
            holder_pid = holder_pids[0]
            event.listen(engine.sync_engine, "before_cursor_execute", capture_writer)
            listening = True
            writer = asyncio.create_task(
                _approve_shot(gate_export_client, project_dir, "SH01", b"binding-parent-a-next")
            )
            async with asyncio.timeout(5):
                while True:
                    async with session_factory() as observer:
                        observed_waits = list(
                            (
                                await observer.execute(
                                    text(
                                        "SELECT pid, wait_event_type, pg_blocking_pids(pid), left(query, 90) "
                                        "FROM pg_stat_activity WHERE datname = current_database() "
                                        "AND wait_event_type = 'Lock' ORDER BY pid"
                                    )
                                )
                            ).all()
                        )
                    if writer_pids:
                        async with session_factory() as observer:
                            blockers = await observer.scalar(
                                text("SELECT pg_blocking_pids(:pid)"), {"pid": writer_pids[0]}
                            )
                        if holder_pid in blockers:
                            assert writer_pids[0] != holder_pid
                            assert not writer.done()
                            break
                    if writer.done():
                        raise AssertionError("Gate C writer did not wait on the binding-held M7 row")
                    await asyncio.sleep(0.01)
        except TimeoutError as exc:
            raise AssertionError(f"writer SQL not observed; waits={observed_waits}, writer_pids={writer_pids}") from exc
        finally:
            release_reader.set()
            if listening:
                event.remove(engine.sync_engine, "before_cursor_execute", capture_writer)
            monkeypatch.setattr(SpatialFrameReader, "read_locked", original_read_locked)
            if writer is None:
                await asyncio.wait_for(asyncio.gather(replay, return_exceptions=True), timeout=15)
            else:
                await asyncio.wait_for(asyncio.gather(replay, writer, return_exceptions=True), timeout=15)
        assert await asyncio.wait_for(replay, timeout=15) == first
        assert writer is not None
        await asyncio.wait_for(writer, timeout=15)
    else:
        await _approve_shot(gate_export_client, project_dir, "SH01", b"binding-parent-a-next")
    with pytest.raises(FrameSourceConflictError, match="superseded"):
        await service.create(command)

    monkeypatch.setattr(target_service_module, "TAKE_DERIVATION_VERSION", "r2-take-director-v2-test")
    advanced = await TakeTargetRegistrationService(session_factory).register(
        target_helpers._command(admission, command_id="take-binding-target-next", user_id=USER.id, project_name=PROJECT)
    )
    assert advanced.shot_targets[0].registry_version == 2
    with pytest.raises(ProductionBindingIntegrityError, match="target or Scene location is stale"):
        await service.create(command)
