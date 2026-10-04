"""A frame receipt is usable only while its parent and PNG bytes remain current."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.artifact_manifest import ArtifactKey, ProjectArtifactManifestAdapter
from lib.db.models.host_hardening import CandidateObjectModel
from lib.db.repositories.spatial_source import _receipt_digest
from r2.m3.host_integration import GoldenAHostIntegration
from server.services.master_authority import serialized_artifacts
from server.services.spatial_frame_reader import SpatialFrameReader
from server.services.spatial_source import FrameDerivationService, FrameSourceConflictError
from tests.integration.server.routers.test_gates_export import PROJECT, USER, _approve_shot

type Factory = async_sessionmaker[AsyncSession]


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
