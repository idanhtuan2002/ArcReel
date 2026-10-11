"""A review session pins two current PNG streams behind a signed scoped grant."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.content_digest import canonical_json_bytes
from lib.db.models.spatial_review import SpatialReviewDeliveryModel, SpatialReviewSessionModel
from lib.db.repositories.spatial_review import SpatialReviewIntegrityError
from lib.db.repositories.spatial_source import _receipt_digest
from r2.contracts.production_binding_authority import BindingCreateCommandV1
from r2.governance.grant_transition import GrantScopeV1
from r2.m3.host_integration import GoldenAHostIntegration
from r2.production_intelligence.take_director import TakeDirectorAdapter
from r2.spatial_pair.review_digests import review_snapshot_digest
from r2.target_registry.service import TakeTargetRegistrationService
from server.services.governance_grants import (
    CurrentShowrunnerGrantReader,
    GovernanceGrantImporter,
    ShowrunnerGrantUnavailableError,
)
from server.services.location_binding import LocationBindingCreationService
from server.services.spatial_review_session import SpatialReviewSessionService
from server.services.spatial_source import FrameDerivationService, FrameSourceConflictError
from tests.integration.r2.adaptation import test_screenplay_admission as admission_helpers
from tests.integration.r2.target_registry import test_take_registration as target_helpers
from tests.integration.server.routers.test_gates_export import PROJECT, USER, _approve_shot


@pytest.mark.asyncio
async def test_review_session_requires_current_grant_and_pins_verified_png_bytes(
    gate_export_client: AsyncClient,
    project_dir: Path,
    session_factory: async_sessionmaker[AsyncSession],
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
    receipts = []
    for shot, tag in (("SH01", b"review-parent-a"), ("SH02", b"review-parent-b")):
        await _approve_shot(gate_export_client, project_dir, shot, tag)
        key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for(shot)
        receipts.append(
            await FrameDerivationService(session_factory=session_factory, project_dir=project_dir).derive(
                user_id=USER.id,
                project_name=PROJECT,
                parent_artifact_key=key,
                expected_master_version=1,
                decoded_frame_index=0,
                command_id=f"review-frame-{shot}",
            )
        )
    receipts.sort(key=lambda receipt: receipt.frame_candidate_id)
    await LocationBindingCreationService(session_factory=session_factory, project_dir=project_dir).create(
        BindingCreateCommandV1.model_validate(
            {
                "user_id": USER.id,
                "project_name": PROJECT,
                "principal": USER.sub,
                "command_id": "review-binding-1",
                "expected_target_ref": registered.shot_targets[0].model_dump(mode="json"),
                "ordered_frame_receipts": [
                    {"receipt_id": receipt.frame_candidate_id, "receipt_digest": _receipt_digest(receipt)}
                    for receipt in receipts
                ],
            }
        )
    )

    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    reader = CurrentShowrunnerGrantReader(key_id="test-review-key", public_key=public)
    service = SpatialReviewSessionService(session_factory=session_factory, project_dir=project_dir, grants=reader)
    arguments = {
        "user_id": USER.id,
        "project_name": PROJECT,
        "principal": USER.sub,
        "target_id": registered.shot_targets[0].target_id,
    }
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await service.create(**arguments)
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(SpatialReviewSessionModel)) == 0

    scope = GrantScopeV1(USER.id, PROJECT, USER.sub)
    issued_at = (datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "schema": "governance.showrunner_grant_event.v1",
        "event_type": "ISSUE",
        "user_id": USER.id,
        "project_name": PROJECT,
        "principal": USER.sub,
        "role": "HUMAN_SHOWRUNNER",
        "sequence": 1,
        "previous_event_digest": None,
        "issued_at": issued_at,
        "not_before": issued_at,
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "signer_key_id": "test-review-key",
    }
    signature = base64.urlsafe_b64encode(private.sign(canonical_json_bytes(body, allow_nan=False))).decode().rstrip("=")
    raw = canonical_json_bytes({"body": body, "signature": signature}, allow_nan=False)
    issue = await GovernanceGrantImporter(session_factory, key_id="test-review-key", public_key=public).import_event(
        raw, scope=scope
    )
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await service.create(**(arguments | {"principal": "other-reviewer"}))
    snapshot = await service.create(**arguments)
    assert snapshot.session_id != (await service.create(**arguments)).session_id
    assert [frame.role for frame in snapshot.frames] == ["MASTER", "REVERSE"]
    assert [frame.receipt_id for frame in snapshot.frames] == [receipt.frame_candidate_id for receipt in receipts]
    fetch_scope = {
        "user_id": USER.id,
        "project_name": PROJECT,
        "principal": USER.sub,
        "session_id": snapshot.session_id,
    }
    with pytest.raises(SpatialReviewIntegrityError):
        await service.fetch_frame(**(fetch_scope | {"principal": "other-reviewer"}), role="MASTER")
    for frame in snapshot.frames:
        frame_path = project_dir / "spatial" / "frames" / f"{frame.receipt_id}.png"
        assert frame.png_digest == "sha256:" + hashlib.sha256(frame_path.read_bytes()).hexdigest()
        served, delivery = await service.fetch_frame(**fetch_scope, role=frame.role)
        assert served == frame_path.read_bytes()
        assert delivery.role == frame.role
        assert delivery.png_digest == frame.png_digest
    frame_path = project_dir / "spatial" / "frames" / f"{snapshot.frames[0].receipt_id}.png"
    original = frame_path.read_bytes()
    frame_path.write_bytes(original + b"changed")
    try:
        with pytest.raises(FrameSourceConflictError):
            await service.create(**arguments)
        with pytest.raises(FrameSourceConflictError):
            await service.fetch_frame(**fetch_scope, role="MASTER")
    finally:
        frame_path.write_bytes(original)
    async with session_factory() as session:
        row = await session.get(SpatialReviewSessionModel, (USER.id, PROJECT, snapshot.session_id))
        assert row is not None
        assert row.snapshot_digest == review_snapshot_digest(snapshot.model_dump(mode="json"))
        assert await session.scalar(select(func.count()).select_from(SpatialReviewSessionModel)) == 2
        assert await session.scalar(select(func.count()).select_from(SpatialReviewDeliveryModel)) == 2

    revoke_body = {key: value for key, value in body.items() if key not in {"not_before", "expires_at"}} | {
        "event_type": "REVOKE",
        "sequence": 2,
        "previous_event_digest": issue.event_digest,
        "issued_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    revoke_signature = (
        base64.urlsafe_b64encode(private.sign(canonical_json_bytes(revoke_body, allow_nan=False))).decode().rstrip("=")
    )
    revoke_raw = canonical_json_bytes({"body": revoke_body, "signature": revoke_signature}, allow_nan=False)
    await GovernanceGrantImporter(session_factory, key_id="test-review-key", public_key=public).import_event(
        revoke_raw, scope=scope
    )
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await service.create(**arguments)
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await service.fetch_frame(**fetch_scope, role="REVERSE")
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(SpatialReviewSessionModel)) == 2
        assert await session.scalar(select(func.count()).select_from(SpatialReviewDeliveryModel)) == 2
