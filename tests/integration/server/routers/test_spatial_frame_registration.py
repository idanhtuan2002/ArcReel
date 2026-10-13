"""A derived frame is registered only against a current projected Gate C video master."""

from __future__ import annotations

import asyncio
import hashlib
import os
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
from lib.db.repositories.spatial_source import SpatialFrameReceiptRepository, _receipt_digest
from r2.contracts.host_hardening import CandidateIdentity, VerifiedCandidateObject
from r2.contracts.spatial_source import FrameDerivationReceiptV1
from r2.host_hardening.master_resolver import MasterDivergedError
from r2.m3.host_integration import GoldenAHostIntegration
from server.services import spatial_source
from server.services.spatial_source import FrameDerivationService, FrameProbe, FrameSourceConflictError
from tests.integration.server.routers.test_gates_export import PROJECT, USER, _approve_shot, _body

type Factory = async_sessionmaker[AsyncSession]


def test_parent_snapshot_rejects_bytes_that_differ_from_pinned_digest(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"changed")
    with pytest.raises(FrameSourceConflictError, match="snapshot capture"):
        spatial_source._copy_parent_verified(
            source,
            tmp_path / "snapshot.mp4",
            expected_digest="sha256:" + "0" * 64,
            expected_size=len(b"changed"),
        )


def _write_rgb_png(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=64x36:d=0.04",
            "-frames:v",
            "1",
            "-vf",
            "format=rgb24",
            "-y",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )


def test_frame_snapshot_returns_exact_verified_png_bytes(tmp_path: Path) -> None:
    source = tmp_path / "frame.png"
    _write_rgb_png(source)
    original = source.read_bytes()
    probe = spatial_source._probe_png(source)[2]
    copied = spatial_source.copy_frame_verified(
        source,
        tmp_path / "snapshot.png",
        expected_digest="sha256:" + hashlib.sha256(original).hexdigest(),
        expected_size=len(original),
        expected_probe_digest=probe,
    )
    assert copied == original


def test_frame_snapshot_rejects_changed_bytes_with_same_size(tmp_path: Path) -> None:
    source = tmp_path / "frame.png"
    _write_rgb_png(source)
    original = source.read_bytes()
    source.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with pytest.raises(FrameSourceConflictError, match="frame bytes"):
        spatial_source.copy_frame_verified(
            source,
            tmp_path / "snapshot.png",
            expected_digest="sha256:" + hashlib.sha256(original).hexdigest(),
            expected_size=len(original),
            expected_probe_digest=spatial_source._probe_png(source)[2],
        )


def test_frame_snapshot_rejects_probe_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "frame.png"
    _write_rgb_png(source)
    original = source.read_bytes()
    with pytest.raises(FrameSourceConflictError, match="frame probe"):
        spatial_source.copy_frame_verified(
            source,
            tmp_path / "snapshot.png",
            expected_digest="sha256:" + hashlib.sha256(original).hexdigest(),
            expected_size=len(original),
            expected_probe_digest="sha256:" + "0" * 64,
        )


def test_frame_snapshot_rejects_non_regular_source(tmp_path: Path) -> None:
    source = tmp_path / "frame.pipe"
    os.mkfifo(source)
    with pytest.raises(FrameSourceConflictError, match="regular file"):
        spatial_source.copy_frame_verified(
            source,
            tmp_path / "snapshot.png",
            expected_digest="sha256:" + "0" * 64,
            expected_size=1,
            expected_probe_digest="sha256:" + "0" * 64,
        )


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
async def test_replay_rejects_receipt_probe_that_disagrees_with_registered_frame(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"parent-one")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    service = FrameDerivationService(session_factory=session_factory, project_dir=project_dir)
    receipt = await service.derive(
        user_id=USER.id,
        project_name=PROJECT,
        parent_artifact_key=key,
        expected_master_version=1,
        decoded_frame_index=0,
        command_id="probe-replay",
    )
    changed = receipt.model_copy(update={"frame_probe_digest": "sha256:" + "f" * 64})
    async with session_factory() as session, session.begin():
        row = (await session.execute(select(SpatialFrameReceiptModel))).scalar_one()
        row.frame_probe_digest = changed.frame_probe_digest
        row.receipt_body_json = changed.model_dump(mode="json")
        row.receipt_digest = _receipt_digest(changed)
    with pytest.raises(FrameSourceConflictError, match="receipt candidate"):
        await service.derive(
            user_id=USER.id,
            project_name=PROJECT,
            parent_artifact_key=key,
            expected_master_version=1,
            decoded_frame_index=0,
            command_id="probe-replay",
        )


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
async def test_decode_uses_digest_verified_private_parent_snapshot(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"parent-one")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    async with session_factory() as session:
        head = await MasterAuthorityRepository(session).get_current(
            user_id=USER.id, project_name=PROJECT, artifact_key=key
        )
    assert head is not None
    original_path = Path(head.object_ref)
    white_path = project_dir / "white.mp4"
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
            str(white_path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    decoder_identity = spatial_source.ffmpeg_decoder_identity()
    expected = await asyncio.to_thread(
        spatial_source.decode_frame,
        parent_path=original_path,
        decoded_frame_index=0,
        recipe_version=spatial_source.FRAME_RECIPE_VERSION,
        decoder_identity=decoder_identity,
        output_temp=project_dir / "expected.png",
    )

    def swap_during_decode(
        *, parent_path: Path, decoded_frame_index: int, recipe_version: str, decoder_identity: str, output_temp: Path
    ) -> FrameProbe:
        assert parent_path != original_path
        old_bytes = original_path.read_bytes()
        original_path.write_bytes(white_path.read_bytes())
        try:
            return spatial_source.decode_frame(
                parent_path=parent_path,
                decoded_frame_index=decoded_frame_index,
                recipe_version=recipe_version,
                decoder_identity=decoder_identity,
                output_temp=output_temp,
            )
        finally:
            original_path.write_bytes(old_bytes)

    receipt = await FrameDerivationService(
        session_factory=session_factory, project_dir=project_dir, decoder=swap_during_decode
    ).derive(
        user_id=USER.id,
        project_name=PROJECT,
        parent_artifact_key=key,
        expected_master_version=1,
        decoded_frame_index=0,
        command_id="snapshot-parent",
    )
    assert receipt.identity.frame_content_digest == expected.content_digest


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
    with pytest.raises(FrameSourceConflictError, match="command conflicts"):
        await service.derive(**{**request, "decoded_frame_index": spatial_source.MAX_DECODED_FRAME_INDEX + 1})
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


@pytest.mark.asyncio
async def test_two_parents_racing_one_command_have_one_typed_conflict(
    concurrent_gate_client: AsyncClient, project_dir: Path, concurrent_session_factory: Factory
) -> None:
    async with concurrent_session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("cross-parent unique-key races require PostgreSQL")
    await _approve_shot(concurrent_gate_client, project_dir, "SH01", b"parent-one")
    await _approve_white_shot(concurrent_gate_client, project_dir)
    keys = [
        GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for(shot)
        for shot in ("SH01", "SH02")
    ]
    both_decoded = asyncio.Barrier(2)

    async def meet_after_decode() -> None:
        await both_decoded.wait()

    service = FrameDerivationService(
        session_factory=concurrent_session_factory, project_dir=project_dir, after_decode=meet_after_decode
    )
    results = await asyncio.gather(
        *(
            service.derive(
                user_id=USER.id,
                project_name=PROJECT,
                parent_artifact_key=key,
                expected_master_version=1,
                decoded_frame_index=0,
                command_id="cross-parent-race",
            )
            for key in keys
        ),
        return_exceptions=True,
    )
    winners = [result for result in results if isinstance(result, FrameDerivationReceiptV1)]
    losers = [result for result in results if isinstance(result, BaseException)]
    assert len(winners) == 1, results
    assert len(losers) == 1, results
    assert isinstance(losers[0], FrameSourceConflictError), results
    assert await _row_count(concurrent_session_factory, SpatialFrameReceiptModel) == 1
