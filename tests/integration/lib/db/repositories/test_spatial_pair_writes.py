"""Pair decisions advance one scoped head atomically in the caller transaction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.spatial_pair import SpatialPairDecisionModel, SpatialPairHeadModel
from lib.db.repositories.spatial_pair import SpatialPairIntegrityError, SpatialPairRepository
from r2.contracts.production_target import TargetVersionRef
from r2.contracts.spatial_pair import PairDecisionV1

FIXTURE = Path(__file__).resolve().parents[4] / "fixtures/r2/m8c_pair_contract_vectors.json"
type Factory = async_sessionmaker[AsyncSession]


def _case(name: str) -> dict[str, Any]:
    return next(item for item in json.loads(FIXTURE.read_text())["cases"] if item["name"] == name)


def _refs(decision: PairDecisionV1) -> tuple[TargetVersionRef, TargetVersionRef]:
    return decision.command.expected_target_ref, decision.command.expected_scene_ref


async def _append(repo: SpatialPairRepository, decision: PairDecisionV1) -> None:
    target, scene = _refs(decision)
    head = await repo.lock_pair_head(
        user_id="u1",
        project_name="demo",
        pair_id=decision.pair_id,
    )
    row = await repo.append_decision(
        head=head,
        decision=decision,
        expected_binding_version=decision.command.expected_binding_version,
        expected_envelope_digest=decision.command.expected_envelope_digest,
        expected_core_digest=decision.command.expected_core_digest,
        expected_target_ref=target,
        expected_scene_ref=scene,
    )
    await repo.advance_pair_head(
        head=head,
        decision=row,
        expected_binding_version=decision.command.expected_binding_version,
        expected_envelope_digest=decision.command.expected_envelope_digest,
        expected_core_digest=decision.command.expected_core_digest,
        expected_target_ref=target,
        expected_scene_ref=scene,
    )


async def _fail_after_append(session: AsyncSession, decision: PairDecisionV1) -> None:
    async with session.begin():
        await _append(SpatialPairRepository(session), decision)
        raise RuntimeError("forced rollback")


async def test_pair_head_advances_approval_then_rejection(session_factory: Factory) -> None:
    async with session_factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            pytest.skip("synthetic vector has no registered target, binding and frame FK rows")
        repo = SpatialPairRepository(session)
        approve = PairDecisionV1.model_validate(_case("pair_decision_approve")["body"])
        reject = PairDecisionV1.model_validate(_case("pair_decision_reject")["body"])
        await _append(repo, approve)
        await _append(repo, reject)
        head = await session.get(SpatialPairHeadModel, ("u1", "demo", approve.pair_id))
        assert head is not None
        assert head.current_version == 2
        assert head.current_decision_digest == _case("pair_decision_reject")["digest"]
        assert await session.scalar(select(func.count()).select_from(SpatialPairDecisionModel)) == 2


async def test_pair_append_rolls_back_unfinished_genesis(session_factory: Factory) -> None:
    async with session_factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            pytest.skip("synthetic vector has no registered target, binding and frame FK rows")
        approve = PairDecisionV1.model_validate(_case("pair_decision_approve")["body"])
        with pytest.raises(RuntimeError, match="forced rollback"):
            await _fail_after_append(session, approve)
        assert await session.scalar(select(func.count()).select_from(SpatialPairHeadModel)) == 0
        assert await session.scalar(select(func.count()).select_from(SpatialPairDecisionModel)) == 0


async def test_pair_head_rejects_committed_genesis(session_factory: Factory) -> None:
    async with session_factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            pytest.skip("synthetic vector has no registered target, binding and frame FK rows")
        approve = PairDecisionV1.model_validate(_case("pair_decision_approve")["body"])
        session.add(
            SpatialPairHeadModel(
                user_id="u1",
                project_name="demo",
                pair_id=approve.pair_id,
                current_version=None,
                current_decision_digest=None,
            )
        )
        await session.flush()
        with pytest.raises(SpatialPairIntegrityError, match="committed genesis"):
            await SpatialPairRepository(session).lock_pair_head(
                user_id="u1",
                project_name="demo",
                pair_id=approve.pair_id,
            )


async def test_pair_head_rejects_corrupt_predecessor_digest(session_factory: Factory) -> None:
    async with session_factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            pytest.skip("synthetic vector has no registered target, binding and frame FK rows")
        approve = PairDecisionV1.model_validate(_case("pair_decision_approve")["body"])
        repo = SpatialPairRepository(session)
        await _append(repo, approve)
        head = await session.get(SpatialPairHeadModel, ("u1", "demo", approve.pair_id))
        assert head is not None
        head.current_decision_digest = "sha256:" + "f" * 64
        await session.flush()
        with pytest.raises(SpatialPairIntegrityError, match="pair head integrity"):
            await repo.lock_pair_head(user_id="u1", project_name="demo", pair_id=approve.pair_id)
