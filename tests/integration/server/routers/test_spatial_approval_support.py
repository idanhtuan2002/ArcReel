"""The approval support builds a binding whose V2 APPROVE the current reader accepts."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.services.spatial_pair_current_v2 import CurrentApprovedSpatialPairReaderV2
from tests.integration.server.routers.spatial_approval_support import approved_location
from tests.integration.server.routers.test_gates_export import PROJECT, USER


@pytest.mark.asyncio
async def test_the_support_produces_a_current_v2_approval(
    gate_export_client: AsyncClient,
    project_dir: Path,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = await approved_location(gate_export_client, project_dir, session_factory, monkeypatch)

    current = await CurrentApprovedSpatialPairReaderV2(
        session_factory=session_factory, project_dir=project_dir, grants=approved.grants
    ).read_current(user_id=USER.id, project_name=PROJECT, target_id=approved.target_id)

    assert current.decision_digest == approved.approval.decision_digest
    assert current.body.command.decision == "APPROVE"
