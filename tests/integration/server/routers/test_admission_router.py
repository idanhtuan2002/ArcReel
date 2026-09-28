"""Portfolio admission API (ADR-0094) over the real settings store."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db import get_async_session
from server.auth import CurrentUserInfo, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import admission
from tests.auth_deps import AUTH_DEPENDENCIES

type Factory = async_sessionmaker[AsyncSession]


class _Projects:
    def project_exists(self, name: str) -> bool:
        return name in {"alpha", "beta"}


def _app(monkeypatch: pytest.MonkeyPatch, session_factory: Factory, *, authed: bool) -> FastAPI:
    monkeypatch.setattr(admission, "get_project_manager", lambda: _Projects())
    app = FastAPI()

    async def _session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_async_session] = _session
    if authed:
        app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="op", role="admin")
    app.include_router(admission.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)
    return app


async def test_admission_needs_authentication(monkeypatch, session_factory: Factory) -> None:
    app = _app(monkeypatch, session_factory, authed=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/admission")).status_code == 401


async def test_pause_resume_and_ceiling_round_trip(monkeypatch, session_factory: Factory) -> None:
    app = _app(monkeypatch, session_factory, authed=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        paused_a = await client.put("/api/v1/projects/alpha/admission", json={"paused": True})
        paused_b = await client.put("/api/v1/projects/beta/admission", json={"paused": True})
        resumed_a = await client.put("/api/v1/projects/alpha/admission", json={"paused": False})
        ceiling = await client.put("/api/v1/admission", json={"max_running_per_project": 2})
        state = await client.get("/api/v1/admission")

    assert paused_a.json() == {"project": "alpha", "paused": True}
    assert paused_b.status_code == 200
    assert resumed_a.json() == {"project": "alpha", "paused": False}
    assert ceiling.json() == {"paused": ["beta"], "max_running_per_project": 2}
    assert state.json() == {"paused": ["beta"], "max_running_per_project": 2}


async def test_unknown_project_and_negative_ceiling_are_refused(monkeypatch, session_factory: Factory) -> None:
    app = _app(monkeypatch, session_factory, authed=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unknown = await client.put("/api/v1/projects/ghost/admission", json={"paused": True})
        negative = await client.put("/api/v1/admission", json={"max_running_per_project": -1})

    assert unknown.status_code == 404
    assert negative.status_code == 422
