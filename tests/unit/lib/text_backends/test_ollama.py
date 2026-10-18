"""Ollama 原生 /api/chat 后端：精确请求体、响应解析、错误分类与「一次调用一次 HTTP」。

响应体取自 tests/fixtures/ollama/ 里 Ollama 0.32.6 的真实返回；传输层用 httpx.MockTransport 记录请求。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from lib.text_backends.base import (
    StructuredOutputExhaustedError,
    TextGenerationRequest,
    TextOutputTruncatedError,
)
from lib.text_backends.ollama import (
    OllamaChatClient,
    OllamaChatRequest,
    OllamaChatTextBackend,
    OllamaHTTPError,
    OllamaOutcomeUnknownError,
    OllamaOverContextError,
    OllamaProtocolError,
    OllamaUnavailableError,
    normalize_ollama_base_url,
)

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "ollama"


def _fixture(name: str) -> httpx.Response:
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return httpx.Response(data["status"], content=data["body"].encode("utf-8"))


class _Recorder:
    def __init__(self, respond) -> None:
        self.requests: list[httpx.Request] = []
        self._respond = respond

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            outcome = self._respond(request)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return httpx.MockTransport(handler)


def _request(**overrides) -> OllamaChatRequest:
    fields = {
        "model": "ornith-32k:9b",
        "messages": (("system", "Bạn là người viết văn tiếng Việt."), ("user", "Viết một câu về mưa.")),
        "num_ctx": 32768,
        "num_predict": 60,
        "options": {"temperature": 0.7, "seed": 1},
    }
    fields.update(overrides)
    return OllamaChatRequest(**fields)


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("http://localhost:11434", "http://localhost:11434"),
        ("http://localhost:11434/", "http://localhost:11434"),
        ("http://localhost:11434/v1", "http://localhost:11434"),
        ("http://localhost:11434/v1/", "http://localhost:11434"),
    ],
)
def test_base_url_drops_the_openai_compatible_suffix(configured, expected):
    assert normalize_ollama_base_url(configured) == expected


async def test_the_request_body_is_exact_and_fail_closed():
    recorder = _Recorder(lambda _: _fixture("stop_text"))
    client = OllamaChatClient(base_url="http://localhost:11434/v1", transport=recorder.transport())
    schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

    await client.chat(_request(format=schema, keep_alive="30m"))

    (sent,) = recorder.requests
    assert str(sent.url) == "http://localhost:11434/api/chat"
    assert "authorization" not in sent.headers
    assert json.loads(sent.content) == {
        "model": "ornith-32k:9b",
        "stream": False,
        "think": False,
        "truncate": False,
        "shift": False,
        "messages": [
            {"role": "system", "content": "Bạn là người viết văn tiếng Việt."},
            {"role": "user", "content": "Viết một câu về mưa."},
        ],
        "options": {"temperature": 0.7, "seed": 1, "num_ctx": 32768, "num_predict": 60},
        "format": schema,
        "keep_alive": "30m",
    }


async def test_limits_in_options_cannot_override_the_explicit_limits():
    recorder = _Recorder(lambda _: _fixture("stop_text"))
    client = OllamaChatClient(base_url="http://h:1", transport=recorder.transport())

    await client.chat(_request(options={"num_ctx": 999999, "num_predict": -1}))

    options = json.loads(recorder.requests[0].content)["options"]
    assert options["num_ctx"] == 32768
    assert options["num_predict"] == 60


async def test_an_api_key_is_sent_as_bearer_only_when_configured():
    recorder = _Recorder(lambda _: _fixture("stop_text"))
    client = OllamaChatClient(base_url="http://h:1", api_key="proxy-token", transport=recorder.transport())

    await client.chat(_request())

    assert recorder.requests[0].headers["authorization"] == "Bearer proxy-token"


async def test_a_stop_response_is_parsed_with_its_counts():
    client = OllamaChatClient(base_url="http://h:1", transport=_Recorder(lambda _: _fixture("stop_text")).transport())

    response = await client.chat(_request())

    assert response.done is True
    assert response.done_reason == "stop"
    assert response.prompt_eval_count == 32
    assert response.eval_count == 30
    assert response.content.startswith("Bọn trẻ thơ")
    assert response.model == "ornith-32k:9b"


async def test_a_length_response_keeps_its_done_reason():
    client = OllamaChatClient(base_url="http://h:1", transport=_Recorder(lambda _: _fixture("length")).transport())

    response = await client.chat(_request(num_predict=8))

    assert (response.done, response.done_reason, response.eval_count) == (True, "length", 8)


async def test_over_context_yields_the_exact_server_count_in_one_request():
    recorder = _Recorder(lambda _: _fixture("over_context"))
    client = OllamaChatClient(base_url="http://h:1", transport=recorder.transport())

    with pytest.raises(OllamaOverContextError) as caught:
        await client.chat(_request())

    assert (caught.value.prompt_tokens, caught.value.context_tokens) == (80026, 32768)
    assert len(recorder.requests) == 1


async def test_an_unknown_model_is_an_http_error_without_retry():
    recorder = _Recorder(lambda _: _fixture("unknown_model"))
    client = OllamaChatClient(base_url="http://h:1", transport=recorder.transport())

    with pytest.raises(OllamaHTTPError) as caught:
        await client.chat(_request(model="no-such-model:1b"))

    assert caught.value.status_code == 404
    assert "not found" in caught.value.message
    assert len(recorder.requests) == 1


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (httpx.ConnectError("refused"), OllamaUnavailableError),
        (httpx.ConnectTimeout("slow"), OllamaUnavailableError),
        (httpx.ReadTimeout("slow"), OllamaOutcomeUnknownError),
        (httpx.RemoteProtocolError("closed"), OllamaOutcomeUnknownError),
    ],
)
async def test_transport_failures_are_classified_without_retry(raised, expected):
    recorder = _Recorder(lambda _: raised)
    client = OllamaChatClient(base_url="http://h:1", transport=recorder.transport())

    with pytest.raises(expected):
        await client.chat(_request())

    assert len(recorder.requests) == 1


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b'{"model": "m", "done": true}',
        b'{"model": "m", "message": {"content": "x"}}',
        b'{"model": "m", "message": {"content": 3}, "done": true}',
        b'{"model": "m", "message": {"content": "x"}, "done": "yes"}',
    ],
)
async def test_a_200_with_a_malformed_body_is_a_protocol_error(body):
    client = OllamaChatClient(
        base_url="http://h:1", transport=_Recorder(lambda _: httpx.Response(200, content=body)).transport()
    )

    with pytest.raises(OllamaProtocolError):
        await client.chat(_request())


class _Sentence(BaseModel):
    text: str


async def test_the_text_backend_returns_the_finish_reason_and_usage():
    recorder = _Recorder(lambda _: _fixture("format_envelope"))
    backend = OllamaChatTextBackend(base_url="http://h:1", model="ornith-32k:9b", transport=recorder.transport())

    result = await backend.generate(
        TextGenerationRequest(prompt="Viết một câu.", system_prompt="Viết tiếng Việt.", response_schema=_Sentence)
    )

    assert _Sentence.model_validate_json(result.text).text.startswith("Mưa")
    assert (result.finish_reason, result.input_tokens, result.output_tokens) == ("stop", 38, 27)
    body = json.loads(recorder.requests[0].content)
    assert body["format"] == _Sentence.model_json_schema()
    assert body["messages"][0] == {"role": "system", "content": "Viết tiếng Việt."}


async def test_a_structured_length_stop_is_a_hard_error():
    backend = OllamaChatTextBackend(
        base_url="http://h:1", model="m", transport=_Recorder(lambda _: _fixture("length")).transport()
    )

    with pytest.raises(TextOutputTruncatedError):
        await backend.generate(TextGenerationRequest(prompt="x", response_schema=_Sentence))


async def test_free_text_length_stop_is_reported_not_raised():
    backend = OllamaChatTextBackend(
        base_url="http://h:1", model="m", transport=_Recorder(lambda _: _fixture("length")).transport()
    )

    result = await backend.generate(TextGenerationRequest(prompt="x"))

    assert result.finish_reason == "length"


async def test_schema_violation_fails_without_a_fallback_call():
    recorder = _Recorder(lambda _: _fixture("stop_text"))
    backend = OllamaChatTextBackend(base_url="http://h:1", model="m", transport=recorder.transport())

    with pytest.raises(StructuredOutputExhaustedError):
        await backend.generate(TextGenerationRequest(prompt="x", response_schema=_Sentence))

    assert len(recorder.requests) == 1


async def test_images_are_refused_before_any_request():
    from lib.text_backends.base import ImageInput

    recorder = _Recorder(lambda _: _fixture("stop_text"))
    backend = OllamaChatTextBackend(base_url="http://h:1", model="m", transport=recorder.transport())

    with pytest.raises(OllamaProtocolError):
        await backend.generate(TextGenerationRequest(prompt="x", images=[ImageInput(url="http://i")]))

    assert recorder.requests == []
