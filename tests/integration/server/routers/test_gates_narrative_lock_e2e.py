"""End-to-end coverage for Gate B (Narrative Lock) through the real HTTP
route -- server/routers/gates.py's narrative-lock endpoint calling the real,
unmodified AdaptationAuthorityService.admit_screenplay_for_direction via the
new SessionAuthenticatedShowrunnerAuthority adapter. Reuses Golden B's real
corpus setup (tests/fixtures/r2/m6_dual_profile_corpus.py) up through a
ready-to-submit ScreenplayAdmissionCommand, then submits it as a real HTTP
request rather than calling the service directly -- proving the route, the
new authority adapter, and the existing service genuinely work together for
a real admission, not just in isolation (Task 5's own router tests only
exercise Greenlight/Publish Approval/Final Cut and an auth-failure case for
Narrative Lock)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.adaptation_uow import adaptation_uow_factory
from server.auth import CurrentUserInfo, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import gates
from tests.auth_deps import AUTH_DEPENDENCIES
from tests.fixtures.r2.m6_dual_profile_corpus import build_golden_b_canon, build_screenplay_admission_command
from tests.integration.r2.test_m6_dual_profile_acceptance import PROJECT, USER, _western_ref

type Factory = async_sessionmaker[AsyncSession]

OPERATOR = CurrentUserInfo(id="default", sub="operator-1", role="admin")


class _FakeProjectManager:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def get_project_path(self, project_name: str) -> Path:
        path = self.project_root / project_name
        path.mkdir(parents=True, exist_ok=True)
        return path


@pytest.mark.timeout(60)
async def test_narrative_lock_admits_a_real_screenplay_through_the_real_route(
    monkeypatch: pytest.MonkeyPatch, session_factory: Factory, tmp_path: Path
) -> None:
    monkeypatch.setattr(gates, "async_session_factory", session_factory)
    monkeypatch.setattr(gates, "get_project_manager", lambda: _FakeProjectManager(tmp_path / "projects"))

    canon = build_golden_b_canon()
    uow_factory = adaptation_uow_factory(session_factory)
    setup = await build_screenplay_admission_command(
        _western_ref(), canon=canon, uow_factory=uow_factory, user_id=USER, project_name=PROJECT
    )

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: OPERATOR
    app.include_router(gates.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)

    # ASGITransport keeps the request on this test's own event loop -- a sync
    # TestClient spins up a separate portal-thread event loop, and reusing a
    # real asyncpg-backed session_factory (whose pool was created on THIS
    # loop by the fixture's own migration step) from that other loop raises
    # "Task ... got Future ... attached to a different loop" under real
    # Postgres. Matches tests/integration/server/routers/test_onboarding_router.py's
    # established async-DB-route testing idiom.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/projects/{PROJECT}/gates/narrative-lock",
            json=setup.admit.model_dump(mode="json"),
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision_ref"]["decision_id"] == setup.admit.decision_id
    assert body["outcome"] == "RECORDED"
    assert body["current_at_return"] is True


@pytest.mark.timeout(60)
async def test_narrative_lock_rejects_a_project_name_mismatch_before_touching_the_service(
    monkeypatch: pytest.MonkeyPatch, session_factory: Factory, tmp_path: Path
) -> None:
    monkeypatch.setattr(gates, "async_session_factory", session_factory)
    monkeypatch.setattr(gates, "get_project_manager", lambda: _FakeProjectManager(tmp_path / "projects"))

    canon = build_golden_b_canon()
    uow_factory = adaptation_uow_factory(session_factory)
    setup = await build_screenplay_admission_command(
        _western_ref(), canon=canon, uow_factory=uow_factory, user_id=USER, project_name=PROJECT
    )

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: OPERATOR
    app.include_router(gates.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/projects/a-completely-different-project/gates/narrative-lock",
            json=setup.admit.model_dump(mode="json"),
        )
    assert response.status_code == 400
    assert "does not match" in response.json()["detail"]
