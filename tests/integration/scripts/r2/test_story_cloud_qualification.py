"""The operator canary qualifies only the exact story workload and binding."""

import httpx
import pytest

from lib.config.service import ConfigService
from r2.host_hardening.paid_routes import (
    PaidRoute,
    PaidRouteUnqualifiedError,
    media_route,
    paid_route_inventory,
    require_paid_route,
    set_qualification_lookup,
)
from r2.host_hardening.route_qualifications import install_runtime_qualification_lookup
from scripts.r2.qualify_route import build_parser, run_story_canary
from server.story_authoring.routes import resolve_cloud_route


def test_story_route_is_in_the_operator_inventory():
    assert PaidRoute("story", provider_id="gemini-aistudio") in paid_route_inventory()


async def test_story_canary_opens_only_the_exact_story_model_and_configuration(
    db_factory, monkeypatch, tmp_path, respx_mock
):
    monkeypatch.setenv("ARCREEL_RELEASE_MODE", "PRODUCTION_CANDIDATE")
    async with db_factory() as session:
        await ConfigService(session).set_provider_config("gemini-aistudio", "api_key", "fixture-secret-key")
        await session.commit()
    install_runtime_qualification_lookup(tmp_path)
    count = respx_mock.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:countTokens"
    ).mock(return_value=httpx.Response(200, json={"totalTokens": 25}))
    generation = respx_mock.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": '{"greeting":"Xin chào từ kiểm tra kết nối."}'}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 26, "candidatesTokenCount": 10, "thoughtsTokenCount": 5},
            },
        )
    )
    args = build_parser().parse_args(
        ["--provider", "gemini-aistudio", "--media", "story", "--model", "gemini-2.5-flash"]
    )
    try:
        result = await run_story_canary(args, session_factory=db_factory, root=tmp_path)
        assert result["qualified"] == "story:gemini-aistudio"
        assert count.call_count == generation.call_count == 1
        resolved = await resolve_cloud_route(db_factory, "gemini-aistudio", "gemini-2.5-flash")
        with pytest.raises(PaidRouteUnqualifiedError):
            require_paid_route(
                media_route("gemini-aistudio", "text"), model_id="gemini-2.5-flash", binding=resolved.profile.binding
            )
        with pytest.raises(PaidRouteUnqualifiedError):
            await resolve_cloud_route(db_factory, "gemini-aistudio", "gemini-3.6-flash")
        async with db_factory() as session:
            await ConfigService(session).set_provider_config("gemini-aistudio", "api_key", "rotated-fixture-key")
            await session.commit()
        with pytest.raises(PaidRouteUnqualifiedError):
            await resolve_cloud_route(db_factory, "gemini-aistudio", "gemini-2.5-flash")
        for path in tmp_path.rglob("*.json"):
            assert "fixture-secret-key" not in path.read_text()
    finally:
        set_qualification_lookup(None)


async def test_rejected_canary_keeps_failed_attempt_and_actual_billed_usage(
    db_factory, monkeypatch, tmp_path, respx_mock
):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from lib.db.models.task import Task
    from lib.db.repositories.usage_repo import UsageRepository
    from server.story_authoring.contracts import StoryFailureCode
    from server.story_authoring.generation import StoryStepError
    from server.story_authoring.runtime import AttemptState, RunStateStore

    monkeypatch.setenv("ARCREEL_RELEASE_MODE", "PRODUCTION_CANDIDATE")
    async with db_factory() as session:
        await ConfigService(session).set_provider_config("gemini-aistudio", "api_key", "fixture-secret-key")
        await session.commit()
    respx_mock.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:countTokens").mock(
        return_value=httpx.Response(200, json={"totalTokens": 25})
    )
    respx_mock.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent").mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": '{"greeting":"Incomplete'}]}, "finishReason": "MAX_TOKENS"}
                ],
                "usageMetadata": {"promptTokenCount": 26, "candidatesTokenCount": 10, "thoughtsTokenCount": 5},
            },
        )
    )
    args = build_parser().parse_args(
        ["--provider", "gemini-aistudio", "--media", "story", "--model", "gemini-2.5-flash"]
    )
    with pytest.raises(StoryStepError) as error:
        await run_story_canary(args, session_factory=db_factory, root=tmp_path)
    assert error.value.code is StoryFailureCode.OUTPUT_TRUNCATED
    assert not (tmp_path / ".route_qualifications" / "qualifications.json").exists()
    databases = list(tmp_path.rglob("attempts.db"))
    assert len(databases) == 1
    engine = create_async_engine(f"sqlite+aiosqlite:///{databases[0]}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            task_id = (await session.execute(select(Task.task_id))).scalar_one()
            calls = await UsageRepository(session).get_calls(project_name="story-cloud-canary")
        state = await RunStateStore(factory, task_id=task_id).load()
        failed = state.attempts[-1]
        assert failed.state is AttemptState.FAILED
        assert failed.failure_code is StoryFailureCode.OUTPUT_TRUNCATED
        assert (failed.charged_input_tokens, failed.charged_output_tokens) == (26, 15)
        generated = next(call for call in calls["items"] if call["output_tokens"] == 15)
        assert generated["status"] == "failed"
        assert generated["currency"] == "USD"
        assert generated["cost_amount"] == pytest.approx((26 * 0.3 + 15 * 2.5) / 1_000_000)
    finally:
        await engine.dispose()
