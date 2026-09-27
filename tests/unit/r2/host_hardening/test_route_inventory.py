from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from r2.host_hardening.provider_capabilities import ProviderCapabilityUnqualifiedError, ReleaseMode
from r2.host_hardening.route_inventory import (
    BUILTIN_VIDEO_SUBMIT_PROVIDER,
    HOST_VIDEO_ADAPTER_VERSION,
    SubmitRouteUnboundError,
    discovered_submit_families,
    registered_submit_families,
    require_submit_route,
)

NOW = datetime(2026, 9, 18, tzinfo=UTC)


def test_every_built_in_video_provider_submits_through_an_inventoried_family() -> None:
    """The inventory is checked against the backend spec registry, not against itself.

    A new built-in ``(provider, "video")`` spec fails here until it is mapped to the
    provider id its backend submits as, and that id has a submit family.
    """
    from lib.backend_assembly.specs import PROVIDER_SPEC_REGISTRY

    built_in_video = {provider for provider, media in PROVIDER_SPEC_REGISTRY if media == "video"}
    assert set(BUILTIN_VIDEO_SUBMIT_PROVIDER) == built_in_video
    family_providers = {key.provider_id for key in discovered_submit_families()}
    assert set(BUILTIN_VIDEO_SUBMIT_PROVIDER.values()) <= family_providers
    assert discovered_submit_families() == registered_submit_families()


def test_every_literal_submit_endpoint_in_source_has_a_family() -> None:
    """Every ``submit_video_attempt(..., endpoint_id="...")`` literal in ``lib`` is inventoried."""
    lib_root = Path(__file__).resolve().parents[4] / "lib"
    endpoints: set[str] = set()
    for path in lib_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "submit_video_attempt"):
                continue
            for keyword in node.keywords:
                if keyword.arg == "endpoint_id" and isinstance(keyword.value, ast.Constant):
                    endpoints.add(keyword.value.value)
    assert endpoints, "no submit_video_attempt call sites found"
    assert endpoints <= {key.endpoint_id for key in discovered_submit_families()}


def test_built_in_minimax_video_is_bound() -> None:
    profile = require_submit_route("minimax", "declarative-video-submit", HOST_VIDEO_ADAPTER_VERSION, now=NOW)
    assert profile.provider_id == "minimax"


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
