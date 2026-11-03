"""GeminiReviewer: one generateContent call with the final inline; the answer maps onto the shared assessment."""

from __future__ import annotations

import base64
import json
import shutil

import httpx
import pytest

from r2.contracts.automation import ModelRoute
from server.production_run.evaluators import WATCH, prompt_digest, review_method
from server.production_run.gemini_reviewer import GeminiReviewer, RoutedReviewer
from tests.unit.server.production_run.test_evaluators import ANSWER, ROUTE, _evidence

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

GEMINI = ModelRoute(
    role="reviewer_a",
    provider_id="custom-4",
    model_id="gemini-3.8-flash",
    model_identity="gemini/gemini-3.8-flash",
    config_digest="sha256:" + "5" * 64,
    local=False,
    paid=True,
    currency="USD",
    max_cost_per_call=5,
)


async def _credentials(provider_id: str) -> tuple[str, str]:
    assert provider_id == "custom-4"
    return "https://gemini.test", "test-key"


def _reviewer(handler) -> GeminiReviewer:
    return GeminiReviewer(credentials_for=_credentials, transport=httpx.MockTransport(handler))


async def test_the_final_is_sent_inline_and_the_answer_becomes_the_assessment(tmp_path):
    evidence = _evidence(tmp_path)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(ANSWER)}]}}]})

    review = await _reviewer(handler).assess(route=GEMINI, evidence=evidence)

    assert review.outcome == "COMPLETED"
    assert review.prompt_digest == prompt_digest(WATCH)
    assert dict(review.scores) == ANSWER["scores"]
    [request] = requests
    assert str(request.url) == "https://gemini.test/v1beta/models/gemini-3.8-flash:generateContent"
    assert request.headers["x-goog-api-key"] == "test-key"
    body = json.loads(request.content)
    video = body["contents"][0]["parts"][0]["inline_data"]
    assert video["mime_type"] == "video/mp4"
    assert base64.b64decode(video["data"]) == evidence.final_path.read_bytes()
    assert body["generationConfig"]["temperature"] == 0
    assert body["generationConfig"]["responseMimeType"] == "application/json"


async def test_an_api_error_is_a_failed_review(tmp_path):
    review = await _reviewer(lambda request: httpx.Response(429, json={"error": "quota"})).assess(
        route=GEMINI, evidence=_evidence(tmp_path)
    )

    assert review.outcome == "FAILED"


class _Named:
    def __init__(self, name: str) -> None:
        self.name, self.routes = name, []

    async def assess(self, *, route, evidence):
        self.routes.append(route.model_id)
        return self.name


async def test_gemini_routes_are_watched_and_local_routes_keep_their_method():
    local, gemini = _Named("local"), _Named("gemini")
    routed = RoutedReviewer(local=local, gemini=gemini)

    assert await routed.assess(route=GEMINI, evidence=None) == "gemini"
    assert await routed.assess(route=ROUTE, evidence=None) == "local"
    assert review_method(GEMINI) == WATCH
