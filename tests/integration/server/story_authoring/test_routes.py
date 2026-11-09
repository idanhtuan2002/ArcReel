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
        language_after_send = projects.load_project(PROJECT).get("source_language")
        projects.update_project(PROJECT, lambda project: project.pop("source_language", None))
        repeated = await client.post(handoff, json={"command_id": "cmd-00000001"})
        language_after_replay = projects.load_project(PROJECT).get("source_language")
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
    assert (language_after_send, language_after_replay) == ("vi", "vi")
    assert repeated.json() == sent.json()
    assert (withdrawn.status_code, withdrawn.json()["phase"]) == (200, "WITHDRAWN")
    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "ALREADY_HANDED_OFF")


async def test_a_book_brief_is_drafted_over_http_and_the_project_has_no_book_yet(
    concurrent_session_factory: Factory, grants, projects: ProjectManager
):
    provider_id = await _provider(concurrent_session_factory)
    async with _client(concurrent_session_factory, grants, projects, interactive=False) as client:
        drafted = await client.post(
            f"/api/v1/projects/{PROJECT}/story-runs/brief",
            json={
                "idea": "Một người con về làng.",
                "genre": "đời thường",
                "provider_id": provider_id,
                "model_id": MODEL,
                "book": {"chapters": 30, "part_chapters": 5},
            },
        )
        refused = await client.post(
            f"/api/v1/projects/{PROJECT}/story-runs/brief",
            json={"genre": "g", "provider_id": provider_id, "model_id": MODEL, "book": {"chapters": 3}},
        )
        book = await client.get(f"/api/v1/projects/{PROJECT}/story-book")

    assert drafted.status_code == 200, drafted.text
    assert drafted.json()["brief"]["book"] == {
        "spec": {"chapters": 30, "chapter_syllables": 3000, "part_chapters": 5},
        "part": 1,
        "state_digest": None,
    }
    assert refused.status_code == 422
    assert book.json() == {"book": None}


async def test_the_source_preview_lists_the_chapters_a_run_would_read(
    concurrent_session_factory: Factory, grants, projects: ProjectManager
):
    source = projects.get_project_path(PROJECT) / "source"
    source.mkdir(parents=True, exist_ok=True)
    (source / "truyen.txt").write_text("Chương 1\nMinh về làng.\n\nChương 2\nLan đợi.", encoding="utf-8")
    async with _client(concurrent_session_factory, grants, projects, interactive=False) as client:
        response = await client.get(f"/api/v1/projects/{PROJECT}/story-sources/preview")

    assert response.status_code == 200, response.text
    [preview] = response.json()["sources"]
    assert (preview["rel_path"], preview["chapters"], preview["headings"], preview["warnings"]) == (
        "source/truyen.txt",
        2,
        ["Chương 1", "Chương 2"],
        [],
    )


async def test_a_story_translation_is_queued_for_the_projects_showrunner(
    concurrent_session_factory: Factory, grants, projects: ProjectManager, monkeypatch
):
    queued: list[tuple[str, str, str]] = []

    async def translate(request, scope, caller, services):
        from server.tool_runtime import ToolOutcome

        queued.append((request.value.target_language, scope.project_name, caller.source))
        return ToolOutcome(value={"batch_id": "b"})

    monkeypatch.setattr(story_runs, "translate_story", translate)
    monkeypatch.setattr(story_runs, "get_project_manager", lambda: projects)
    async with _client(concurrent_session_factory, grants, projects, interactive=True) as client:
        response = await client.post(f"/api/v1/projects/{PROJECT}/story-translations", json={"target_language": "en"})
        refused = await client.post(f"/api/v1/projects/{PROJECT}/story-translations", json={"target_language": "xx"})

    assert response.status_code == 200, response.text
    assert response.json() == {"queued": True, "target_language": "en"}
    assert queued == [("en", PROJECT, "mcp")]
    assert refused.status_code == 422


async def test_a_film_project_imports_its_story_projects_text_without_overwriting_its_own(
    concurrent_session_factory: Factory, grants, projects: ProjectManager, monkeypatch
):
    import json as _json

    from server.tool_runtime import CallerContext, CreateProjectToolRequest, Services, ToolRequest, create_project

    class _Unused:
        pass

    created = await create_project(
        ToolRequest(
            CreateProjectToolRequest(
                name="ben-do", title="Bến đò", content_mode="narration", generation_mode="storyboard"
            )
        ),
        CallerContext(user_id=USER, source="embedded"),
        Services(projects=projects, workflow_planner=_Unused(), capabilities=_Unused()),
    )
    assert created.problem is None
    story_dir = projects.get_project_path("ben-do")
    story_json = story_dir / "project.json"
    story_json.write_text(
        _json.dumps({**_json.loads(story_json.read_text()), "project_kind": "story"}), encoding="utf-8"
    )
    (story_dir / "source").mkdir(exist_ok=True)
    (story_dir / "source" / "phan-1.txt").write_text("Chương 1\nMinh về làng.", encoding="utf-8")
    (story_dir / "source" / "phan-2.md").write_text("Chương 2\nLan đợi.", encoding="utf-8")
    film_json = projects.get_project_path(PROJECT) / "project.json"
    film_json.write_text(
        _json.dumps({**_json.loads(film_json.read_text()), "story_project": "ben-do"}), encoding="utf-8"
    )
    film_source = projects.get_project_path(PROJECT) / "source"
    film_source.mkdir(exist_ok=True)
    (film_source / "phan-2.txt").write_text("Bản khác của chương 2.", encoding="utf-8")

    monkeypatch.setattr(story_runs, "get_project_manager", lambda: projects)
    async with _client(concurrent_session_factory, grants, projects, interactive=True) as client:
        first = await client.post(f"/api/v1/projects/{PROJECT}/story-sync")
        again = await client.post(f"/api/v1/projects/{PROJECT}/story-sync")

    assert first.status_code == 200, first.text
    assert first.json() == {
        "story_project": "ben-do",
        "imported": ["phan-1.txt"],
        "skipped": [],
        "conflicts": ["phan-2.txt"],
    }
    assert (film_source / "phan-1.txt").read_text(encoding="utf-8").startswith("Chương 1")
    assert (film_source / "phan-2.txt").read_text(encoding="utf-8") == "Bản khác của chương 2."
    assert again.json()["skipped"] == ["phan-1.txt"]
