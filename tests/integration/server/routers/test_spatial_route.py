"""The M8-C spatial API: frame receipts and one spatial execution over HTTP, with an offline vision call."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.advanced_creative import M8CandidateRevisionModel
from r2.m3.host_integration import GoldenAHostIntegration
from server.auth import get_current_user
from server.error_handlers import register_error_handlers
from server.routers import gates, spatial
from tests.auth_deps import AUTH_DEPENDENCIES
from tests.fakes import GateProjectManager
from tests.integration.server.routers.test_gates_export import PROJECT, USER
from tests.integration.server.routers.test_spatial_execution import ROUTE, _approve_shot, _Vision

type Factory = async_sessionmaker[AsyncSession]

BASE = f"/api/v1/projects/{PROJECT}/m8/spatial"


class _SpatialProjects(GateProjectManager):
    """Gate projects whose metadata indexes one episode script."""

    def load_project_readonly(self, project_name: str) -> dict[str, Any]:
        return {"episodes": [{"episode": 1, "script_file": "episode_1.json"}]}


@pytest.fixture
def vision() -> _Vision:
    return _Vision()


@pytest.fixture
async def spatial_client(
    monkeypatch: pytest.MonkeyPatch, session_factory: Factory, project_dir: Path, vision: _Vision
) -> AsyncIterator[AsyncClient]:
    (project_dir / "scripts").mkdir()
    (project_dir / "scripts" / "episode_1.json").write_text('{"episode": 1}', encoding="utf-8")
    projects = _SpatialProjects(project_dir.parent)
    for module in (gates, spatial):
        monkeypatch.setattr(module, "async_session_factory", session_factory)
        monkeypatch.setattr(module, "get_project_manager", lambda: projects)
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[spatial.spatial_vision] = lambda: spatial.SpatialVision(route=ROUTE, call=vision)
    app.include_router(gates.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    app.include_router(spatial.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def _derive(client: AsyncClient, project_dir: Path, shot: str, color: str) -> dict[str, Any]:
    await _approve_shot(client, project_dir, shot, color)
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for(shot)
    response = await client.post(
        f"{BASE}/frames",
        json={
            "parent_artifact_key": key,
            "expected_master_version": 1,
            "decoded_frame_index": 0,
            "command_id": f"frame-{shot}",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _frames(client: AsyncClient, project_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    master = await _derive(client, project_dir, "SH01", "red")
    reverse = await _derive(client, project_dir, "SH02", "blue")
    pick = ("receipt_id", "receipt_digest")
    return {k: master[k] for k in pick}, {k: reverse[k] for k in pick}


def _execution(master: dict[str, str], reverse: dict[str, str], **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "command_id": "spatial-1",
        "candidate_id": "spatial-candidate-1",
        "expected_head_version": None,
        "episode": 1,
        "scene_name": "Lobby",
        "master": master,
        "reverse": reverse,
    }
    body.update(overrides)
    return body


async def _revisions(factory: Factory) -> int:
    async with factory() as session:
        return (await session.execute(select(func.count()).select_from(M8CandidateRevisionModel))).scalar_one()


async def test_frames_then_execution_append_one_revision_and_replay_is_identical(
    spatial_client: AsyncClient, project_dir: Path, session_factory: Factory, vision: _Vision
) -> None:
    master, reverse = await _frames(spatial_client, project_dir)
    again = await spatial_client.post(
        f"{BASE}/frames",
        json={
            "parent_artifact_key": GoldenAHostIntegration(
                project_dir, resource_type="videos", episode=1
            ).artifact_key_for("SH01"),
            "expected_master_version": 1,
            "decoded_frame_index": 0,
            "command_id": "frame-SH01",
        },
    )
    assert again.status_code == 200
    assert again.json()["receipt_id"] == master["receipt_id"]

    first = await spatial_client.post(f"{BASE}/executions", json=_execution(master, reverse))
    replay = await spatial_client.post(f"{BASE}/executions", json=_execution(master, reverse))

    assert first.status_code == 200, first.text
    assert first.json() == {"candidate_id": "spatial-candidate-1", "current_revision": 1, "head_version": 1}
    assert replay.content == first.content
    assert len(vision.calls) == 1
    assert "Scene: Lobby" in vision.calls[0][0]
    assert await _revisions(session_factory) == 1

    changed = await spatial_client.post(f"{BASE}/executions", json=_execution(master, reverse, scene_name="Hall"))
    assert changed.status_code == 409
    assert len(vision.calls) == 1


@pytest.mark.parametrize("scene_name", ["", "   ", "x" * 121])
async def test_scene_name_is_bounded_before_any_provider_call(
    spatial_client: AsyncClient, project_dir: Path, vision: _Vision, scene_name: str
) -> None:
    master, reverse = await _frames(spatial_client, project_dir)

    response = await spatial_client.post(f"{BASE}/executions", json=_execution(master, reverse, scene_name=scene_name))

    assert response.status_code == 422
    assert vision.calls == []


async def test_an_unindexed_episode_is_not_found_before_any_provider_call(
    spatial_client: AsyncClient, project_dir: Path, session_factory: Factory, vision: _Vision
) -> None:
    master, reverse = await _frames(spatial_client, project_dir)

    response = await spatial_client.post(f"{BASE}/executions", json=_execution(master, reverse, episode=2))

    assert response.status_code == 404
    assert vision.calls == []
    assert await _revisions(session_factory) == 0


async def test_unknown_or_repeated_frames_write_nothing(
    spatial_client: AsyncClient, project_dir: Path, session_factory: Factory, vision: _Vision
) -> None:
    master, reverse = await _frames(spatial_client, project_dir)
    unknown = {"receipt_id": master["receipt_id"], "receipt_digest": "sha256:" + "0" * 64}

    stale = await spatial_client.post(f"{BASE}/executions", json=_execution(unknown, reverse))
    same = await spatial_client.post(f"{BASE}/executions", json=_execution(master, master, command_id="spatial-2"))

    assert stale.status_code == 503
    assert same.status_code == 409
    assert vision.calls == []
    assert await _revisions(session_factory) == 0


async def test_unusable_model_output_is_unavailable_and_writes_no_revision(
    spatial_client: AsyncClient, project_dir: Path, session_factory: Factory, vision: _Vision
) -> None:
    master, reverse = await _frames(spatial_client, project_dir)
    vision.raw = json.dumps({"schema_version": "v0"}).encode()

    response = await spatial_client.post(f"{BASE}/executions", json=_execution(master, reverse))

    assert response.status_code == 503
    assert len(vision.calls) == 1
    assert await _revisions(session_factory) == 0


async def test_frame_requests_refuse_a_non_video_parent_and_a_superseded_master(
    spatial_client: AsyncClient, project_dir: Path
) -> None:
    await _approve_shot(spatial_client, project_dir, "SH01", "red")
    key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    body = {"parent_artifact_key": key, "expected_master_version": 2, "decoded_frame_index": 0, "command_id": "f-1"}

    superseded = await spatial_client.post(f"{BASE}/frames", json=body)
    not_video = await spatial_client.post(f"{BASE}/frames", json={**body, "parent_artifact_key": "not-a-key"})

    assert superseded.status_code == 409
    assert not_video.status_code == 422
