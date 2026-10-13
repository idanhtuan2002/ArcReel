"""R2 shot generation on DashScope: an explicit prompt_extend, a captured payload and its M7 identity envelope."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from lib.video_backends.base import VideoCapabilityError, VideoGenerationRequest
from lib.video_backends.dashscope import DashScopeVideoBackend
from lib.video_backends.execution_adapter import provider_payload_digest
from tests.unit.lib.video_backends.attempt_bound_support import RecordingAttemptSubmitter
from tests.unit.lib.video_backends.test_dashscope_video_backend import _client, _ref, _resp, _submit

MODEL = "wan2.7-r2v-2026-06-12"


def _request(tmp_path: Path, **fields: object) -> VideoGenerationRequest:
    return VideoGenerationRequest(
        prompt="Image 1 is the front view of the set.",
        output_path=tmp_path / "out.mp4",
        aspect_ratio="16:9",
        duration_seconds=5,
        resolution="720P",
        reference_images=[_ref(tmp_path, "front.png"), _ref(tmp_path, "reverse.png")],
        **fields,
    )


def test_prompt_extend_is_sent_only_when_set(tmp_path: Path) -> None:
    backend = DashScopeVideoBackend(api_key="sk", model=MODEL)

    legacy = backend.build_submit_payload(_request(tmp_path))
    pinned = backend.build_submit_payload(_request(tmp_path, prompt_extend=False))

    assert "prompt_extend" not in legacy["parameters"]
    assert pinned["parameters"]["prompt_extend"] is False
    assert {key: value for key, value in pinned["parameters"].items() if key != "prompt_extend"} == legacy["parameters"]
    assert [item["type"] for item in pinned["input"]["media"]] == ["reference_image", "reference_image"]


def test_a_captured_payload_is_submitted_unchanged_and_must_name_this_model(tmp_path: Path) -> None:
    backend = DashScopeVideoBackend(api_key="sk", model=MODEL)
    captured = backend.build_submit_payload(_request(tmp_path, prompt_extend=False))

    assert backend._submit_payload(_request(tmp_path, captured_payload=captured)) is captured
    with pytest.raises(VideoCapabilityError):
        backend._submit_payload(_request(tmp_path, captured_payload={**captured, "model": "wan2.6-r2v"}))


async def test_the_m7_request_carries_the_r2_envelope_that_names_the_captured_payload(tmp_path: Path) -> None:
    backend = DashScopeVideoBackend(api_key="sk", model=MODEL)
    captured = backend.build_submit_payload(_request(tmp_path, prompt_extend=False))
    envelope = {
        "provider_payload_digest": provider_payload_digest(captured),
        "binding_snapshot_digest": "sha256:" + "1" * 64,
    }
    submitter = RecordingAttemptSubmitter()
    network = AsyncMock(return_value=_resp(_submit("job-1")))
    request = _request(
        tmp_path,
        captured_payload=captured,
        r2_execution_options=envelope,
        task_id="task-1",
        attempt_submitter=submitter,
    )

    await backend._create_task(_client(post=network), captured, request)

    assert submitter.calls[0]["request"].execution_options == envelope
    assert network.await_args.kwargs["json"] is captured


@pytest.mark.parametrize(
    "envelope",
    [None, {"provider_payload_digest": "sha256:" + "0" * 64}],
    ids=["missing", "wrong-digest"],
)
async def test_a_captured_payload_without_its_identity_never_reaches_the_provider(
    tmp_path: Path, envelope: dict | None
) -> None:
    backend = DashScopeVideoBackend(api_key="sk", model=MODEL)
    captured = backend.build_submit_payload(_request(tmp_path, prompt_extend=False))
    network = AsyncMock(return_value=_resp(_submit("job-1")))
    request = _request(
        tmp_path,
        captured_payload=captured,
        r2_execution_options=envelope,
        task_id="task-1",
        attempt_submitter=RecordingAttemptSubmitter(),
    )

    with pytest.raises(RuntimeError, match="M7_R2_IDENTITY_MISSING"):
        await backend._create_task(_client(post=network), captured, request)
    network.assert_not_awaited()
