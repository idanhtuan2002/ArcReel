"""The M8-C human steps through their routes: binding, review, pair decision and typed promotion."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.auth import CurrentUserInfo, get_current_interactive_user, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import spatial_review
from server.services.advanced_creative import exploration_service
from server.services.location_binding_snapshot import CurrentLocationBindingSnapshotReader
from server.services.spatial_execution import SpatialFrameRef
from tests.auth_deps import AUTH_DEPENDENCIES
from tests.fakes import GateProjectManager
from tests.integration.server.routers.spatial_approval_support import (
    PAIR_V2_VECTOR,
    showrunner_grants,
)
from tests.integration.server.routers.test_gates_export import PROJECT, USER
from tests.integration.server.routers.test_spatial_constraint_snapshot import registered_frames
from tests.integration.server.routers.test_spatial_execution import _command, _service, _Vision

type Factory = async_sessionmaker[AsyncSession]

REVIEWER = CurrentUserInfo(id=USER.id, sub=USER.sub, role="user")
BASE = f"/api/v1/projects/{PROJECT}/m8/spatial"


def _app(monkeypatch: pytest.MonkeyPatch, factory: Factory, project_dir: Path, grants, *, interactive: bool) -> FastAPI:
    monkeypatch.setattr(spatial_review, "async_session_factory", factory)
    monkeypatch.setattr(spatial_review, "get_project_manager", lambda: GateProjectManager(project_dir.parent))
    app = FastAPI()
    app.state.governance_grants = grants
    app.dependency_overrides[get_current_user] = lambda: USER
    if interactive:
        app.dependency_overrides[get_current_interactive_user] = lambda: REVIEWER
    app.include_router(spatial_review.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def review_client(
    monkeypatch: pytest.MonkeyPatch, session_factory: Factory, project_dir: Path
) -> AsyncIterator[AsyncClient]:
    grants = await showrunner_grants(session_factory)
    async with _client(_app(monkeypatch, session_factory, project_dir, grants, interactive=True)) as http:
        yield http


async def _bound(gate_client, review_client, project_dir, factory, monkeypatch) -> dict:
    target_ref, receipts = await registered_frames(gate_client, project_dir, factory, monkeypatch, shot_duration=5.0)
    response = await review_client.post(
        f"{BASE}/bindings",
        json={"command_id": "binding-1", "expected_target_ref": target_ref, "ordered_frame_receipts": receipts},
    )
    assert response.status_code == 200, response.text
    return {"target_id": target_ref["target_id"], "binding": response.json()}


async def _reviewed(review_client: AsyncClient, target_id: str) -> dict:
    opened = await review_client.post(f"{BASE}/review-sessions", json={"target_id": target_id})
    assert opened.status_code == 200, opened.text
    snapshot = opened.json()
    for frame in snapshot["frames"]:
        served = await review_client.get(f"{BASE}/review-sessions/{snapshot['session_id']}/frames/{frame['role']}")
        assert served.status_code == 200, served.text
        assert served.headers["cache-control"] == "no-store"
        digest = "sha256:" + hashlib.sha256(served.content).hexdigest()
        assert digest == frame["png_digest"] == served.headers["x-review-png-digest"]
        acknowledged = await review_client.post(
            f"{BASE}/review-sessions/{snapshot['session_id']}/acknowledgments",
            json={
                "attempt_id": served.headers["x-review-attempt-id"],
                "role": frame["role"],
                "png_digest": digest,
                "decoded": True,
            },
        )
        assert acknowledged.status_code == 200, acknowledged.text
    return snapshot


def _decision_body(snapshot: dict, **overrides: object) -> dict:
    body = {
        "command_id": "pair-approve-1",
        "review_session_id": snapshot["session_id"],
        "expected_scene_ref": snapshot["scene_ref"],
        "expected_target_ref": snapshot["target_ref"],
        "binding_id": snapshot["binding_id"],
        "expected_binding_version": snapshot["binding_version"],
        "expected_envelope_digest": snapshot["envelope_digest"],
        "expected_core_digest": snapshot["core_digest"],
        "views": [
            {"role": frame["role"], "receipt_id": frame["receipt_id"], "receipt_digest": frame["receipt_digest"]}
            for frame in snapshot["frames"]
        ],
        "decision": "APPROVE",
        "observations": PAIR_V2_VECTOR["body"]["command"]["observations"],
    }
    body.update(overrides)
    return body


async def _visible_ids(factory: Factory) -> tuple[str, ...]:
    async with factory() as session:
        revision = await exploration_service(session).get_exact(
            user_id=USER.id, project_name=PROJECT, candidate_id="spatial-candidate-1", revision=1
        )
    by_subject = {a.subject_refs[0]: a.assertion_id for a in revision.payload.spatial.assertions if a.subject_refs}
    return (by_subject["red fire extinguisher cabinet"], by_subject["blue exit door"])


@pytest.mark.asyncio
async def test_the_human_steps_run_through_the_routes_to_a_promoted_binding(
    gate_export_client: AsyncClient,
    review_client: AsyncClient,
    project_dir: Path,
    session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound = await _bound(gate_export_client, review_client, project_dir, session_factory, monkeypatch)
    snapshot = await _reviewed(review_client, bound["target_id"])

    decided = await review_client.post(f"{BASE}/pair-decisions", json=_decision_body(snapshot))
    assert decided.status_code == 200, decided.text
    assert decided.json()["review_session_id"] == snapshot["session_id"]

    frames = {frame["role"]: frame for frame in snapshot["frames"]}
    await _service(session_factory, project_dir, _Vision()).execute(
        _command(
            *(
                SpatialFrameRef(receipt_id=frames[role]["receipt_id"], receipt_digest=frames[role]["receipt_digest"])
                for role in ("MASTER", "REVERSE")
            )
        )
    )
    previewed = await review_client.post(
        f"{BASE}/promotion-previews",
        json={
            "command_id": "preview-1",
            "candidate_id": "spatial-candidate-1",
            "candidate_revision": 1,
            "target_id": bound["target_id"],
            "expected_binding_version": 1,
            "selected_assertion_ids": list(await _visible_ids(session_factory)),
        },
    )
    assert previewed.status_code == 200, previewed.text
    preview = previewed.json()
    promote = {
        "command_id": "promote-1",
        "preview_id": preview["preview"]["base_preview"]["preview_id"],
        "preview_digest": preview["preview_digest"],
        "expected_candidate_head_version": 1,
    }

    promoted = await review_client.post(f"{BASE}/promotions", json=promote)
    replayed = await review_client.post(f"{BASE}/promotions", json=promote)
    changed = await review_client.post(f"{BASE}/promotions", json=promote | {"preview_digest": "sha256:" + "0" * 64})

    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["result"]["binding_version"] == 2
    assert replayed.status_code == 200, replayed.text
    assert replayed.json() == promoted.json()
    assert changed.status_code == 409
    current = await CurrentLocationBindingSnapshotReader(
        session_factory=session_factory, project_dir=project_dir
    ).read_current(user_id=USER.id, project_name=PROJECT, target_id=bound["target_id"])
    assert current.spatial_set is not None


@pytest.mark.asyncio
async def test_a_stale_or_scoped_decision_body_is_refused(
    gate_export_client: AsyncClient,
    review_client: AsyncClient,
    project_dir: Path,
    session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound = await _bound(gate_export_client, review_client, project_dir, session_factory, monkeypatch)
    snapshot = await _reviewed(review_client, bound["target_id"])

    stale = await review_client.post(
        f"{BASE}/pair-decisions", json=_decision_body(snapshot, expected_envelope_digest="sha256:" + "0" * 64)
    )
    scoped = await review_client.post(f"{BASE}/pair-decisions", json=_decision_body(snapshot, principal="someone"))
    evidence = await review_client.post(
        f"{BASE}/pair-decisions", json=_decision_body(snapshot, review_evidence_digest="sha256:" + "0" * 64)
    )
    actor = await review_client.post(
        f"{BASE}/promotions",
        json={
            "command_id": "promote-1",
            "preview_id": "p",
            "preview_digest": "sha256:" + "0" * 64,
            "expected_candidate_head_version": 1,
            "actor_id": "someone",
        },
    )

    assert stale.status_code == 409
    assert (scoped.status_code, evidence.status_code, actor.status_code) == (422, 422, 422)


@pytest.mark.asyncio
async def test_review_routes_need_an_interactive_session_and_activated_governance(
    session_factory: Factory, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    grants = await showrunner_grants(session_factory)
    session = {"target_id": "scene-1-TAKE-1"}
    async with _client(_app(monkeypatch, session_factory, project_dir, grants, interactive=False)) as keyed:
        api_key = await keyed.post(
            f"{BASE}/review-sessions", json=session, headers={"Authorization": "Bearer arc-test-key"}
        )
        binding = await keyed.post(f"{BASE}/bindings", json={})
    async with _client(_app(monkeypatch, session_factory, project_dir, None, interactive=True)) as inactive:
        unavailable = await inactive.post(f"{BASE}/review-sessions", json=session)
        promotions = await inactive.post(f"{BASE}/promotions", json={})

    assert (api_key.status_code, api_key.json()["detail"]) == (401, "INTERACTIVE_SESSION_REQUIRED")
    assert binding.status_code == 401
    assert unavailable.status_code == 503
    assert promotions.status_code == 503
