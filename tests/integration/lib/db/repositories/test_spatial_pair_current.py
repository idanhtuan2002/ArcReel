"""Current pair reads require a complete head and exact stored decision."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.spatial_pair import SpatialPairDecisionModel, SpatialPairHeadModel
from lib.db.repositories.spatial_pair import SpatialPairIntegrityError, SpatialPairRepository
from r2.contracts.production_target import TargetVersionRef

FIXTURE = Path(__file__).resolve().parents[4] / "fixtures/r2/m8c_pair_contract_vectors.json"
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
