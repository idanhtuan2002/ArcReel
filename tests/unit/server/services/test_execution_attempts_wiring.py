"""server.services.execution_attempts's adapter-resolver wiring: the
recovery-scan fallback (default_to_unsupported=True) versus the fail-loud
default used everywhere else (submit)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lib.video_backends.execution_adapter import BackendCapabilityUnsupportedError
from r2.contracts.host_hardening import ProviderRouteSnapshot
from server.services.execution_attempts import NoAdapterRegisteredError, build_adapter_resolver

NOW = datetime(2026, 9, 21, tzinfo=UTC)

# A route whose ref is actually registered in the real capability registry --
# the fallback adapter still needs to resolve a real ProviderCapabilityProfile
# for its own .capability_profile attribute.
ROUTE = ProviderRouteSnapshot(
    provider_id="kling",
    provider_account_ref="default",
    provider_model_id="kling-v2-5-turbo",
    backend_model_id="kling-v2-5-turbo",
    endpoint_id="videos.text2video",
    submitted_base_url="https://api-beijing.klingai.com/v1",
    adapter_version="host-video-v1",
    capability_profile_ref="kling-videos-text2video@host-video-v1",
)


def test_default_resolver_raises_loud_for_an_unregistered_route() -> None:
    resolve = build_adapter_resolver({})
    with pytest.raises(NoAdapterRegisteredError):
        resolve(ROUTE)


def test_default_resolver_still_returns_a_real_registered_adapter() -> None:
    sentinel = object()
    resolve = build_adapter_resolver({ROUTE.capability_profile_ref: sentinel})
    assert resolve(ROUTE) is sentinel


async def test_unsupported_fallback_resolver_never_raises_for_an_unregistered_route() -> None:
    resolve = build_adapter_resolver({}, default_to_unsupported=True)
    adapter = resolve(ROUTE)
    assert adapter.capability_profile.ref == ROUTE.capability_profile_ref

    with pytest.raises(BackendCapabilityUnsupportedError):
        await adapter.cancel(None)
    with pytest.raises(BackendCapabilityUnsupportedError):
        await adapter.poll(None)
    assert await adapter.reconcile(None) is None


async def test_unsupported_fallback_resolver_still_prefers_a_real_registered_adapter() -> None:
    sentinel = object()
    resolve = build_adapter_resolver({ROUTE.capability_profile_ref: sentinel}, default_to_unsupported=True)
    assert resolve(ROUTE) is sentinel
