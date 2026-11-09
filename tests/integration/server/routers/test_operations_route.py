"""ADR-0122: one read of what needs the operator across projects."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.task_repo import STORY_RUN_TASK_TYPE, TaskRepository
from lib.project_manager import ProjectManager
from server.auth import CurrentUserInfo, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import operations
from tests.auth_deps import AUTH_DEPENDENCIES

type Factory = async_sessionmaker[AsyncSession]
USER = CurrentUserInfo(id="default", sub="sponsor", role="admin")


async def test_story_runs_and_tasks_fall_into_lanes_with_project_titles(
    monkeypatch: pytest.MonkeyPatch, session_factory: Factory, tmp_path: Path
) -> None:
    for name, title, kind in (("truyen-a", "Truyện A", "story"), ("phim-b", "Phim B", None)):
        (tmp_path / name).mkdir()
        data = {"title": title, "episodes": [], **({"project_kind": kind} if kind else {})}
        (tmp_path / name / "project.json").write_text(json.dumps(data), encoding="utf-8")
    async with session_factory() as session:
        repo = TaskRepository(session)
        story = await repo.enqueue(
            project_name="truyen-a", task_type=STORY_RUN_TASK_TYPE, media_type="text", resource_id="story-1"
        )
        state = {"schema_id": "s", "state_version": 1, "run_id": "story-1", "phase": "READY_FOR_APPROVAL"}
        await repo.write_story_run_state(
            story["task_id"], expected_version=None, state_json=json.dumps(state, separators=(",", ":")), new_version=1
        )
        await repo.enqueue(project_name="phim-b", task_type="image", media_type="image", resource_id="E1S01")
        await session.commit()
    monkeypatch.setattr(operations, "async_session_factory", session_factory)
    monkeypatch.setattr(operations, "get_project_manager", lambda: ProjectManager(tmp_path))
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.include_router(operations.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        body = (await http.get("/api/v1/operations")).json()

    assert body["counts"] == {"decision": 1, "blocked": 0, "running": 0, "tasks": 1}
    [decision] = body["lanes"]["decision"]
    assert (decision["project"], decision["title"], decision["project_kind"], decision["state"]) == (
        "truyen-a",
        "Truyện A",
        "story",
        "READY_FOR_APPROVAL",
    )
    assert body["tasks"] == [{"project": "phim-b", "title": "Phim B", "tasks": 1}]
