"""The spatial vision dependency binds only a Gemini text model, on the registered spatial route."""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib.api_errors import ServiceUnavailableError
from r2.host_hardening.route_inventory import HOST_SPATIAL_ADAPTER_VERSION
from server.routers.spatial import spatial_vision


def _resolver(provider_id: str, model: str, config: dict[str, str]) -> MagicMock:
    mock = MagicMock()
    mock.text_backend_for_task = AsyncMock(return_value=(provider_id, model))
    mock.provider_config = AsyncMock(return_value=config)

    @contextlib.asynccontextmanager
    async def _session():
        yield mock

    mock.session = _session
    return mock


async def test_a_gemini_text_model_binds_the_registered_spatial_route() -> None:
    resolver = _resolver("gemini-aistudio", "gemini-3-flash", {"api_key": "key"})
    with patch("lib.text_backends.factory.ConfigResolver", return_value=resolver):
        vision = await spatial_vision("demo-project")

    assert vision.route.provider_id == "gemini"
    assert vision.route.provider_model_id == "gemini-3-flash"
    assert vision.route.endpoint_id == "gemini-generate"
    assert vision.route.adapter_version == HOST_SPATIAL_ADAPTER_VERSION
    assert vision.route.capability_profile_ref == "gemini-generate-spatial@host-spatial-v1"
    assert vision.route.submitted_base_url == "https://generativelanguage.googleapis.com"


async def test_a_non_gemini_text_model_is_unavailable_before_any_call() -> None:
    resolver = _resolver("ark", "doubao-seed-2-0-lite-260215", {"api_key": "ark-key"})
    with (
        patch("lib.text_backends.factory.ConfigResolver", return_value=resolver),
        pytest.raises(ServiceUnavailableError) as raised,
    ):
        await spatial_vision("demo-project")

    assert raised.value.key == "m8_spatial_unavailable"
