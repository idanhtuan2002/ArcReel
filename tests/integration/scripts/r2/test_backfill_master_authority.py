"""Backfilling file masters into the database master authority (ADR-0096)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.host_hardening import (
    CandidateObjectModel,
    MasterAuthorityModel,
    MasterHeadVersionModel,
    ProjectEventModel,
    PromotionReceiptModel,
)
from lib.db.repositories.host_hardening import CandidateObjectRepository
from r2.host_hardening.master_authority import MasterDivergedError, m7_candidate_id
from scripts.r2 import backfill_master_authority as backfill
from server.auth import get_current_user
from server.error_handlers import register_error_handlers
from server.routers import gates
from server.services import master_authority as composition
from tests.auth_deps import AUTH_DEPENDENCIES
from tests.fakes import GateProjectManager
from tests.integration.server.routers.test_gates_export import PROJECT, USER, _approve_shot

type Factory = async_sessionmaker[AsyncSession]


def _make_project(root: Path) -> Path:
    path = root / "projects" / PROJECT
    (path / "production").mkdir(parents=True)
    return path


@pytest.fixture
def legacy_dir(monkeypatch: pytest.MonkeyPatch, session_factory: Factory, tmp_path: Path) -> Path:
    project_dir = _make_project(tmp_path)
    manager = GateProjectManager(project_dir.parent)
    monkeypatch.setattr(gates, "async_session_factory", session_factory)
    monkeypatch.setattr(gates, "get_project_manager", lambda: manager)
    monkeypatch.setattr(backfill, "async_session_factory", session_factory)
    monkeypatch.setattr(backfill, "get_project_manager", lambda: manager)
    return project_dir


async def _legacy_project(project_dir: Path, session_factory: Factory) -> None:
    """Two shots approved with file masters only, as a project from before the database authority."""
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.include_router(gates.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _approve_shot(client, project_dir, "SH01", b"shot one")
        await _approve_shot(client, project_dir, "SH02", b"shot two")
    async with session_factory() as session:
        for model in (
            ProjectEventModel,
            PromotionReceiptModel,
            MasterHeadVersionModel,
            MasterAuthorityModel,
            CandidateObjectModel,
        ):
            await session.execute(delete(model))
        await session.commit()


async def _verify(session_factory: Factory, project_dir: Path) -> None:
    async with session_factory() as session:
        await composition.verify_masters(session, user_id=USER.id, project_name=PROJECT, project_dir=project_dir)


async def test_backfill_makes_a_legacy_project_verifiable_and_is_idempotent(
    legacy_dir: Path, session_factory: Factory
) -> None:
    project_dir = legacy_dir
    await _legacy_project(project_dir, session_factory)
    with pytest.raises(MasterDivergedError):
        await _verify(session_factory, project_dir)

    first = await backfill.backfill_project(user_id=USER.id, project_name=PROJECT, project_dir=project_dir)
    await _verify(session_factory, project_dir)
    second = await backfill.backfill_project(user_id=USER.id, project_name=PROJECT, project_dir=project_dir)

    assert (len(first["promoted"]), first["current"], first["diverged"]) == (2, [], [])
    assert (second["promoted"], len(second["current"]), second["diverged"]) == ([], 2, [])


async def test_a_divergent_head_is_reported_and_exits_2(
    legacy_dir: Path, session_factory: Factory, capsys: pytest.CaptureFixture[str]
) -> None:
    project_dir = legacy_dir
    await _legacy_project(project_dir, session_factory)
    await backfill.backfill_project(user_id=USER.id, project_name=PROJECT, project_dir=project_dir)
    async with session_factory() as session:
        await session.execute(delete(ProjectEventModel))
        await session.execute(delete(MasterHeadVersionModel))
        await session.execute(delete(PromotionReceiptModel))
        await session.execute(delete(MasterAuthorityModel))
        await session.commit()
    # Re-promote SH01 from SH02's registered bytes: the database head now names another candidate.
    records = composition.projected_master_records(project_dir)
    sh01, sh02 = sorted(records)
    async with session_factory() as session:
        sh02_object = await CandidateObjectRepository(session).get_exact(
            user_id=USER.id,
            project_name=PROJECT,
            candidate_id=m7_candidate_id(sh02, records[sh02].selected_candidate_id),
        )
    assert sh02_object is not None
    async with session_factory() as session:
        await composition.master_authority_unit(session).promote_staged(
            user_id=USER.id,
            project_name=PROJECT,
            project_dir=await asyncio.to_thread(project_dir.resolve),
            artifact_key=sh01,
            generation_candidate_id="CAND-rogue",
            version_file=Path(sh02_object.object_ref),
            expected_content_digest=sh02_object.content_digest,
            approval_record="APR-rogue",
            command_id="rogue",
        )

    status = await backfill.main_async(["--user-id", USER.id, "--project", PROJECT])

    summary = json.loads(capsys.readouterr().out)
    assert status == 2
    assert summary[PROJECT]["diverged"] == [sh01]
