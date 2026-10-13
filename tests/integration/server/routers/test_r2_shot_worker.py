"""An admitted R2 shot runs from its queued evidence to one M7 submit of the exact captured payload."""

from __future__ import annotations

from pathlib import Path

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
from lib.video_backends.execution_adapter import provider_payload_digest
from server.services.r2_shot_generation import R2ShotAdmissionRefused, derive_shot_admission
from server.services.r2_shot_worker import execute_r2_shot_task
from tests.fakes import GateProjectManager, bind_safe_session_factory, bounded_poll_clock
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

    with capture_http() as router, bounded_poll_clock():
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
