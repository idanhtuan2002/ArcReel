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

from lib.artifact_manifest import ArtifactKey
from lib.db.models.host_hardening import (
    CandidateObjectModel,
    MasterAuthorityModel,
    MasterHeadVersionModel,
    ProjectEventModel,
    PromotionReceiptModel,
)
from lib.db.repositories.host_hardening import CandidateObjectRepository, MasterAuthorityRepository
from r2.host_hardening.master_authority import MasterDivergedError, m7_candidate_id
from r2.m3.host_integration import GoldenAHostIntegration
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


async def test_a_gate_c_approval_between_the_head_check_and_the_promotion_is_not_overwritten(
    legacy_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("row locks between sessions need PostgreSQL")
    project_dir = legacy_dir
    await _legacy_project(project_dir, session_factory)
    records = composition.projected_master_records(project_dir)
    sh01, sh02 = sorted(records)
    sh02_target = str(ArtifactKey.decode(sh02).components[1])
    late_file, late_digest = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).staged_version(
        sh02_target, records[sh02].host_version_ref
    )
    root = await asyncio.to_thread(project_dir.resolve)

    async def approve_late() -> None:
        async with composition.serialized_artifact(
            session_factory, user_id=USER.id, project_name=PROJECT, artifact_key=sh01
        ) as session:
            await composition.master_authority_unit(session, defer_commit=True).promote_staged(
                user_id=USER.id,
                project_name=PROJECT,
                project_dir=root,
                artifact_key=sh01,
                generation_candidate_id="CAND-late",
                version_file=late_file,
                expected_content_digest=late_digest,
                approval_record="APR-late",
                command_id="late",
            )

    late: list[asyncio.Task[None]] = []
    original_unit = composition.master_authority_unit

    def unit_with_a_late_approval(session: AsyncSession, **kwargs: bool):
        unit = original_unit(session, **kwargs)
        promote = unit.promote_staged

        async def promote_after_a_late_approval(**fields: object):
            if fields["artifact_key"] == sh01 and not late:
                late.append(asyncio.create_task(approve_late()))
                # Without the row lock the late approval commits here; with it, it waits.
                await asyncio.wait([asyncio.shield(late[0])], timeout=1.5)
            return await promote(**fields)

        unit.promote_staged = promote_after_a_late_approval
        return unit

    monkeypatch.setattr(backfill, "master_authority_unit", unit_with_a_late_approval)
    summary = await backfill.backfill_project(user_id=USER.id, project_name=PROJECT, project_dir=project_dir)
    await asyncio.wait_for(late[0], timeout=10.0)

    async with session_factory() as session:
        head = await MasterAuthorityRepository(session).get_current(
            user_id=USER.id, project_name=PROJECT, artifact_key=sh01
        )
    assert summary["promoted"] == [sh01, sh02]
    assert head is not None
    assert (head.master_version, head.candidate_id) == (2, m7_candidate_id(sh01, "CAND-late"))
