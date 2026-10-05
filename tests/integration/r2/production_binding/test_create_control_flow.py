"""The first binding command owns one SQL transaction and rechecks its sources on replay."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.production_binding import (
    ProductionBindingCommandModel,
    ProductionBindingHeadModel,
    ProductionBindingVersionModel,
)
from lib.db.repositories.production_binding import ProductionBindingIntegrityError
from lib.db.repositories.production_target import VerifiedTargetVersion
from lib.db.repositories.spatial_source import _receipt_digest
from r2.contracts.adaptation import AdmittedScreenplayRef
from r2.contracts.production import SceneSpec, ShotSpecV2
from r2.contracts.production_binding_authority import BindingCreateCommandV1
from r2.contracts.production_target import TargetVersionRef
from r2.contracts.spatial_source import FrameDerivationReceiptV1, FrameIdentityV1
from server.services import location_binding as binding_service
from server.services.spatial_frame_reader import VerifiedSpatialFrame

type Factory = async_sessionmaker[AsyncSession]
FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/r2/m8c_target_registry_vectors.json"


def _cases() -> dict[str, dict[str, Any]]:
    return {case["name"]: case for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]}


def _target() -> VerifiedTargetVersion:
    cases = _cases()
    admission = AdmittedScreenplayRef.model_validate(cases["scene_version_v1"]["body"]["admitted_screenplay_ref"])
    scene_body = cases["scene_body_v1"]["body"]["target"] | {"location_ref": "location:room-1"}
    scene = VerifiedTargetVersion(
        ref=TargetVersionRef(
            target_type="SCENE",
            target_id="scene-1",
            registry_version=1,
            version_digest=cases["scene_version_v1"]["digest"],
        ),
        target=SceneSpec.model_validate(scene_body),
        admitted_screenplay_ref=admission,
        take_derivation_version="test",
    )
    return VerifiedTargetVersion(
        ref=TargetVersionRef(
            target_type="SHOT",
            target_id="scene-1-TAKE-1",
            registry_version=1,
            version_digest=cases["shot_version_v1"]["digest"],
        ),
        target=ShotSpecV2.model_validate(cases["shot_body_v1"]["body"]["target"]),
        admitted_screenplay_ref=admission,
        take_derivation_version="test",
        scene=scene,
    )


def _frames() -> tuple[VerifiedSpatialFrame, VerifiedSpatialFrame]:
    frames = []
    for letter in "ab":
        identity = FrameIdentityV1(
            user_id="u1",
            project_name="project-a",
            parent_artifact_key=f"video:room-{letter}",
            parent_master_version=1,
            parent_candidate_id=f"candidate-{letter}",
            parent_content_digest="sha256:" + letter * 64,
            decoded_frame_index=0,
            recipe_version="frame-v1",
            decoder_identity="ffmpeg-7",
            frame_content_digest="sha256:" + ("1" if letter == "a" else "2") * 64,
        )
        receipt = FrameDerivationReceiptV1(
            identity=identity,
            frame_candidate_id=identity.candidate_id,
            frame_byte_size=128,
            frame_probe_digest="sha256:" + "3" * 64,
            created_at=datetime.now(UTC),
            command_digest="sha256:" + "4" * 64,
        )
        frames.append(VerifiedSpatialFrame(receipt=receipt, receipt_digest=_receipt_digest(receipt), png_bytes=b"PNG"))
    return tuple(sorted(frames, key=lambda frame: frame.receipt.frame_candidate_id))


async def test_binding_create_and_replay_recheck_target_and_frames(
    session_factory: Factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session_factory() as probe:
        if probe.get_bind().dialect.name == "postgresql":
            pytest.skip("control-flow fixture substitutes target and source authority; PostgreSQL needs real FK rows")
    target = _target()
    frames = _frames()
    receipts = {frame.receipt.frame_candidate_id: frame for frame in frames}
    calls = {"target": 0, "frame": 0, "lock": 0}

    async def resolve_current(_self, **_kwargs):
        calls["target"] += 1
        return target

    async def get_exact(_self, *, receipt_id: str, **_kwargs):
        return receipts[receipt_id].receipt

    async def lock_rows(_session, **kwargs):
        calls["lock"] += 1
        assert kwargs["artifact_keys"] == tuple(frame.receipt.identity.parent_artifact_key for frame in frames)
        return tuple((key, 1) for key in sorted(kwargs["artifact_keys"]))

    async def read_locked(_self, _session, *, receipt_id: str, **_kwargs):
        calls["frame"] += 1
        return receipts[receipt_id]

    monkeypatch.setattr(binding_service.TransactionBoundTargetAuthorityResolver, "resolve_current", resolve_current)
    monkeypatch.setattr(binding_service.SpatialFrameReceiptRepository, "get_exact", get_exact)
    monkeypatch.setattr(binding_service, "lock_current_master_rows", lock_rows)
    monkeypatch.setattr(binding_service.SpatialFrameReader, "read_locked", read_locked)
    command = BindingCreateCommandV1(
        user_id="u1",
        project_name="project-a",
        principal="human:anhtuan",
        command_id="location-1",
        expected_target_ref=target.ref,
        ordered_frame_receipts=tuple(
            {"receipt_id": frame.receipt.frame_candidate_id, "receipt_digest": frame.receipt_digest} for frame in frames
        ),
    )
    service = binding_service.LocationBindingCreationService(session_factory=session_factory, project_dir=tmp_path)
    first = await service.create(command)
    assert first.result.binding_version == 1
    assert first.result.target_ref == target.ref
    assert await service.create(command) == first
    assert calls == {"target": 2, "frame": 4, "lock": 2}
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProductionBindingHeadModel)) == 1
        assert await session.scalar(select(func.count()).select_from(ProductionBindingVersionModel)) == 1
        assert await session.scalar(select(func.count()).select_from(ProductionBindingCommandModel)) == 1
    with pytest.raises(ProductionBindingIntegrityError, match="already current"):
        await service.create(command.model_copy(update={"command_id": "location-2"}))
