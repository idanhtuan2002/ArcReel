"""The M8 exploration API (plan M8-A fixed API surface)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.project_manager import ProjectManager
from r2.advanced_creative.digests import digest_payload
from r2.advanced_creative.lineage import resolve_episode_lineage
from r2.contracts.advanced_creative import (
    CanvasCandidate,
    ExplorationKind,
    ExplorationRevision,
    LineageBinding,
)
from server.auth import CurrentUserInfo, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import advanced_creative
from tests.auth_deps import AUTH_DEPENDENCIES

type Factory = async_sessionmaker[AsyncSession]

USER = CurrentUserInfo(id="default", sub="operator-1", role="admin")
PROJECT = "demo"
DIGEST = "sha256:" + "a" * 64
BASE = f"/api/v1/projects/{PROJECT}/m8/exploration"


@pytest.fixture
async def m8_client(monkeypatch: pytest.MonkeyPatch, session_factory: Factory):
    monkeypatch.setattr(advanced_creative, "async_session_factory", session_factory)
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.include_router(advanced_creative.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def _canvas_revision(*, project: str = PROJECT, created_by: str = "default") -> dict[str, object]:
    payload = CanvasCandidate(
        kind=ExplorationKind.CANVAS,
        graph_schema_version="1",
        nodes=(),
        edges=(),
        groups=(),
        storyboard_order=(),
        viewport_bookmarks=(),
    )
    lineage = LineageBinding(
        project_name=project,
        content_basis_digest=DIGEST,
        approved_master_id=None,
        approved_master_digest=None,
        creative_profile_id="profile",
        creative_profile_version="1",
        policy_digest=DIGEST,
    )
    revision = ExplorationRevision(
        candidate_id="c-1",
        revision=1,
        kind=ExplorationKind.CANVAS,
        parent_revision=None,
        payload=payload,
        payload_digest=digest_payload(payload, lineage),
        lineage=lineage,
        created_by=created_by,
        created_at=datetime(2026, 9, 29, 12, 0, tzinfo=UTC),
    )
    return revision.model_dump(mode="json")


def _append_body(**overrides: object) -> dict[str, object]:
    return {"candidate": _canvas_revision(**overrides), "expected_head_version": None, "command_id": "cmd-1"}


async def test_append_returns_the_head_and_an_exact_replay_is_byte_identical(m8_client: AsyncClient) -> None:
    first = await m8_client.post(f"{BASE}/revisions", json=_append_body())
    again = await m8_client.post(f"{BASE}/revisions", json=_append_body())

    assert first.status_code == 200, first.text
    assert first.json() == {"candidate_id": "c-1", "current_revision": 1, "head_version": 1}
    assert again.content == first.content


async def test_a_reused_command_for_another_request_is_a_command_conflict(m8_client: AsyncClient) -> None:
    assert (await m8_client.post(f"{BASE}/revisions", json=_append_body())).status_code == 200
    other = _append_body()
    other["candidate"]["candidate_id"] = "c-2"  # type: ignore[index]

    response = await m8_client.post(f"{BASE}/revisions", json=other)

    assert response.status_code == 409


@pytest.mark.parametrize("override", [{"project": "other"}, {"created_by": "someone-else"}])
async def test_a_body_cannot_inject_another_scope(m8_client: AsyncClient, override: dict[str, str]) -> None:
    response = await m8_client.post(f"{BASE}/revisions", json=_append_body(**override))

    assert response.status_code == 404


async def test_a_foreign_revision_is_indistinguishable_from_an_unknown_one(m8_client: AsyncClient) -> None:
    assert (await m8_client.post(f"{BASE}/revisions", json=_append_body())).status_code == 200

    foreign = await m8_client.get("/api/v1/projects/other/m8/exploration/candidates/c-1/revisions/1")
    unknown = await m8_client.get(f"{BASE}/candidates/missing/revisions/1")
    own = await m8_client.get(f"{BASE}/candidates/c-1/revisions/1")

    assert (foreign.status_code, unknown.status_code, own.status_code) == (404, 404, 200)
    assert foreign.json() == unknown.json()


async def test_the_head_reports_the_current_revision_and_hides_foreign_candidates(m8_client: AsyncClient) -> None:
    assert (await m8_client.post(f"{BASE}/revisions", json=_append_body())).status_code == 200

    own = await m8_client.get(f"{BASE}/candidates/c-1")
    foreign = await m8_client.get("/api/v1/projects/other/m8/exploration/candidates/c-1")
    unknown = await m8_client.get(f"{BASE}/candidates/missing")

    assert own.status_code == 200
    assert own.json() == {"candidate_id": "c-1", "current_revision": 1, "head_version": 1}
    assert (foreign.status_code, unknown.status_code) == (404, 404)
    assert foreign.json() == unknown.json()


async def test_a_genesis_reusing_a_foreign_id_is_indistinguishable_from_a_new_one(m8_client: AsyncClient) -> None:
    assert (await m8_client.post(f"{BASE}/revisions", json=_append_body())).status_code == 200
    other = "/api/v1/projects/other/m8/exploration"
    reused = _append_body(project="other")
    fresh = _append_body(project="other")
    fresh["candidate"]["candidate_id"] = "c-new"  # type: ignore[index]
    fresh["command_id"] = "cmd-2"

    reused_response = await m8_client.post(f"{other}/revisions", json=reused)
    fresh_response = await m8_client.post(f"{other}/revisions", json=fresh)
    own_history = await m8_client.get(f"{BASE}/candidates/c-1/revisions")

    assert (reused_response.status_code, fresh_response.status_code) == (200, 200)
    assert reused_response.json() == {"candidate_id": "c-1", "current_revision": 1, "head_version": 1}
    assert [item["lineage"]["project_name"] for item in own_history.json()] == [PROJECT]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "after_revision=-1"])
async def test_pagination_bounds_are_validated(m8_client: AsyncClient, query: str) -> None:
    response = await m8_client.get(f"{BASE}/candidates/c-1/revisions?{query}")

    assert response.status_code == 422


async def test_history_lists_revisions_in_order(m8_client: AsyncClient) -> None:
    assert (await m8_client.post(f"{BASE}/revisions", json=_append_body())).status_code == 200

    response = await m8_client.get(f"{BASE}/candidates/c-1/revisions?limit=10")

    assert response.status_code == 200
    assert [item["revision"] for item in response.json()] == [1]


async def test_a_canvas_preview_is_an_unavailable_target(m8_client: AsyncClient) -> None:
    assert (await m8_client.post(f"{BASE}/revisions", json=_append_body())).status_code == 200

    response = await m8_client.post(
        f"{BASE}/promotion-previews",
        json={
            "candidate_id": "c-1",
            "revision": 1,
            "target": {"kind": "ARTIFACT_SLOT", "target_ref": "m8-slot:x", "expected_target_version": 1},
            "command_id": "p-1",
        },
    )

    assert response.status_code == 409


async def test_a_malformed_body_is_a_validation_error(m8_client: AsyncClient) -> None:
    response = await m8_client.post(f"{BASE}/revisions", json={"candidate": {}, "command_id": "x"})

    assert response.status_code == 422


async def test_a_promotion_for_an_unknown_preview_is_not_found(m8_client: AsyncClient) -> None:
    response = await m8_client.post(
        f"{BASE}/promotions",
        json={
            "authorization": {
                "command_id": "promote-1",
                "project_name": PROJECT,
                "preview_id": "missing",
                "preview_digest": DIGEST,
                "actor_id": "default",
                "actor_scope": "default",
                "decision": "APPROVE",
                "authorized_at": "2026-09-29T12:00:00Z",
            },
            "expected_candidate_head_version": 1,
        },
    )

    assert response.status_code == 404


def _project(root: Path, episodes: list[dict[str, object]], scripts: dict[str, bytes]) -> ProjectManager:
    project_dir = root / PROJECT
    (project_dir / "scripts").mkdir(parents=True)
    (project_dir / "project.json").write_text(json.dumps({"title": PROJECT, "episodes": episodes}), encoding="utf-8")
    for name, data in scripts.items():
        (project_dir / "scripts" / name).write_bytes(data)
    return ProjectManager(root)


async def test_the_context_binds_the_indexed_script_and_the_session_author(
    m8_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    projects = _project(
        tmp_path,
        [{"episode": 1, "script_file": "scripts/episode_1.json"}, {"episode": 2, "script_file": "episode_2.json"}],
        {"episode_1.json": b"one", "episode_2.json": b"two"},
    )
    monkeypatch.setattr(advanced_creative, "get_project_manager", lambda: projects)

    first = await m8_client.get(f"{BASE}/context", params={"episode": 1})
    second = await m8_client.get(f"{BASE}/context", params={"episode": 2})

    assert first.status_code == 200
    assert first.json() == {
        "lineage": resolve_episode_lineage(PROJECT, 1, b"one").model_dump(mode="json"),
        "created_by": USER.id,
    }
    assert second.json()["lineage"] == resolve_episode_lineage(PROJECT, 2, b"two").model_dump(mode="json")


@pytest.mark.parametrize(
    ("episodes", "episode"),
    [
        ([{"episode": 1, "script_file": "episode_1.json"}], 2),
        ([{"episode": 1}], 1),
        ([{"episode": 1, "script_file": "missing.json"}], 1),
        ([{"episode": 1, "script_file": "../project.json"}], 1),
    ],
    ids=["unindexed-episode", "no-script-file", "missing-script", "script-outside-scripts"],
)
async def test_an_episode_without_a_readable_indexed_script_has_no_context(
    m8_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    episodes: list[dict[str, object]],
    episode: int,
) -> None:
    projects = _project(tmp_path, episodes, {"episode_1.json": b"one"})
    monkeypatch.setattr(advanced_creative, "get_project_manager", lambda: projects)

    response = await m8_client.get(f"{BASE}/context", params={"episode": episode})

    assert response.status_code == 404


@pytest.mark.parametrize(
    "metadata",
    [{"title": PROJECT, "episodes": 42}, {"title": PROJECT, "episodes": [1, "x", None]}, [1, 2]],
    ids=["episodes-not-a-list", "episode-entries-not-objects", "metadata-not-an-object"],
)
async def test_malformed_project_metadata_has_no_context(
    m8_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, metadata: object
) -> None:
    projects = _project(tmp_path, [], {})
    (tmp_path / PROJECT / "project.json").write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(advanced_creative, "get_project_manager", lambda: projects)

    response = await m8_client.get(f"{BASE}/context", params={"episode": 1})

    assert response.status_code == 404


async def test_a_script_symlink_leaving_the_scripts_directory_has_no_context(
    m8_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    projects = _project(tmp_path, [{"episode": 1, "script_file": "episode_1.json"}], {})
    (tmp_path / "secret.json").write_bytes(b"secret")
    (tmp_path / PROJECT / "scripts" / "episode_1.json").symlink_to(tmp_path / "secret.json")
    monkeypatch.setattr(advanced_creative, "get_project_manager", lambda: projects)

    response = await m8_client.get(f"{BASE}/context", params={"episode": 1})

    assert response.status_code == 404


async def test_a_padded_project_name_has_no_context(
    m8_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    projects = _project(tmp_path, [{"episode": 1, "script_file": "episode_1.json"}], {"episode_1.json": b"one"})
    monkeypatch.setattr(advanced_creative, "get_project_manager", lambda: projects)

    padded = await m8_client.get(f"/api/v1/projects/%20{PROJECT}%20/m8/exploration/context", params={"episode": 1})
    own = await m8_client.get(f"{BASE}/context", params={"episode": 1})

    assert (padded.status_code, own.status_code) == (404, 200)
    assert padded.json() == (await m8_client.get(f"{BASE}/context", params={"episode": 9})).json()


async def test_an_unknown_project_has_no_context(
    m8_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(advanced_creative, "get_project_manager", lambda: ProjectManager(tmp_path))

    response = await m8_client.get(f"{BASE}/context", params={"episode": 1})

    assert response.status_code == 404


@pytest.mark.parametrize("query", ["", "?episode=0", "?episode=x"])
async def test_the_context_episode_is_validated(m8_client: AsyncClient, query: str) -> None:
    response = await m8_client.get(f"{BASE}/context{query}")

    assert response.status_code == 422
