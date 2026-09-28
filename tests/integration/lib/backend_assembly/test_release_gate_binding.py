"""Release gate binds to the backend actually built (model and configuration), ADR-0091 amendment."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import update

from lib.backend_assembly import assemble_backend
from lib.backend_assembly.assembler import paid_route_binding
from lib.config.resolver import ConfigResolver
from lib.config.service import ConfigService
from lib.custom_provider import make_provider_id
from lib.db.models.custom_provider import CustomProviderModel
from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from r2.host_hardening.paid_routes import (
    RELEASE_MODE_ENV,
    PaidRouteUnqualifiedError,
    media_route,
    set_qualification_lookup,
)
from r2.host_hardening.route_qualifications import install_runtime_qualification_lookup, record_qualification


def _model(model_id: str, *, default: bool, endpoint: str = "openai-images") -> dict:
    return {
        "model_id": model_id,
        "display_name": model_id,
        "endpoint": endpoint,
        "is_default": default,
        "is_enabled": True,
    }


async def _provider(db_factory) -> str:
    async with db_factory() as session:
        provider = await CustomProviderRepository(session).create_provider(
            display_name="Relay",
            discovery_format="openai",
            base_url="https://relay.example/v1",
            api_key="sk-relay",
            models=[_model("img-a", default=False), _model("img-b", default=True)],
        )
        await session.commit()
        return make_provider_id(provider.id)


async def _qualify(provider_id: str, model_id: str, resolver: ConfigResolver, root: Path) -> None:
    binding = await paid_route_binding(
        provider_id=provider_id, media_type="image", resolver=resolver, model_id=model_id
    )
    now = datetime.now(UTC)
    record_qualification(
        route=media_route(provider_id, "image"),
        model_id=model_id,
        binding=binding,
        evidence={"result": "PASS"},
        expires_at=now + timedelta(days=30),
        cost_record_ref=None,
        recorded_by="operator",
        now=now,
        root=root,
    )


@pytest.fixture
def release_gate(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(RELEASE_MODE_ENV, "PRODUCTION_CANDIDATE")
    install_runtime_qualification_lookup(root=tmp_path)
    yield tmp_path
    set_qualification_lookup(None)


async def test_a_custom_model_fallback_is_gated_on_the_model_actually_built(db_factory, release_gate: Path) -> None:
    """Qualifying img-a does not open the default img-b when img-a is disabled and the loader falls back."""
    provider_id = await _provider(db_factory)
    resolver = ConfigResolver(db_factory)
    await _qualify(provider_id, "img-a", resolver, release_gate)

    backend = await assemble_backend(provider_id=provider_id, media_type="image", model_id="img-a", resolver=resolver)
    assert backend.model == "img-a"

    async with db_factory() as session:
        await session.execute(
            update(CustomProviderModel).where(CustomProviderModel.model_id == "img-a").values(is_enabled=False)
        )
        await session.commit()
    with pytest.raises(PaidRouteUnqualifiedError) as raised:
        await assemble_backend(provider_id=provider_id, media_type="image", model_id="img-a", resolver=resolver)
    assert raised.value.params["model"] == "img-b"


async def test_changing_a_custom_model_endpoint_needs_a_new_canary(db_factory, release_gate: Path) -> None:
    provider_id = await _provider(db_factory)
    resolver = ConfigResolver(db_factory)
    await _qualify(provider_id, "img-a", resolver, release_gate)

    async with db_factory() as session:
        await session.execute(
            update(CustomProviderModel)
            .where(CustomProviderModel.model_id == "img-a")
            .values(endpoint="openai-images-generations")
        )
        await session.commit()
    with pytest.raises(PaidRouteUnqualifiedError):
        await assemble_backend(provider_id=provider_id, media_type="image", model_id="img-a", resolver=resolver)


async def test_tuning_a_built_in_provider_keeps_its_binding(db_factory) -> None:
    """Throughput settings (rpm, workers, request gap) are not part of the binding; the key is."""
    resolver = ConfigResolver(db_factory)
    async with db_factory() as session:
        await ConfigService(session).set_provider_config("ark", "api_key", "ark-secret")
        await session.commit()
    before = await paid_route_binding(provider_id="ark", media_type="image", resolver=resolver)

    async with db_factory() as session:
        await ConfigService(session).set_provider_config("ark", "image_rpm", "30")
        await session.commit()
    assert await paid_route_binding(provider_id="ark", media_type="image", resolver=resolver) == before

    async with db_factory() as session:
        await ConfigService(session).set_provider_config("ark", "api_key", "ark-rotated")
        await session.commit()
    assert await paid_route_binding(provider_id="ark", media_type="image", resolver=resolver) != before
