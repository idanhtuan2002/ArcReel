"""M10-C quality routes over HTTP: prepare/submit through the accepted services to a READY PASS disposition."""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest
from fastapi import Depends, FastAPI

from r2.quality.host_catalog import HOST_CATALOG
from server import auth
from server.auth import get_current_user
from server.error_handlers import register_error_handlers
from server.routers import quality
from server.services.quality_requests import RUBRIC_CRITERIA
from tests.integration.server.services.test_quality_probes import ACTOR
from tests.integration.server.services.test_quality_profile_custodian import SECRET
from tests.integration.server.services.test_quality_runs import closure_host as closure_host

BASE = "/api/v1/projects/project/quality"


def _app(env) -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(quality.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
    tree, sockets = env["governance"]
    app.dependency_overrides[quality.quality_deps] = lambda: quality.QualityDeps(
        sessions=env["factory"],
        project_root=lambda _name: env["project"],
        grant_reader=env["reader"],
        read_directory=tree / "read",
        socket_directory=sockets,
        catalog=HOST_CATALOG,
        runtime=env["runtime"],
        secret=SECRET,
        custody_uid=os.getuid(),
        custody_gid=os.getgid(),
    )
    return app


@pytest.fixture
async def http(closure_host):
    env = closure_host
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(env)), base_url="http://test") as client:
        env["client"] = client
        yield env


def _headers(subject: str = ACTOR) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth.create_token(subject)}"}


async def _do(env, path: str, intent: dict[str, Any]) -> dict[str, Any]:
    client = env["client"]
    prepared = await client.post(f"{BASE}/{path}/prepare", json=intent, headers=_headers())
    assert prepared.status_code == 200, prepared.text
    body = prepared.json()
    done = await client.post(
        f"{BASE}/{path}", json={"request": body["request"], "seal": body["seal"]}, headers=_headers()
    )
    assert done.status_code == 200, done.text
    env.setdefault("sealed", {})[path] = {"request": body["request"], "seal": body["seal"]}
    return done.json()


async def _chain(env) -> dict[str, Any]:
    client = env["client"]
    root = env["root"].artifact_key
    template = await client.get(
        f"{BASE}/template",
        params={
            "platform_profile_id": "pilot",
            "width": 64,
            "height": 64,
            "min_duration_ms": 1000,
            "max_duration_ms": 900000,
            "locales": "en",
        },
        headers=_headers(),
    )
    assert template.status_code == 200, template.text
    profile = (
        await _do(
            env,
            "profiles",
            {
                "command_id": "publish-c1",
                "profile_id": None,
                "expected_profile_revision": 0,
                "cohort_id": "cohort-c",
                "product_surface": "video",
                "policy": template.json()["policy"],
            },
        )
    )["profile"]
    scope = {"profile_id": profile["profile_id"], "revision": profile["revision"], "root_artifact_key": root}
    ids = []
    for requirement in ("technical-container", "technical-decode"):
        observation = (
            await _do(env, "probes", {"command_id": "probe-" + requirement, **scope, "requirement_id": requirement})
        )["observation"]
        assert observation["status"] == "PASS"
        ids.append(observation["observation_id"])
    review = await _do(
        env,
        "reviews",
        {
            "command_id": "review-1",
            **scope,
            "status": "PASS",
            "criteria_verdicts": dict.fromkeys(RUBRIC_CRITERIA, "PASS"),
            "findings": [],
            "notes": "Watched in full.",
        },
    )
    ids.append(review["observation"]["observation_id"])
    sealed = await _do(env, "runs", {"command_id": "seal-1", **scope, "observation_ids": ids})
    disposition = await _do(
        env,
        "dispositions",
        {
            "command_id": "dispose-1",
            "run_id": sealed["run"]["run_id"],
            "decision": "PASS",
            "reason": "every requirement met",
            "expected_disposition_version": 0,
            "requested_ttl_seconds": 3600,
        },
    )
    return {"profile": profile, "run": sealed, "disposition": disposition["disposition"], "root": root}


async def test_an_operator_drives_a_master_to_a_ready_pass_disposition_over_http(http) -> None:
    env = http
    chain = await _chain(env)
    assert chain["disposition"]["decision"] == "PASS"
    runs = await env["client"].get(f"{BASE}/runs", params={"root": chain["root"]}, headers=_headers())
    assert runs.status_code == 200, runs.text
    [listed] = runs.json()["runs"]
    assert listed["run"]["run_id"] == chain["run"]["run"]["run_id"]
    assert (listed["readiness"]["state"], listed["disposition_version"]) == ("READY", 1)
    observations = await env["client"].get(
        f"{BASE}/observations",
        params={"profile_id": chain["profile"]["profile_id"], "revision": 1, "root": chain["root"]},
        headers=_headers(),
    )
    assert sorted(o["requirement_id"] for o in observations.json()["observations"]) == [
        "review",
        "technical-container",
        "technical-decode",
    ]


async def test_resending_a_sealed_request_replays_its_result(http) -> None:
    env = http
    chain = await _chain(env)
    again = await env["client"].post(f"{BASE}/runs", json=env["sealed"]["runs"], headers=_headers())
    assert again.status_code == 200, again.text
    assert again.json()["run"]["run_id"] == chain["run"]["run"]["run_id"]


async def test_a_changed_request_or_another_actor_cannot_use_a_seal(http) -> None:
    env = http
    await _chain(env)
    sealed = env["sealed"]["dispositions"]
    tampered = {
        "request": sealed["request"] | {"command": sealed["request"]["command"] | {"command_id": "x"}},
        "seal": sealed["seal"],
    }
    refused = await env["client"].post(f"{BASE}/dispositions", json=tampered, headers=_headers())
    assert refused.status_code == 422
    other = await env["client"].post(f"{BASE}/dispositions", json=sealed, headers=_headers("someone-else"))
    assert other.status_code == 422


async def test_the_embedded_agent_cannot_prepare_any_mutation(http) -> None:
    env = http
    agent = {"Authorization": f"Bearer {auth.create_token('embedded-agent', expiry_seconds=900, via='embedded-agent')}"}
    for path in ("profiles", "probes", "reviews", "runs", "dispositions"):
        refused = await env["client"].post(f"{BASE}/{path}/prepare", json={}, headers=agent)
        assert refused.status_code == 401, path


async def test_the_routes_are_unavailable_when_authentication_is_disabled(
    http, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = http
    monkeypatch.setenv("AUTH_ENABLED", "false")
    response = await env["client"].get(f"{BASE}/profiles")
    assert response.status_code == 503
