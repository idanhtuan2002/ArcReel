"""Cloud story choices freeze current configuration and prices before Gate A."""

import json
from decimal import Decimal

import pytest

from lib.config.service import ConfigService
from r2.host_hardening.paid_routes import PaidRouteUnqualifiedError, set_qualification_lookup
from server.story_authoring.contracts import CloudPriceBounds
from server.story_authoring.driver import StoryBrief
from server.story_authoring.routes import resolve_cloud_route, story_routes, validate_cloud_brief
from server.story_authoring.service import StoryAuthoringService


async def _configure(factory, key="fixture-key"):
    async with factory() as session:
        await ConfigService(session).set_provider_config("gemini-aistudio", "api_key", key)
        await session.commit()


async def test_choices_report_missing_credentials_then_enable_exact_configured_route(db_factory, monkeypatch):
    monkeypatch.setenv("ARCREEL_RELEASE_MODE", "DEV")
    rows = await story_routes(db_factory)
    row = next(row for row in rows if row["model_id"] == "gemini-2.5-flash")
    assert not row["enabled"]
    assert row["reason"] == "MISSING_CREDENTIAL"
    await _configure(db_factory)
    rows = await story_routes(db_factory)
    row = next(row for row in rows if row["model_id"] == "gemini-2.5-flash")
    assert row["enabled"]
    assert row["cloud"]
    assert "fixture-key" not in json.dumps(rows)


async def test_cloud_brief_freezes_cap_profile_and_detects_key_rotation(db_factory, monkeypatch, tmp_path):
    monkeypatch.setenv("ARCREEL_RELEASE_MODE", "DEV")
    await _configure(db_factory)
    service = StoryAuthoringService(session_factory=db_factory, authority=object(), project_dir_for=lambda _: tmp_path)
    brief = await service.draft_brief(
        idea="A village story",
        genre="drama",
        provider_id="gemini-aistudio",
        model_id="gemini-2.5-flash",
        max_cost_minor_units=50,
    )
    assert brief.limits.currency == "USD"
    assert brief.limits.max_cost_minor_units == 50
    assert brief.cloud_profiles[0].adapter_version == "gemini-story-v1"
    assert brief.limits.cloud_prices == CloudPriceBounds(
        input_per_million=Decimal("0.30"), output_per_million=Decimal("2.50")
    )
    frozen = brief.model_dump(mode="json")
    assert "fixture-key" not in json.dumps(frozen)
    assert StoryBrief.model_validate(frozen).digest() == brief.digest()
    await validate_cloud_brief(db_factory, brief)
    await _configure(db_factory, "rotated-fixture-key")
    with pytest.raises(ValueError, match="changed"):
        await validate_cloud_brief(db_factory, brief)


async def test_generic_text_qualification_never_opens_story_route(db_factory, monkeypatch):
    monkeypatch.setenv("ARCREEL_RELEASE_MODE", "PRODUCTION_CANDIDATE")
    await _configure(db_factory)
    set_qualification_lookup(lambda route, model, binding: route.ref == "media:gemini-aistudio:text")
    try:
        with pytest.raises(PaidRouteUnqualifiedError):
            await resolve_cloud_route(db_factory, "gemini-aistudio", "gemini-2.5-flash")
    finally:
        set_qualification_lookup(None)


async def test_real_story_executor_uses_cloud_gateway_and_records_usd_usage(
    concurrent_session_factory, monkeypatch, tmp_path, respx_mock
):
    import httpx
    from google.genai import types

    from lib.db.repositories.task_repo import STORY_RUN_TASK_TYPE, TaskRepository
    from lib.db.repositories.usage_repo import UsageRepository
    from server.story_authoring.executor import execute_story_run_task
    from tests.integration.server.story_authoring.test_driver import ScriptedModel
    from tests.integration.server.story_authoring.test_narrative import IDENTITY, NOW

    monkeypatch.setenv("ARCREEL_RELEASE_MODE", "DEV")
    await _configure(concurrent_session_factory)
    service = StoryAuthoringService(
        session_factory=concurrent_session_factory, authority=object(), project_dir_for=lambda _: tmp_path
    )
    brief = await service.draft_brief(
        idea="A village story",
        genre="drama",
        provider_id="gemini-aistudio",
        model_id="gemini-2.5-flash",
        max_cost_minor_units=500,
    )
    brief = brief.model_copy(update={"gate_a_decision_id": "fixture-approved"})
    model = ScriptedModel()

    async def generate(request):
        body = json.loads(request.content)
        schema = types.Schema.model_validate(body["generationConfig"]["responseSchema"]).model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        fixture_request = httpx.Request(
            "POST",
            "http://fixture.invalid/chat",
            json={
                "format": schema,
                "options": {"num_predict": 4096},
                "messages": [
                    {"role": "system", "content": body["systemInstruction"]["parts"][0]["text"]},
                    {"role": "user", "content": body["contents"][0]["parts"][0]["text"]},
                ],
            },
        )
        result = (await model.handler(fixture_request)).json()
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": result["message"]["content"]}]}, "finishReason": "STOP"}
                ],
                "usageMetadata": {"promptTokenCount": 700, "candidatesTokenCount": 80, "thoughtsTokenCount": 5},
            },
        )

    count = respx_mock.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:countTokens"
    ).mock(return_value=httpx.Response(200, json={"totalTokens": 700}))
    generation = respx_mock.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    ).mock(side_effect=generate)
    async with concurrent_session_factory() as session:
        task = await TaskRepository(session).enqueue(
            project_name=IDENTITY.project_name,
            task_type=STORY_RUN_TASK_TYPE,
            media_type="text",
            resource_id=IDENTITY.run_id,
            payload={"brief": brief.model_dump(mode="json")},
            user_id=IDENTITY.user_id,
        )
    result = await execute_story_run_task(
        IDENTITY.project_name,
        IDENTITY.run_id,
        {"brief": brief.model_dump(mode="json")},
        user_id=IDENTITY.user_id,
        task_id=task["task_id"],
        session_factory=concurrent_session_factory,
        project_dir=tmp_path,
        clock=lambda: NOW,
    )
    assert result["phase"] == "READY_FOR_APPROVAL", result
    assert count.call_count == generation.call_count
    assert generation.call_count > 20
    async with concurrent_session_factory() as session:
        calls = await UsageRepository(session).get_calls(project_name=IDENTITY.project_name, page_size=1000)
    assert calls["total"] == count.call_count + generation.call_count
    generated = [call for call in calls["items"] if call["output_tokens"] == 85]
    assert len(generated) == generation.call_count
    assert all(
        call["provider"] == "gemini-aistudio" and call["currency"] == "USD" and call["cost_amount"] > 0
        for call in generated
    )


async def test_concurrent_reservations_cannot_overrun_the_cloud_usd_cap(concurrent_session_factory):
    import asyncio

    from server.story_authoring.contracts import StoryLimits
    from server.story_authoring.generation import StoryStepError
    from server.story_authoring.runtime import RunStateStore, StoryAttemptSink
    from tests.integration.server.story_authoring.test_driver import _store
    from tests.unit.server.story_authoring.test_generation import SCOPE

    limits = StoryLimits(
        input_tokens_max=10_000_000,
        output_tokens_max=10_000_000,
        wall_clock_max_seconds=3600,
        currency="USD",
        max_cost_minor_units=1,
        cloud_prices=CloudPriceBounds(input_per_million=10, output_per_million=10),
    )
    store = await _store(concurrent_session_factory, limits=limits)
    sinks = [
        StoryAttemptSink(
            store=RunStateStore(concurrent_session_factory, task_id=store.task_id),
            session_factory=concurrent_session_factory,
            provider_id="gemini-aistudio",
            model_id="gemini-2.5-flash",
        )
        for _ in range(8)
    ]
    from server.story_authoring.contracts import AttemptKind

    outcomes = await asyncio.gather(
        *(
            sink.reserve(
                scope=SCOPE,
                step_id=f"s{i}",
                kind=AttemptKind.GENERATE,
                request_digest="d",
                reserved_input_tokens=500,
                reserved_output_tokens=500,
            )
            for i, sink in enumerate(sinks)
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(outcome, str) for outcome in outcomes) == 1
    assert all(isinstance(outcome, (str, StoryStepError)) for outcome in outcomes)
    state = await store.load()
    assert len(state.attempts) == 1
    assert state.usage.input_tokens == 500


@pytest.mark.parametrize(
    "base_url",
    [
        "http://provider.invalid",
        "https://user:secret@provider.invalid",
        "https://provider.invalid?key=secret",
        "https://provider.invalid#secret",
    ],
)
async def test_cloud_route_never_freezes_credentials_from_a_base_url(db_factory, monkeypatch, base_url):
    monkeypatch.setenv("ARCREEL_RELEASE_MODE", "DEV")
    await _configure(db_factory)
    async with db_factory() as session:
        await ConfigService(session).set_provider_config("gemini-aistudio", "base_url", base_url)
        await session.commit()
    with pytest.raises(ValueError, match="URL"):
        await resolve_cloud_route(db_factory, "gemini-aistudio", "gemini-2.5-flash")


def test_local_brief_retains_the_shipped_v2_approval_digest():
    from tests.integration.server.story_authoring.test_driver import BRIEF

    assert BRIEF.digest() == "sha256:2af86f738aca946a61e3e24ef8ba357cdb8942354bf5bc1ad935dca930e86174"
    assert "cloud_profiles" not in BRIEF.model_dump(mode="json")
    assert "cloud_prices" not in BRIEF.model_dump(mode="json")["limits"]
