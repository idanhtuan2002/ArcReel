"""Shared Gate route fixtures: a project directory and an authenticated gates client."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.auth import CurrentUserInfo, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import gates
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
