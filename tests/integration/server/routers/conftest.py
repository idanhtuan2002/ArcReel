"""Shared Gate route fixtures: a project directory and an authenticated gates client."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.generation_queue import GenerationQueue
from lib.video_backends.dashscope import DashScopeVideoBackend
from r2.contracts.shot_generation import R2ExecutionProfileV1
from server.auth import CurrentUserInfo, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import gates, r2_shots
from tests.auth_deps import AUTH_DEPENDENCIES
from tests.fakes import GateProjectManager

type Factory = async_sessionmaker[AsyncSession]

GATE_USER = CurrentUserInfo(id="default", sub="operator-1", role="admin")
GATE_PROJECT = "demo-project"


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    path = tmp_path / "projects" / GATE_PROJECT
    (path / "production").mkdir(parents=True)
    return path


@pytest.fixture
async def gate_export_client(monkeypatch: pytest.MonkeyPatch, session_factory: Factory, project_dir: Path):
    monkeypatch.setattr(gates, "async_session_factory", session_factory)
    monkeypatch.setattr(gates, "get_project_manager", lambda: GateProjectManager(project_dir.parent))
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: GATE_USER
    app.include_router(gates.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    app.include_router(gates.self_auth_router, prefix="/api/v1")
    register_error_handlers(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


@pytest.fixture
async def concurrent_gate_client(
    monkeypatch: pytest.MonkeyPatch, concurrent_session_factory: Factory, project_dir: Path
):
    """The gates client on independent connections, so database locks act between requests."""
    monkeypatch.setattr(gates, "async_session_factory", concurrent_session_factory)
    monkeypatch.setattr(gates, "get_project_manager", lambda: GateProjectManager(project_dir.parent))
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: GATE_USER
    app.include_router(gates.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    app.include_router(gates.self_auth_router, prefix="/api/v1")
    register_error_handlers(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def offline_shot_backend(profile: R2ExecutionProfileV1) -> DashScopeVideoBackend:
    """The R2 shot payload builder with an offline key; tests capture its HTTP calls."""
    return DashScopeVideoBackend(api_key="sk-offline", model=profile.backend_model_id)


@pytest.fixture
async def shots_client(monkeypatch: pytest.MonkeyPatch, session_factory: Factory, project_dir: Path):
    """The R2 shot generation route on the test database, with an offline payload builder."""
    projects = GateProjectManager(project_dir.parent)
    queue = GenerationQueue(session_factory=session_factory, project_manager=projects)
    monkeypatch.setattr(r2_shots, "async_session_factory", session_factory)
    monkeypatch.setattr(r2_shots, "get_project_manager", lambda: projects)
    monkeypatch.setattr(r2_shots, "get_generation_queue", lambda: queue)
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: GATE_USER
    app.dependency_overrides[r2_shots.payload_builder] = lambda: offline_shot_backend
    app.include_router(r2_shots.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
