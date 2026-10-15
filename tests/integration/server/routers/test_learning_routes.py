"""The M8-D learning API: ingest, evaluate, list and Human decisions (plan D3 decision 10)."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.project_manager import ProjectManager
from r2.advanced_creative.lineage import resolve_episode_lineage
from r2.contracts.adaptation import AdaptationProfileId
from r2.contracts.advanced_creative import MetricWindow
from server.auth import CurrentUserInfo, get_current_interactive_user, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import learning
from tests.auth_deps import AUTH_DEPENDENCIES
from tests.fixtures.r2.m8f_profiles import admit_profile
from tests.unit.r2.learning.test_observations import T0, obs

type Factory = async_sessionmaker[AsyncSession]

USER = CurrentUserInfo(id="default", sub="operator-1", role="admin")
REVIEWER = CurrentUserInfo(id="default", sub="reviewer-a", role="admin")
PROJECT = "demo"
BASE = f"/api/v1/projects/{PROJECT}/m8/learning"
LINEAGE = resolve_episode_lineage(PROJECT, 1, b"one")
EVALUATE = {
    "source_family": "youtube.analytics",
    "metric_name": "views",
    "metric_definition_version": "2024-01",
    "aggregation": "sum_day",
    "creative_profile_id": LINEAGE.creative_profile_id,
    "creative_profile_version": LINEAGE.creative_profile_version,
    "arm_a": "16x9",
    "arm_b": "9x16",
    "min_per_arm": 3,
    "min_relative_lift": "0.10",
    "expires_in_days": 30,
    "command_id": "eval-1",
}


def _app(monkeypatch: pytest.MonkeyPatch, factory: Factory, root: Path, *, interactive: bool) -> FastAPI:
    project_dir = root / PROJECT
    (project_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (project_dir / "project.json").write_text(
        json.dumps({"title": PROJECT, "episodes": [{"episode": 1, "script_file": "scripts/episode_1.json"}]}),
        encoding="utf-8",
    )
    (project_dir / "scripts" / "episode_1.json").write_bytes(b"one")
    monkeypatch.setattr(learning, "async_session_factory", factory)
    monkeypatch.setattr(learning, "get_project_manager", lambda: ProjectManager(root))
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: USER
    if interactive:
        app.dependency_overrides[get_current_interactive_user] = lambda: REVIEWER
    app.include_router(learning.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _observation(index: int, arm: str, value: str, **changes) -> dict:
    window = MetricWindow(
        starts_at=T0 + timedelta(days=index),
        ends_at=T0 + timedelta(days=index + 1),
        timezone_name="UTC",
        aggregation="sum_day",
    )
    return obs(
        f"{arm}-{index}",
        source_record_id=f"{arm}-video-{index}",
        format_profile_ref=arm,
        metric_value=Decimal(value),
        window=window,
        **{"lineage": LINEAGE, **changes},
    ).model_dump(mode="json")


async def _ingest(http: AsyncClient, body: dict, command: str):
    return await http.post(f"{BASE}/observations", json={"episode": 1, "observation": body, "command_id": command})


async def _seed(http: AsyncClient, b_value: str = "120") -> None:
    for index in range(3):
        for arm, value in (("16x9", "100"), ("9x16", b_value)):
            response = await _ingest(http, _observation(index, arm, value), f"i-{arm}-{index}")
            assert response.status_code == 200, response.text


async def test_evaluate_list_and_decide_a_recommendation(
    monkeypatch: pytest.MonkeyPatch, session_factory: Factory, tmp_path: Path
) -> None:
    async with _client(_app(monkeypatch, session_factory, tmp_path, interactive=True)) as http:
        await _seed(http)
        evaluated = await http.post(f"{BASE}/recommendations/evaluate", json=EVALUATE)
        assert evaluated.status_code == 200, evaluated.text
        body = evaluated.json()
        assert (body["fired"], body["relative_lift"]) == (True, "0.2")
        assert [arm["mean"] for arm in body["arms"]] == ["100", "120"]
        view = body["recommendation"]
        assert view["language"] == "associative"
        assert "is associated with" in view["recommendation"]["hypothesis"]
        assert len(view["recommendation"]["evidence_observation_ids"]) == 6

        again = (await http.post(f"{BASE}/recommendations/evaluate", json=EVALUATE)).json()
        assert again == body

        listed = (await http.get(f"{BASE}/recommendations")).json()
        assert [item["recommendation"]["recommendation_id"] for item in listed] == [
            view["recommendation"]["recommendation_id"]
        ]

        decision_url = f"{BASE}/recommendations/{view['recommendation']['recommendation_id']}/decisions"
        accept = {
            "disposition": "ACCEPT",
            "expected_recommendation_digest": view["recommendation_digest"],
            "reason": "matches our format review",
            "command_id": "d-1",
        }
        decided = await http.post(decision_url, json=accept)
        assert decided.status_code == 200, decided.text
        assert decided.json()["actor_id"] == "reviewer-a"
        assert decided.json()["governed_proposal_ref"].startswith("learning-proposal:")
        second = await http.post(decision_url, json={**accept, "disposition": "REJECT", "command_id": "d-2"})
        assert second.status_code == 409
        assert (await http.get(f"{BASE}/recommendations")).json()[0]["final"] is True


async def test_a_decision_needs_an_interactive_session(
    monkeypatch: pytest.MonkeyPatch, session_factory: Factory, tmp_path: Path
) -> None:
    async with _client(_app(monkeypatch, session_factory, tmp_path, interactive=False)) as http:
        await _seed(http)
        view = (await http.post(f"{BASE}/recommendations/evaluate", json=EVALUATE)).json()["recommendation"]
        response = await http.post(
            f"{BASE}/recommendations/{view['recommendation']['recommendation_id']}/decisions",
            json={
                "disposition": "ACCEPT",
                "expected_recommendation_digest": view["recommendation_digest"],
                "reason": "ok",
                "command_id": "d-1",
            },
        )
    assert response.status_code == 401


async def test_ingest_needs_the_server_resolved_lineage_and_a_rule_below_threshold_proposes_nothing(
    monkeypatch: pytest.MonkeyPatch, session_factory: Factory, tmp_path: Path
) -> None:
    async with _client(_app(monkeypatch, session_factory, tmp_path, interactive=True)) as http:
        forged = _observation(0, "16x9", "1", lineage=LINEAGE.model_copy(update={"creative_profile_id": "zh-shuang"}))
        refused = await _ingest(http, forged, "forged")
        assert refused.status_code == 422
        assert (await http.post(f"{BASE}/recommendations/evaluate", json=EVALUATE)).json()[
            "reason"
        ] == "no observations"

        await _seed(http, b_value="105")
        # The first command already recorded "no observations"; a retry replays that outcome.
        assert (await http.post(f"{BASE}/recommendations/evaluate", json=EVALUATE)).json()[
            "reason"
        ] == "no observations"
        conflict = await http.post(f"{BASE}/recommendations/evaluate", json={**EVALUATE, "arm_b": "1x1"})
        assert conflict.status_code == 409
        quiet = (await http.post(f"{BASE}/recommendations/evaluate", json={**EVALUATE, "command_id": "eval-2"})).json()
        assert (quiet["fired"], quiet["reason"], quiet["recommendation"]) == (False, "lift below threshold", None)
        assert (await http.get(f"{BASE}/recommendations")).json() == []
        unknown = await http.post(
            f"{BASE}/recommendations/nope/decisions",
            json={"disposition": "DEFER", "expected_recommendation_digest": "x", "reason": "r", "command_id": "d"},
        )
        assert unknown.status_code == 404


async def test_an_admitted_project_ingests_only_its_profile_lineage_and_evaluates_its_own_cohort(
    monkeypatch: pytest.MonkeyPatch, session_factory: Factory, tmp_path: Path
) -> None:
    admission = (
        await admit_profile(
            session_factory,
            user_id=USER.id,
            project_name=PROJECT,
            profile_id=AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN,
        )
    ).ref
    shuang = resolve_episode_lineage(PROJECT, 1, b"one", admissions=(admission,))
    async with _client(_app(monkeypatch, session_factory, tmp_path, interactive=True)) as http:
        host = await _ingest(http, _observation(0, "16x9", "1"), "host-lineage")
        assert host.status_code == 422

        for index in range(3):
            for arm, value in (("16x9", "100"), ("9x16", "130")):
                response = await _ingest(http, _observation(index, arm, value, lineage=shuang), f"s-{arm}-{index}")
                assert response.status_code == 200, response.text

        host_cohort = await http.post(f"{BASE}/recommendations/evaluate", json=EVALUATE)
        assert (host_cohort.json()["fired"], host_cohort.json()["reason"]) == (False, "both arms need observations")
        own = await http.post(
            f"{BASE}/recommendations/evaluate",
            json={
                **EVALUATE,
                "creative_profile_id": "CN_SHORT_DRAMA_SHUANGWEN",
                "creative_profile_version": "v1",
                "command_id": "eval-shuang",
            },
        )
        assert own.json()["fired"] is True
        lineage = own.json()["recommendation"]["recommendation"]["lineage"]
        assert (lineage["creative_profile_id"], lineage["creative_profile_version"], lineage["policy_digest"]) == (
            shuang.creative_profile_id,
            shuang.creative_profile_version,
            shuang.policy_digest,
        )
