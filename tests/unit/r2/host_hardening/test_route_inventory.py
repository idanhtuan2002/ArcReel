from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.host_hardening.provider_capabilities import ProviderCapabilityUnqualifiedError, ReleaseMode
from r2.host_hardening.route_inventory import (
    HOST_VIDEO_ADAPTER_VERSION,
    SubmitRouteUnboundError,
    discovered_submit_families,
    registered_submit_families,
    require_submit_route,
)

NOW = datetime(2026, 9, 18, tzinfo=UTC)


def test_every_paid_async_submit_family_is_inventoried() -> None:
    assert len(discovered_submit_families()) == 9
    assert discovered_submit_families() == registered_submit_families()


def test_new_unlisted_submit_route_fails_closed() -> None:
    with pytest.raises(SubmitRouteUnboundError, match="M7_SUBMIT_ROUTE_UNBOUND"):
        require_submit_route("new-provider", "videos.create", HOST_VIDEO_ADAPTER_VERSION, now=NOW)


def test_declarative_custom_provider_ids_share_only_the_declarative_family() -> None:
    profile = require_submit_route(
        "custom-42",
        "declarative-video-submit",
        HOST_VIDEO_ADAPTER_VERSION,
        now=NOW,
    )
    assert profile.provider_id == "custom-*"

    with pytest.raises(SubmitRouteUnboundError, match="M7_SUBMIT_ROUTE_UNBOUND"):
        require_submit_route("custom-42", "videos.create", HOST_VIDEO_ADAPTER_VERSION, now=NOW)


def test_unqualified_inventory_entry_is_not_a_production_candidate() -> None:
    with pytest.raises(ProviderCapabilityUnqualifiedError, match="UNQUALIFIED"):
        require_submit_route(
            "openai",
            "videos.create",
            HOST_VIDEO_ADAPTER_VERSION,
            release_mode=ReleaseMode.PRODUCTION_CANDIDATE,
            now=NOW,
        )
