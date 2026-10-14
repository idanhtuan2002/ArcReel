"""A finished R2 shot becomes its target's episode-video master only through Gate C, from server authority."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.artifact_manifest import ArtifactKey, ArtifactManifestEntry, ProjectArtifactManifestAdapter
from lib.db.models.production_binding import ProductionBindingVersionModel
from lib.generation_queue import GenerationQueue
from lib.version_manager import VersionManager
from server.routers import gates
from tests.fakes import bind_safe_session_factory
from tests.http_capture import capture_http
from tests.integration.server.routers.test_gates_export import PROJECT, _body, _media
from tests.integration.server.routers.test_r2_shot_worker import SUBMIT_URL, _queued, _run
from tests.integration.server.routers.test_spatial_constraint_snapshot import _attach, _envelope, _set, _sources

type Factory = async_sessionmaker[AsyncSession]

VIDEO = _media(b"r2-shot")


def _url(target_id: str) -> str:
    return f"/api/v1/projects/{PROJECT}/gates/r2-shots/{target_id}"


async def _generated(client, project_dir, factory, monkeypatch, *, seal: bool = True):
    """Run the shot worker against a fake provider and finish the task the way the queue does."""
    bind_safe_session_factory(monkeypatch, factory)
    _command, evidence = await _queued(client, project_dir, factory, monkeypatch)
    with capture_http() as router, patch("lib.retry.asyncio.sleep", new_callable=AsyncMock):
        router.post(SUBMIT_URL).mock(
            return_value=httpx.Response(200, json={"output": {"task_id": "job-1", "task_status": "PENDING"}})
        )
        router.get("https://dashscope.aliyuncs.com/api/v1/tasks/job-1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "output": {"task_status": "SUCCEEDED", "video_url": "https://x/shot.mp4"},
                    "usage": {"duration": 5, "output_video_duration": 5},
                },
            )
        )
        router.get("https://x/shot.mp4").mock(return_value=httpx.Response(200, content=VIDEO))
        if seal:
            result = await _run(evidence, factory, project_dir)
        else:
            # An output generated before the worker sealed outputs: only the queue's legacy mirror ran.
            with patch("server.services.r2_shot_worker.seal_r2_shot_output", new=AsyncMock(return_value="")):
                result = await _run(evidence, factory, project_dir)
    queue = GenerationQueue(session_factory=factory)
    claimed = await queue.claim_next_task("video")
    assert claimed is not None
    assert claimed["task_id"] == evidence.task_id
    assert await queue.mark_task_succeeded(evidence.task_id, result) == 1
    return evidence


def _versions(project_dir: Path, target_id: str) -> list[dict]:
    return VersionManager(project_dir).get_versions("videos", target_id)["versions"]


@pytest.mark.asyncio
async def test_a_sealed_shot_output_becomes_the_target_master_and_replays(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = await _generated(gate_export_client, project_dir, session_factory, monkeypatch)
    body = {"task_id": evidence.task_id, "approval_record": "APR-r2-shot-1"}

    response = await gate_export_client.post(_url(evidence.target_id), json=body)

    assert response.status_code == 200, response.text
    approved = response.json()
    assert approved["receipt"]["artifact_key"] == ArtifactKey.episode_video(1, evidence.target_id).encode()
    assert approved["approved_master"]["approval_record"] == "APR-r2-shot-1"
    [version] = _versions(project_dir, evidence.target_id)
    assert version["method"] == "GENERATED_VIDEO"
    assert version["execution_fingerprint"] == evidence.host_request_digest
    assert version["output_sha256"] == hashlib.sha256(VIDEO).hexdigest()
    assert version["prompt"].startswith("R2 provider candidate m7:")
    assert (project_dir / "r2_m3_current" / f"{evidence.target_id}.mp4").read_bytes() == VIDEO

    replay = await gate_export_client.post(_url(evidence.target_id), json=body)
    assert replay.status_code == 200, replay.text
    assert replay.json()["receipt"] == approved["receipt"]
    assert len(_versions(project_dir, evidence.target_id)) == 1


@pytest.mark.asyncio
async def test_a_mistargeted_or_changed_output_is_refused(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = await _generated(gate_export_client, project_dir, session_factory, monkeypatch)
    other = await gate_export_client.post(
        _url("scene-9-TAKE-1"), json={"task_id": evidence.task_id, "approval_record": "APR-1"}
    )
    assert (other.status_code, other.json()["detail"]) == (409, "r2_shot_task_target_mismatch")
    (project_dir / "r2" / "shot_tasks" / evidence.task_id / "output.mp4").write_bytes(b"swapped")

    response = await gate_export_client.post(
        _url(evidence.target_id), json={"task_id": evidence.task_id, "approval_record": "APR-1"}
    )

    assert (response.status_code, response.json()["detail"]) == (409, "r2_shot_output_changed")
    assert _versions(project_dir, evidence.target_id) == []


@pytest.mark.asyncio
async def test_an_unsealed_output_is_refused(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = await _generated(gate_export_client, project_dir, session_factory, monkeypatch, seal=False)

    response = await gate_export_client.post(
        _url(evidence.target_id), json={"task_id": evidence.task_id, "approval_record": "APR-1"}
    )

    assert (response.status_code, response.json()["detail"]) == (409, "r2_shot_output_unsealed")


@pytest.mark.asyncio
async def test_unknown_unfinished_or_malformed_requests_are_refused(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    bind_safe_session_factory(monkeypatch, session_factory)
    _command, evidence = await _queued(gate_export_client, project_dir, session_factory, monkeypatch)

    unknown = await gate_export_client.post(
        _url(evidence.target_id), json={"task_id": "missing", "approval_record": "APR-1"}
    )
    queued = await gate_export_client.post(
        _url(evidence.target_id), json={"task_id": evidence.task_id, "approval_record": "APR-1"}
    )
    unsafe = await gate_export_client.post(
        _url("scene-1-TAKE-1:x"), json={"task_id": evidence.task_id, "approval_record": "APR-1"}
    )
    extra = await gate_export_client.post(
        _url(evidence.target_id),
        json={"task_id": evidence.task_id, "approval_record": "APR-1", "produced": {"sha256": "x"}},
    )

    assert (unknown.status_code, unknown.json()["detail"]) == (404, "r2_shot_task_not_found")
    assert (queued.status_code, queued.json()["detail"]) == (409, "r2_shot_task_not_succeeded")
    assert unsafe.status_code == 400
    assert extra.status_code == 422


@pytest.mark.asyncio
async def test_a_binding_change_after_generation_is_refused_as_stale(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = await _generated(gate_export_client, project_dir, session_factory, monkeypatch)
    async with session_factory() as session:
        current_binding = (await session.execute(select(ProductionBindingVersionModel.binding_id))).scalars().first()
    changed = _set(current_binding, _sources(await _envelope(session_factory, current_binding)))
    await _attach(session_factory, current_binding, changed.model_copy(update={"normalizer_version": "spatial-r2-v2"}))

    response = await gate_export_client.post(
        _url(evidence.target_id), json={"task_id": evidence.task_id, "approval_record": "APR-1"}
    )

    assert (response.status_code, response.json()["detail"]) == (409, "r2_shot_binding_stale")
    assert _versions(project_dir, evidence.target_id) == []


@pytest.mark.asyncio
async def test_a_slot_owned_by_a_non_r2_artifact_is_refused(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = await _generated(gate_export_client, project_dir, session_factory, monkeypatch)
    ProjectArtifactManifestAdapter(project_dir).put_entry(
        ArtifactKey.episode_video(1, evidence.target_id),
        ArtifactManifestEntry(artifact_path=f"videos/{evidence.target_id}.mp4", basis_digest="sha256-v1:" + "0" * 64),
    )

    response = await gate_export_client.post(
        _url(evidence.target_id), json={"task_id": evidence.task_id, "approval_record": "APR-1"}
    )

    assert (response.status_code, response.json()["detail"]) == (409, "r2_shot_slot_owned")
    assert _versions(project_dir, evidence.target_id) == []


@pytest.mark.asyncio
async def test_a_slot_taken_after_the_unlocked_check_is_refused_under_the_lock(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = await _generated(gate_export_client, project_dir, session_factory, monkeypatch)
    prepare = gates.prepare_r2_shot_cut

    async def prepare_then_lose_the_slot(**kwargs):
        cut = await prepare(**kwargs)
        # Another approval establishes a non-R2 contract between the unlocked check and the slot lock.
        ProjectArtifactManifestAdapter(project_dir).put_entry(
            ArtifactKey.episode_video(1, evidence.target_id),
            ArtifactManifestEntry(
                artifact_path=f"videos/{evidence.target_id}.mp4", basis_digest="sha256-v1:" + "0" * 64
            ),
        )
        return cut

    monkeypatch.setattr(gates, "prepare_r2_shot_cut", prepare_then_lose_the_slot)

    response = await gate_export_client.post(
        _url(evidence.target_id), json={"task_id": evidence.task_id, "approval_record": "APR-1"}
    )

    assert (response.status_code, response.json()["detail"]) == (409, "r2_shot_slot_owned")
    assert _versions(project_dir, evidence.target_id) == []


@pytest.mark.asyncio
async def test_the_legacy_gate_c_route_refuses_a_registered_r2_shot(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = await _generated(gate_export_client, project_dir, session_factory, monkeypatch)
    data = _media(b"client-chosen-bytes")
    (project_dir / "production" / f"{evidence.target_id}.mp4").write_bytes(data)

    response = await gate_export_client.post(
        f"/api/v1/projects/{PROJECT}/gates/final-cut", json=_body(evidence.target_id, data)
    )

    assert (response.status_code, response.json()["detail"]) == (409, "r2_shot_requires_task_custody")
    assert _versions(project_dir, evidence.target_id) == []

    # Only the R2 episode's slot is reserved: the same ID in another episode is an ordinary approval.
    other_episode = await gate_export_client.post(
        f"/api/v1/projects/{PROJECT}/gates/final-cut", json=_body(evidence.target_id, data) | {"episode": 2}
    )
    assert other_episode.status_code == 200, other_episode.text
