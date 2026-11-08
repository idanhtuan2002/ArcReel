"""Frame reviewers and the image judge reach a model through the endpoint its provider declares."""

from __future__ import annotations

import json
import math
from pathlib import Path

import httpx

from r2.contracts.automation import ModelRoute
from server.production_run.evaluators import FRAME_COUNT, FrameReviewer, first_token_probability, strip_fence
from server.production_run.vision_chat import ModelAccess, vision_chat
from tests.unit.server.production_run.test_evaluators import ANSWER, _evidence

CLOUD = ModelRoute(
    role="reviewer_b",
    provider_id="custom-9",
    model_id="any-vision-model",
    model_identity="cloud/any-vision-model",
    config_digest="sha256:" + "3" * 64,
    local=False,
    paid=True,
    currency="USD",
    max_cost_per_call=5,
)


def _openai(sent: list[dict], *, fenced: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append({"url": str(request.url), "auth": request.headers.get("authorization"), "body": body})
        text = body["messages"][0]["content"][0]["text"]
        if "response_format" in body:
            content = json.dumps(ANSWER)
            content = f"```json\n{content}\n```" if fenced else content
        elif "Which one is upright" in text:
            content = "A"
        else:
            content = "yes" if "«" in text else "no"
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return handler


async def test_a_frame_reviewer_on_an_openai_compatible_endpoint_asks_the_same_questions(tmp_path: Path) -> None:
    sent: list[dict] = []

    async def access(provider_id: str, model_id: str) -> ModelAccess:
        assert (provider_id, model_id) == ("custom-9", "any-vision-model")
        return ModelAccess("openai", "https://vision.example.test/v1", "fixture-vision-key")

    reviewer = FrameReviewer(access_for=access, transport=httpx.MockTransport(_openai(sent, fenced=True)))
    review = await reviewer.assess(route=CLOUD, evidence=_evidence(tmp_path))

    assert review.outcome == "COMPLETED"
    assert [f.code for f in review.findings] == ["SOFT_FOCUS"]
    assert len(sent) == 4 * FRAME_COUNT + 1
    assert {call["url"] for call in sent} == {"https://vision.example.test/v1/chat/completions"}
    assert {call["auth"] for call in sent} == {"Bearer fixture-vision-key"}
    final = sent[-1]["body"]
    assert final["temperature"] == 0
    assert final["response_format"]["json_schema"]["schema"]["required"] == ["language", "scores", "findings"]
    pictures = [part for part in final["messages"][0]["content"] if part["type"] == "image_url"]
    assert len(pictures) == FRAME_COUNT
    assert pictures[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert all(call["body"]["max_tokens"] == 8 for call in sent[:-1])


async def test_a_cloud_reviewer_that_keeps_failing_is_a_failed_review(tmp_path: Path) -> None:
    async def access(_provider_id: str, _model_id: str) -> ModelAccess:
        return ModelAccess("openai", "https://vision.example.test/v1", "k")

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503)

    reviewer = FrameReviewer(access_for=access, transport=httpx.MockTransport(handler), backoff_seconds=0)
    review = await reviewer.assess(route=CLOUD, evidence=_evidence(tmp_path))
    assert review.outcome == "FAILED"
    assert len(calls) == 6


async def test_gemini_and_openai_logprobs_read_as_one_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "generationConfig" in body:
            assert body["generationConfig"]["responseLogprobs"] is True
            assert body["contents"][0]["parts"][0]["inline_data"]["mime_type"] == "image/png"
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {"parts": [{"text": "yes"}]},
                            "logprobsResult": {
                                "topCandidates": [
                                    {
                                        "candidates": [
                                            {"token": "yes", "logProbability": math.log(0.75)},
                                            {"token": "no", "logProbability": math.log(0.25)},
                                        ]
                                    }
                                ]
                            },
                        }
                    ]
                },
            )
        assert body["logprobs"] is True
        assert body["top_logprobs"] == 10
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "yes"},
                        "logprobs": {
                            "content": [
                                {
                                    "token": "yes",
                                    "logprob": math.log(0.75),
                                    "top_logprobs": [
                                        {"token": "yes", "logprob": math.log(0.75)},
                                        {"token": " no", "logprob": math.log(0.25)},
                                    ],
                                }
                            ]
                        },
                    }
                ]
            },
        )

    png = b"\x89PNG\r\n\x1a\nfixture"
    for access in (ModelAccess("gemini", "https://g.example.test", "k"), ModelAccess("openai", "https://o.test/v1")):
        async with vision_chat(access, "m", timeout_seconds=5, transport=httpx.MockTransport(handler)) as chat:
            reply = await chat.ask("Does it?", [png], max_tokens=1, top_logprobs=10)
        assert math.isclose(first_token_probability(reply.logprobs, yes="yes", no="no") or 0, 0.75)


def test_a_fenced_json_answer_is_unwrapped() -> None:
    assert json.loads(strip_fence('```json\n{"a": 1}\n```')) == {"a": 1}
    assert strip_fence('{"a": 1}') == '{"a": 1}'
