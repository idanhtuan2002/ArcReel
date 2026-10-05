"""A frame receipt is usable only while its parent and PNG bytes remain current."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine, Mapping
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.artifact_manifest import MANIFEST_FILENAME, ArtifactKey, ProjectArtifactManifestAdapter
from lib.db.models.host_hardening import CandidateObjectModel, MasterAuthorityModel, MasterHeadVersionModel
from lib.db.repositories.host_hardening import MasterAuthorityRepository
from lib.db.repositories.spatial_source import _receipt_digest
from r2.m3.host_integration import GoldenAHostIntegration
from server.services import master_authority, spatial_frame_reader
from server.services.master_authority import MasterSupersededError, serialized_artifacts
from server.services.spatial_frame_reader import SpatialFrameReader
from server.services.spatial_source import FrameDerivationService, FrameSourceConflictError
from tests.integration.server.routers.test_gates_export import PROJECT, USER, _approve_shot

type Factory = async_sessionmaker[AsyncSession]


async def _start_blocked_master_writer(factory: Factory, request: Coroutine[Any, Any, str]) -> asyncio.Task[str]:
    engine = factory.kw["bind"]
    writer_pids: list[int] = []

    def capture_writer(
        connection: Connection, _cursor: object, statement: str, _parameters: object, _context: object, _many: bool
    ) -> None:
        if not writer_pids and statement.lstrip().upper().startswith("UPDATE MASTER_AUTHORITIES"):
            writer_pids.append(connection.connection.driver_connection.get_server_pid())

    event.listen(engine.sync_engine, "before_cursor_execute", capture_writer)
    try:
        approval = asyncio.create_task(request)
        async with asyncio.timeout(10):
            while True:
                if writer_pids:
                    async with factory() as observer:
                        blocked = (
                            await observer.execute(
                                text(
                                    "SELECT pid FROM pg_stat_activity "
                                    "WHERE pid = :writer_pid AND datname = current_database() "
                                    "AND wait_event_type = 'Lock' "
                                    "AND cardinality(pg_blocking_pids(pid)) > 0"
                                ),
                                {"writer_pid": writer_pids[0]},
                            )
                        ).first()
                    if blocked is not None:
                        assert not approval.done()
                        return approval
                if approval.done():
                    raise AssertionError("Gate C approval finished without waiting on the master row")
                await asyncio.sleep(0.01)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture_writer)


@pytest.mark.asyncio
async def test_reader_returns_verified_frame_and_rejects_wrong_digest(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"reader-parent")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    receipt = await FrameDerivationService(session_factory=session_factory, project_dir=project_dir).derive(
        user_id=USER.id,
        project_name=PROJECT,
        parent_artifact_key=key,
        expected_master_version=1,
        decoded_frame_index=0,
        command_id="reader-frame",
    )
    reader = SpatialFrameReader(session_factory=session_factory, project_dir=project_dir)
    verified = await reader.read_current(
        user_id=USER.id,
        project_name=PROJECT,
        receipt_id=receipt.frame_candidate_id,
        expected_receipt_digest=_receipt_digest(receipt),
    )
    assert verified.receipt == receipt
    assert verified.receipt_digest == _receipt_digest(receipt)
    assert verified.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    with pytest.raises(FrameSourceConflictError, match="digest"):
        await reader.read_current(
            user_id=USER.id,
            project_name=PROJECT,
            receipt_id=receipt.frame_candidate_id,
            expected_receipt_digest="sha256:" + "0" * 64,
        )
    with pytest.raises(FrameSourceConflictError, match="scope"):
        await reader.read_current(
            user_id=USER.id,
            project_name="another-project",
            receipt_id=receipt.frame_candidate_id,
            expected_receipt_digest=_receipt_digest(receipt),
        )
    async with serialized_artifacts(
        session_factory, user_id=USER.id, project_name=PROJECT, artifact_keys=(key,)
    ) as session:
        locked = await reader.read_locked(
            session,
            user_id=USER.id,
            project_name=PROJECT,
            receipt_id=receipt.frame_candidate_id,
            expected_receipt_digest=_receipt_digest(receipt),
            expected_parent_artifact_key=key,
        )
        assert locked.png_bytes == verified.png_bytes
        with pytest.raises(FrameSourceConflictError, match="locked artifact key"):
            await reader.read_locked(
                session,
                user_id=USER.id,
                project_name=PROJECT,
                receipt_id=receipt.frame_candidate_id,
                expected_receipt_digest=_receipt_digest(receipt),
                expected_parent_artifact_key="different-parent",
            )


@pytest.mark.asyncio
async def test_reader_refuses_superseded_parent_and_changed_png(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"reader-parent")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    receipt = await FrameDerivationService(session_factory=session_factory, project_dir=project_dir).derive(
        user_id=USER.id,
        project_name=PROJECT,
        parent_artifact_key=key,
        expected_master_version=1,
        decoded_frame_index=0,
        command_id="reader-frame",
    )
    reader = SpatialFrameReader(session_factory=session_factory, project_dir=project_dir)
    frame_path = project_dir / "spatial" / "frames" / f"{receipt.frame_candidate_id}.png"
    frame_path.write_bytes(frame_path.read_bytes() + b"changed")
    with pytest.raises(FrameSourceConflictError, match="frame bytes"):
        await reader.read_current(
            user_id=USER.id,
            project_name=PROJECT,
            receipt_id=receipt.frame_candidate_id,
            expected_receipt_digest=_receipt_digest(receipt),
        )
    await _approve_shot(gate_export_client, project_dir, "SH01", b"reader-parent-next")
    with pytest.raises(FrameSourceConflictError, match="superseded"):
        await reader.read_current(
            user_id=USER.id,
            project_name=PROJECT,
            receipt_id=receipt.frame_candidate_id,
            expected_receipt_digest=_receipt_digest(receipt),
        )


@pytest.mark.asyncio
async def test_reader_refuses_candidate_metadata_mismatch(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"reader-parent")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    receipt = await FrameDerivationService(session_factory=session_factory, project_dir=project_dir).derive(
        user_id=USER.id,
        project_name=PROJECT,
        parent_artifact_key=key,
        expected_master_version=1,
        decoded_frame_index=0,
        command_id="reader-frame",
    )
    async with session_factory() as session, session.begin():
        row = (
            await session.execute(
                select(CandidateObjectModel).where(CandidateObjectModel.candidate_id == receipt.frame_candidate_id)
            )
        ).scalar_one()
        row.byte_size += 1
    with pytest.raises(FrameSourceConflictError, match="frame candidate"):
        await SpatialFrameReader(session_factory=session_factory, project_dir=project_dir).read_current(
            user_id=USER.id,
            project_name=PROJECT,
            receipt_id=receipt.frame_candidate_id,
            expected_receipt_digest=_receipt_digest(receipt),
        )


@pytest.mark.asyncio
async def test_reader_refuses_missing_parent_projection(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"reader-parent")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    receipt = await FrameDerivationService(session_factory=session_factory, project_dir=project_dir).derive(
        user_id=USER.id,
        project_name=PROJECT,
        parent_artifact_key=key,
        expected_master_version=1,
        decoded_frame_index=0,
        command_id="reader-frame",
    )
    assert ProjectArtifactManifestAdapter(project_dir).delete_entry(ArtifactKey.decode(key))
    with pytest.raises(FrameSourceConflictError, match="projection"):
        await SpatialFrameReader(session_factory=session_factory, project_dir=project_dir).read_current(
            user_id=USER.id,
            project_name=PROJECT,
            receipt_id=receipt.frame_candidate_id,
            expected_receipt_digest=_receipt_digest(receipt),
        )


@pytest.mark.asyncio
async def test_reader_normalizes_malformed_parent_manifest(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"reader-parent")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    receipt = await FrameDerivationService(session_factory=session_factory, project_dir=project_dir).derive(
        user_id=USER.id,
        project_name=PROJECT,
        parent_artifact_key=key,
        expected_master_version=1,
        decoded_frame_index=0,
        command_id="reader-frame",
    )
    (project_dir / MANIFEST_FILENAME).write_text("{", encoding="utf-8")
    with pytest.raises(FrameSourceConflictError, match="projection"):
        await SpatialFrameReader(session_factory=session_factory, project_dir=project_dir).read_current(
            user_id=USER.id,
            project_name=PROJECT,
            receipt_id=receipt.frame_candidate_id,
            expected_receipt_digest=_receipt_digest(receipt),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["missing", "escape"])
async def test_reader_normalizes_missing_or_unsafe_parent_file(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, mutation: str
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"reader-parent")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    receipt = await FrameDerivationService(session_factory=session_factory, project_dir=project_dir).derive(
        user_id=USER.id,
        project_name=PROJECT,
        parent_artifact_key=key,
        expected_master_version=1,
        decoded_frame_index=0,
        command_id="reader-frame",
    )
    async with session_factory() as session:
        head = await MasterAuthorityRepository(session).get_current(
            user_id=USER.id, project_name=PROJECT, artifact_key=key
        )
    assert head is not None
    parent_path = Path(head.object_ref)
    assert await asyncio.to_thread(parent_path.is_file)
    await asyncio.to_thread(parent_path.unlink)
    if mutation == "escape":
        outside = project_dir.parent / "outside-parent.mp4"
        await asyncio.to_thread(outside.write_bytes, b"outside")
        await asyncio.to_thread(parent_path.symlink_to, outside)
    with pytest.raises(FrameSourceConflictError, match="parent media"):
        await SpatialFrameReader(session_factory=session_factory, project_dir=project_dir).read_current(
            user_id=USER.id,
            project_name=PROJECT,
            receipt_id=receipt.frame_candidate_id,
            expected_receipt_digest=_receipt_digest(receipt),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["frame_candidate", "parent_candidate", "parent_head"])
async def test_reader_normalizes_malformed_persisted_metadata(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, corruption: str
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"reader-parent")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    receipt = await FrameDerivationService(session_factory=session_factory, project_dir=project_dir).derive(
        user_id=USER.id,
        project_name=PROJECT,
        parent_artifact_key=key,
        expected_master_version=1,
        decoded_frame_index=0,
        command_id="reader-frame",
    )
    async with session_factory() as session, session.begin():
        if corruption == "parent_head":
            row = (
                await session.execute(
                    select(MasterHeadVersionModel).where(
                        MasterHeadVersionModel.artifact_key == key,
                        MasterHeadVersionModel.master_version == 1,
                    )
                )
            ).scalar_one()
            row.object_ref = ""
        else:
            candidate_id = (
                receipt.frame_candidate_id if corruption == "frame_candidate" else receipt.identity.parent_candidate_id
            )
            row = (
                await session.execute(
                    select(CandidateObjectModel).where(CandidateObjectModel.candidate_id == candidate_id)
                )
            ).scalar_one()
            row.object_ref = ""
    with pytest.raises(FrameSourceConflictError, match="metadata"):
        await SpatialFrameReader(session_factory=session_factory, project_dir=project_dir).read_current(
            user_id=USER.id,
            project_name=PROJECT,
            receipt_id=receipt.frame_candidate_id,
            expected_receipt_digest=_receipt_digest(receipt),
        )


@pytest.mark.asyncio
async def test_caller_session_lock_blocks_parent_approval_on_postgres(
    concurrent_gate_client: AsyncClient, project_dir: Path, concurrent_session_factory: Factory
) -> None:
    async with concurrent_session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("row-lock interleaving requires PostgreSQL")
    await _approve_shot(concurrent_gate_client, project_dir, "SH01", b"reader-parent")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    receipt = await FrameDerivationService(session_factory=concurrent_session_factory, project_dir=project_dir).derive(
        user_id=USER.id,
        project_name=PROJECT,
        parent_artifact_key=key,
        expected_master_version=1,
        decoded_frame_index=0,
        command_id="reader-frame",
    )
    reader = SpatialFrameReader(session_factory=concurrent_session_factory, project_dir=project_dir)
    async with concurrent_session_factory() as session, session.begin():
        with pytest.raises(MasterSupersededError, match="current master"):
            await master_authority.lock_current_master_rows(
                session, user_id="foreign", project_name=PROJECT, artifact_keys=(key,)
            )
        locked = await master_authority.lock_current_master_rows(
            session, user_id=USER.id, project_name=PROJECT, artifact_keys=(key,)
        )
        assert locked == ((key, 1),)
        verified = await reader.read_locked(
            session,
            user_id=USER.id,
            project_name=PROJECT,
            receipt_id=receipt.frame_candidate_id,
            expected_receipt_digest=_receipt_digest(receipt),
            expected_parent_artifact_key=key,
        )
        approval = await _start_blocked_master_writer(
            concurrent_session_factory, _approve_shot(concurrent_gate_client, project_dir, "SH01", b"reader-next")
        )
        assert verified.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    await asyncio.wait_for(approval, timeout=10)
    with pytest.raises(FrameSourceConflictError, match="superseded"):
        await reader.read_current(
            user_id=USER.id,
            project_name=PROJECT,
            receipt_id=receipt.frame_candidate_id,
            expected_receipt_digest=_receipt_digest(receipt),
        )


@pytest.mark.asyncio
async def test_caller_session_lock_rejects_missing_master_without_genesis(
    session_factory: Factory,
) -> None:
    async with session_factory() as session, session.begin():
        with pytest.raises(MasterSupersededError, match="current master"):
            await master_authority.lock_current_master_rows(
                session, user_id=USER.id, project_name=PROJECT, artifact_keys=("missing-video",)
            )
        assert (await session.get(MasterAuthorityModel, (USER.id, PROJECT, "missing-video"))) is None


@pytest.mark.asyncio
async def test_caller_session_locks_distinct_master_keys_in_sorted_order(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"first-parent")
    await _approve_shot(gate_export_client, project_dir, "SH02", b"second-parent")
    host = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1)
    first_key = host.artifact_key_for("SH01")
    second_key = host.artifact_key_for("SH02")
    ordered = tuple(sorted((first_key, second_key)))
    observed: list[str] = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("UPDATE MASTER_AUTHORITIES"):
            values = parameters.values() if isinstance(parameters, Mapping) else parameters
            observed.extend(key for key in ordered if key in values)

    async with session_factory() as session, session.begin():
        event.listen(session.bind.sync_engine, "before_cursor_execute", capture)
        try:
            locked = await master_authority.lock_current_master_rows(
                session, user_id=USER.id, project_name=PROJECT, artifact_keys=(second_key, first_key, second_key)
            )
        finally:
            event.remove(session.bind.sync_engine, "before_cursor_execute", capture)
    assert locked == tuple((key, 1) for key in ordered)
    assert observed == list(ordered)


@pytest.mark.asyncio
async def test_current_reader_holds_parent_lock_through_frame_snapshot_on_postgres(
    concurrent_gate_client: AsyncClient,
    project_dir: Path,
    concurrent_session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with concurrent_session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("row-lock interleaving requires PostgreSQL")
    await _approve_shot(concurrent_gate_client, project_dir, "SH01", b"reader-parent")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    receipt = await FrameDerivationService(session_factory=concurrent_session_factory, project_dir=project_dir).derive(
        user_id=USER.id,
        project_name=PROJECT,
        parent_artifact_key=key,
        expected_master_version=1,
        decoded_frame_index=0,
        command_id="reader-frame",
    )
    entered = threading.Event()
    release = threading.Event()
    original_copy = spatial_frame_reader.copy_frame_verified

    def held_copy(
        source_path: Path,
        snapshot_path: Path,
        *,
        expected_digest: str,
        expected_size: int,
        expected_probe_digest: str,
    ) -> bytes:
        result = original_copy(
            source_path,
            snapshot_path,
            expected_digest=expected_digest,
            expected_size=expected_size,
            expected_probe_digest=expected_probe_digest,
        )
        entered.set()
        if not release.wait(timeout=10):
            raise AssertionError("reader snapshot barrier timed out")
        return result

    monkeypatch.setattr(spatial_frame_reader, "copy_frame_verified", held_copy)
    reader = SpatialFrameReader(session_factory=concurrent_session_factory, project_dir=project_dir)
    reading = asyncio.create_task(
        reader.read_current(
            user_id=USER.id,
            project_name=PROJECT,
            receipt_id=receipt.frame_candidate_id,
            expected_receipt_digest=_receipt_digest(receipt),
        )
    )
    approval: asyncio.Task[str] | None = None
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        approval = await _start_blocked_master_writer(
            concurrent_session_factory, _approve_shot(concurrent_gate_client, project_dir, "SH01", b"reader-next")
        )
    finally:
        release.set()
    verified = await asyncio.wait_for(reading, timeout=10)
    assert verified.receipt == receipt
    assert approval is not None
    await asyncio.wait_for(approval, timeout=10)
    with pytest.raises(FrameSourceConflictError, match="superseded"):
        await reader.read_current(
            user_id=USER.id,
            project_name=PROJECT,
            receipt_id=receipt.frame_candidate_id,
            expected_receipt_digest=_receipt_digest(receipt),
        )
