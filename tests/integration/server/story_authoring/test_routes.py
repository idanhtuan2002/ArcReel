"""Story run routes: authentication kinds, the refusal mapping and one run through HTTP to export and hand-off."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.project_manager import ProjectManager
from server.auth import CurrentUserInfo, get_current_interactive_user, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import story_runs
from server.story_authoring.service import StoryRunRef, run_id_for
from tests.auth_deps import AUTH_DEPENDENCIES
from tests.integration.server.story_authoring.test_driver import MODEL, ScriptedModel
from tests.integration.server.story_authoring.test_executor import _provider
from tests.integration.server.story_authoring.test_service import (
    PROJECT,
    SPONSOR,
    USER,
    _execute,
    _greenlight,
    _service,
)

type Factory = async_sessionmaker[AsyncSession]

HUMAN = CurrentUserInfo(id=USER, sub=SPONSOR, role="user")


def _client(factory: Factory, grants, projects: ProjectManager, *, interactive: bool) -> AsyncClient:
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: HUMAN
    if interactive:
        app.dependency_overrides[get_current_interactive_user] = lambda: HUMAN
    app.dependency_overrides[story_runs.story_service] = lambda: _service(factory, grants, projects)
    app.include_router(story_runs.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _draft(client: AsyncClient, provider_id: str) -> dict:
    response = await client.post(
        f"/api/v1/projects/{PROJECT}/story-runs/brief",
        json={"idea": "Một người con về làng.", "genre": "đời thường", "provider_id": provider_id, "model_id": MODEL},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_changing_a_run_needs_an_interactive_session(
    concurrent_session_factory: Factory, grants, projects: ProjectManager
):
    provider_id = await _provider(concurrent_session_factory)
    async with _client(concurrent_session_factory, grants, projects, interactive=False) as client:
        drafted = await _draft(client, provider_id)
        decision = await _greenlight(concurrent_session_factory, drafted["brief_digest"])
        start = await client.post(
            f"/api/v1/projects/{PROJECT}/story-runs",
            json={"brief": drafted["brief"], "gate_a_decision_id": decision},
        )
        approve = await client.post(
            f"/api/v1/projects/{PROJECT}/story-runs/{run_id_for(decision)}/approve", json={"manifest_digest": "x"}
        )

    assert (start.status_code, approve.status_code) == (401, 401)


async def test_refusals_map_to_stable_codes(concurrent_session_factory: Factory, grants, projects: ProjectManager):
    provider_id = await _provider(concurrent_session_factory)
    async with _client(concurrent_session_factory, grants, projects, interactive=True) as client:
        drafted = await _draft(client, provider_id)
        missing_gate = await client.post(
            f"/api/v1/projects/{PROJECT}/story-runs",
            json={"brief": drafted["brief"], "gate_a_decision_id": "no-such-decision"},
        )
        unknown_run = await client.get(f"/api/v1/projects/{PROJECT}/story-runs/story-none")
        bad_action = await client.post(f"/api/v1/projects/{PROJECT}/story-runs/story-none/explode")
        bad_route = await client.post(
            f"/api/v1/projects/{PROJECT}/story-runs/brief",
            json={"idea": "x", "genre": "y", "provider_id": "openai", "model_id": MODEL},
        )

    assert (missing_gate.status_code, missing_gate.json()["detail"]["code"]) == (409, "GATE_A_MISSING")
    assert (unknown_run.status_code, unknown_run.json()["detail"]["code"]) == (404, "RUN_NOT_FOUND")
    assert bad_action.status_code == 422
    assert (bad_route.status_code, bad_route.json()["detail"]["code"]) == (422, "ROUTE_NOT_QUALIFIED")


async def test_a_run_started_over_http_is_approved_exported_and_handed_off(
    concurrent_session_factory: Factory, grants, projects: ProjectManager, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(story_runs, "get_project_manager", lambda: projects)
    provider_id = await _provider(concurrent_session_factory)
    async with _client(concurrent_session_factory, grants, projects, interactive=True) as client:
        drafted = await _draft(client, provider_id)
        decision = await _greenlight(concurrent_session_factory, drafted["brief_digest"])
        started = await client.post(
            f"/api/v1/projects/{PROJECT}/story-runs",
            json={"brief": drafted["brief"], "gate_a_decision_id": decision},
        )
        assert started.status_code == 200, started.text
        run_id = started.json()["run_id"]
        service = _service(concurrent_session_factory, grants, projects)
        ref, _ = await service.get(user_id=USER, project_name=PROJECT, run_id=run_id)
        await _execute(
            concurrent_session_factory, StoryRunRef(run_id, ref.task_id, ref.brief), projects, ScriptedModel()
        )

        run = (await client.get(f"/api/v1/projects/{PROJECT}/story-runs/{run_id}")).json()
        listed = (await client.get(f"/api/v1/projects/{PROJECT}/story-runs")).json()
        stale = await client.post(
            f"/api/v1/projects/{PROJECT}/story-runs/{run_id}/approve",
            json={"manifest_digest": "sha256:" + "0" * 64, "accepted_exceptions": run["offered"]["exceptions_offered"]},
        )
        approved = await client.post(
            f"/api/v1/projects/{PROJECT}/story-runs/{run_id}/approve",
            json={
                "manifest_digest": run["offered"]["manifest_digest"],
                "accepted_exceptions": run["offered"]["exceptions_offered"],
            },
        )
        export = await client.get(f"/api/v1/projects/{PROJECT}/story-runs/{run_id}/export")
        handoff = f"/api/v1/projects/{PROJECT}/story-runs/{run_id}/send-to-video"
        sent = await client.post(handoff, json={"command_id": "cmd-00000001"})
        repeated = await client.post(handoff, json={"command_id": "cmd-00000001"})
        withdrawn = await client.post(f"/api/v1/projects/{PROJECT}/story-runs/{run_id}/withdraw")
        refused = await client.post(handoff, json={"command_id": "cmd-00000002"})

    assert run["phase"] == "READY_FOR_APPROVAL"
    assert [(r["run_id"], r["phase"], r["genre"]) for r in listed["runs"]] == [
        (run_id, "READY_FOR_APPROVAL", "đời thường")
    ]
    assert run["brief_digest"] == drafted["brief_digest"]
    assert len(run["offered"]["scenes"]) == 9
    assert (stale.status_code, stale.json()["detail"]["code"]) == (409, "STALE_MANIFEST")
    assert (approved.status_code, approved.json()["phase"]) == (200, "COMMITTED")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/markdown")
    assert export.text.startswith("# Căn nhà cũ\n")
    assert (sent.status_code, sent.json()["path"]) == (200, "source/can-nha-cu.txt"), sent.text
    assert projects.load_project(PROJECT)["source_language"] == "vi"
    assert repeated.json() == sent.json()
    assert (withdrawn.status_code, withdrawn.json()["phase"]) == (200, "WITHDRAWN")
    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "ALREADY_HANDED_OFF")
