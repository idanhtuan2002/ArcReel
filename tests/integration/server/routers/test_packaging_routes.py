"""M10-B packaging routes over HTTP: server-built commands, Human-only selection/export, scoped download."""

from __future__ import annotations

import hashlib
import io
import os
import zipfile
from typing import Any

import httpx
import pytest
from fastapi import Depends, FastAPI

from server import auth
from server.auth import get_current_user
from server.error_handlers import register_error_handlers
from server.routers import packaging
from tests.integration.server.services.test_quality_dispositions import issue
from tests.integration.server.services.test_quality_dispositions import request_for as disposition_request
from tests.integration.server.services.test_quality_packaging import candidate_for
from tests.integration.server.services.test_quality_packaging import packaging_host as packaging_host
from tests.integration.server.services.test_quality_probes import ACTOR

_SERVER_FIELDS = {
    "kind",
    "approved_master_id",
    "approved_master_digest",
    "assessed_subject_digest",
    "quality_profile_id",
    "quality_profile_revision",
    "quality_profile_digest",
    "platform_profile_id",
    "platform_profile_revision",
    "constraint_snapshot_digest",
    "content_closure_digest",
    "presentation_closure_digest",
    "provenance",
}


def _app(env) -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(packaging.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
    app.include_router(packaging.download_router, prefix="/api/v1")
    root_dir, socket_dir = env["governance"]
    app.dependency_overrides[packaging.packaging_deps] = lambda: packaging.PackagingDeps(
        sessions=env["factory"],
        project_root=lambda _name: env["project"],
        grant_reader=env["reader"],
        read_directory=root_dir / "read",
        socket_directory=socket_dir,
        custody_uid=os.getuid(),
        custody_gid=os.getgid(),
    )
    return app


def _draft(env) -> dict[str, Any]:
    payload = candidate_for(env).model_dump(mode="json")
    draft = {key: value for key, value in payload.items() if key not in _SERVER_FIELDS}
    draft["variant_groups"] = [
        {
            "group_id": "titles",
            "field": "title",
            "variants": [
                {"variant_id": "t1", "value": {"text": "A history of the river"}, "asset_role": None},
                {"variant_id": "t2", "value": {"text": "The river that made a valley: a history"}, "asset_role": None},
            ],
        }
    ]
    return draft


@pytest.fixture
async def http(packaging_host):
    env = packaging_host
    env["disposition"] = await issue(env, disposition_request(env["run"]))
    env["app"] = _app(env)
    transport = httpx.ASGITransport(app=env["app"])
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        env["client"] = client
        yield env


def _headers(subject: str = ACTOR) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth.create_token(subject)}"}


async def _flow_to_selection(env, *, select_status: int = 200) -> dict[str, Any]:
    client = env["client"]
    run = env["run"]
    from r2.quality.runs import run_digest

    appended = await client.post(
        "/api/v1/projects/project/packaging/revisions",
        json={"command_id": "rev-1", "quality_run_id": run.run_id, "draft": _draft(env)},
        headers=_headers(),
    )
    assert appended.status_code == 200, appended.text
    revision = appended.json()["revision"]
    checked = await client.post(
        "/api/v1/projects/project/packaging/checks",
        json={
            "command_id": "check-1",
            "candidate_id": revision["candidate_id"],
            "candidate_revision": revision["revision"],
            "candidate_payload_digest": revision["payload_digest"],
            "quality_run_id": run.run_id,
            "quality_run_digest": run_digest(run),
        },
        headers=_headers(),
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["status"] == "PASS", checked.json()["findings"]
    profile = env["profile"]
    slot = {
        "source_artifact_key": run.subject.master_binding.root.artifact_key,
        "cohort_id": profile.cohort_id,
        "product_surface": profile.product_surface,
    }
    previewed = await client.post(
        "/api/v1/projects/project/packaging/previews",
        json={
            "command_id": "preview-1",
            **slot,
            "candidate_id": revision["candidate_id"],
            "candidate_revision": revision["revision"],
            "candidate_payload_digest": revision["payload_digest"],
            "packaging_observation_id": checked.json()["observation_id"],
            "selected_variant_ids": ["t2"],
            "waivers": [],
        },
        headers=_headers(),
    )
    assert previewed.status_code == 200, previewed.text
    preview = previewed.json()
    selected = await client.post(
        "/api/v1/projects/project/packaging/selections",
        json={
            "command_id": "select-1",
            "preview_id": preview["preview"]["preview_id"],
            "preview_digest": preview["preview_digest"],
            "expected_head_version": preview["preview"]["expected_head_version"],
        },
        headers=_headers(),
    )
    assert selected.status_code == select_status, selected.text
    return {"revision": revision, "selection": selected.json(), "slot": slot}


async def test_the_full_packaging_flow_ends_in_a_downloadable_verified_archive(http) -> None:
    env = http
    flow = await _flow_to_selection(env)
    revision = flow["revision"]
    assert {(p["field_group"], p["author_kind"]) for p in revision["payload"]["provenance"]} == {
        ("content", "HUMAN"),
        ("presentation", "HUMAN"),
    }
    assert {v["provenance"]["author_kind"] for v in revision["payload"]["variant_groups"][0]["variants"]} == {"HUMAN"}
    exported = await env["client"].post(
        "/api/v1/projects/project/packaging/exports",
        json={
            "command_id": "export-1",
            **flow["slot"],
            "selection_id": flow["selection"]["selection_id"],
            "selection_digest": flow["selection"]["selection_digest"],
        },
        headers=_headers(),
    )
    assert exported.status_code == 200, exported.text
    receipt = exported.json()
    archive_hex = receipt["archive_digest"].removeprefix("sha256:")
    downloaded = await env["client"].get(
        f"/api/v1/projects/project/packaging/exports/{archive_hex}/archive",
        params={"token": receipt["download_token"]},
    )
    assert downloaded.status_code == 200
    assert "sha256:" + hashlib.sha256(downloaded.content).hexdigest() == receipt["archive_digest"]
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as bundle:
        assert "video/output.mp4" in bundle.namelist()
    other = packaging.create_export_token(ACTOR, "other-project", receipt["archive_digest"])
    mismatched = await env["client"].get(
        f"/api/v1/projects/project/packaging/exports/{archive_hex}/archive", params={"token": other}
    )
    assert mismatched.status_code == 403


async def test_clients_cannot_supply_bindings_or_provenance(http) -> None:
    env = http
    draft = _draft(env) | {"provenance": [{"field_group": "content", "author_kind": "HUMAN", "actor_id": "x"}]}
    response = await env["client"].post(
        "/api/v1/projects/project/packaging/revisions",
        json={"command_id": "rev-1", "quality_run_id": env["run"].run_id, "draft": draft},
        headers=_headers(),
    )
    assert response.status_code == 422
    variant = _draft(env)
    variant["variant_groups"][0]["variants"][0]["provenance"] = {"author_kind": "HUMAN", "actor_id": "x"}
    response = await env["client"].post(
        "/api/v1/projects/project/packaging/revisions",
        json={"command_id": "rev-2", "quality_run_id": env["run"].run_id, "draft": variant},
        headers=_headers(),
    )
    assert response.status_code == 422


async def test_a_retried_revision_command_returns_the_recorded_revision(http) -> None:
    env = http
    body = {"command_id": "rev-1", "quality_run_id": env["run"].run_id, "draft": _draft(env)}
    first = await env["client"].post("/api/v1/projects/project/packaging/revisions", json=body, headers=_headers())
    second = await env["client"].post("/api/v1/projects/project/packaging/revisions", json=body, headers=_headers())
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


async def test_selection_and_export_need_an_interactive_session(http) -> None:
    env = http
    no_session = await env["client"].post(
        "/api/v1/projects/project/packaging/selections",
        json={"command_id": "s", "preview_id": "x", "preview_digest": "sha256:" + "0" * 64, "expected_head_version": 0},
    )
    assert no_session.status_code == 401
    exported = await env["client"].post(
        "/api/v1/projects/project/packaging/exports",
        json={
            "command_id": "e",
            "source_artifact_key": "k",
            "cohort_id": "c",
            "product_surface": "s",
            "selection_id": "x",
            "selection_digest": "sha256:" + "0" * 64,
        },
    )
    assert exported.status_code == 401


async def test_selection_verifies_custody_against_the_configured_owner(http) -> None:
    env = http
    root_dir, socket_dir = env["governance"]
    env["app"].dependency_overrides[packaging.packaging_deps] = lambda: packaging.PackagingDeps(
        sessions=env["factory"],
        project_root=lambda _name: env["project"],
        grant_reader=env["reader"],
        read_directory=root_dir / "read",
        socket_directory=socket_dir,
        custody_uid=os.getuid() + 1,
        custody_gid=os.getgid(),
    )
    flow = await _flow_to_selection(env, select_status=403)
    assert flow["selection"]["detail"]


def test_an_activated_host_expects_root_owned_custody(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARCREEL_GOVERNANCE_READ_DIR", raising=False)
    deps = packaging.packaging_deps()
    assert (deps.custody_uid, deps.custody_gid) == (0, 0)


async def _replace_selection(env, flow: dict[str, Any]) -> Any:
    """Select the other title variant into the same slot, replacing the flow's selection."""
    from lib.db.repositories.advanced_creative import ExplorationRepository
    from lib.db.repositories.quality_packaging import PackagingObservationRepository
    from tests.integration.server.services.test_quality_package_selection import (
        preview,
        preview_request,
        select,
        selection_request,
    )

    async with env["factory"]() as session:
        env["candidate"] = await ExplorationRepository(session).get_exact(
            user_id="default", project_name="project", candidate_id=flow["revision"]["candidate_id"], revision=1
        )
        env["observation"] = await PackagingObservationRepository(session).get(
            user_id="default",
            project_name="project",
            observation_id=flow["selection"]["preview"]["packaging_observation_id"],
        )
    return await select(
        env,
        selection_request(
            env,
            await preview(env, preview_request(env, command_id="preview-2", selected_variant_ids=["t1"])),
            command_id="select-2",
        ),
    )


async def test_a_download_of_a_replaced_selection_is_refused(http) -> None:
    env = http
    flow = await _flow_to_selection(env)
    exported = await env["client"].post(
        "/api/v1/projects/project/packaging/exports",
        json={
            "command_id": "export-1",
            **flow["slot"],
            "selection_id": flow["selection"]["selection_id"],
            "selection_digest": flow["selection"]["selection_digest"],
        },
        headers=_headers(),
    )
    receipt = exported.json()
    await _replace_selection(env, flow)
    archive_hex = receipt["archive_digest"].removeprefix("sha256:")
    refused = await env["client"].get(
        f"/api/v1/projects/project/packaging/exports/{archive_hex}/archive", params={"token": receipt["download_token"]}
    )
    assert refused.status_code == 409


def _agent_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {auth.create_token('embedded-agent', expiry_seconds=900, via='embedded-agent')}"}


async def test_the_embedded_agent_authors_as_agent_and_cannot_select_or_export(http) -> None:
    env = http
    appended = await env["client"].post(
        "/api/v1/projects/project/packaging/revisions",
        json={"command_id": "rev-agent", "quality_run_id": env["run"].run_id, "draft": _draft(env)},
        headers=_agent_headers(),
    )
    assert appended.status_code == 200, appended.text
    provenance = appended.json()["revision"]["payload"]["provenance"]
    assert {(p["author_kind"], p["actor_id"]) for p in provenance} == {("AGENT", "embedded-agent")}
    selected = await env["client"].post(
        "/api/v1/projects/project/packaging/selections",
        json={"command_id": "s", "preview_id": "x", "preview_digest": "sha256:" + "0" * 64, "expected_head_version": 0},
        headers=_agent_headers(),
    )
    assert selected.status_code == 401
    exported = await env["client"].post(
        "/api/v1/projects/project/packaging/exports",
        json={
            "command_id": "e",
            "source_artifact_key": "k",
            "cohort_id": "c",
            "product_surface": "s",
            "selection_id": "x",
            "selection_digest": "sha256:" + "0" * 64,
        },
        headers=_agent_headers(),
    )
    assert exported.status_code == 401


async def test_reusing_a_revision_command_for_another_draft_conflicts(http) -> None:
    env = http
    body = {"command_id": "rev-1", "quality_run_id": env["run"].run_id, "draft": _draft(env)}
    assert (
        await env["client"].post("/api/v1/projects/project/packaging/revisions", json=body, headers=_headers())
    ).status_code == 200
    changed = body | {"draft": _draft(env) | {"title": "A different history of the river"}}
    response = await env["client"].post(
        "/api/v1/projects/project/packaging/revisions", json=changed, headers=_headers()
    )
    assert response.status_code == 409
    other_actor = await env["client"].post(
        "/api/v1/projects/project/packaging/revisions", json=body, headers=_agent_headers()
    )
    assert other_actor.status_code == 409


async def test_a_stale_revision_head_is_a_conflict_not_a_server_error(http) -> None:
    env = http
    first = await env["client"].post(
        "/api/v1/projects/project/packaging/revisions",
        json={"command_id": "rev-1", "quality_run_id": env["run"].run_id, "draft": _draft(env)},
        headers=_headers(),
    )
    candidate = first.json()["revision"]["candidate_id"]
    stale = await env["client"].post(
        "/api/v1/projects/project/packaging/revisions",
        json={
            "command_id": "rev-2",
            "quality_run_id": env["run"].run_id,
            "candidate_id": candidate,
            "expected_head_version": 7,
            "draft": _draft(env) | {"title": "A history of the river, revised"},
        },
        headers=_headers(),
    )
    assert stale.status_code == 409


async def _exported(env) -> dict[str, Any]:
    flow = await _flow_to_selection(env)
    exported = await env["client"].post(
        "/api/v1/projects/project/packaging/exports",
        json={
            "command_id": "export-1",
            **flow["slot"],
            "selection_id": flow["selection"]["selection_id"],
            "selection_digest": flow["selection"]["selection_digest"],
        },
        headers=_headers(),
    )
    assert exported.status_code == 200, exported.text
    return exported.json()


async def test_a_download_after_the_disposition_is_superseded_is_refused(http) -> None:
    env = http
    receipt = await _exported(env)
    await issue(env, disposition_request(env["run"], "REWORK", command_id="decide-2", version=1))
    archive_hex = receipt["archive_digest"].removeprefix("sha256:")
    refused = await env["client"].get(
        f"/api/v1/projects/project/packaging/exports/{archive_hex}/archive", params={"token": receipt["download_token"]}
    )
    assert refused.status_code == 409


async def test_altered_archive_bytes_are_never_served(http) -> None:
    import os

    env = http
    receipt = await _exported(env)
    archive_hex = receipt["archive_digest"].removeprefix("sha256:")
    path = env["project"] / "exports" / f"{archive_hex}.zip"
    data = bytearray(_bytes(path))
    data[len(data) // 2] ^= 0xFF
    _put(path, bytes(data))
    refused = await env["client"].get(
        f"/api/v1/projects/project/packaging/exports/{archive_hex}/archive", params={"token": receipt["download_token"]}
    )
    assert refused.status_code == 409
    assert [name for name in os.listdir(env["project"] / "exports") if name.startswith(".work-")] == []


async def test_a_download_token_without_expiry_is_refused(http) -> None:
    import jwt

    env = http
    receipt = await _exported(env)
    archive_hex = receipt["archive_digest"].removeprefix("sha256:")
    forged = jwt.encode(
        {"sub": ACTOR, "project": "project", "purpose": "m10-export", "archive": receipt["archive_digest"]},
        auth.get_token_secret(),
        algorithm="HS256",
    )
    refused = await env["client"].get(
        f"/api/v1/projects/project/packaging/exports/{archive_hex}/archive", params={"token": forged}
    )
    assert refused.status_code == 401


def _bytes(path) -> bytes:
    return path.read_bytes()


def _put(path, data: bytes) -> None:
    path.write_bytes(data)


async def test_concurrent_retries_of_one_revision_command_return_one_revision(http) -> None:
    import asyncio

    env = http
    body = {"command_id": "rev-1", "quality_run_id": env["run"].run_id, "draft": _draft(env)}
    first, second = await asyncio.gather(
        env["client"].post("/api/v1/projects/project/packaging/revisions", json=body, headers=_headers()),
        env["client"].post("/api/v1/projects/project/packaging/revisions", json=body, headers=_headers()),
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


async def test_a_retry_cannot_change_its_genesis_or_update_shape(http) -> None:
    env = http
    body = {"command_id": "rev-1", "quality_run_id": env["run"].run_id, "draft": _draft(env)}
    first = await env["client"].post("/api/v1/projects/project/packaging/revisions", json=body, headers=_headers())
    reshaped = body | {"candidate_id": first.json()["revision"]["candidate_id"], "expected_head_version": 0}
    response = await env["client"].post(
        "/api/v1/projects/project/packaging/revisions", json=reshaped, headers=_headers()
    )
    assert response.status_code == 409


async def _slot_status(env, slot: dict[str, str], headers: dict[str, str] | None = None) -> dict[str, Any]:
    found = await env["client"].get(
        "/api/v1/projects/project/packaging/slot", params=slot, headers=headers or _headers()
    )
    assert found.status_code == 200, found.text
    return found.json()


async def test_an_empty_slot_reports_no_selection_and_is_not_exportable(http) -> None:
    env = http
    run, profile = env["run"], env["profile"]
    slot = {
        "source_artifact_key": run.subject.master_binding.root.artifact_key,
        "cohort_id": profile.cohort_id,
        "product_surface": profile.product_surface,
    }
    status = await _slot_status(env, slot)
    assert status == {
        "head_version": 0,
        "exportable": False,
        "refusal_code": "M10_STALE_HEAD",
        "readiness": None,
        "selection": None,
        "exports": [],
    }


async def test_the_slot_reports_the_current_selection_and_its_exports_from_the_server(http) -> None:
    env = http
    flow = await _flow_to_selection(env)
    before = await _slot_status(env, flow["slot"])
    assert before["selection"]["selection_id"] == flow["selection"]["selection_id"]
    assert before["selection"]["selection_digest"] == flow["selection"]["selection_digest"]
    assert (before["head_version"], before["exportable"], before["refusal_code"], before["exports"]) == (
        1,
        True,
        None,
        [],
    )
    exported = await env["client"].post(
        "/api/v1/projects/project/packaging/exports",
        json={
            "command_id": "export-1",
            **flow["slot"],
            "selection_id": flow["selection"]["selection_id"],
            "selection_digest": flow["selection"]["selection_digest"],
        },
        headers=_headers(),
    )
    assert exported.status_code == 200, exported.text
    after = await _slot_status(env, flow["slot"])
    [listed] = after["exports"]
    assert listed["archive_digest"] == exported.json()["archive_digest"]
    assert (listed["selection_id"], listed["current"]) == (flow["selection"]["selection_id"], True)
    downloaded = await env["client"].get(
        f"/api/v1/projects/project/packaging/exports/{listed['archive_digest'].removeprefix('sha256:')}/archive",
        params={"token": listed["download_token"]},
    )
    assert downloaded.status_code == 200
    assert hashlib.sha256(downloaded.content).hexdigest() == listed["archive_digest"].removeprefix("sha256:")
    as_agent = await _slot_status(env, flow["slot"], _agent_headers())
    assert as_agent["exportable"] is True
    assert [item["download_token"] for item in as_agent["exports"]] == [None]


async def test_a_superseded_disposition_makes_the_slot_not_exportable_and_withholds_downloads(http) -> None:
    env = http
    receipt = await _exported(env)
    await issue(env, disposition_request(env["run"], "REWORK", command_id="decide-2", version=1))
    run, profile = env["run"], env["profile"]
    status = await _slot_status(
        env,
        {
            "source_artifact_key": run.subject.master_binding.root.artifact_key,
            "cohort_id": profile.cohort_id,
            "product_surface": profile.product_surface,
        },
    )
    assert (status["exportable"], status["refusal_code"]) == (False, "M10_DISPOSITION_STALE")
    assert status["readiness"]["disposition_decision"] == "REWORK"
    assert status["readiness"]["state"] != "READY"
    assert [(item["archive_digest"], item["download_token"]) for item in status["exports"]] == [
        (receipt["archive_digest"], None)
    ]


async def test_a_replaced_selection_keeps_its_exports_as_history_that_cannot_be_downloaded(http) -> None:
    env = http
    flow = await _flow_to_selection(env)
    exported = await env["client"].post(
        "/api/v1/projects/project/packaging/exports",
        json={
            "command_id": "export-1",
            **flow["slot"],
            "selection_id": flow["selection"]["selection_id"],
            "selection_digest": flow["selection"]["selection_digest"],
        },
        headers=_headers(),
    )
    assert exported.status_code == 200, exported.text
    replacement = await _replace_selection(env, flow)
    status = await _slot_status(env, flow["slot"])
    assert (status["selection"]["selection_id"], status["head_version"], status["exportable"]) == (
        replacement.selection_id,
        2,
        True,
    )
    assert [(item["selection_id"], item["current"], item["download_token"]) for item in status["exports"]] == [
        (flow["selection"]["selection_id"], False, None)
    ]


@pytest.mark.parametrize("new_disposition", [False, True], ids=["same-disposition", "new-disposition"])
async def test_a_selection_replaced_during_the_slot_read_is_projected_from_the_replacement(
    http, new_disposition: bool
) -> None:
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from lib.db.models.quality_packaging import PackagingHeadModel
    from r2.contracts import packaging as p
    from server.services.package_export import PackageExportService

    env = http
    flow = await _flow_to_selection(env)
    head_read, proceed = asyncio.Event(), asyncio.Event()

    class PausingSession(AsyncSession):
        """Stops once, right after the first unlocked head read, until the test has replaced the selection."""

        async def execute(self, statement, *args, **kwargs):
            result = await super().execute(statement, *args, **kwargs)
            descriptions = getattr(statement, "column_descriptions", None) or []
            names = [item.get("name") for item in descriptions]
            entities = {item.get("entity") for item in descriptions}
            if (
                not head_read.is_set()
                and names == ["current_selection_id", "head_version"]
                and entities == {PackagingHeadModel}
            ):
                head_read.set()
                await proceed.wait()
            return result

    pausing = async_sessionmaker(**{**env["factory"].kw, "class_": PausingSession})
    service = PackageExportService(
        sessions=pausing, grant_reader=env["reader"], project_root=env["project"], interactive_token=None
    )
    slot = p.PackagingSlotKey(user_id="default", project_name="project", **flow["slot"])
    reading = asyncio.create_task(service.slot_status(slot, ACTOR))
    await asyncio.wait_for(head_read.wait(), timeout=30)
    if new_disposition:
        await issue(env, disposition_request(env["run"], command_id="decide-2", version=1))
    replacement = await _replace_selection(env, flow)
    proceed.set()
    status = await asyncio.wait_for(reading, timeout=60)
    assert status.selection is not None
    assert (status.selection.selection_id, status.head_version) == (replacement.selection_id, 2)
    assert (status.exportable, status.refusal_code, status.readiness_state) == (True, None, "READY")
    if new_disposition:
        assert replacement.preview.disposition_id != flow["selection"]["preview"]["disposition_id"]
