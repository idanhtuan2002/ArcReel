"""The M8-E format API over HTTP: plan from the current master, render, measure, blind review, candidate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.project_manager import ProjectManager
from r2.advanced_creative.formats import SEMANTIC_ITEMS, format_slot_key
from server.auth import CurrentUserInfo, get_current_interactive_user, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import formats
from server.services.format_render import ffmpeg_available, file_digest
from tests.auth_deps import AUTH_DEPENDENCIES
from tests.integration.r2.advanced_creative.test_format_render import make_source
from tests.integration.server.services.test_format_projection_flow import SOURCE_KEY, _seed_master
from tests.unit.r2.advanced_creative.test_formats import overlay, profile

type Factory = async_sessionmaker[AsyncSession]

pytestmark = pytest.mark.skipif(not ffmpeg_available(), reason="needs ffmpeg and ffprobe")

USER = CurrentUserInfo(id="default", sub="sponsor", role="admin")
OTHER = CurrentUserInfo(id="default", sub="someone-else", role="admin")
PROJECT = "demo"
BASE = f"/api/v1/projects/{PROJECT}/m8/formats"


def _app(monkeypatch: pytest.MonkeyPatch, factory: Factory, root: Path, *, reviewer: CurrentUserInfo | None) -> FastAPI:
    project_dir = root / PROJECT
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project.json").write_text(json.dumps({"title": PROJECT, "episodes": []}), encoding="utf-8")
    monkeypatch.setattr(formats, "async_session_factory", factory)
    monkeypatch.setattr(formats, "get_project_manager", lambda: ProjectManager(root))
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: USER
    if reviewer is not None:
        app.dependency_overrides[get_current_interactive_user] = lambda: reviewer
    app.include_router(formats.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _box(x0: str, y0: str, x1: str, y1: str) -> dict[str, str]:
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}


async def _setup(http: AsyncClient, factory: Factory, root: Path) -> None:
    source = make_source(root / PROJECT / "masters" / "episode.mp4")
    await _seed_master(factory, root / PROJECT, source, "a")
    target = profile(1080, 1080, profile_ref="square@1")
    assert (await http.post(f"{BASE}/profiles", json=target.model_dump(mode="json"))).status_code == 200
    assert (await http.post(f"{BASE}/overlays", json=overlay().model_dump(mode="json"))).status_code == 200


async def test_the_api_takes_a_projection_from_plan_to_candidate(
    monkeypatch: pytest.MonkeyPatch, session_factory: Factory, tmp_path: Path
) -> None:
    async with _client(_app(monkeypatch, session_factory, tmp_path, reviewer=USER)) as http:
        await _setup(http, session_factory, tmp_path)
        planned = await http.post(
            f"{BASE}/plans",
            json={
                "plan_id": "square-pad",
                "source_artifact_key": SOURCE_KEY,
                "profile_ref": "square@1",
                "constraint_ref": "tiktok-feed-ui@1",
                "kind": "PAD",
                "subject": _box("2/5", "1/4", "3/5", "3/4"),
                "rationale": "keep the whole frame",
            },
        )
        assert planned.status_code == 200, planned.text
        source_digest = file_digest(tmp_path / PROJECT / "masters" / "episode.mp4")
        assert planned.json()["source_master_digest"] == source_digest

        rendered = (await http.post(f"{BASE}/plans/square-pad/renders", json={"command_id": "r-1"})).json()
        execution_id = rendered["execution_id"]
        technical = await http.post(f"{BASE}/renders/{execution_id}/validation")
        assert technical.json()["passed"] is True

        packet = (await http.post(f"{BASE}/renders/{execution_id}/review-packets")).json()
        assert packet["items"] == list(SEMANTIC_ITEMS)
        clips = [await http.get(f"{BASE}/review-packets/{packet['packet_id']}/clips/{label}") for label in ("A", "B")]
        assert [clip.status_code for clip in clips] == [200, 200]
        assert {clip.headers["content-type"] for clip in clips} == {"video/mp4"}
        reviewed = await http.post(
            f"{BASE}/review-packets/{packet['packet_id']}/reviews",
            json={"items": dict.fromkeys(SEMANTIC_ITEMS, "PASS"), "note": "same meaning"},
        )
        assert reviewed.json()["passed"] is True

        candidate = (await http.post(f"{BASE}/renders/{execution_id}/candidate")).json()
        assert candidate["slot_key"] == format_slot_key(SOURCE_KEY, "square@1")
        assert candidate["expected_target_version"] == 0

        previewed = await http.post(
            f"{BASE}/previews",
            json={
                "candidate_id": candidate["candidate_id"],
                "revision": candidate["revision"],
                "slot_key": candidate["slot_key"],
                "expected_target_version": 0,
                "command_id": "preview-1",
            },
        )
        assert previewed.status_code == 200, previewed.text
        preview = previewed.json()
        approve = {
            "preview_id": preview["preview"]["preview_id"],
            "preview_digest": "sha256:" + "0" * 64,
            "expected_candidate_head_version": candidate["head_version"],
            "command_id": "promote-1",
        }
        assert (await http.post(f"{BASE}/promotions", json=approve)).status_code == 409
        receipt = await http.post(
            f"{BASE}/promotions",
            json={**approve, "preview_digest": preview["preview_digest"], "command_id": "promote-2"},
        )
        assert receipt.status_code == 200, receipt.text
        assert receipt.json()["result_digest"] == rendered["artifact_digest"]

        # The promoted format slot is a master too, but never a projection source.
        sources = (await http.get(f"{BASE}/sources")).json()
        assert [(item["artifact_key"], item["master_version"]) for item in sources] == [(SOURCE_KEY, 1)]

        listed = (await http.get(f"{BASE}/plans")).json()
        assert [item["plan"]["plan_id"] for item in listed] == ["square-pad"]
        assert listed[0]["technical"]["passed"] is True
        assert listed[0]["semantic"]["passed"] is True
        assert [render["execution_id"] for render in listed[0]["renders"]] == [execution_id]


async def test_review_needs_an_interactive_session_and_clips_belong_to_their_reviewer(
    monkeypatch: pytest.MonkeyPatch, session_factory: Factory, tmp_path: Path
) -> None:
    async with _client(_app(monkeypatch, session_factory, tmp_path, reviewer=USER)) as http:
        await _setup(http, session_factory, tmp_path)
        await http.post(
            f"{BASE}/plans",
            json={
                "plan_id": "p",
                "source_artifact_key": SOURCE_KEY,
                "profile_ref": "square@1",
                "constraint_ref": "tiktok-feed-ui@1",
                "kind": "PAD",
                "subject": _box("2/5", "1/4", "3/5", "3/4"),
                "rationale": "keep all",
            },
        )
        execution_id = (await http.post(f"{BASE}/plans/p/renders", json={"command_id": "r-1"})).json()["execution_id"]
        packet = (await http.post(f"{BASE}/renders/{execution_id}/review-packets")).json()

    async with _client(_app(monkeypatch, session_factory, tmp_path, reviewer=OTHER)) as http:
        assert (await http.get(f"{BASE}/review-packets/{packet['packet_id']}/clips/A")).status_code == 404
    async with _client(_app(monkeypatch, session_factory, tmp_path, reviewer=None)) as http:
        assert (await http.post(f"{BASE}/renders/{execution_id}/review-packets")).status_code == 401
        approval = {
            "preview_id": "x",
            "preview_digest": "sha256:" + "0" * 64,
            "expected_candidate_head_version": 1,
            "command_id": "c",
        }
        assert (await http.post(f"{BASE}/promotions", json=approval)).status_code == 401


async def test_a_plan_needs_an_approved_master_and_a_well_formed_box(
    monkeypatch: pytest.MonkeyPatch, session_factory: Factory, tmp_path: Path
) -> None:
    async with _client(_app(monkeypatch, session_factory, tmp_path, reviewer=USER)) as http:
        await _setup(http, session_factory, tmp_path)
        body = {
            "plan_id": "p",
            "source_artifact_key": "unknown-key",
            "profile_ref": "square@1",
            "constraint_ref": "tiktok-feed-ui@1",
            "kind": "PAD",
            "subject": _box("2/5", "1/4", "3/5", "3/4"),
            "rationale": "keep all",
        }
        assert (await http.post(f"{BASE}/plans", json=body)).status_code == 404
        bad = {**body, "source_artifact_key": SOURCE_KEY, "subject": _box("3/5", "1/4", "2/5", "3/4")}
        assert (await http.post(f"{BASE}/plans", json=bad)).status_code == 422
        wrong_ratio = profile(1080, 1350, profile_ref="portrait-45@1").model_dump(mode="json")
        assert (await http.post(f"{BASE}/profiles", json=wrong_ratio)).status_code == 422
