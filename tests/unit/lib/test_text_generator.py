"""Tests for TextGenerator wrapper."""

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.usage_repo import UsageRepository
from lib.ledger import Ledger
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult
from lib.text_generator import TextGenerator


@dataclass
class _Wired:
    """记账写侧注入 Ledger，读侧直连 UsageRepository，共享同一内存库。"""

    ledger: Ledger
    session_factory: async_sessionmaker[AsyncSession]

    async def get_calls(self, **kwargs):
        async with self.session_factory() as session:
            return await UsageRepository(session).get_calls(**kwargs)


@pytest.fixture
async def wired(db_factory):
    return _Wired(ledger=Ledger(session_factory=db_factory), session_factory=db_factory)


def _make_backend(provider="gemini", model="gemini-3-flash-preview"):
    backend = AsyncMock()
    backend.name = provider
    backend.model = model
    backend.generate = AsyncMock(
        return_value=TextGenerationResult(
            text="生成的文本",
            provider=provider,
            model=model,
            input_tokens=100,
            output_tokens=50,
        )
    )
    return backend


class TestTextGenerator:
    async def test_generate_records_usage_on_success(self, wired):
        # backend.name 为裸 "gemini"，记账须取解析层 provider_id（"gemini-aistudio"）。
        backend = _make_backend()
        gen = TextGenerator(backend, wired.ledger, "gemini-aistudio")

        result = await gen.generate(
            TextGenerationRequest(prompt="测试"),
            project_name="demo",
        )

        assert result.text == "生成的文本"
        assert result.input_tokens == 100
        assert result.output_tokens == 50

        calls = await wired.get_calls(project_name="demo")
        assert calls["total"] == 1
        item = calls["items"][0]
        assert item["call_type"] == "text"
        assert item["status"] == "success"
        assert item["input_tokens"] == 100
        assert item["output_tokens"] == 50
        assert item["provider"] == "gemini-aistudio"
        assert item["cost_amount"] == pytest.approx((100 * 0.50 + 50 * 3.00) / 1_000_000)

    async def test_generate_records_usage_on_failure(self, wired):
        backend = _make_backend()
        backend.generate = AsyncMock(side_effect=RuntimeError("API 超时"))
        gen = TextGenerator(backend, wired.ledger, "gemini-aistudio")

        with pytest.raises(RuntimeError, match="API 超时"):
            await gen.generate(
                TextGenerationRequest(prompt="测试"),
                project_name="demo",
            )

        calls = await wired.get_calls(project_name="demo")
        assert calls["total"] == 1
        item = calls["items"][0]
        assert item["status"] == "failed"
        assert item["cost_amount"] == 0.0
        assert "API 超时" in item["error_message"]

    async def test_generate_without_project_name(self, wired):
        backend = _make_backend()
        gen = TextGenerator(backend, wired.ledger, "gemini-aistudio")

        result = await gen.generate(TextGenerationRequest(prompt="工具箱调用"))

        assert result.text == "生成的文本"
        calls = await wired.get_calls()
        assert calls["total"] == 1
        item = calls["items"][0]
        assert item["project_name"] == ""


async def test_generate_calls_the_backend_without_ambient_baggage(wired):
    from opentelemetry import baggage
    from opentelemetry import context as otel_context

    backend = _make_backend()
    seen: list[dict] = []
    result = backend.generate.return_value

    async def _observe(_request):
        seen.append(dict(baggage.get_all()))
        return result

    backend.generate = AsyncMock(side_effect=_observe)
    gen = TextGenerator(backend, wired.ledger, "gemini-aistudio")

    token = otel_context.attach(baggage.set_baggage("user_id", "u1"))
    try:
        await gen.generate(TextGenerationRequest(prompt="测试"), project_name="demo")
        assert baggage.get_all() == {"user_id": "u1"}
    finally:
        otel_context.detach(token)

    assert seen == [{}]


class _QuotaError(Exception):
    status_code = 429


class _BadOutput(Exception):
    status_code = 400


class TestRouteFallback:
    """ADR-0139: a call that fails on its route is made again on the project's next fallback model."""

    async def test_a_quota_failure_moves_to_the_next_fallback_and_stays_there(self, wired, monkeypatch):
        from lib import text_generator
        from lib.text_backends.base import TextTaskType

        primary = _make_backend("openai", "spent")
        primary.generate = AsyncMock(side_effect=_QuotaError("quota"))
        spare = _make_backend("openai", "spare")
        built: list[tuple[str, str]] = []

        async def build(task_type, *, provider_id, model_id):
            built.append((provider_id, model_id))
            if model_id == "broken":
                raise ValueError("model disabled")
            return spare, provider_id

        monkeypatch.setattr(text_generator, "create_text_backend_for_model", build)
        gen = TextGenerator(
            primary,
            wired.ledger,
            "custom-1",
            task_type=TextTaskType.SCRIPT,
            fallbacks=(("custom-2", "broken"), ("custom-3", "spare")),
        )

        result = await gen.generate(TextGenerationRequest(prompt="x"), project_name="demo")
        again = await gen.generate(TextGenerationRequest(prompt="y"), project_name="demo")

        assert (result.model, again.model) == ("spare", "spare")
        assert built == [("custom-2", "broken"), ("custom-3", "spare")]
        assert primary.generate.await_count == 1
        assert gen.model == "spare"

    async def test_an_answer_failure_or_no_fallback_left_is_raised(self, wired, monkeypatch):
        from lib import text_generator
        from lib.text_backends.base import TextTaskType

        backend = _make_backend("openai", "m")
        backend.generate = AsyncMock(side_effect=_BadOutput("schema"))
        build = AsyncMock()
        monkeypatch.setattr(text_generator, "create_text_backend_for_model", build)
        gen = TextGenerator(
            backend, wired.ledger, "custom-1", task_type=TextTaskType.SCRIPT, fallbacks=(("custom-2", "x"),)
        )
        with pytest.raises(_BadOutput):
            await gen.generate(TextGenerationRequest(prompt="x"), project_name="demo")
        build.assert_not_awaited()

        backend.generate = AsyncMock(side_effect=_QuotaError("quota"))
        lone = TextGenerator(backend, wired.ledger, "custom-1", task_type=TextTaskType.SCRIPT)
        with pytest.raises(_QuotaError):
            await lone.generate(TextGenerationRequest(prompt="x"), project_name="demo")


class TestRunPinnedScriptModel:
    """ADR-0139: inside a run's task, script work stays on the run's frozen script model."""

    async def test_a_run_task_uses_the_frozen_script_model_not_the_projects_current_one(self, monkeypatch):
        from lib import text_generator
        from lib.text_backends.base import TextTaskType
        from lib.text_backends.fallback_rules import FallbackRules, run_fallback_rules

        built: list[tuple[str, str]] = []

        async def by_model(task_type, *, provider_id, model_id):
            built.append((provider_id, model_id))
            return _make_backend("openai", model_id), provider_id

        async def by_project(task_type, project_name):
            raise AssertionError("a run task must not read the project's current text model")

        monkeypatch.setattr(text_generator, "create_text_backend_for_model", by_model)
        monkeypatch.setattr(text_generator, "create_text_backend_for_task", by_project)
        monkeypatch.setattr(text_generator, "project_text_fallbacks", lambda name: ())
        with run_fallback_rules(FallbackRules(text_route=("custom-7", "frozen"))):
            gen = await TextGenerator.create(TextTaskType.SCRIPT, "demo")
        assert (gen.model, built) == ("frozen", [("custom-7", "frozen")])


class TestFallbackRules:
    def test_a_runs_rules_pass_over_cloud_unbounded_and_reviewer_models(self):
        from lib.text_backends.fallback_rules import FallbackRules, allowed_fallback, run_fallback_rules

        local = {"local": True, "model_identity": "ollama/a"}
        cloud = {"local": False, "max_cost_per_call": 3, "model_identity": "openai/b"}
        assert allowed_fallback(local)
        assert allowed_fallback(cloud)
        assert not allowed_fallback({**cloud, "max_cost_per_call": None})
        with run_fallback_rules(FallbackRules(local_only=True, excluded_identities=frozenset({"ollama/a"}))):
            assert not allowed_fallback(local)
            assert not allowed_fallback(cloud)
        assert allowed_fallback(local)
