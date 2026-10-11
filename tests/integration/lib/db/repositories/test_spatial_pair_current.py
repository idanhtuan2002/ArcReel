"""Current pair reads require a complete head and exact stored decision."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.spatial_pair import SpatialPairDecisionModel, SpatialPairHeadModel, SpatialPairV2CustodyModel
from lib.db.models.spatial_review import (
    SpatialReviewAcknowledgmentModel,
    SpatialReviewDeliveryModel,
    SpatialReviewSessionModel,
)
from lib.db.repositories.spatial_pair import SpatialPairIntegrityError, SpatialPairRepository
from lib.db.repositories.spatial_pair_v2 import SpatialPairVersionedRepository
from r2.contracts.production_target import TargetVersionRef
from r2.contracts.spatial_pair import PairDecisionV2
from r2.spatial_pair.digests import pair_decision_digest_v2

FIXTURE = Path(__file__).resolve().parents[4] / "fixtures/r2/m8c_pair_contract_vectors.json"
V2_FIXTURE = Path(__file__).resolve().parents[4] / "fixtures/r2/m8c_pair_v2_decision_vector.json"
type Factory = async_sessionmaker[AsyncSession]


def _case() -> dict[str, Any]:
    return next(item for item in json.loads(FIXTURE.read_text())["cases"] if item["name"] == "pair_decision_approve")


async def _seed(session: AsyncSession) -> tuple[SpatialPairHeadModel, SpatialPairDecisionModel]:
    case = _case()
    body = case["body"]
    command = body["command"]
    head = SpatialPairHeadModel(
        user_id="u1",
        project_name="demo",
        pair_id=body["pair_id"],
        current_version=None,
        current_decision_digest=None,
    )
    session.add(head)
    await session.flush()
    row = SpatialPairDecisionModel(
        user_id="u1",
        project_name="demo",
        pair_id=body["pair_id"],
        pair_version=1,
        decision_body_json=body,
        decision_digest=case["digest"],
        command_digest=body["command_digest"],
        authorization_digest=body["authorization_digest"],
        binding_id=command["binding_id"],
        binding_version=command["expected_binding_version"],
        binding_envelope_digest=command["expected_envelope_digest"],
        binding_core_digest=command["expected_core_digest"],
        target_type="SHOT",
        target_id=command["expected_target_ref"]["target_id"],
        target_registry_version=command["expected_target_ref"]["registry_version"],
        target_version_digest=command["expected_target_ref"]["version_digest"],
        scene_type="SCENE",
        scene_id=command["expected_scene_ref"]["target_id"],
        scene_registry_version=command["expected_scene_ref"]["registry_version"],
        scene_version_digest=command["expected_scene_ref"]["version_digest"],
        master_receipt_id=command["views"][0]["receipt_id"],
        reverse_receipt_id=command["views"][1]["receipt_id"],
        decision="APPROVE",
        created_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    head.current_version = 1
    head.current_decision_digest = case["digest"]
    await session.flush()
    return head, row


async def _read(repo: SpatialPairRepository, *, project_name: str = "demo") -> Any:
    command = _case()["body"]["command"]
    return await repo.get_current_verified(
        user_id="u1",
        project_name=project_name,
        binding_id=command["binding_id"],
        expected_binding_version=1,
        expected_envelope_digest=command["expected_envelope_digest"],
        expected_core_digest=command["expected_core_digest"],
        expected_target_ref=TargetVersionRef.model_validate(command["expected_target_ref"]),
        expected_scene_ref=TargetVersionRef.model_validate(command["expected_scene_ref"]),
    )


async def test_current_pair_read_verifies_scope_head_and_decision(session_factory: Factory) -> None:
    async with session_factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            pytest.skip("synthetic vector has no registered target, binding and frame FK rows")
        head, _ = await _seed(session)
        repo = SpatialPairRepository(session)
        verified = await _read(repo)
        assert verified is not None
        assert verified.decision_digest == head.current_decision_digest
        assert await _read(repo, project_name="other") is None


async def test_versioned_current_read_preserves_v1_and_rejects_unexpected_custody(session_factory: Factory) -> None:
    async with session_factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            pytest.skip("synthetic vector has no registered target, binding and frame FK rows")
        head, row = await _seed(session)
        command = row.decision_body_json["command"]
        expected = {
            "user_id": row.user_id,
            "project_name": row.project_name,
            "binding_id": command["binding_id"],
            "expected_binding_version": command["expected_binding_version"],
            "expected_envelope_digest": command["expected_envelope_digest"],
            "expected_core_digest": command["expected_core_digest"],
            "expected_target_ref": TargetVersionRef.model_validate(command["expected_target_ref"]),
            "expected_scene_ref": TargetVersionRef.model_validate(command["expected_scene_ref"]),
        }
        repo = SpatialPairVersionedRepository(session)
        verified = await repo.get_current_verified(**expected)
        assert verified is not None
        assert verified.decision_digest == head.current_decision_digest
        session.add(
            SpatialPairV2CustodyModel(
                user_id=row.user_id,
                project_name=row.project_name,
                pair_id=row.pair_id,
                pair_version=row.pair_version,
                review_session_id="a" * 32,
                review_evidence_digest="sha256:" + "1" * 64,
                decision_digest=row.decision_digest,
            )
        )
        await session.flush()
        with pytest.raises(SpatialPairIntegrityError, match="V1 pair decision has V2 custody"):
            await repo.get_current_verified(**expected)


async def test_versioned_current_read_verifies_v1_to_v2_history_and_review_custody(session_factory: Factory) -> None:
    async with session_factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            pytest.skip("synthetic vector has no registered target, binding and frame FK rows")
        head, prior = await _seed(session)
        vector = json.loads(V2_FIXTURE.read_text())
        body = PairDecisionV2.model_validate(vector["body"]).model_copy(update={"pair_version": 2})
        body_json = body.model_dump(mode="json")
        digest = pair_decision_digest_v2(body_json)
        command = body.command
        evidence = body.review_evidence
        snapshot = evidence.snapshot
        session.add(
            SpatialReviewSessionModel(
                user_id=command.user_id,
                project_name=command.project_name,
                session_id=snapshot.session_id,
                principal=command.principal,
                snapshot_body_json=snapshot.model_dump(mode="json"),
                snapshot_digest=evidence.snapshot_digest,
                created_at=snapshot.created_at,
                expires_at=snapshot.expires_at,
                consumed_command_digest=body.command_digest,
            )
        )
        session.add_all(
            SpatialReviewDeliveryModel(
                user_id=command.user_id,
                project_name=command.project_name,
                session_id=snapshot.session_id,
                attempt_id=item.attempt_id,
                role=item.role,
                png_digest=item.png_digest,
                recorded_at=item.delivered_at,
            )
            for item in evidence.deliveries
        )
        session.add_all(
            SpatialReviewAcknowledgmentModel(
                user_id=command.user_id,
                project_name=command.project_name,
                session_id=snapshot.session_id,
                role=item.role,
                attempt_id=item.delivery_attempt_id,
                principal=item.principal,
                png_digest=item.png_digest,
                decoded=item.decoded,
                recorded_at=item.acknowledged_at,
            )
            for item in evidence.acknowledgments
        )
        session.add(
            SpatialPairDecisionModel(
                **{
                    column.name: getattr(prior, column.name)
                    for column in prior.__table__.columns
                    if column.name
                    not in {
                        "pair_version",
                        "decision_body_json",
                        "decision_digest",
                        "command_digest",
                        "authorization_digest",
                    }
                },
                pair_version=2,
                decision_body_json=body_json,
                decision_digest=digest,
                command_digest=body.command_digest,
                authorization_digest=body.authorization_digest,
            )
        )
        session.add(
            SpatialPairV2CustodyModel(
                user_id=command.user_id,
                project_name=command.project_name,
                pair_id=body.pair_id,
                pair_version=2,
                review_session_id=snapshot.session_id,
                review_evidence_digest=command.review_evidence_digest,
                decision_digest=digest,
            )
        )
        await session.flush()
        head.current_version = 2
        head.current_decision_digest = digest
        await session.flush()
        expected = {
            "user_id": command.user_id,
            "project_name": command.project_name,
            "binding_id": command.binding_id,
            "expected_binding_version": command.expected_binding_version,
            "expected_envelope_digest": command.expected_envelope_digest,
            "expected_core_digest": command.expected_core_digest,
            "expected_target_ref": command.expected_target_ref,
            "expected_scene_ref": command.expected_scene_ref,
        }
        repo = SpatialPairVersionedRepository(session)
        verified = await repo.get_current_verified(**expected)
        assert verified is not None
        assert verified.decision_digest == digest
        assert isinstance(verified.body, PairDecisionV2)
        review = await session.get(
            SpatialReviewSessionModel, (command.user_id, command.project_name, snapshot.session_id)
        )
        assert review is not None
        review.consumed_command_digest = "sha256:" + "0" * 64
        await session.flush()
        with pytest.raises(SpatialPairIntegrityError):
            await repo.get_current_verified(**expected)
        review.consumed_command_digest = body.command_digest
        delivery = await session.get(
            SpatialReviewDeliveryModel,
            (command.user_id, command.project_name, snapshot.session_id, evidence.deliveries[0].attempt_id),
        )
        assert delivery is not None
        original_delivery_time = delivery.recorded_at
        delivery.recorded_at = original_delivery_time + timedelta(seconds=1)
        await session.flush()
        with pytest.raises(SpatialPairIntegrityError):
            await repo.get_current_verified(**expected)
        delivery.recorded_at = original_delivery_time
        custody = await session.get(SpatialPairV2CustodyModel, (command.user_id, command.project_name, body.pair_id, 2))
        assert custody is not None
        custody.review_evidence_digest = "sha256:" + "0" * 64
        await session.flush()
        with pytest.raises(SpatialPairIntegrityError):
            await repo.get_current_verified(**expected)
        custody.review_evidence_digest = command.review_evidence_digest
        await session.flush()
        await session.delete(custody)
        await session.flush()
        with pytest.raises(SpatialPairIntegrityError):
            await repo.get_current_verified(**expected)


@pytest.mark.parametrize("tamper", ["head_digest", "body", "genesis", "latest"])
async def test_current_pair_read_rejects_head_or_decision_drift(session_factory: Factory, tamper: str) -> None:
    async with session_factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            pytest.skip("synthetic vector has no registered target, binding and frame FK rows")
        head, row = await _seed(session)
        if tamper == "head_digest":
            head.current_decision_digest = "sha256:" + "f" * 64
        elif tamper == "body":
            row.decision_body_json = row.decision_body_json | {"reviewer_id": "someone-else"}
        elif tamper == "genesis":
            head.current_version = None
            head.current_decision_digest = None
        else:
            session.add(
                SpatialPairDecisionModel(
                    **{
                        column.name: getattr(row, column.name)
                        for column in row.__table__.columns
                        if column.name != "pair_version"
                    },
                    pair_version=2,
                )
            )
        await session.flush()
        with pytest.raises(SpatialPairIntegrityError, match=r"pair head integrity|pair decision integrity"):
            await _read(SpatialPairRepository(session))
