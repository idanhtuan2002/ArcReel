from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lib.video_backends.base import VideoGenerationRequest
from lib.video_backends.execution_adapter import (
    AttemptReplayRequiresResume,
    accepted_submit_receipt,
    submit_video_attempt,
)


class _RecordingSubmitter:
    def __init__(self, *, replay: bool = False) -> None:
        self.calls: list[dict] = []
        self.replay = replay

    async def submit(self, **kwargs):
        self.calls.append(kwargs)
        if self.replay:
            return SimpleNamespace(
                execution_id="execution-1",
                snapshot=SimpleNamespace(execution_id="execution-1", state=SimpleNamespace(value="ACCEPTED")),
                value=None,
            )
        receipt = await kwargs["submit"](SimpleNamespace(execution_id="execution-1"))
        return SimpleNamespace(
            execution_id="execution-1",
            snapshot=SimpleNamespace(execution_id="execution-1", state=SimpleNamespace(value="ACCEPTED")),
            value=receipt.value,
        )


def _request(tmp_path: Path, **overrides) -> VideoGenerationRequest:
    start = tmp_path / "start.png"
    start.write_bytes(b"start")
    values = {
        "prompt": "paper boat",
        "output_path": tmp_path / "out.mp4",
        "start_image": start,
        "duration_seconds": 5,
        "aspect_ratio": "16:9",
    }
    values.update(overrides)
    return VideoGenerationRequest(**values)


async def test_worker_submit_builds_durable_route_and_semantic_request(tmp_path: Path) -> None:
    submitter = _RecordingSubmitter()
    request = _request(
        tmp_path,
        task_id="task-1",
        api_call_id=7,
        attempt_submitter=submitter,
    )
    network = AsyncMock(return_value=accepted_submit_receipt("job-1", provider_job_id="job-1"))

    result = await submit_video_attempt(
        request,
        provider_id="dashscope",
        provider_model_id="wan2.7-i2v",
        backend_model_id="wan2.7-i2v",
        endpoint_id="video-synthesis",
        submitted_base_url="https://dashscope.example",
        submit=network,
    )

    assert result == "job-1"
    assert request.execution_id == "execution-1"
    assert len(submitter.calls) == 1
    call = submitter.calls[0]
    assert call["task_id"] == "task-1"
    assert call["api_call_id"] == 7
    assert call["route"].provider_id == "dashscope"
    assert call["route"].endpoint_id == "video-synthesis"
    assert call["request"].host_task_ref == "task-1"
    assert call["request"].provider == "dashscope"
    assert call["request"].payload["prompt"] == "paper boat"
    assert call["request"].payload["start_image_digest"].startswith("sha256:")
    network.assert_awaited_once()


async def test_direct_submit_keeps_non_worker_path_unbound(tmp_path: Path) -> None:
    request = _request(tmp_path)
    network = AsyncMock(return_value=accepted_submit_receipt("job-1", provider_job_id="job-1"))

    result = await submit_video_attempt(
        request,
        provider_id="dashscope",
        provider_model_id="wan2.7-i2v",
        backend_model_id="wan2.7-i2v",
        endpoint_id="video-synthesis",
        submitted_base_url="https://dashscope.example",
        submit=network,
    )

    assert result == "job-1"
    assert request.execution_id is None
    network.assert_awaited_once()


async def test_exact_replay_requires_resume_without_network_resubmit(tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        task_id="task-1",
        api_call_id=7,
        attempt_submitter=_RecordingSubmitter(replay=True),
    )
    network = AsyncMock(return_value=accepted_submit_receipt("job-1", provider_job_id="job-1"))

    with pytest.raises(AttemptReplayRequiresResume, match="execution-1"):
        await submit_video_attempt(
            request,
            provider_id="dashscope",
            provider_model_id="wan2.7-i2v",
            backend_model_id="wan2.7-i2v",
            endpoint_id="video-synthesis",
            submitted_base_url="https://dashscope.example",
            submit=network,
        )

    network.assert_not_awaited()


async def test_worker_submit_emits_an_attempt_span_joining_task_execution_and_usage(tmp_path: Path) -> None:
    from server.telemetry import configure_test_tracer

    exporter = configure_test_tracer()
    request = _request(tmp_path, task_id="task-1", api_call_id=7, attempt_submitter=_RecordingSubmitter())
    network = AsyncMock(return_value=accepted_submit_receipt("job-1", provider_job_id="job-1"))

    await submit_video_attempt(
        request,
        provider_id="dashscope",
        provider_model_id="wan2.7-i2v",
        backend_model_id="wan2.7-i2v",
        endpoint_id="video-synthesis",
        submitted_base_url="https://dashscope.example",
        submit=network,
    )

    (span,) = [s for s in exporter.get_finished_spans() if s.name == "execution.attempt_submitted"]
    attributes = dict(span.attributes or {})
    assert attributes["task_id"] == "task-1"
    assert attributes["execution_id"] == "execution-1"
    assert attributes["usage_entry_id"] == "7"
    assert attributes["provider.id"] == "dashscope"
    assert attributes["attempt.state"] == "ACCEPTED"
    assert "dashscope.example" not in str(attributes)


async def test_a_release_deployment_binds_a_direct_submit_before_the_network(tmp_path: Path, monkeypatch) -> None:
    """发布部署下非 worker 提交同样先过提交路线登记：未登记的路线不发任何供应商请求。"""
    from r2.host_hardening.paid_routes import RELEASE_MODE_ENV
    from r2.host_hardening.route_inventory import SubmitRouteUnboundError

    monkeypatch.setenv(RELEASE_MODE_ENV, "PRODUCTION_CANDIDATE")
    network = AsyncMock(return_value=accepted_submit_receipt("job-1", provider_job_id="job-1"))

    with pytest.raises(SubmitRouteUnboundError):
        await submit_video_attempt(
            _request(tmp_path),
            provider_id="unlisted-provider",
            provider_model_id="m",
            backend_model_id="m",
            endpoint_id="video-synthesis",
            submitted_base_url="https://provider.example",
            submit=network,
        )

    network.assert_not_awaited()
