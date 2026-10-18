"""AuthoringTextGateway: COUNT then GENERATE on a frozen route, fail-closed acceptance, every attempt recorded."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx
import pytest
from pydantic import BaseModel

from lib.text_backends.ollama import OllamaChatClient
from server.story_authoring.contracts import (
    AttemptKind,
    OutputMode,
    StoryDecoding,
    StoryFailureCode,
    StoryLimits,
    StoryModelSelection,
    StoryScope,
    StoryStepKind,
    StoryStepRequest,
)
from server.story_authoring.generation import AuthoringTextGateway, StoryStepError
from server.story_authoring.script_guard import no_cjk_pattern

MODEL = "ornith-32k:9b"
SCOPE = StoryScope(user_id="u1", project_name="p1", actor_id="u1")
LIMITS = StoryLimits(input_tokens_max=3_000_000, output_tokens_max=600_000, wall_clock_max_seconds=36_000)
SELECTION = StoryModelSelection.create(
    provider_id="custom-1", endpoint="ollama-chat", base_url="http://h:1", model_id=MODEL, has_credential=False
)


@dataclass
class _Sink:
    events: list[tuple] = field(default_factory=list)
    refuse: bool = False

    async def reserve(self, *, scope, step_id, kind, request_digest, reserved_input_tokens, reserved_output_tokens):
        if self.refuse:
            raise StoryStepError(StoryFailureCode.BUDGET_EXHAUSTED, "cap", step_id=step_id)
        attempt = f"a{len(self.events)}"
        self.events.append(("reserve", attempt, kind, reserved_input_tokens, reserved_output_tokens, request_digest))
        return attempt

    async def dispatched(self, attempt_id):
        self.events.append(("dispatched", attempt_id))

    async def completed(self, attempt_id, *, input_tokens, output_tokens, done_reason, duration_ms):
        self.events.append(("completed", attempt_id, input_tokens, output_tokens, done_reason))

    async def failed(self, attempt_id, *, code, detail, input_tokens=None):
        self.events.append(("failed", attempt_id, code, input_tokens))

    async def unknown(self, attempt_id, *, detail):
        self.events.append(("unknown", attempt_id))

    def kinds(self) -> list[str]:
        return [event[0] for event in self.events]


def _reply(content: str, *, prompt_tokens: int = 900, done_reason: str = "stop", done: bool = True, model=MODEL):
    return httpx.Response(
        200,
        json={
            "model": model,
            "message": {"role": "assistant", "content": content},
            "done": done,
            "done_reason": done_reason,
            "prompt_eval_count": prompt_tokens,
            "eval_count": 120,
        },
    )


def _count_reply(prompt_tokens: int = 900, done_reason: str = "length", **kwargs):
    return _reply("{", prompt_tokens=prompt_tokens, done_reason=done_reason, **kwargs)


class _Server:
    def __init__(self, *replies: httpx.Response | Exception) -> None:
        self.replies = list(replies)
        self.bodies: list[dict] = []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.bodies.append(json.loads(request.content))
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        return httpx.MockTransport(handler)


def _gateway(server: _Server, sink: _Sink, **kwargs) -> AuthoringTextGateway:
    client = OllamaChatClient(base_url="http://h:1", transport=server.transport())
    return AuthoringTextGateway(
        selection=kwargs.get("selection", SELECTION), limits=kwargs.get("limits", LIMITS), client=client, sink=sink
    )


def _step(**overrides) -> StoryStepRequest:
    fields = {
        "step_id": "scene_draft[1,1]#0",
        "kind": StoryStepKind.SCENE_DRAFT,
        "context_digest": "sha256:" + "0" * 64,
        "selection": SELECTION,
        "system_prompt": "Bạn là người viết văn tiếng Việt.",
        "prompt": "Viết cảnh 1.",
        "output_mode": OutputMode.PROSE,
        "decoding": StoryDecoding(temperature=0.7, seed=7),
        "max_output_tokens": 3000,
    }
    fields.update(overrides)
    return StoryStepRequest(**fields)


async def _fails(server: _Server, sink: _Sink, code: StoryFailureCode, **step) -> StoryStepError:
    with pytest.raises(StoryStepError) as caught:
        await _gateway(server, sink).generate(scope=SCOPE, request=_step(**step))
    assert caught.value.code is code
    return caught.value


P1 = "Minh mở cửa căn nhà cũ sau mười năm xa cách."
P2 = "“Anh về rồi à?” Lan hỏi, giọng khẽ run."


def _prose(*paragraphs: str) -> str:
    return json.dumps({"paragraphs": list(paragraphs)}, ensure_ascii=False)


async def test_prose_is_counted_then_generated_and_joined_into_paragraphs():
    server = _Server(_count_reply(), _reply(_prose(P1, P2)))
    sink = _Sink()

    output = await _gateway(server, sink).generate(scope=SCOPE, request=_step(min_paragraphs=2, max_paragraphs=4))

    assert output.text == P1 + "\n\n" + P2
    assert (output.input_tokens, output.finish_reason, output.model_id) == (900, "stop", MODEL)
    count_body, generate_body = server.bodies
    assert count_body["options"]["num_predict"] == 1
    assert generate_body["options"]["num_predict"] == 3000
    count_body["options"]["num_predict"] = 3000
    assert count_body == generate_body
    assert generate_body["messages"][0] == {"role": "system", "content": "Bạn là người viết văn tiếng Việt."}
    paragraphs = generate_body["format"]["properties"]["paragraphs"]
    assert (paragraphs["minItems"], paragraphs["maxItems"]) == (2, 4)
    assert paragraphs["items"]["pattern"] == no_cjk_pattern()
    assert generate_body["options"]["seed"] == 7
    assert (generate_body["truncate"], generate_body["shift"], generate_body["think"]) == (False, False, False)
    assert sink.kinds() == ["reserve", "dispatched", "completed", "reserve", "dispatched", "completed"]
    count_reserve, generate_reserve = sink.events[0], sink.events[3]
    assert count_reserve[2:5] == (AttemptKind.COUNT, 32768, 1)
    assert generate_reserve[2:5] == (AttemptKind.GENERATE, 900, 3000)
    assert count_reserve[5] == generate_reserve[5] == output.request_digest
    assert (output.count_attempt_id, output.generate_attempt_id) == ("a0", "a3")


class _Outline(BaseModel):
    title: str
    chapters: list[str]
    mood: str = "u buồn"


async def test_structured_output_constrains_every_string_and_validates():
    payload = json.dumps({"title": "Căn nhà cũ", "chapters": ["Về", "Sổ", "Đi"], "mood": "lặng"}, ensure_ascii=False)
    server = _Server(_count_reply(), _reply(payload))

    output = await _gateway(server, _Sink()).generate(
        scope=SCOPE,
        request=_step(output_mode=OutputMode.STRUCTURED, response_model=_Outline, kind=StoryStepKind.OUTLINE),
    )

    assert json.loads(output.text)["chapters"] == ["Về", "Sổ", "Đi"]
    properties = server.bodies[1]["format"]["properties"]
    assert properties["title"]["pattern"] == no_cjk_pattern()
    assert properties["chapters"]["items"]["pattern"] == no_cjk_pattern()


async def test_input_over_the_authored_limit_stops_after_the_count():
    server = _Server(_count_reply(prompt_tokens=24577))
    sink = _Sink()

    await _fails(server, sink, StoryFailureCode.INPUT_OVER_LIMIT)

    assert len(server.bodies) == 1
    assert sink.kinds() == ["reserve", "dispatched", "completed"]


async def test_input_over_the_server_context_is_refused_with_the_exact_count():
    over = httpx.Response(
        400,
        json={
            "error": json.dumps(
                {"error": {"type": "exceed_context_size_error", "n_prompt_tokens": 40001, "n_ctx": 32768}}
            )
        },
    )
    server = _Server(over)
    sink = _Sink()

    await _fails(server, sink, StoryFailureCode.INPUT_OVER_CONTEXT)

    assert sink.events[-1] == ("failed", "a0", StoryFailureCode.INPUT_OVER_CONTEXT, 40001)
    assert len(server.bodies) == 1


@pytest.mark.parametrize(
    ("generation", "code"),
    [
        (_reply('{"paragraphs": ["Minh mở', done_reason="length"), StoryFailureCode.OUTPUT_TRUNCATED),
        (_reply(_prose(P1), done=False), StoryFailureCode.OUTPUT_INVALID),
        (_reply(_prose(P1), done_reason="unload"), StoryFailureCode.OUTPUT_INVALID),
        (_reply(_prose(P1), prompt_tokens=899), StoryFailureCode.COUNT_MISMATCH),
        (_reply(_prose(P1, "Anh ấy 突然 dừng lại giữa sân.")), StoryFailureCode.CJK_IN_OUTPUT),
        (_reply(_prose("Mưa rơi trên mái ngói cũ。")), StoryFailureCode.CJK_IN_OUTPUT),
        (_reply("Minh mở cửa căn nhà cũ."), StoryFailureCode.OUTPUT_INVALID),
        (_reply('{"paragraphs": ["' + P1 + '"], "note": "y"}'), StoryFailureCode.OUTPUT_INVALID),
        (_reply(_prose(P1, "   ")), StoryFailureCode.OUTPUT_INVALID),
        (_reply(_prose(P1, "Ngắn.")), StoryFailureCode.OUTPUT_INVALID),
        (_reply('{"paragraphs": [5]}'), StoryFailureCode.OUTPUT_INVALID),
        (_reply('{"paragraphs": "' + P1 + '"}'), StoryFailureCode.OUTPUT_INVALID),
    ],
)
async def test_a_generation_is_accepted_only_when_every_condition_holds(generation, code):
    sink = _Sink()

    await _fails(_Server(_count_reply(), generation), sink, code)

    assert sink.events[-1][0:3] == ("failed", "a3", code)


async def test_structured_output_violating_the_model_is_invalid():
    server = _Server(_count_reply(), _reply('{"title": "x", "chapters": "not a list"}'))

    error = await _fails(
        server, _Sink(), StoryFailureCode.OUTPUT_INVALID, output_mode=OutputMode.STRUCTURED, response_model=_Outline
    )

    assert "schema errors" in error.detail


@pytest.mark.parametrize(
    "count",
    [
        _count_reply(done=False),
        _count_reply(done_reason="unload"),
        _count_reply(prompt_tokens=0),
        _count_reply(model="other:1b"),
    ],
)
async def test_an_unusable_count_probe_stops_before_generation(count):
    server = _Server(count)
    sink = _Sink()

    await _fails(server, sink, StoryFailureCode.OUTPUT_INVALID)

    assert len(server.bodies) == 1
    assert sink.events[-1][0] == "failed"


async def test_a_stop_count_probe_is_accepted():
    server = _Server(_count_reply(done_reason="stop"), _reply(_prose(P1)))

    assert (await _gateway(server, _Sink()).generate(scope=SCOPE, request=_step())).text == P1


@pytest.mark.parametrize(("min_paragraphs", "max_paragraphs", "given"), [(2, 3, 1), (1, 2, 3)])
async def test_a_paragraph_count_outside_the_bounds_is_invalid(min_paragraphs, max_paragraphs, given):
    server = _Server(_count_reply(), _reply(_prose(*([P1] * given))))

    error = await _fails(
        server, _Sink(), StoryFailureCode.OUTPUT_INVALID, min_paragraphs=min_paragraphs, max_paragraphs=max_paragraphs
    )

    assert error.detail == f"{given} paragraphs"


@pytest.mark.parametrize(
    ("raised", "code", "recorded"),
    [
        (httpx.ConnectError("refused"), StoryFailureCode.MODEL_UNAVAILABLE, "failed"),
        (httpx.ReadTimeout("slow"), StoryFailureCode.OUTCOME_UNKNOWN, "unknown"),
        (httpx.Response(500, json={"error": "boom"}), StoryFailureCode.PROVIDER_ERROR, "failed"),
    ],
)
async def test_transport_failures_are_typed_recorded_and_never_retried(raised, code, recorded):
    server = _Server(_count_reply(), raised)
    sink = _Sink()

    await _fails(server, sink, code)

    assert len(server.bodies) == 2
    assert sink.events[-1][0] == recorded


async def test_a_refused_reservation_sends_nothing():
    server = _Server()

    await _fails(server, _Sink(refuse=True), StoryFailureCode.BUDGET_EXHAUSTED)

    assert server.bodies == []


async def test_a_step_naming_another_route_is_refused_before_any_request():
    server = _Server()
    other = StoryModelSelection.create(
        provider_id="custom-1",
        endpoint="ollama-chat",
        base_url="http://h:1",
        model_id="ornith:9b",
        has_credential=False,
    )

    await _fails(server, _Sink(), StoryFailureCode.SELECTION_CHANGED, selection=other)

    assert server.bodies == []


async def test_an_output_limit_above_the_authored_limit_is_refused_before_any_request():
    server = _Server()

    await _fails(server, _Sink(), StoryFailureCode.INPUT_OVER_LIMIT, max_output_tokens=5000)

    assert server.bodies == []


def test_only_the_ollama_chat_endpoint_is_qualified():
    openai = StoryModelSelection.create(
        provider_id="custom-1", endpoint="openai-chat", base_url="http://h:1/v1", model_id=MODEL, has_credential=True
    )
    with pytest.raises(StoryStepError) as caught:
        _gateway(_Server(), _Sink(), selection=openai)
    assert caught.value.code is StoryFailureCode.PROVIDER_NOT_QUALIFIED
