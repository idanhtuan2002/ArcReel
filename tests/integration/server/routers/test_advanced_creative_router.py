"""The M8 exploration API (plan M8-A fixed API surface)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from r2.advanced_creative.digests import digest_payload
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
