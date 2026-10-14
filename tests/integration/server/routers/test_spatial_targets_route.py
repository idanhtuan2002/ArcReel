"""Shot targets: registration from an admitted screenplay, and each target's workflow state."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.auth import get_current_user
from server.error_handlers import register_error_handlers
from server.routers import spatial_targets
from tests.auth_deps import AUTH_DEPENDENCIES
from tests.fakes import GateProjectManager
from tests.integration.r2.adaptation import test_screenplay_admission as admission_helpers
from tests.integration.r2.target_registry import test_take_registration as target_helpers
from tests.integration.server.routers.spatial_approval_support import approved_location
from tests.integration.server.routers.test_gates_export import PROJECT, USER
from tests.integration.server.routers.test_spatial_constraint_snapshot import _current_binding

type Factory = async_sessionmaker[AsyncSession]

URL = f"/api/v1/projects/{PROJECT}/m8/spatial"
_EMPTY_BINDING_FIELDS = {
    "binding_id": None,
    "binding_version": None,
    "snapshot_digest": None,
    "target_registry_version": None,
    "has_spatial_set": False,
}


def _client(monkeypatch: pytest.MonkeyPatch, factory: Factory, project_dir: Path, grants=None) -> AsyncClient:
    monkeypatch.setattr(spatial_targets, "async_session_factory", factory)
    monkeypatch.setattr(spatial_targets, "get_project_manager", lambda: GateProjectManager(project_dir.parent))
    app = FastAPI()
    app.state.governance_grants = grants
    app.dependency_overrides[get_current_user] = lambda: USER
    app.include_router(spatial_targets.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_registration_registers_the_admitted_take_targets_and_replays(
    project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(admission_helpers, "USER", USER.id)
    monkeypatch.setattr(admission_helpers, "PROJECT", PROJECT)
    ref, *_ = await target_helpers._admit(session_factory)
    body = {"command_id": "take-1", "admitted_screenplay_ref": ref.model_dump(mode="json")}
    stale_ref = ref.model_dump(mode="json")
    stale_ref["admission_ref"]["decision_id"] = "d-unknown"

    async with _client(monkeypatch, session_factory, project_dir) as http:
        first = await http.post(f"{URL}/target-registrations", json=body)
        replay = await http.post(f"{URL}/target-registrations", json=body)
        stale = await http.post(
            f"{URL}/target-registrations", json={"command_id": "take-2", "admitted_screenplay_ref": stale_ref}
        )
        listed = await http.get(f"{URL}/targets")

    assert first.status_code == 200, first.text
    assert replay.json() == first.json()
    assert stale.status_code == 409
    [state] = listed.json()
    assert state["target_ref"] == first.json()["shot_targets"][0]
    assert state["binding"] == {"status": "none", **_EMPTY_BINDING_FIELDS}
    assert state["pair"]["status"] == "unavailable"
    assert (state["shot"], state["master_version"]) == (None, None)


@pytest.mark.asyncio
async def test_the_state_follows_binding_and_pair_approval(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = await approved_location(gate_export_client, project_dir, session_factory, monkeypatch)

    async with _client(monkeypatch, session_factory, project_dir, approved.grants) as http:
        [state] = (await http.get(f"{URL}/targets")).json()
    async with _client(monkeypatch, session_factory, project_dir) as http:
        [without_grants] = (await http.get(f"{URL}/targets")).json()

    assert state["target_ref"]["target_id"] == approved.target_id
    assert state["location_ref"] == "location:room-1"
    binding = state["binding"]
    assert (binding["status"], binding["binding_id"], binding["binding_version"]) == (
        "current",
        approved.binding_id,
        1,
    )
    assert binding["snapshot_digest"].startswith("sha256:")
    assert binding["has_spatial_set"] is False
    pair = state["pair"]
    assert (pair["status"], pair["binding_version"]) == ("approved", 1)
    assert [view["role"] for view in pair["views"]] == ["MASTER", "REVERSE"]
    assert without_grants["pair"]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_a_target_whose_bound_frame_bytes_changed_reads_stale(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _binding_id, _target_id = await _current_binding(gate_export_client, project_dir, session_factory, monkeypatch)
    async with _client(monkeypatch, session_factory, project_dir) as http:
        [before] = (await http.get(f"{URL}/targets")).json()
        for frame in (project_dir / "spatial" / "frames").glob("*.png"):
            frame.write_bytes(b"not the bound frame")
        [after] = (await http.get(f"{URL}/targets")).json()

    assert before["binding"]["status"] == "current"
    assert after["binding"] == {"status": "stale", **_EMPTY_BINDING_FIELDS}
