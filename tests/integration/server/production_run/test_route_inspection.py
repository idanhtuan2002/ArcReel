"""Inspect real host configuration without provider calls or model fallback."""

import pytest
import sqlalchemy as sa

from lib.config.resolver import ConfigResolver
from lib.db.models.custom_provider import CustomProvider, CustomProviderModel


@pytest.fixture
async def configured_route(db_session, session_factory):
    from r2.contracts.automation import ModelRoute

    provider = CustomProvider(
        display_name="Local model",
        discovery_format="openai",
        base_url="http://127.0.0.1:11434",
        api_key="must-not-appear-in-report",
    )
    db_session.add(provider)
    await db_session.flush()
    model = CustomProviderModel(
        provider_id=provider.id,
        model_id="reviewer-a",
        display_name="Reviewer A",
        endpoint="ollama-chat",
        is_enabled=True,
        is_default=True,
        price_unit="token",
        price_input=0,
        price_output=0,
        currency="USD",
    )
    db_session.add(model)
    await db_session.flush()
    resolver = ConfigResolver(session_factory, _bound_session=db_session)
    route = ModelRoute(
        role="reviewer_a",
        provider_id=f"custom-{provider.id}",
        model_id=model.model_id,
        model_identity="reviewer-a@weights-v1",
        config_digest="sha256:" + "a" * 64,
        local=True,
        paid=False,
        currency="USD",
        max_cost_per_call=0,
    )
    return resolver, route, provider, model


async def test_real_custom_route_pins_config_without_exposing_secret_or_calling_provider(
    db_session, configured_route, monkeypatch
):
    import httpx

    from server.production_run.configuration import inspect_model_route

    def forbid(*args, **kwargs):
        raise AssertionError("configuration inspection submitted an HTTP request")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbid)
    resolver, route, provider, _ = configured_route
    result = await inspect_model_route(db_session, resolver, route=route, project={})
    assert result.config_digest != route.config_digest
    assert result.local
    assert not result.paid
    assert provider.api_key not in result.model_dump_json()
    assert await inspect_model_route(db_session, resolver, route=result, project={}) == result


async def test_configuration_change_invalidates_pin(db_session, configured_route):
    from server.production_run.configuration import inspect_model_route

    resolver, route, provider, _ = configured_route
    first = await inspect_model_route(db_session, resolver, route=route, project={})
    provider.base_url = "http://127.0.0.1:11435"
    await db_session.flush()
    second = await inspect_model_route(db_session, resolver, route=route, project={})
    assert second.config_digest != first.config_digest


async def test_disabled_selection_cannot_fall_back_to_another_model(db_session, configured_route):
    from server.production_run.configuration import inspect_model_route

    resolver, route, provider, model = configured_route
    model.is_enabled = False
    db_session.add(
        CustomProviderModel(
            provider_id=provider.id,
            model_id="fallback",
            display_name="Fallback",
            endpoint="ollama-chat",
            is_enabled=True,
            is_default=True,
        )
    )
    await db_session.flush()
    with pytest.raises(ValueError, match="PINNED_MODEL_UNAVAILABLE"):
        await inspect_model_route(db_session, resolver, route=route, project={})
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(CustomProviderModel)) == 2
