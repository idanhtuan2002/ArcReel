"""A review session pins two current PNG streams behind a signed scoped grant."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx import AsyncClient
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.content_digest import canonical_json_bytes
from lib.db.models.spatial_pair import SpatialPairCommandModel, SpatialPairDecisionModel, SpatialPairV2CustodyModel
from lib.db.models.spatial_review import (
    SpatialReviewAcknowledgmentModel,
    SpatialReviewDeliveryModel,
    SpatialReviewSessionModel,
)
from lib.db.repositories.spatial_pair import SpatialPairIntegrityError
from lib.db.repositories.spatial_pair_v2 import SpatialPairVersionedRepository
from lib.db.repositories.spatial_review import SpatialReviewIntegrityError, SpatialReviewRepository
from lib.db.repositories.spatial_source import _receipt_digest
from r2.contracts.production_binding_authority import BindingCreateCommandV1
from r2.contracts.spatial_pair import PairDecisionCommandV2, PairDecisionV2
from r2.governance.grant_transition import GrantScopeV1
from r2.m3.host_integration import GoldenAHostIntegration
from r2.production_intelligence.take_director import TakeDirectorAdapter
from r2.spatial_pair.digests import (
    pair_authorization_digest,
    pair_command_digest_v2,
    pair_decision_digest_v2,
    pair_result_digest_v2,
    scoped_pair_id,
)
from r2.spatial_pair.review_digests import review_evidence_digest, review_snapshot_digest
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

PAIR_V2_VECTOR = json.loads(
    (Path(__file__).resolve().parents[3] / "fixtures/r2/m8c_pair_v2_decision_vector.json").read_text()
)


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
    deliveries = []
    for frame in snapshot.frames:
        frame_path = project_dir / "spatial" / "frames" / f"{frame.receipt_id}.png"
        assert frame.png_digest == "sha256:" + hashlib.sha256(frame_path.read_bytes()).hexdigest()
        served, delivery = await service.fetch_frame(**fetch_scope, role=frame.role)
        assert served == frame_path.read_bytes()
        assert delivery.role == frame.role
        assert delivery.png_digest == frame.png_digest
        deliveries.append(delivery)
    with pytest.raises(SpatialReviewIntegrityError):
        await service.acknowledge_frame(
            **fetch_scope,
            attempt_id=deliveries[0].attempt_id,
            role="REVERSE",
            png_digest=snapshot.frames[0].png_digest,
            decoded=True,
        )
    with pytest.raises(SpatialReviewIntegrityError):
        await service.acknowledge_frame(
            **fetch_scope,
            attempt_id=deliveries[0].attempt_id,
            role="MASTER",
            png_digest=snapshot.frames[0].png_digest,
            decoded=False,
        )
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await service.acknowledge_frame(
            **(fetch_scope | {"principal": "other-reviewer"}),
            attempt_id=deliveries[0].attempt_id,
            role="MASTER",
            png_digest=snapshot.frames[0].png_digest,
            decoded=True,
        )
    for frame, delivery in zip(snapshot.frames, deliveries, strict=True):
        acknowledgment = await service.acknowledge_frame(
            **fetch_scope,
            attempt_id=delivery.attempt_id,
            role=frame.role,
            png_digest=frame.png_digest,
            decoded=True,
        )
        assert acknowledgment.delivery_attempt_id == delivery.attempt_id
        assert acknowledgment.principal == USER.sub
    async with session_factory() as session, session.begin():
        evidence, digest = await SpatialReviewRepository(session).read_complete(**fetch_scope)
        assert evidence.snapshot == snapshot
        assert digest.startswith("sha256:")
        command = PairDecisionCommandV2.model_validate(
            PAIR_V2_VECTOR["body"]["command"]
            | {
                "user_id": USER.id,
                "project_name": PROJECT,
                "principal": USER.sub,
                "expected_scene_ref": snapshot.scene_ref.model_dump(mode="json"),
                "expected_target_ref": snapshot.target_ref.model_dump(mode="json"),
                "binding_id": snapshot.binding_id,
                "expected_binding_version": snapshot.binding_version,
                "expected_envelope_digest": snapshot.envelope_digest,
                "expected_core_digest": snapshot.core_digest,
                "views": [
                    {"role": frame.role, "receipt_id": frame.receipt_id, "receipt_digest": frame.receipt_digest}
                    for frame in snapshot.frames
                ],
                "review_session_id": snapshot.session_id,
                "review_evidence_digest": review_evidence_digest(evidence.model_dump(mode="json")),
            }
        )
        command_digest = pair_command_digest_v2(command.model_dump(mode="json"))
        now = datetime.now(UTC)
        authorization = {
            "user_id": USER.id,
            "project_name": PROJECT,
            "authenticated_principal": USER.sub,
            "authority_role": "HUMAN_SHOWRUNNER",
            "command_digest": command_digest,
            "authorization_ref": issue.event_digest,
            "authenticated_at": now.isoformat(),
        }
        decision = PairDecisionV2.model_validate(
            {
                "decision_schema": "r2.m8.spatial.pair.decision.v2",
                "command": command.model_dump(mode="json"),
                "command_digest": command_digest,
                "pair_id": scoped_pair_id(user_id=USER.id, project_name=PROJECT, binding_id=snapshot.binding_id),
                "pair_version": 1,
                "reviewer_id": USER.sub,
                "authorization": authorization,
                "authorization_digest": pair_authorization_digest(authorization),
                "review_evidence": evidence.model_dump(mode="json"),
                "decided_at": now.isoformat(),
            }
        )
        decision_digest = pair_decision_digest_v2(decision.model_dump(mode="json"))
        pair_repo = SpatialPairVersionedRepository(session)
        locked = await pair_repo.claim_pair_head(user_id=USER.id, project_name=PROJECT, pair_id=decision.pair_id)
        await session.execute(
            insert(SpatialPairCommandModel).values(
                user_id=USER.id,
                project_name=PROJECT,
                principal=USER.sub,
                command_id=command.command_id,
                command_digest=command_digest,
                result_json={"invalid": True},
                result_digest="sha256:" + "0" * 64,
                created_at=now,
            )
        )

        async def append_with_colliding_receipt() -> None:
            async with session.begin_nested():
                await pair_repo.append_reviewed_decision(locked=locked, decision=decision)

        with pytest.raises(IntegrityError):
            await append_with_colliding_receipt()
        still_open = await session.get(
            SpatialReviewSessionModel,
            (USER.id, PROJECT, snapshot.session_id),
            populate_existing=True,
        )
        assert still_open is not None
        assert still_open.consumed_command_digest is None
        assert await session.scalar(select(func.count()).select_from(SpatialPairDecisionModel)) == 0
        await session.execute(
            delete(SpatialPairCommandModel).where(
                SpatialPairCommandModel.user_id == USER.id,
                SpatialPairCommandModel.project_name == PROJECT,
                SpatialPairCommandModel.principal == USER.sub,
                SpatialPairCommandModel.command_id == command.command_id,
            )
        )
        result = await pair_repo.append_reviewed_decision(locked=locked, decision=decision)
        assert result.decision_digest == decision_digest
        receipt_row = await session.get(SpatialPairCommandModel, (USER.id, PROJECT, USER.sub, command.command_id))
        assert receipt_row is not None
        assert receipt_row.result_json == result.model_dump(mode="json")
        assert receipt_row.result_digest == pair_result_digest_v2(result.model_dump(mode="json"))
        hint = await pair_repo.get_command_receipt_v2(
            user_id=USER.id,
            project_name=PROJECT,
            principal=USER.sub,
            command_id=command.command_id,
            expected_command_digest=command_digest,
        )
        assert hint is not None
        assert hint.result == result
        replay = await pair_repo.verify_historical_receipt(hint=hint, command=command)
        assert replay.decision_digest == decision_digest
        receipt_row.result_digest = "sha256:" + "0" * 64
        await session.flush()
        with pytest.raises(SpatialPairIntegrityError):
            await pair_repo.get_command_receipt_v2(
                user_id=USER.id,
                project_name=PROJECT,
                principal=USER.sub,
                command_id=command.command_id,
                expected_command_digest=command_digest,
            )
        receipt_row.result_digest = pair_result_digest_v2(result.model_dump(mode="json"))
        await session.flush()
        session_row = await session.get(SpatialReviewSessionModel, (USER.id, PROJECT, snapshot.session_id))
        assert session_row is not None
        assert session_row.consumed_command_digest == command_digest
        reused = PairDecisionV2.model_validate(decision.model_dump(mode="json") | {"pair_version": 2})
        reused_head = await pair_repo.claim_pair_head(user_id=USER.id, project_name=PROJECT, pair_id=decision.pair_id)
        with pytest.raises(SpatialReviewIntegrityError):
            await pair_repo.append_reviewed_decision(locked=reused_head, decision=reused)
        assert await session.scalar(select(func.count()).select_from(SpatialPairDecisionModel)) == 1
        verified_pair = await SpatialPairVersionedRepository(session).get_current_verified(
            user_id=USER.id,
            project_name=PROJECT,
            binding_id=command.binding_id,
            expected_binding_version=command.expected_binding_version,
            expected_envelope_digest=command.expected_envelope_digest,
            expected_core_digest=command.expected_core_digest,
            expected_target_ref=command.expected_target_ref,
            expected_scene_ref=command.expected_scene_ref,
        )
        assert verified_pair is not None
        assert verified_pair.decision_digest == decision_digest
        if session.get_bind().dialect.name == "postgresql":

            async def link_foreign_session() -> None:
                async with session.begin_nested():
                    session.add(
                        SpatialReviewSessionModel(
                            user_id=USER.id,
                            project_name="foreign-project",
                            session_id="b" * 32,
                            principal=USER.sub,
                            snapshot_body_json=snapshot.model_dump(mode="json"),
                            snapshot_digest=review_snapshot_digest(snapshot.model_dump(mode="json")),
                            created_at=snapshot.created_at,
                            expires_at=snapshot.expires_at,
                            consumed_command_digest=None,
                        )
                    )
                    await session.flush()
                    custody = await session.get(
                        SpatialPairV2CustodyModel, (USER.id, PROJECT, decision.pair_id, 1), with_for_update=True
                    )
                    assert custody is not None
                    custody.review_session_id = "b" * 32
                    await session.flush()

            with pytest.raises(IntegrityError):
                await link_foreign_session()
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
        assert await session.scalar(select(func.count()).select_from(SpatialReviewAcknowledgmentModel)) == 2

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
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await service.acknowledge_frame(
            **fetch_scope,
            attempt_id=deliveries[0].attempt_id,
            role="MASTER",
            png_digest=snapshot.frames[0].png_digest,
            decoded=True,
        )
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(SpatialReviewSessionModel)) == 2
        assert await session.scalar(select(func.count()).select_from(SpatialReviewDeliveryModel)) == 2
        assert await session.scalar(select(func.count()).select_from(SpatialReviewAcknowledgmentModel)) == 2
