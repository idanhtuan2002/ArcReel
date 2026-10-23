"""Custom model facts use read-only model columns, never provider credentials or defaults."""

from copy import deepcopy
from dataclasses import fields

import pytest
from sqlalchemy import event

from lib.catalog import custom_models
from lib.custom_provider import make_endpoint_key
from lib.custom_provider.endpoint_resolution import derive_mirror_columns
from lib.custom_provider.endpoints import ENDPOINT_REGISTRY
from lib.db.models.custom_provider import CustomProvider
from lib.db.repositories.custom_endpoint_repo import CustomEndpointRepository
from lib.db.repositories.custom_provider_repo import CustomProviderRepository


async def seed(factory):
    async with factory() as session:
        repo = CustomProviderRepository(session)
        first = await repo.create_provider(
            "One",
            "openai",
            "https://private-one.invalid",
            "CANARY_PROVIDER_KEY_ONE",
            models=[
                {
                    "model_id": "publisher/same",
                    "display_name": "First",
                    "endpoint": "openai-chat",
                    "is_enabled": False,
                    "is_default": True,
                    "price_unit": "token",
                    "price_input": 0.45,
                    "price_output": 1.25,
                    "currency": "CNY",
                    "supported_durations": "[5, 8]",
                    "resolution": "1024x1536",
                    "capability_overrides": {"max_reference_images": 2},
                },
                {"model_id": "a-unknown", "display_name": "Unknown model", "endpoint": "openai-chat"},
            ],
        )
        second = await repo.create_provider(
            "Two",
            "openai",
            "https://private-two.invalid",
            "CANARY_PROVIDER_KEY_TWO",
            models=[
                {
                    "model_id": "publisher/same",
                    "display_name": "Second",
                    "endpoint": "openai-chat",
                    "is_default": True,
                    "price_unit": "token",
                    "price_input": 0,
                    "price_output": 0,
                    "currency": "USD",
                },
            ],
        )
        ids = (first.provider_id, second.provider_id)
        await session.commit()
        return ids


async def test_custom_models_preserve_routes_prices_disabled_and_unknown_facts(concurrent_session_factory):
    first, second = await seed(concurrent_session_factory)
    async with concurrent_session_factory() as session:
        views = await custom_models(session)
        assert [(v.provider_id, v.model_id) for v in views] == [
            (first, "a-unknown"),
            (first, "publisher/same"),
            (second, "publisher/same"),
        ]
        unknown, one, two = views
        assert one.pricing is not None
        assert two.pricing is not None
        assert (one.enabled, one.default, one.hidden, one.endpoint) == (False, True, False, "openai-chat")
        assert one.api_model_name is None
        assert one.pricing.kind == "custom"
        assert one.pricing.currency == "CNY"
        assert dict(one.pricing.details) == {"price_unit": "token", "price_input": 0.45, "price_output": 1.25}
        assert two.pricing.currency == "USD"
        assert two.pricing.details["price_input"] == two.pricing.details["price_output"] == 0
        assert unknown.pricing is None
        assert one.capabilities is None
        assert unknown.supported_durations is None
        assert one.supported_durations == (5, 8)
        assert one.resolution == "1024x1536"
        assert dict(one.capability_overrides) == {"max_reference_images": 2}
        assert one.source == "custom_model"
        assert one.source_version
        assert await custom_models(session, provider_id=first) == (unknown, one)
        assert await custom_models(session, provider_id="custom-999999") == ()
        exposed = {f.name for f in fields(one)}
        assert not exposed.intersection({"api_key", "base_url", "credential", "binding", "definition"})
        assert "CANARY_PROVIDER_KEY" not in repr(views)
        assert "private-one.invalid" not in repr(views)


async def test_projection_never_autoflushes_pending_work_or_reads_provider_credentials(concurrent_session_factory):
    first, _ = await seed(concurrent_session_factory)
    async with concurrent_session_factory() as session:
        await session.connection()
        pending = CustomProvider(
            display_name="Pending",
            discovery_format="openai",
            base_url="https://pending.invalid",
            api_key="CANARY_PENDING_KEY",
        )
        session.add(pending)
        statements = []

        def capture(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(session.bind.sync_engine, "before_cursor_execute", capture)
        try:
            views = await custom_models(session, provider_id=first)
        finally:
            event.remove(session.bind.sync_engine, "before_cursor_execute", capture)
        assert len(views) == 2
        assert pending.id is None
        assert pending in session.new
        assert statements
        assert all(s.lstrip().upper().startswith("SELECT") for s in statements)
        assert all("api_key" not in s and "base_url" not in s for s in statements)
        assert all("FROM custom_provider " not in s for s in statements)


async def test_custom_endpoint_is_read_without_exporting_its_definition(concurrent_session_factory):
    definition = deepcopy(dict(ENDPOINT_REGISTRY["minimax-hailuo-v1"].definition))
    definition["meta"]["description"] = "CANARY_ENDPOINT_PRIVATE_METADATA"
    columns = derive_mirror_columns(definition)
    async with concurrent_session_factory() as session:
        endpoint = await CustomEndpointRepository(session).create(
            definition=definition,
            kind=columns.kind,
            schema_version=columns.schema_version,
            media_type=columns.media_type,
            display_name=columns.display_name,
        )
        key = make_endpoint_key(endpoint.id)
        provider = await CustomProviderRepository(session).create_provider(
            "Video",
            "openai",
            "https://private.invalid",
            "CANARY_PROVIDER_KEY",
            models=[{"model_id": "unmatched/video", "display_name": "Unknown", "endpoint": key}],
        )
        provider_id = provider.provider_id
        await session.commit()
    async with concurrent_session_factory() as session:
        views = await custom_models(session, provider_id=provider_id)
        assert len(views) == 1
        assert (views[0].model_id, views[0].media_type, views[0].endpoint) == ("unmatched/video", "video", key)
        assert "CANARY_ENDPOINT_PRIVATE_METADATA" not in repr(views)
        assert "CANARY_PROVIDER_KEY" not in repr(views)


async def test_invalid_endpoint_propagates_without_dropping_a_model(concurrent_session_factory):
    async with concurrent_session_factory() as session:
        await CustomProviderRepository(session).create_provider(
            "Broken",
            "openai",
            "https://x.invalid",
            "key",
            models=[{"model_id": "broken", "display_name": "Broken", "endpoint": "ce-999999"}],
        )
        await session.commit()
    async with concurrent_session_factory() as session:
        with pytest.raises(ValueError, match="unknown endpoint"):
            await custom_models(session)


@pytest.mark.parametrize("provider_id", ["gemini-aistudio", "7", "custom-01", "custom-0", "custom-bad"])
async def test_provider_filter_requires_canonical_custom_identity(concurrent_session_factory, provider_id):
    async with concurrent_session_factory() as session:
        with pytest.raises(ValueError, match=r"canonical|invalid literal"):
            await custom_models(session, provider_id=provider_id)


async def test_custom_snapshot_survives_source_edit_and_requery(concurrent_session_factory):
    first, _ = await seed(concurrent_session_factory)
    async with concurrent_session_factory() as session:
        one = (await custom_models(session, provider_id=first))[1]
        assert one.pricing is not None
        with pytest.raises(TypeError):
            one.pricing.details["price_input"] = 99
        with pytest.raises(TypeError):
            one.capability_overrides["max_reference_images"] = 9
        row = await CustomProviderRepository(session).get_model_by_ids(
            int(first.removeprefix("custom-")), "publisher/same"
        )
        assert row is not None
        row.price_input = 8
        await session.flush()
        fresh = (await custom_models(session, provider_id=first))[1]
        assert fresh.pricing is not None
        assert fresh.pricing.details["price_input"] == 8
        assert one.pricing.details["price_input"] == 0.45


@pytest.mark.parametrize("durations", ["{}", "[true]", "[1.5]", "not-json"])
async def test_invalid_duration_declaration_is_reported(concurrent_session_factory, durations):
    async with concurrent_session_factory() as session:
        await CustomProviderRepository(session).create_provider(
            "Bad durations",
            "openai",
            "https://x.invalid",
            "key",
            models=[
                {"model_id": "a", "display_name": "A", "endpoint": "openai-chat", "supported_durations": durations}
            ],
        )
        await session.commit()
    async with concurrent_session_factory() as session:
        with pytest.raises(ValueError, match=r"integer list|Expecting"):
            await custom_models(session)


async def test_partial_price_does_not_acquire_a_zero_input_rate(concurrent_session_factory):
    async with concurrent_session_factory() as session:
        await CustomProviderRepository(session).create_provider(
            "Partial",
            "openai",
            "https://x.invalid",
            "key",
            models=[
                {
                    "model_id": "a",
                    "display_name": "A",
                    "endpoint": "openai-chat",
                    "price_unit": "token",
                    "price_output": 2.5,
                    "currency": "USD",
                }
            ],
        )
        await session.commit()
    async with concurrent_session_factory() as session:
        (view,) = await custom_models(session)
        assert view.pricing is not None
        assert view.pricing.details["price_input"] is None
        assert view.pricing.details["price_output"] == 2.5
