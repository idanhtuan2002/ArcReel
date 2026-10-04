"""A derived frame is registered only against a current projected Gate C video master."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.artifact_manifest import ArtifactKey, ProjectArtifactManifestAdapter
from lib.db.models.host_hardening import CandidateObjectModel
from lib.db.models.spatial_source import SpatialFrameReceiptModel
from lib.db.repositories.host_hardening import MasterAuthorityRepository
from lib.db.repositories.spatial_source import SpatialFrameReceiptRepository
from r2.contracts.host_hardening import CandidateIdentity, VerifiedCandidateObject
from r2.contracts.spatial_source import FrameDerivationReceiptV1
from r2.host_hardening.master_resolver import MasterDivergedError
from r2.m3.host_integration import GoldenAHostIntegration
from server.services import spatial_source
from server.services.spatial_source import FrameDerivationService, FrameProbe, FrameSourceConflictError
from tests.integration.server.routers.test_gates_export import PROJECT, USER, _approve_shot, _body

type Factory = async_sessionmaker[AsyncSession]


async def _row_count(factory: Factory, model: type) -> int:
    async with factory() as session:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def _approve_white_shot(client: AsyncClient, project_dir: Path) -> None:
    path = project_dir / "production" / "SH02.mp4"
    await asyncio.to_thread(
        subprocess.run,
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=64x36:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    response = await client.post(f"/api/v1/projects/{PROJECT}/gates/final-cut", json=_body("SH02", path.read_bytes()))
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_two_approved_video_masters_register_distinct_frame_receipts(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"parent-one")
    await _approve_white_shot(gate_export_client, project_dir)
    keys = {
        shot: GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for(shot)
        for shot in ("SH01", "SH02")
    }
    baseline_candidates = await _row_count(session_factory, CandidateObjectModel)
    service = FrameDerivationService(session_factory=session_factory, project_dir=project_dir)
    master = await service.derive(
        user_id=USER.id,
        project_name=PROJECT,
        parent_artifact_key=keys["SH01"],
        expected_master_version=1,
        decoded_frame_index=0,
        command_id="derive-master",
    )
    reverse = await service.derive(
        user_id=USER.id,
        project_name=PROJECT,
        parent_artifact_key=keys["SH02"],
        expected_master_version=1,
        decoded_frame_index=0,
        command_id="derive-reverse",
    )
    assert master.frame_candidate_id != reverse.frame_candidate_id
    assert master.identity.frame_content_digest != reverse.identity.frame_content_digest
    assert master.identity.parent_master_version == reverse.identity.parent_master_version == 1
    assert await _row_count(session_factory, SpatialFrameReceiptModel) == 2
    assert await _row_count(session_factory, CandidateObjectModel) == baseline_candidates + 2

    replay = await service.derive(
        user_id=USER.id,
        project_name=PROJECT,
        parent_artifact_key=keys["SH01"],
        expected_master_version=1,
        decoded_frame_index=0,
        command_id="derive-master",
    )
    assert replay == master
    assert await _row_count(session_factory, SpatialFrameReceiptModel) == 2


@pytest.mark.asyncio
async def test_wrong_project_leaves_no_frame_rows(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"parent-one")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    service = FrameDerivationService(session_factory=session_factory, project_dir=project_dir)
    with pytest.raises((ValueError, RuntimeError)):
        await service.derive(
            user_id=USER.id,
            project_name="another-project",
            parent_artifact_key=key,
            expected_master_version=1,
            decoded_frame_index=0,
            command_id="wrong-project",
        )
    assert await _row_count(session_factory, SpatialFrameReceiptModel) == 0


@pytest.mark.asyncio
async def test_missing_master_projection_leaves_no_frame_rows(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"parent-one")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    baseline = await _row_count(session_factory, CandidateObjectModel)
    assert ProjectArtifactManifestAdapter(project_dir).delete_entry(ArtifactKey.decode(key))
    with pytest.raises(MasterDivergedError):
        await FrameDerivationService(session_factory=session_factory, project_dir=project_dir).derive(
            user_id=USER.id,
            project_name=PROJECT,
            parent_artifact_key=key,
            expected_master_version=1,
            decoded_frame_index=0,
            command_id="no-projection",
        )
    assert await _row_count(session_factory, SpatialFrameReceiptModel) == 0
    assert await _row_count(session_factory, CandidateObjectModel) == baseline


@pytest.mark.asyncio
async def test_parent_advance_after_decode_refuses_registration(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"parent-one")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    baseline = await _row_count(session_factory, CandidateObjectModel)

    async def advance_master() -> None:
        await _approve_shot(gate_export_client, project_dir, "SH01", b"parent-two")

    service = FrameDerivationService(
        session_factory=session_factory, project_dir=project_dir, after_decode=advance_master
    )
    with pytest.raises(FrameSourceConflictError, match="superseded"):
        await service.derive(
            user_id=USER.id,
            project_name=PROJECT,
            parent_artifact_key=key,
            expected_master_version=1,
            decoded_frame_index=0,
            command_id="stale-parent",
        )
    assert await _row_count(session_factory, SpatialFrameReceiptModel) == 0
    assert await _row_count(session_factory, CandidateObjectModel) == baseline + 1


@pytest.mark.asyncio
async def test_parent_bytes_changed_after_decode_refuse_registration(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"parent-one")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    baseline = await _row_count(session_factory, CandidateObjectModel)

    async def alter_parent() -> None:
        async with session_factory() as session:
            head = await MasterAuthorityRepository(session).get_current(
                user_id=USER.id, project_name=PROJECT, artifact_key=key
            )
        assert head is not None
        await asyncio.to_thread(Path(head.object_ref).write_bytes, b"changed-parent")

    service = FrameDerivationService(
        session_factory=session_factory, project_dir=project_dir, after_decode=alter_parent
    )
    with pytest.raises(FrameSourceConflictError, match="parent video bytes"):
        await service.derive(
            user_id=USER.id,
            project_name=PROJECT,
            parent_artifact_key=key,
            expected_master_version=1,
            decoded_frame_index=0,
            command_id="changed-parent",
        )
    assert await _row_count(session_factory, SpatialFrameReceiptModel) == 0
    assert await _row_count(session_factory, CandidateObjectModel) == baseline


@pytest.mark.asyncio
async def test_changed_published_frame_bytes_refuse_registration(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"parent-one")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    baseline = await _row_count(session_factory, CandidateObjectModel)
    real_publish = spatial_source.publish_frame

    def corrupted_publish(
        *, temp: Path, final: Path, media_root: Path, identity: CandidateIdentity, probe: FrameProbe
    ) -> VerifiedCandidateObject:
        candidate = real_publish(temp=temp, final=final, media_root=media_root, identity=identity, probe=probe)
        Path(candidate.object_ref).write_bytes(b"changed-after-publication")
        return candidate

    with pytest.raises(FrameSourceConflictError, match="published frame bytes"):
        await FrameDerivationService(
            session_factory=session_factory, project_dir=project_dir, publisher=corrupted_publish
        ).derive(
            user_id=USER.id,
            project_name=PROJECT,
            parent_artifact_key=key,
            expected_master_version=1,
            decoded_frame_index=0,
            command_id="changed-frame",
        )
    assert await _row_count(session_factory, SpatialFrameReceiptModel) == 0
    assert await _row_count(session_factory, CandidateObjectModel) == baseline


@pytest.mark.asyncio
async def test_command_conflict_and_crash_after_file_publication(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"parent-one")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    service = FrameDerivationService(session_factory=session_factory, project_dir=project_dir)
    baseline = await _row_count(session_factory, CandidateObjectModel)
    original_insert = SpatialFrameReceiptRepository.insert
    calls = 0

    async def fail_first_insert(
        self: SpatialFrameReceiptRepository, *, command_id: str, receipt: FrameDerivationReceiptV1
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("crash-after-file-link")
        await original_insert(self, command_id=command_id, receipt=receipt)

    monkeypatch.setattr(SpatialFrameReceiptRepository, "insert", fail_first_insert)
    request: dict[str, Any] = {
        "user_id": USER.id,
        "project_name": PROJECT,
        "parent_artifact_key": key,
        "expected_master_version": 1,
        "decoded_frame_index": 0,
        "command_id": "crash-retry",
    }
    with pytest.raises(OSError, match="crash-after-file-link"):
        await service.derive(**request)
    assert await _row_count(session_factory, SpatialFrameReceiptModel) == 0
    assert await _row_count(session_factory, CandidateObjectModel) == baseline
    receipt = await service.derive(**request)
    assert await _row_count(session_factory, SpatialFrameReceiptModel) == 1
    assert await _row_count(session_factory, CandidateObjectModel) == baseline + 1

    with pytest.raises(FrameSourceConflictError, match="command conflicts"):
        await service.derive(**{**request, "decoded_frame_index": 1})
    assert await _row_count(session_factory, SpatialFrameReceiptModel) == 1
    assert receipt.frame_candidate_id.startswith("m8f:")


@pytest.mark.asyncio
async def test_two_writers_same_frame_command_converge_on_one_receipt(
    concurrent_gate_client: AsyncClient, project_dir: Path, concurrent_session_factory: Factory
) -> None:
    await _approve_shot(concurrent_gate_client, project_dir, "SH01", b"parent-one")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    both_decoded = asyncio.Barrier(2)

    async def meet_after_decode() -> None:
        await both_decoded.wait()

    service = FrameDerivationService(
        session_factory=concurrent_session_factory, project_dir=project_dir, after_decode=meet_after_decode
    )
    request: dict[str, Any] = {
        "user_id": USER.id,
        "project_name": PROJECT,
        "parent_artifact_key": key,
        "expected_master_version": 1,
        "decoded_frame_index": 0,
        "command_id": "concurrent-same-frame",
    }
    first, second = await asyncio.gather(service.derive(**request), service.derive(**request))
    assert first == second
    assert await _row_count(concurrent_session_factory, SpatialFrameReceiptModel) == 1
