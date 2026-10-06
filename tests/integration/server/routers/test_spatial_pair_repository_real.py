"""Pair repository writes use real Take, binding and frame foreign keys."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.spatial_pair import SpatialPairDecisionModel, SpatialPairHeadModel
from lib.db.repositories.production_binding import ProductionBindingRepository
from lib.db.repositories.spatial_pair import SpatialPairRepository
from lib.db.repositories.spatial_source import _receipt_digest
from r2.contracts.production_binding_authority import BindingCreateCommandV1
from r2.contracts.spatial_pair import (
    PairAuthorizationV1,
    PairDecisionCommandV1,
    PairDecisionResultV1,
    PairDecisionV1,
)
from r2.m3.host_integration import GoldenAHostIntegration
from r2.production_intelligence.take_director import TakeDirectorAdapter
from r2.spatial_pair.digests import (
    pair_authorization_digest,
    pair_command_digest,
    pair_decision_digest,
    scoped_pair_id,
)
from r2.target_registry.service import TakeTargetRegistrationService
from server.services.location_binding import LocationBindingCreationService
from server.services.location_binding_snapshot import CurrentLocationBindingSnapshotReader
from server.services.spatial_pair_decision import PairAuthorizationDeniedError, SpatialPairDecisionService
from server.services.spatial_source import FrameDerivationService, FrameSourceConflictError
from tests.integration.r2.adaptation import test_screenplay_admission as admission_helpers
from tests.integration.r2.target_registry import test_take_registration as target_helpers
from tests.integration.server.routers.test_gates_export import PROJECT, USER, _approve_shot

type Factory = async_sessionmaker[AsyncSession]


async def test_pair_repository_accepts_real_foreign_keys_and_replays_result(
    gate_export_client: AsyncClient,
    project_dir: Path,
    session_factory: Factory,
    monkeypatch,
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
    for shot, tag in (("SH01", b"pair-parent-a"), ("SH02", b"pair-parent-b")):
        await _approve_shot(gate_export_client, project_dir, shot, tag)
        key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for(shot)
        derived.append(
            await FrameDerivationService(session_factory=session_factory, project_dir=project_dir).derive(
                user_id=USER.id,
                project_name=PROJECT,
                parent_artifact_key=key,
                expected_master_version=1,
                decoded_frame_index=0,
                command_id=f"pair-frame-{shot}",
            )
        )
    derived.sort(key=lambda receipt: receipt.frame_candidate_id)
    binding_command = BindingCreateCommandV1.model_validate(
        {
            "user_id": USER.id,
            "project_name": PROJECT,
            "principal": USER.sub,
            "command_id": "pair-binding-1",
            "expected_target_ref": registered.shot_targets[0].model_dump(mode="json"),
            "ordered_frame_receipts": [
                {"receipt_id": receipt.frame_candidate_id, "receipt_digest": _receipt_digest(receipt)}
                for receipt in derived
            ],
        }
    )
    binding = await LocationBindingCreationService(session_factory=session_factory, project_dir=project_dir).create(
        binding_command
    )
    snapshot = await CurrentLocationBindingSnapshotReader(
        session_factory=session_factory, project_dir=project_dir
    ).read_current(user_id=USER.id, project_name=PROJECT, target_id=registered.shot_targets[0].target_id)
    scene_ref, target_ref = snapshot.body.target_versions
    async with session_factory() as session:
        verified_binding = await ProductionBindingRepository(session).get_current_verified(
            user_id=USER.id,
            project_name=PROJECT,
            binding_id=binding.result.binding_id,
            expected_target_ref=target_ref,
            expected_scene_ref=scene_ref,
        )
        assert verified_binding is not None
        command = PairDecisionCommandV1.model_validate(
            {
                "user_id": USER.id,
                "project_name": PROJECT,
                "principal": USER.sub,
                "command_id": "pair-review-1",
                "expected_scene_ref": scene_ref.model_dump(mode="json"),
                "expected_target_ref": target_ref.model_dump(mode="json"),
                "binding_id": binding.result.binding_id,
                "expected_binding_version": binding.result.binding_version,
                "expected_envelope_digest": binding.result.envelope_digest,
                "expected_core_digest": verified_binding.core_digest,
                "views": [
                    {"role": role, "receipt_id": receipt.frame_candidate_id, "receipt_digest": _receipt_digest(receipt)}
                    for role, receipt in zip(("MASTER", "REVERSE"), derived, strict=True)
                ],
                "decision": "APPROVE",
                "observations": {
                    "view_coverage": "Both frames show the same doorway and floor edge.",
                    "camera_center": "Doorway edges meet at one camera center.",
                    "yaw_relation": "The reverse frame faces opposite the master frame.",
                    "rejection_reason": None,
                },
            }
        )
        command_digest = pair_command_digest(command.model_dump(mode="json"))
        now = datetime.now(UTC)
        authorization = PairAuthorizationV1(
            user_id=USER.id,
            project_name=PROJECT,
            authenticated_principal=USER.sub,
            authority_role="HUMAN_SHOWRUNNER",
            command_digest=command_digest,
            authorization_ref="test-only-grant",
            authenticated_at=now - timedelta(seconds=1),
        )
        decision = PairDecisionV1(
            command=command,
            command_digest=command_digest,
            pair_id=scoped_pair_id(user_id=USER.id, project_name=PROJECT, binding_id=binding.result.binding_id),
            pair_version=1,
            reviewer_id=USER.sub,
            authorization=authorization,
            authorization_digest=pair_authorization_digest(authorization.model_dump(mode="json")),
            decided_at=now,
        )
        repo = SpatialPairRepository(session)
        head = await repo.lock_pair_head(user_id=USER.id, project_name=PROJECT, pair_id=decision.pair_id)
        row = await repo.append_decision(
            head=head,
            decision=decision,
            expected_binding_version=binding.result.binding_version,
            expected_envelope_digest=binding.result.envelope_digest,
            expected_core_digest=verified_binding.core_digest,
            expected_target_ref=target_ref,
            expected_scene_ref=scene_ref,
        )
        await repo.advance_head(
            head=head,
            decision=row,
            expected_binding_version=binding.result.binding_version,
            expected_envelope_digest=binding.result.envelope_digest,
            expected_core_digest=verified_binding.core_digest,
            expected_target_ref=target_ref,
            expected_scene_ref=scene_ref,
        )
        result = PairDecisionResultV1(
            command_digest=command_digest,
            pair_id=decision.pair_id,
            pair_version=1,
            decision_digest=pair_decision_digest(decision.model_dump(mode="json")),
            decision="APPROVE",
            binding_id=binding.result.binding_id,
            binding_version=binding.result.binding_version,
            binding_envelope_digest=binding.result.envelope_digest,
            binding_core_digest=verified_binding.core_digest,
            scene_ref=scene_ref,
            target_ref=target_ref,
        )
        await repo.record_command(
            user_id=USER.id, project_name=PROJECT, principal=USER.sub, command_id=command.command_id, result=result
        )
        await session.commit()

    async with session_factory() as session:
        repo = SpatialPairRepository(session)
        current = await repo.get_current_verified(
            user_id=USER.id,
            project_name=PROJECT,
            binding_id=binding.result.binding_id,
            expected_binding_version=binding.result.binding_version,
            expected_envelope_digest=binding.result.envelope_digest,
            expected_core_digest=verified_binding.core_digest,
            expected_target_ref=target_ref,
            expected_scene_ref=scene_ref,
        )
        assert current is not None
        assert current.body.command.decision == "APPROVE"
        assert current.decision_digest == result.decision_digest
        receipt = await repo.get_command_receipt(
            user_id=USER.id,
            project_name=PROJECT,
            principal=USER.sub,
            command_id=command.command_id,
            expected_command_digest=command_digest,
        )
        assert receipt is not None
        assert receipt.result == result
        assert await session.scalar(select(func.count()).select_from(SpatialPairHeadModel)) == 1
        assert await session.scalar(select(func.count()).select_from(SpatialPairDecisionModel)) == 1

    class TestAuthority:
        async def authorize(self, *, session, command, command_digest, frames):
            assert all(frame.png_bytes for frame in frames)
            return PairAuthorizationV1(
                user_id=command.user_id,
                project_name=command.project_name,
                authenticated_principal=command.principal,
                authority_role="HUMAN_SHOWRUNNER",
                command_digest=command_digest,
                authorization_ref="test-only-grant-for-reject",
                authenticated_at=datetime.now(UTC),
            )

    reject = command.model_copy(
        update={
            "command_id": "pair-review-2",
            "decision": "REJECT",
            "observations": command.observations.model_copy(
                update={
                    "view_coverage": None,
                    "camera_center": None,
                    "yaw_relation": None,
                    "rejection_reason": "The views do not share a camera center.",
                }
            ),
        }
    )
    service = SpatialPairDecisionService(
        session_factory=session_factory,
        project_dir=project_dir,
        authority=TestAuthority(),
    )
    rejected = await service.decide(reject)
    assert rejected.result.pair_version == 2
    assert rejected.result.decision == "REJECT"
    assert await service.decide(reject) == rejected
    assert await service.decide(command) == receipt
    async with session_factory() as session:
        current = await SpatialPairRepository(session).get_current_verified(
            user_id=USER.id,
            project_name=PROJECT,
            binding_id=binding.result.binding_id,
            expected_binding_version=binding.result.binding_version,
            expected_envelope_digest=binding.result.envelope_digest,
            expected_core_digest=verified_binding.core_digest,
            expected_target_ref=target_ref,
            expected_scene_ref=scene_ref,
        )
        assert current is not None
        assert current.body.command.decision == "REJECT"
        assert await session.scalar(select(func.count()).select_from(SpatialPairDecisionModel)) == 2

    new_command = reject.model_copy(update={"command_id": "pair-review-3"})
    denied_service = SpatialPairDecisionService(session_factory=session_factory, project_dir=project_dir)
    with pytest.raises(PairAuthorizationDeniedError, match="project-scoped grant"):
        await denied_service.decide(new_command)
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(SpatialPairDecisionModel)) == 2

    frame_path = project_dir / "spatial" / "frames" / f"{derived[0].frame_candidate_id}.png"
    original_bytes = frame_path.read_bytes()
    frame_path.write_bytes(original_bytes + b"changed")
    try:
        with pytest.raises(FrameSourceConflictError, match="frame bytes"):
            await service.decide(reject)
    finally:
        frame_path.write_bytes(original_bytes)

    await _approve_shot(gate_export_client, project_dir, "SH01", b"pair-parent-a-next")
    with pytest.raises(FrameSourceConflictError, match="superseded"):
        await service.decide(reject)
