"""A route's protocol comes from its provider's endpoint, never from the model name."""

import pytest

from lib.config.service import ConfigService
from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from server.production_run.vision_chat import ModelAccess, model_access


async def test_each_custom_endpoint_and_builtin_provider_names_its_protocol(db_factory):
    async with db_factory() as session:
        provider = await CustomProviderRepository(session).create_provider(
            display_name="Mixed",
            discovery_format="openai",
            base_url="https://mixed.example.test/v1",
            api_key="fixture-mixed-key",
            models=[
                {"model_id": "gemini-looking-name", "display_name": "a", "endpoint": "openai-chat", "is_enabled": True},
                {"model_id": "local-vlm", "display_name": "b", "endpoint": "ollama-chat", "is_enabled": True},
                {"model_id": "native", "display_name": "c", "endpoint": "gemini-generate", "is_enabled": True},
                {"model_id": "painter", "display_name": "d", "endpoint": "openai-images", "is_enabled": True},
            ],
        )
        await ConfigService(session).set_provider_config("gemini-aistudio", "api_key", "fixture-gemini-key")
        await session.commit()
    access = model_access(db_factory)
    custom = f"custom-{provider.id}"
    assert await access(custom, "gemini-looking-name") == ModelAccess(
        "openai", "https://mixed.example.test/v1", "fixture-mixed-key"
    )
    assert (await access(custom, "local-vlm")).protocol == "ollama"
    assert (await access(custom, "native")).protocol == "gemini"
    gemini = await access("gemini-aistudio", "any-future-gemini")
    assert (gemini.protocol, gemini.api_key) == ("gemini", "fixture-gemini-key")
    assert "fixture" not in repr(gemini)
    for provider_id, model_id in ((custom, "painter"), (custom, "missing"), ("vidu", "x")):
        with pytest.raises(KeyError):
            await access(provider_id, model_id)
