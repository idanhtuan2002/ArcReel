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
    env["app"] = _app(env)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env["app"]), base_url="http://test") as client:
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


async def test_probe_history_lists_each_command_with_its_attempt_state(http) -> None:
    env = http
    chain = await _chain(env)
    probes = await env["client"].get(
        f"{BASE}/probes",
        params={"profile_id": chain["profile"]["profile_id"], "revision": 1, "root": chain["root"]},
        headers=_headers(),
    )
    assert probes.status_code == 200, probes.text
    rows = sorted(probes.json()["probes"], key=lambda row: row["requirement_id"])
    assert [(row["requirement_id"], row["attempt_state"], row["status"]) for row in rows] == [
        ("technical-container", "SUCCEEDED", "PASS"),
        ("technical-decode", "SUCCEEDED", "PASS"),
    ]


async def test_with_new_probe_work_disabled_only_an_existing_command_continues(http) -> None:
    env = http
    chain = await _chain(env)
    tree, sockets = env["governance"]
    disabled = quality.QualityDeps(
        sessions=env["factory"],
        project_root=lambda _name: env["project"],
        grant_reader=env["reader"],
        read_directory=tree / "read",
        socket_directory=sockets,
        catalog=None,
        runtime=env["runtime"],
        secret=SECRET,
        custody_uid=os.getuid(),
        custody_gid=os.getgid(),
    )
    env["app"].dependency_overrides[quality.quality_deps] = lambda: disabled
    replayed = await env["client"].post(f"{BASE}/probes", json=env["sealed"]["probes"], headers=_headers())
    assert replayed.status_code == 200, replayed.text
    scope = {"profile_id": chain["profile"]["profile_id"], "revision": 1, "root_artifact_key": chain["root"]}
    fresh = await env["client"].post(
        f"{BASE}/probes/prepare",
        json={"command_id": "probe-new", **scope, "requirement_id": "technical-decode"},
        headers=_headers(),
    )
    assert fresh.status_code == 503


async def test_an_oversized_body_is_refused_before_parsing(http) -> None:
    env = http
    response = await env["client"].post(
        f"{BASE}/runs",
        content=b'{"request": {"x": "' + b"a" * (1 << 20) + b'"}, "seal": "s"}',
        headers=_headers() | {"Content-Type": "application/json"},
    )
    assert response.status_code == 413


async def test_an_exact_revision_and_the_runs_own_profile_are_readable(http) -> None:
    env = http
    chain = await _chain(env)
    revision = await env["client"].get(
        f"{BASE}/profiles/{chain['profile']['profile_id']}/revisions/1", headers=_headers()
    )
    assert revision.json()["profile"]["profile_digest"] == chain["profile"]["profile_digest"]
    [listed] = (await env["client"].get(f"{BASE}/runs", params={"root": chain["root"]}, headers=_headers())).json()[
        "runs"
    ]
    assert (listed["cohort_id"], listed["product_surface"]) == ("cohort-c", "video")


def _video_asset(env) -> dict[str, Any]:
    import hashlib
    from pathlib import Path

    media = Path(env["root"].object_ref)
    return {
        "role": "video",
        "variant_id": None,
        "source_ref": media.resolve().relative_to(env["project"].resolve()).as_posix(),
        "content_digest": "sha256:" + hashlib.sha256(media.read_bytes()).hexdigest(),
        "media_type": "video/mp4",
        "byte_size": media.stat().st_size,
        "constraint_rule_id": "asset-video",
    }


async def test_a_run_made_on_the_quality_routes_exports_through_packaging(http) -> None:
    """The same run goes from the quality routes through the Packaging revision, check, preview, selection and export."""
    from server.routers import packaging

    env = http
    chain = await _chain(env)
    tree, sockets = env["governance"]
    env["app"].include_router(packaging.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
    env["app"].dependency_overrides[packaging.packaging_deps] = lambda: packaging.PackagingDeps(
        sessions=env["factory"],
        project_root=lambda _name: env["project"],
        grant_reader=env["reader"],
        read_directory=tree / "read",
        socket_directory=sockets,
        custody_uid=os.getuid(),
        custody_gid=os.getgid(),
    )
    client, base = env["client"], "/api/v1/projects/project/packaging"
    text = {
        "title": "A history of the river",
        "description": "How the river shaped the valley over ten thousand years.",
    }
    draft = text | {
        "tags": ["river"],
        "hashtags": [],
        "chapters": [],
        "localization_variants": [{"locale": "en", **text, "tags": ["river"], "hashtags": [], "chapters": []}],
        "audience_classification": {
            "audience_category": "general",
            "age_restriction": None,
            "classification_policy_digest": "sha256:" + "0" * 64,
        },
        "disclosure": {
            "synthetic_media": True,
            "paid_promotion": False,
            "disclosure_policy_digest": "sha256:" + "0" * 64,
        },
        "variant_groups": [],
        "assets": [_video_asset(env)],
    }
    run = chain["run"]
    revision = await client.post(
        f"{base}/revisions",
        json={"command_id": "pkg-rev", "quality_run_id": run["run"]["run_id"], "draft": draft},
        headers=_headers(),
    )
    assert revision.status_code == 200, revision.text
    candidate = revision.json()["revision"]
    check = await client.post(
        f"{base}/checks",
        json={
            "command_id": "pkg-check",
            "candidate_id": candidate["candidate_id"],
            "candidate_revision": candidate["revision"],
            "candidate_payload_digest": candidate["payload_digest"],
            "quality_run_id": run["run"]["run_id"],
            "quality_run_digest": run["run_digest"],
        },
        headers=_headers(),
    )
    assert check.status_code == 200, check.text
    assert check.json()["status"] == "PASS", check.json()["findings"]
    slot = {"source_artifact_key": chain["root"], "cohort_id": "cohort-c", "product_surface": "video"}
    preview = await client.post(
        f"{base}/previews",
        json={
            "command_id": "pkg-preview",
            **slot,
            "candidate_id": candidate["candidate_id"],
            "candidate_revision": candidate["revision"],
            "candidate_payload_digest": candidate["payload_digest"],
            "packaging_observation_id": check.json()["observation_id"],
            "selected_variant_ids": [],
            "waivers": [],
        },
        headers=_headers(),
    )
    assert preview.status_code == 200, preview.text
    shown = preview.json()
    selection = await client.post(
        f"{base}/selections",
        json={
            "command_id": "pkg-select",
            "preview_id": shown["preview"]["preview_id"],
            "preview_digest": shown["preview_digest"],
            "expected_head_version": shown["preview"]["expected_head_version"],
        },
        headers=_headers(),
    )
    assert selection.status_code == 200, selection.text
    exported = await client.post(
        f"{base}/exports",
        json={
            "command_id": "pkg-export",
            **slot,
            "selection_id": selection.json()["selection_id"],
            "selection_digest": selection.json()["selection_digest"],
        },
        headers=_headers(),
    )
    assert exported.status_code == 200, exported.text
    assert exported.json()["status"] == "EXPORTED"
