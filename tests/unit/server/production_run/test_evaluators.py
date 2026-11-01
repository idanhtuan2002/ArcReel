from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from r2.contracts.automation import ModelRoute
from server.production_run.evaluators import CONTEXT_TOKENS, FRAME_COUNT, FinalEvidence, OllamaReviewer

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

ROUTE = ModelRoute(
    role="reviewer_a",
    provider_id="custom-1",
    model_id="qwen2.5vl:7b",
    model_identity="ollama/qwen2.5vl:7b",
    config_digest="sha256:" + "1" * 64,
    local=True,
    paid=False,
    currency="USD",
    max_cost_per_call=None,
)
ANSWER = {
    "language": "vi",
    "scores": {"story": 4, "visual": 5, "audio": 4, "continuity": 4, "pacing": 4},
    "findings": [{"code": "soft_focus", "severity": "MINOR", "repair_stage": None, "detail": "cảnh 2 hơi mờ"}],
}


def _evidence(tmp_path: Path) -> FinalEvidence:
    final = tmp_path / "final.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=576x1024:r=24:d=4", str(final)],
        check=True,
    )
    subtitles = tmp_path / "final.srt"
    subtitles.write_text("1\n00:00:00,000 --> 00:00:02,000\nXin chào\n", encoding="utf-8")
    return FinalEvidence(
        unit_key="episode:1",
        final_path=final,
        subtitle_path=subtitles,
        narration_text="Xin chào",
        subject_digest="sha256:" + "2" * 64,
    )


async def _base_url(_provider_id: str) -> str:
    return "http://reviewer.test:11434"


async def test_review_request_refuses_silent_truncation_and_sends_every_frame(tmp_path: Path) -> None:
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": json.dumps(ANSWER)}})

    review = await OllamaReviewer(base_url_for=_base_url, transport=httpx.MockTransport(handler)).assess(
        route=ROUTE, evidence=_evidence(tmp_path)
    )

    assert review.outcome == "COMPLETED"
    assert review.language == "vi"
    assert [f.code for f in review.findings] == ["SOFT_FOCUS"]
    body = sent[0]
    assert (body["truncate"], body["shift"], body["stream"]) == (False, False, False)
    assert body["options"]["num_ctx"] == CONTEXT_TOKENS
    assert body["model"] == "qwen2.5vl:7b"
    assert len(body["messages"][0]["images"]) == FRAME_COUNT


async def test_context_overflow_fails_the_review(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "input length exceeds context length"})

    review = await OllamaReviewer(base_url_for=_base_url, transport=httpx.MockTransport(handler)).assess(
        route=ROUTE, evidence=_evidence(tmp_path)
    )

    assert review.outcome == "FAILED"
