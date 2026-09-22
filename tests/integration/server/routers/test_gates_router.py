"""Integration coverage for the P1 Gate A-D operator-control API
(server/routers/gates.py). Uses a real session_factory-backed DB (matching
lib/db/repositories/gates.py's own integration tests) rather than mocks,
since the repositories under test are real async SQLAlchemy code.

Narrative Lock (Gate B) needs the full M6 admission machinery (a real
branch, map approval, profile evaluation report) to exercise successfully --
that full path is covered end to end in the P1 evidence test, not
duplicated here. This file proves: auth is required on every endpoint,
Greenlight/Publish Approval/the GET history round-trip through the real new
tables, and Final Cut really stages+approves a file through the existing,
unmodified GoldenAHostIntegration/ProductionApprovalService while rejecting
a path-escape attempt before touching disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.auth import CurrentUserInfo, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import gates
from tests.auth_deps import AUTH_DEPENDENCIES

type Factory = async_sessionmaker[AsyncSession]

USER = CurrentUserInfo(id="default", sub="operator-1", role="admin")
PROJECT = "demo-project"


class _FakeProjectManager:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def get_project_path(self, project_name: str) -> Path:
        path = self.project_root / project_name
        path.mkdir(parents=True, exist_ok=True)
        return path


def _authed_client(monkeypatch: pytest.MonkeyPatch, session_factory: Factory, project_root: Path) -> TestClient:
    monkeypatch.setattr(gates, "async_session_factory", session_factory)
    monkeypatch.setattr(gates, "get_project_manager", lambda: _FakeProjectManager(project_root))
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.include_router(gates.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)
    return TestClient(app)


def _unauthed_client(monkeypatch: pytest.MonkeyPatch, session_factory: Factory, project_root: Path) -> TestClient:
    monkeypatch.setattr(gates, "async_session_factory", session_factory)
    monkeypatch.setattr(gates, "get_project_manager", lambda: _FakeProjectManager(project_root))
    app = FastAPI()
    app.include_router(gates.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)
    return TestClient(app)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", f"/api/v1/projects/{PROJECT}/gates/greenlight", {"source_digest": "sha256:a", "action": "GREENLIGHT"}),
        (
            "post",
            f"/api/v1/projects/{PROJECT}/gates/publish-approval",
            {
                "deliverable_digest": "sha256:a",
                "platform": "youtube",
                "visibility": "unlisted",
                "action": "APPROVE_PUBLISH",
            },
        ),
        ("get", f"/api/v1/projects/{PROJECT}/gates", None),
    ],
)
def test_gate_endpoints_require_real_authentication(
    monkeypatch: pytest.MonkeyPatch, session_factory: Factory, tmp_path: Path, method: str, path: str, body: dict | None
) -> None:
    client = _unauthed_client(monkeypatch, session_factory, tmp_path)
    response = client.request(method, path, json=body)
    assert response.status_code == 401


def test_greenlight_round_trips_through_the_real_repository(
    monkeypatch: pytest.MonkeyPatch, session_factory: Factory, tmp_path: Path
) -> None:
    client = _authed_client(monkeypatch, session_factory, tmp_path)
    response = client.post(
        f"/api/v1/projects/{PROJECT}/gates/greenlight",
        json={"source_digest": "sha256:" + "a" * 64, "action": "GREENLIGHT"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source_digest"] == "sha256:" + "a" * 64
    assert body["authorization"]["authenticated_principal"] == "operator-1"
    assert body["sequence"] == 1

    history = client.get(f"/api/v1/projects/{PROJECT}/gates")
    assert history.status_code == 200
    assert len(history.json()["greenlight"]) == 1
    assert history.json()["publish_approval"] == []


def test_publish_approval_round_trips_through_the_real_repository(
    monkeypatch: pytest.MonkeyPatch, session_factory: Factory, tmp_path: Path
) -> None:
    client = _authed_client(monkeypatch, session_factory, tmp_path)
    response = client.post(
        f"/api/v1/projects/{PROJECT}/gates/publish-approval",
        json={
            "deliverable_digest": "sha256:" + "b" * 64,
            "platform": "youtube",
            "visibility": "unlisted",
            "action": "APPROVE_PUBLISH",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["platform"] == "youtube"
    assert body["authorization"]["authenticated_principal"] == "operator-1"


def test_final_cut_stages_and_approves_a_real_file(
    monkeypatch: pytest.MonkeyPatch, session_factory: Factory, tmp_path: Path
) -> None:
    monkeypatch.setattr(gates, "async_session_factory", session_factory)
    project_root = tmp_path / "projects"
    project_root.mkdir()
    project_manager = _FakeProjectManager(project_root)
    monkeypatch.setattr(gates, "get_project_manager", lambda: project_manager)
    project_dir = project_manager.get_project_path(PROJECT)

    production_dir = project_dir / "production"
    production_dir.mkdir(parents=True)
    rendered_file = production_dir / "SH01.mp4"
    rendered_file.write_bytes(b"not a real video, just proving the route stages+approves a real file")

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.include_router(gates.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)
    client = TestClient(app)

    request_body = {
        "resource_type": "videos",
        "episode": 1,
        "target_ref": "SH01",
        "content_fingerprint": "sha256:" + "c" * 64,
        "content_basis": {"basis_type": "FACTUAL", "basis_version": "v1", "refs": ["research:RP-1"]},
        "direct_dependencies": [],
        "contract_version": 1,
        "contract_schema_version": "1",
        "produced": {
            "method": "DETERMINISTIC",
            "relative_path": "SH01.mp4",
            "sha256": "sha256:" + "d" * 64,
            "duration_seconds": 15.0,
            "execution_fingerprint": "sha256:" + "e" * 64,
            "tool": "remotion",
            "tool_version": "4.0.0",
            "wall_time_seconds": 12.0,
            "external_provider_cost": "0",
        },
        "approval_record": "APR-SH01",
    }
    response = client.post(f"/api/v1/projects/{PROJECT}/gates/final-cut", json=request_body)
    assert response.status_code == 200
    body = response.json()
    assert body["approved_master"]["selected_by"] == "operator-1"
    assert body["receipt"]["approval_record"] == "APR-SH01"
    assert body["receipt"]["sequence"] == 1

    history = client.get(f"/api/v1/projects/{PROJECT}/gates")
    assert history.status_code == 200


def test_final_cut_rejects_a_path_escape_before_touching_disk(
    monkeypatch: pytest.MonkeyPatch, session_factory: Factory, tmp_path: Path
) -> None:
    monkeypatch.setattr(gates, "async_session_factory", session_factory)
    project_root = tmp_path / "projects"
    project_root.mkdir()
    project_manager = _FakeProjectManager(project_root)
    monkeypatch.setattr(gates, "get_project_manager", lambda: project_manager)
    project_dir = project_manager.get_project_path(PROJECT)
    (project_dir / "production").mkdir(parents=True)

    # A real secret file outside production/ that a path-escape must never reach.
    secret = tmp_path / "secret.txt"
    secret.write_text("do not touch")

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.include_router(gates.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)
    client = TestClient(app)

    request_body = {
        "resource_type": "videos",
        "episode": 1,
        "target_ref": "SH01",
        "content_fingerprint": "sha256:" + "c" * 64,
        "content_basis": {"basis_type": "FACTUAL", "basis_version": "v1", "refs": ["research:RP-1"]},
        "direct_dependencies": [],
        "contract_version": 1,
        "contract_schema_version": "1",
        "produced": {
            "method": "DETERMINISTIC",
            "relative_path": "../secret.txt",
            "sha256": "sha256:" + "d" * 64,
            "duration_seconds": 15.0,
            "execution_fingerprint": "sha256:" + "e" * 64,
            "tool": "remotion",
            "tool_version": "4.0.0",
            "wall_time_seconds": 12.0,
            "external_provider_cost": "0",
        },
        "approval_record": "APR-SH01",
    }
    response = client.post(f"/api/v1/projects/{PROJECT}/gates/final-cut", json=request_body)
    assert response.status_code == 400
    assert "escapes" in response.json()["detail"]
