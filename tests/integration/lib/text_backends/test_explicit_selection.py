"""Explicit model choice uses real assembly, config and ledger seams."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lib.config.registry import PROVIDER_REGISTRY
from lib.config.service import ConfigService
from lib.custom_provider import make_provider_id
from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from lib.db.repositories.usage_repo import UsageRepository
from lib.ledger import Ledger
from lib.text_backends import registry as text_registry
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult, TextTaskType
from lib.text_backends.factory import create_text_backend_for_model
from lib.text_generator import TextGenerator
from r2.host_hardening.paid_routes import PaidRouteUnqualifiedError, set_qualification_lookup
from tests.fakes import captured_openai_clients


def _model(provider):
    return next(
        m for m, info in PROVIDER_REGISTRY[provider].models.items() if info.media_type == "text" and not info.hidden
    )


def _wire(monkeypatch, db_factory, registry_backend):
    built = []

    def construct(**kwargs):
        backend = SimpleNamespace(
            model=kwargs["model"],
            name=registry_backend,
            generate=AsyncMock(
                return_value=TextGenerationResult(
                    text="selected model response",
                    provider=registry_backend,
                    model=kwargs["model"],
                    input_tokens=10,
                    output_tokens=5,
                )
            ),
        )
        built.append((kwargs, backend))
        return backend

    monkeypatch.setitem(text_registry._BACKEND_FACTORIES, registry_backend, construct)
    monkeypatch.setattr("lib.text_backends.factory.async_session_factory", db_factory)
    monkeypatch.setattr("lib.text_generator.Ledger", lambda: Ledger(session_factory=db_factory))
    monkeypatch.setenv("ARCREEL_RELEASE_MODE", "DEV")
    return built


async def _configure(factory, provider):
    async with factory() as session:
        await ConfigService(session).set_provider_config(provider, "api_key", "fixture-not-a-real-key")
        await session.commit()


@pytest.mark.parametrize(
    ("provider", "registry_backend"), [("gemini-aistudio", "gemini"), ("grok", "grok"), ("openai", "openai")]
)
async def test_selected_model_generates_and_records_exact_provider_model(
    db_factory, monkeypatch, provider, registry_backend
):
    built = _wire(monkeypatch, db_factory, registry_backend)
    await _configure(db_factory, provider)
    model = _model(provider)
    generator = await TextGenerator.create(TextTaskType.SCRIPT, provider_id=provider, model_id=model)
    assert generator.model == model
    assert built[0][0]["model"] == model
    result = await generator.generate(
        TextGenerationRequest(prompt="fixture prompt", max_output_tokens=32), project_name="selected-model"
    )
    assert result.text == "selected model response"
    built[0][1].generate.assert_awaited_once()
    async with db_factory() as session:
        calls = await UsageRepository(session).get_calls(project_name="selected-model")
    assert calls["total"] == 1
    assert calls["items"][0]["provider"] == provider
    assert calls["items"][0]["model"] == model


async def test_explicit_selection_does_not_bypass_release_qualification(db_factory, monkeypatch):
    built = _wire(monkeypatch, db_factory, "gemini")
    await _configure(db_factory, "gemini-aistudio")
    monkeypatch.setenv("ARCREEL_RELEASE_MODE", "PRODUCTION_CANDIDATE")
    set_qualification_lookup(None)
    with pytest.raises(PaidRouteUnqualifiedError):
        await create_text_backend_for_model(
            TextTaskType.SCRIPT, provider_id="gemini-aistudio", model_id=_model("gemini-aistudio")
        )
    built[0][1].generate.assert_not_awaited()


async def test_invalid_custom_model_never_returns_the_default_fallback(db_factory, monkeypatch):
    monkeypatch.setattr("lib.text_backends.factory.async_session_factory", db_factory)
    monkeypatch.setenv("ARCREEL_RELEASE_MODE", "DEV")
    async with db_factory() as session:
        provider = await CustomProviderRepository(session).create_provider(
            display_name="Fixture relay",
            discovery_format="openai",
            base_url="https://fixture.invalid/v1",
            api_key="fixture-key",
            models=[
                {
                    "model_id": "wanted",
                    "display_name": "wanted",
                    "endpoint": "openai-chat",
                    "is_enabled": False,
                    "is_default": False,
                },
                {
                    "model_id": "default",
                    "display_name": "default",
                    "endpoint": "openai-chat",
                    "is_enabled": True,
                    "is_default": True,
                },
            ],
        )
        await session.commit()
        provider_id = make_provider_id(provider.id)
    with captured_openai_clients(), pytest.raises(ValueError, match="fallback"):
        await create_text_backend_for_model(TextTaskType.SCRIPT, provider_id=provider_id, model_id="wanted")


@pytest.mark.parametrize(
    ("provider", "model"),
    [("unknown", "x"), ("gemini-aistudio", "unknown"), ("custom-01", "x"), ("grok", ""), ("", "x")],
)
async def test_invalid_explicit_route_is_rejected_before_assembly(provider, model, monkeypatch):
    assemble = AsyncMock()
    monkeypatch.setattr("lib.text_backends.factory.assemble_backend", assemble)
    with pytest.raises(ValueError, match=r"model|provider|identity"):
        await create_text_backend_for_model(TextTaskType.SCRIPT, provider_id=provider, model_id=model)
    assemble.assert_not_awaited()


async def test_vision_task_rejects_a_known_text_only_model_before_assembly(monkeypatch):
    assemble = AsyncMock()
    monkeypatch.setattr("lib.text_backends.factory.assemble_backend", assemble)
    with pytest.raises(ValueError, match="vision"):
        await create_text_backend_for_model(
            TextTaskType.STYLE_ANALYSIS, provider_id="gemini-aistudio", model_id="gemma-4-31b-it"
        )
    assemble.assert_not_awaited()


@pytest.mark.parametrize("pair", [{"provider_id": "grok"}, {"model_id": "some-model"}])
async def test_incomplete_pair_does_not_fall_back_to_configured_default(pair):
    with pytest.raises(ValueError, match="together"):
        await TextGenerator.create(TextTaskType.SCRIPT, **pair)


async def test_omitting_pair_keeps_the_existing_task_and_project_resolution(db_factory, monkeypatch):
    built = _wire(monkeypatch, db_factory, "gemini")
    await _configure(db_factory, "gemini-aistudio")
    model = _model("gemini-aistudio")
    resolve = AsyncMock(return_value=("gemini-aistudio", model))
    monkeypatch.setattr("lib.config.resolver.ConfigResolver.text_backend_for_task", resolve)
    generator = await TextGenerator.create(TextTaskType.OVERVIEW, "existing-project")
    resolve.assert_awaited_once_with(TextTaskType.OVERVIEW, "existing-project")
    assert generator.model == model
    assert built[0][0]["model"] == model


async def test_unknown_task_is_rejected_before_assembly(monkeypatch):
    assemble = AsyncMock()
    monkeypatch.setattr("lib.text_backends.factory.assemble_backend", assemble)
    with pytest.raises(ValueError, match="task"):
        await create_text_backend_for_model("unregistered-task", provider_id="grok", model_id=_model("grok"))
    assemble.assert_not_awaited()


async def test_image_model_is_rejected_before_assembly(monkeypatch):
    assemble = AsyncMock()
    monkeypatch.setattr("lib.text_backends.factory.assemble_backend", assemble)
    model = next(m for m, info in PROVIDER_REGISTRY["gemini-aistudio"].models.items() if info.media_type == "image")
    with pytest.raises(ValueError, match="text model"):
        await create_text_backend_for_model(TextTaskType.SCRIPT, provider_id="gemini-aistudio", model_id=model)
    assemble.assert_not_awaited()
