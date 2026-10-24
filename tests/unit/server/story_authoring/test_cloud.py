"""Cloud story requests retain physical-call custody and local compatibility."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from server.story_authoring.cloud import CloudStoryGateway, GeminiStoryClient
from server.story_authoring.contracts import AttemptKind, CloudPriceBounds, StoryLimits, StoryModelSelection
from server.story_authoring.generation import StoryStepError
from server.story_authoring.runtime import BudgetExhausted, new_run_state, reserve
from tests.unit.server.story_authoring.test_generation import LIMITS, SCOPE, _Sink, _step

MODEL = "gemini-2.5-flash"
SELECTION = StoryModelSelection.create(
    provider_id="gemini-aistudio",
    model_id=MODEL,
    endpoint="gemini-generate",
    base_url="https://generativelanguage.googleapis.com",
    has_credential=True,
)


def _limits(cap=500):
    return LIMITS.model_copy(
        update={
            "currency": "USD",
            "max_cost_minor_units": cap,
            "cloud_prices": CloudPriceBounds(input_per_million=Decimal("0.30"), output_per_million=Decimal("2.50")),
        }
    )


def _reply(*, finish="STOP", usage=True, content=None):
    data = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": content
                            or json.dumps({"paragraphs": ["A sufficiently long paragraph about a quiet village."]})
                        }
                    ]
                },
                "finishReason": finish,
            }
        ]
    }
    if usage:
        data["usageMetadata"] = {"promptTokenCount": 102, "candidatesTokenCount": 20, "thoughtsTokenCount": 5}
    return httpx.Response(200, json=data)


async def _guard():
    pass


def _gateway(sink):
    return CloudStoryGateway(
        selection=SELECTION,
        limits=_limits(),
        sink=sink,
        client=GeminiStoryClient(api_key="fixture-canary-key", base_url=SELECTION.base_url),
        revalidate=_guard,
    )


async def test_sdk_count_and_generate_are_single_calls_and_thoughts_are_charged(respx_mock):
    count = respx_mock.post(f"{SELECTION.base_url}/v1beta/models/{MODEL}:countTokens").mock(
        return_value=httpx.Response(200, json={"totalTokens": 100})
    )
    generate = respx_mock.post(f"{SELECTION.base_url}/v1beta/models/{MODEL}:generateContent").mock(
        return_value=_reply()
    )
    sink = _Sink()
    result = await _gateway(sink).generate(scope=SCOPE, request=_step().model_copy(update={"selection": SELECTION}))
    assert count.call_count == generate.call_count == 1
    assert result.input_tokens == 102
    assert result.output_tokens == 25
    assert "quiet village" in result.text
    payload = json.loads(generate.calls[0].request.content)
    assert payload["generationConfig"]["maxOutputTokens"] == _step().max_output_tokens
    assert payload["systemInstruction"]
    count_payload = json.loads(count.calls[0].request.content)["generateContentRequest"]
    assert count_payload["contents"] == payload["contents"]
    assert count_payload["systemInstruction"]["parts"] == payload["systemInstruction"]["parts"]
    assert count_payload["generationConfig"] == payload["generationConfig"]
    assert "fixture-canary-key" not in str(sink.events)
    assert [e[2] for e in sink.events if e[0] == "reserve"] == [AttemptKind.COUNT, AttemptKind.GENERATE]
    assert [e for e in sink.events if e[0] == "completed"][-1][3] == 25


@pytest.mark.parametrize(
    ("finish", "usage", "content"),
    [
        ("MAX_TOKENS", True, None),
        ("STOP", False, None),
        ("STOP", True, '{"paragraphs":["中文中文中文中文中文中文中文中文中文中文中文中文"]}'),
    ],
)
async def test_invalid_output_is_never_accepted(respx_mock, finish, usage, content):
    respx_mock.post(f"{SELECTION.base_url}/v1beta/models/{MODEL}:countTokens").mock(
        return_value=httpx.Response(200, json={"totalTokens": 100})
    )
    respx_mock.post(f"{SELECTION.base_url}/v1beta/models/{MODEL}:generateContent").mock(
        return_value=_reply(finish=finish, usage=usage, content=content)
    )
    with pytest.raises(StoryStepError):
        await _gateway(_Sink()).generate(scope=SCOPE, request=_step().model_copy(update={"selection": SELECTION}))


async def test_sdk_never_retries_an_ambiguous_failure_or_prints_provider_secret(respx_mock):
    call = respx_mock.post(f"{SELECTION.base_url}/v1beta/models/{MODEL}:countTokens").mock(
        return_value=httpx.Response(503, json={"error": {"code": 503, "message": "fixture-canary-key"}})
    )
    sink = _Sink()
    with pytest.raises(StoryStepError) as error:
        await _gateway(sink).generate(scope=SCOPE, request=_step().model_copy(update={"selection": SELECTION}))
    assert call.call_count == 1
    assert "fixture-canary-key" not in str(error.value) + str(sink.events)
    assert sink.events[-1][0] == "unknown"


def test_cloud_money_reservation_is_conservative_and_atomic():
    state = new_run_state(run_id="money", limits=_limits(cap=20), now=datetime.now(UTC))
    with pytest.raises(BudgetExhausted):
        reserve(
            state,
            attempt_id="a",
            step_id="s",
            kind=AttemptKind.GENERATE,
            request_digest="d",
            reserved_input_tokens=1_000_000,
            reserved_output_tokens=0,
            now=datetime.now(UTC),
        )
    assert state.attempts == ()


def test_old_local_limits_do_not_gain_serialized_fields():
    assert "cloud_prices" not in LIMITS.model_dump()
    assert StoryLimits.model_validate(LIMITS.model_dump()).model_dump() == LIMITS.model_dump()


def test_usage_over_the_cloud_reservation_is_recorded_without_clamping_and_stops_spending():
    from server.story_authoring.runtime import RunPhase, complete, mark_dispatched

    now = datetime.now(UTC)
    state = new_run_state(run_id="over-report", limits=_limits(), now=now)
    state = reserve(
        state,
        attempt_id="a",
        step_id="s",
        kind=AttemptKind.GENERATE,
        request_digest="d",
        reserved_input_tokens=10,
        reserved_output_tokens=10,
        now=now,
    )
    state = mark_dispatched(state, attempt_id="a", ledger_call_id=None)
    state = complete(state, attempt_id="a", input_tokens=11, output_tokens=12, done_reason="STOP", duration_ms=1)
    assert state.phase is RunPhase.BLOCKED_BUDGET
    assert state.usage.input_tokens == 11
    assert state.usage.output_tokens == 12
