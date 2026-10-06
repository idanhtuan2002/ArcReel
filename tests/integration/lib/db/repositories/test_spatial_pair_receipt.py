"""Pair command receipts retain exact scoped replay inputs and outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.spatial_pair import SpatialPairCommandModel
from lib.db.repositories.spatial_pair import SpatialPairIntegrityError, SpatialPairRepository
from r2.contracts.spatial_pair import PairDecisionResultV1

FIXTURE = Path(__file__).resolve().parents[4] / "fixtures/r2/m8c_pair_contract_vectors.json"
type Factory = async_sessionmaker[AsyncSession]


def _case() -> dict[str, Any]:
    return next(item for item in json.loads(FIXTURE.read_text())["cases"] if item["name"] == "pair_result_approve")


async def test_pair_receipt_replays_exact_input_and_rejects_changed_command(session_factory: Factory) -> None:
    case = _case()
    result = PairDecisionResultV1.model_validate(case["body"])
    async with session_factory() as session:
        repo = SpatialPairRepository(session)
        assert (
            await repo.get_command_receipt(
                user_id="u1",
                project_name="demo",
                principal="human:reviewer-1",
                command_id="pair-command-1",
                expected_command_digest=result.command_digest,
            )
            is None
        )
        receipt = await repo.record_command(
            user_id="u1",
            project_name="demo",
            principal="human:reviewer-1",
            command_id="pair-command-1",
            result=result,
        )
        assert receipt.result_digest == case["digest"]
        assert (
            await repo.get_command_receipt(
                user_id="u1",
                project_name="demo",
                principal="human:reviewer-1",
                command_id="pair-command-1",
                expected_command_digest=result.command_digest,
            )
            == receipt
        )
        with pytest.raises(SpatialPairIntegrityError, match="different input"):
            await repo.get_command_receipt(
                user_id="u1",
                project_name="demo",
                principal="human:reviewer-1",
                command_id="pair-command-1",
                expected_command_digest="sha256:" + "f" * 64,
            )


@pytest.mark.parametrize("tamper", ["body", "result_digest", "command_digest"])
async def test_pair_receipt_rejects_stored_drift(session_factory: Factory, tamper: str) -> None:
    result = PairDecisionResultV1.model_validate(_case()["body"])
    async with session_factory() as session:
        repo = SpatialPairRepository(session)
        await repo.record_command(
            user_id="u1",
            project_name="demo",
            principal="human:reviewer-1",
            command_id="pair-command-1",
            result=result,
        )
        row = await session.get(SpatialPairCommandModel, ("u1", "demo", "human:reviewer-1", "pair-command-1"))
        assert row is not None
        if tamper == "body":
            row.result_json = row.result_json | {"binding_version": 2}
        elif tamper == "result_digest":
            row.result_digest = "sha256:" + "f" * 64
        else:
            row.command_digest = "sha256:" + "f" * 64
        await session.flush()
        with pytest.raises(SpatialPairIntegrityError, match="receipt integrity"):
            await repo.get_command_receipt(
                user_id="u1",
                project_name="demo",
                principal="human:reviewer-1",
                command_id="pair-command-1",
                expected_command_digest=result.command_digest,
            )
