"""Receipt reads are scoped and reject altered stored evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.spatial_source import SpatialFrameReceiptModel
from lib.db.repositories.spatial_source import SpatialFrameReceiptRepository
from r2.contracts.spatial_source import FrameDerivationReceiptV1

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/r2/m8c_source_digest_vectors.json"


@pytest.mark.asyncio
async def test_scoped_receipt_round_trip_and_digest_corruption(db_session: AsyncSession) -> None:
    cases = {case["name"]: case for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]}
    receipt = FrameDerivationReceiptV1.model_validate(cases["frame_receipt_master"]["body"])
    repo = SpatialFrameReceiptRepository(db_session)
    await repo.insert(command_id="frame-master-1", receipt=receipt)
    assert await repo.get_exact(user_id="u1", project_name="demo", receipt_id=receipt.frame_candidate_id) == receipt
    assert await repo.get_exact(user_id="u2", project_name="demo", receipt_id=receipt.frame_candidate_id) is None
    assert await repo.get_exact(user_id="u1", project_name="other", receipt_id=receipt.frame_candidate_id) is None

    row = (await db_session.execute(select(SpatialFrameReceiptModel))).scalar_one()
    row.receipt_digest = "sha256:" + "f" * 64
    await db_session.flush()
    with pytest.raises(ValueError, match="integrity"):
        await repo.get_exact(user_id="u1", project_name="demo", receipt_id=receipt.frame_candidate_id)
