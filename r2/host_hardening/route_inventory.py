"""Frozen inventory of Host paid asynchronous video-submit families."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from datetime import datetime

from lib.custom_provider import is_custom_provider
from lib.db.base import utc_now
from r2.contracts.host_hardening import ProviderCapabilityProfile
from r2.host_hardening.provider_capabilities import (
    DEFAULT_REGISTRY_PATH,
    ProviderCapabilityError,
    ReleaseMode,
    load_capability_profile,
    require_enabled_capability,
)

HOST_VIDEO_ADAPTER_VERSION = "host-video-v1"
CUSTOM_PROVIDER_FAMILY = "custom-*"


class SubmitRouteUnboundError(LookupError):
    """A paid asynchronous submit tuple is absent from the frozen inventory."""


@dataclass(frozen=True, order=True)
class SubmitRouteKey:
    provider_id: str
    endpoint_id: str
    adapter_version: str


@dataclass(frozen=True)
class PaidAsyncSubmitFamily:
    key: SubmitRouteKey
    capability_profile_ref: str
    submit_symbol: str


PAID_ASYNC_SUBMIT_FAMILIES = (
    PaidAsyncSubmitFamily(
        SubmitRouteKey("gemini", "generate_videos", HOST_VIDEO_ADAPTER_VERSION),
        "gemini-generate-videos@host-video-v1",
        "lib.video_backends.gemini:GeminiVideoBackend._create_task",
    ),
    PaidAsyncSubmitFamily(
        SubmitRouteKey("dashscope", "video-synthesis", HOST_VIDEO_ADAPTER_VERSION),
        "dashscope-video-synthesis@host-video-v1",
        "lib.video_backends.dashscope:DashScopeVideoBackend._create_task",
    ),
    PaidAsyncSubmitFamily(
        SubmitRouteKey("ark", "content-generation-tasks", HOST_VIDEO_ADAPTER_VERSION),
        "ark-content-generation-tasks@host-video-v1",
        "lib.video_backends.ark:ArkVideoBackend._create_task",
    ),
    PaidAsyncSubmitFamily(
        SubmitRouteKey("agnes", "videos.create", HOST_VIDEO_ADAPTER_VERSION),
        "agnes-videos-create@host-video-v1",
        "lib.video_backends.agnes:AgnesVideoBackend._create_task",
    ),
    PaidAsyncSubmitFamily(
        SubmitRouteKey("vidu", "video-create", HOST_VIDEO_ADAPTER_VERSION),
        "vidu-video-create@host-video-v1",
        "lib.video_backends.vidu:ViduVideoBackend._create_task",
    ),
    PaidAsyncSubmitFamily(
        SubmitRouteKey("kling", "videos.create", HOST_VIDEO_ADAPTER_VERSION),
        "kling-videos-create@host-video-v1",
        "lib.kling_backend_base:KlingBackendBase._submit_task",
    ),
    PaidAsyncSubmitFamily(
        SubmitRouteKey("openai", "videos.create", HOST_VIDEO_ADAPTER_VERSION),
        "openai-videos-create@host-video-v1",
        "lib.video_backends.openai:OpenAIVideoBackend._create_video",
    ),
    PaidAsyncSubmitFamily(
        SubmitRouteKey("grok", "video.generate", HOST_VIDEO_ADAPTER_VERSION),
        "grok-video-generate@host-video-v1",
        "lib.video_backends.grok:GrokVideoBackend._create_video",
    ),
    PaidAsyncSubmitFamily(
        SubmitRouteKey(CUSTOM_PROVIDER_FAMILY, "declarative-video-submit", HOST_VIDEO_ADAPTER_VERSION),
        "custom-*-declarative-video-submit@host-video-v1",
        "lib.custom_provider.declarative_backend:DeclarativeVideoBackend._submit",
    ),
)


def _normalized_provider_id(provider_id: str) -> str:
    return CUSTOM_PROVIDER_FAMILY if is_custom_provider(provider_id) else provider_id


def _family_by_key(key: SubmitRouteKey) -> PaidAsyncSubmitFamily | None:
    return next((family for family in PAID_ASYNC_SUBMIT_FAMILIES if family.key == key), None)


def discovered_submit_families() -> frozenset[SubmitRouteKey]:
    return frozenset(family.key for family in PAID_ASYNC_SUBMIT_FAMILIES)


def registered_submit_families() -> frozenset[SubmitRouteKey]:
    registered: set[SubmitRouteKey] = set()
    for family in PAID_ASYNC_SUBMIT_FAMILIES:
        try:
            profile = load_capability_profile(family.capability_profile_ref)
        except ProviderCapabilityError:
            continue
        if profile.provider_id == family.key.provider_id and profile.adapter_version == family.key.adapter_version:
            registered.add(family.key)
    return frozenset(registered)


def require_submit_route(
    provider_id: str,
    endpoint_id: str,
    adapter_version: str,
    *,
    release_mode: ReleaseMode = ReleaseMode.DEV,
    now: datetime | None = None,
) -> ProviderCapabilityProfile:
    key = SubmitRouteKey(_normalized_provider_id(provider_id), endpoint_id, adapter_version)
    family = _family_by_key(key)
    if family is None:
        raise SubmitRouteUnboundError(f"M7_SUBMIT_ROUTE_UNBOUND:{provider_id}:{endpoint_id}:{adapter_version}")
    return require_enabled_capability(
        family.capability_profile_ref,
        release_mode,
        now=now or utc_now(),
    )


def _resolve_symbol(symbol: str) -> object:
    module_name, qualified_name = symbol.split(":", 1)
    resolved: object = importlib.import_module(module_name)
    for part in qualified_name.split("."):
        resolved = getattr(resolved, part)
    return resolved


def submit_route_inventory_problems() -> list[str]:
    problems: list[str] = []
    registered = registered_submit_families()
    for family in PAID_ASYNC_SUBMIT_FAMILIES:
        try:
            resolved = _resolve_symbol(family.submit_symbol)
        except (AttributeError, ImportError, ValueError):
            resolved = None
        if not callable(resolved) or family.key not in registered:
            problems.append(f"M7_SUBMIT_ROUTE_UNBOUND:{family.submit_symbol}")

    document = json.loads(DEFAULT_REGISTRY_PATH.read_text())
    expected_refs = {family.capability_profile_ref for family in PAID_ASYNC_SUBMIT_FAMILIES}
    actual_refs = {entry["ref"] for entry in document["profiles"]}
    problems.extend(f"M7_SUBMIT_ROUTE_STALE:{ref}" for ref in sorted(actual_refs - expected_refs))
    return problems


__all__ = [
    "CUSTOM_PROVIDER_FAMILY",
    "HOST_VIDEO_ADAPTER_VERSION",
    "PAID_ASYNC_SUBMIT_FAMILIES",
    "PaidAsyncSubmitFamily",
    "SubmitRouteKey",
    "SubmitRouteUnboundError",
    "discovered_submit_families",
    "registered_submit_families",
    "require_submit_route",
    "submit_route_inventory_problems",
]
