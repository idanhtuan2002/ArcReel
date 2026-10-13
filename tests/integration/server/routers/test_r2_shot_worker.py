"""An admitted R2 shot runs from its queued evidence to one M7 submit of the exact captured payload."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.api_call import ApiCall
from lib.db.models.host_hardening import ExecutionAttemptModel
from lib.db.models.production_binding import ProductionBindingVersionModel
from lib.db.repositories.production_binding import ProductionBindingIntegrityError
from lib.generation_queue import R2_SHOT_GENERATION_TASK_TYPE, GenerationQueue
from lib.video_backends.execution_adapter import host_video_route, provider_payload_digest
from r2.production_intelligence.shot_profiles import WAN27_TWO_VIEW_PROFILE
from server.services.r2_shot_generation import R2ShotAdmissionRefused, derive_shot_admission
from server.services.r2_shot_worker import admit_and_plan_spatial_attempt, execute_r2_shot_task, resume_r2_shot_task
from tests.fakes import GateProjectManager, bind_safe_session_factory
from tests.http_capture import capture_http, request_json
from tests.integration.server.routers.test_gates_export import PROJECT, USER
from tests.integration.server.routers.test_r2_shot_admission import _admissible_shot, _builder
from tests.integration.server.routers.test_spatial_constraint_snapshot import _attach, _envelope, _set, _sources

type Factory = async_sessionmaker[AsyncSession]

SUBMIT_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"


async def _queued(client, project_dir, factory, monkeypatch):
    command = await _admissible_shot(client, project_dir, factory, monkeypatch)
    admission = await derive_shot_admission(
        command, session_factory=factory, project_dir=project_dir, payload_builder_for=_builder
    )
    queue = GenerationQueue(session_factory=factory, project_manager=GateProjectManager(project_dir.parent))
    # The backend persists the provider job ID through the process queue; bind it to this test database.
    monkeypatch.setattr("lib.generation_queue.get_generation_queue", lambda: queue)
    evidence = admission.evidence
    await queue.enqueue_task(
        project_name=PROJECT,
        task_type=R2_SHOT_GENERATION_TASK_TYPE,
        media_type="video",
        resource_id=command.target_id,
        resource_type="r2_shot",
        payload=evidence.model_dump(mode="json"),
        user_id=USER.id,
        provider_id="dashscope",
        command_id=command.command_id,
        actor_scope=USER.id,
        command_digest="sha256:" + "c" * 64,
        task_id=evidence.task_id,
    )
    return command, evidence


async def _run(evidence, factory, project_dir):
    return await execute_r2_shot_task(
        PROJECT,
        evidence.target_id,
        evidence.model_dump(mode="json"),
        user_id=USER.id,
        task_id=evidence.task_id,
        session_factory=factory,
        project_dir=project_dir,
        backend_for=_builder,
    )


@pytest.mark.asyncio
async def test_the_worker_submits_the_exact_captured_payload_once_through_m7(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    bind_safe_session_factory(monkeypatch, session_factory)
    _command, evidence = await _queued(gate_export_client, project_dir, session_factory, monkeypatch)

    # Only the poll wait is skipped: the real clock keeps database connect timeouts intact on PostgreSQL,
    # and the fake provider succeeds on the first poll.
    with capture_http() as router, patch("lib.retry.asyncio.sleep", new_callable=AsyncMock):
        submit = router.post(SUBMIT_URL).mock(
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
        router.get("https://x/shot.mp4").mock(return_value=httpx.Response(200, content=b"video-bytes"))
        result = await _run(evidence, session_factory, project_dir)

    assert submit.call_count == 1
    sent = request_json(submit.calls[0].request)
    assert sent["parameters"]["prompt_extend"] is False
    assert sent["model"] == "wan2.7-r2v-2026-06-12"
    assert "Keep the blue exit door on the back wall." in sent["input"]["prompt"]
    assert provider_payload_digest(sent) == evidence.provider_payload_digest
    async with session_factory() as session:
        attempts = list((await session.execute(select(ExecutionAttemptModel))).scalars())
        calls = list((await session.execute(select(ApiCall))).scalars())
    assert [(a.task_id, a.request_digest) for a in attempts] == [(evidence.task_id, evidence.host_request_digest)]
    assert result["r2_shot"]["execution_id"] == attempts[0].execution_id
    assert [(c.call_type, c.execution_id) for c in calls] == [("video", attempts[0].execution_id)]
    assert (project_dir / result["r2_shot"]["output_path"]).read_bytes() == b"video-bytes"
    task = await GenerationQueue(session_factory=session_factory).get_task(evidence.task_id)
    assert task is not None
    assert task["provider_job_id"] == "job-1"


@pytest.mark.asyncio
async def test_a_snapshot_change_after_queueing_stops_before_any_attempt_or_call(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    bind_safe_session_factory(monkeypatch, session_factory)
    _command, evidence = await _queued(gate_export_client, project_dir, session_factory, monkeypatch)
    async with session_factory() as session:
        current_binding = (await session.execute(select(ProductionBindingVersionModel))).scalar_one().binding_id
    changed = _set(current_binding, _sources(await _envelope(session_factory, current_binding)))
    changed = changed.model_copy(update={"normalizer_version": "spatial-r2-v2"})
    await _attach(session_factory, current_binding, changed)

    with capture_http() as router:
        submit = router.post(SUBMIT_URL).mock(return_value=httpx.Response(500))
        with pytest.raises(ProductionBindingIntegrityError, match="stale"):
            await _run(evidence, session_factory, project_dir)

    assert submit.call_count == 0
    async with session_factory() as session:
        assert list((await session.execute(select(ExecutionAttemptModel))).scalars()) == []


@pytest.mark.asyncio
async def test_changed_pinned_bytes_stop_before_any_attempt_or_call(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    bind_safe_session_factory(monkeypatch, session_factory)
    _command, evidence = await _queued(gate_export_client, project_dir, session_factory, monkeypatch)
    pinned = next((project_dir / "r2" / "shot_tasks" / evidence.task_id).glob("image1.png"))
    pinned.write_bytes(b"tampered")

    with capture_http() as router:
        submit = router.post(SUBMIT_URL).mock(return_value=httpx.Response(500))
        with pytest.raises(R2ShotAdmissionRefused, match="r2_shot_source_changed"):
            await _run(evidence, session_factory, project_dir)

    assert submit.call_count == 0
    async with session_factory() as session:
        assert list((await session.execute(select(ExecutionAttemptModel))).scalars()) == []


def _process_dies(_request: httpx.Request) -> httpx.Response:
    """A worker killed mid-poll: cancellation leaves the ledger call pending, as a dead process would."""
    raise asyncio.CancelledError


@pytest.mark.asyncio
async def test_a_crash_while_polling_resumes_the_same_job_without_resubmitting(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    bind_safe_session_factory(monkeypatch, session_factory)
    _command, evidence = await _queued(gate_export_client, project_dir, session_factory, monkeypatch)

    with capture_http() as router, patch("lib.retry.asyncio.sleep", new_callable=AsyncMock):
        router.post(SUBMIT_URL).mock(
            return_value=httpx.Response(200, json={"output": {"task_id": "job-1", "task_status": "PENDING"}})
        )
        router.get("https://dashscope.aliyuncs.com/api/v1/tasks/job-1").mock(side_effect=_process_dies)
        with pytest.raises(asyncio.CancelledError):
            await _run(evidence, session_factory, project_dir)

    task = await GenerationQueue(session_factory=session_factory).get_task(evidence.task_id)
    assert task is not None
    assert task["provider_job_id"] == "job-1"
    with capture_http() as router, patch("lib.retry.asyncio.sleep", new_callable=AsyncMock):
        resubmit = router.post(SUBMIT_URL).mock(return_value=httpx.Response(500))
        router.get("https://dashscope.aliyuncs.com/api/v1/tasks/job-1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "output": {"task_status": "SUCCEEDED", "video_url": "https://x/resumed.mp4"},
                    "usage": {"duration": 5, "output_video_duration": 5},
                },
            )
        )
        router.get("https://x/resumed.mp4").mock(return_value=httpx.Response(200, content=b"resumed-bytes"))
        result = await resume_r2_shot_task(
            task, job_id="job-1", session_factory=session_factory, project_dir=project_dir, backend_for=_builder
        )

    assert resubmit.call_count == 0
    assert (project_dir / result["r2_shot"]["output_path"]).read_bytes() == b"resumed-bytes"
    async with session_factory() as session:
        attempts = list((await session.execute(select(ExecutionAttemptModel))).scalars())
        calls = list((await session.execute(select(ApiCall))).scalars())
    assert len(attempts) == 1
    assert [(c.status, c.execution_id) for c in calls] == [("success", attempts[0].execution_id)]


@pytest.mark.asyncio
async def test_a_binding_change_after_rederivation_blocks_attempt_planning(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The admission transaction rereads the snapshot, so a head change after the worker's check still stops it."""
    bind_safe_session_factory(monkeypatch, session_factory)
    _command, evidence = await _queued(gate_export_client, project_dir, session_factory, monkeypatch)
    backend = await _builder(WAN27_TWO_VIEW_PROFILE)
    route = host_video_route(
        provider_id="dashscope",
        provider_model_id=WAN27_TWO_VIEW_PROFILE.provider_model_id,
        backend_model_id=WAN27_TWO_VIEW_PROFILE.backend_model_id,
        endpoint_id=WAN27_TWO_VIEW_PROFILE.endpoint_id,
        submitted_base_url=backend.submitted_base_url,
    )
    async with session_factory() as session:
        current_binding = (await session.execute(select(ProductionBindingVersionModel))).scalar_one().binding_id
    changed = _set(current_binding, _sources(await _envelope(session_factory, current_binding)))
    await _attach(session_factory, current_binding, changed.model_copy(update={"normalizer_version": "spatial-r2-v2"}))

    with pytest.raises(ProductionBindingIntegrityError, match="stale"):
        await admit_and_plan_spatial_attempt(
            session_factory=session_factory, project_dir=project_dir, evidence=evidence, route=route
        )
    async with session_factory() as session:
        assert list((await session.execute(select(ExecutionAttemptModel))).scalars()) == []

    async with session_factory() as session:
        unchanged = (await session.execute(select(ProductionBindingVersionModel))).scalar_one()
        assert unchanged.binding_id == current_binding
