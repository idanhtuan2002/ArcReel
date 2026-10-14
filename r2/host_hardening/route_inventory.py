"""Frozen inventory of Host paid asynchronous video-submit families."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from datetime import datetime

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
HOST_SPATIAL_ADAPTER_VERSION = "host-spatial-v1"
HOST_FORMAT_ADAPTER_VERSION = "host-format-v1"
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
    # Kling's video API has three distinct URLs by request shape (unlike this
    # inventory's other single-endpoint families) -- see the comment at
    # KlingBackendBase._submit_task's submit_video_attempt call.
    PaidAsyncSubmitFamily(
        SubmitRouteKey("kling", "videos.text2video", HOST_VIDEO_ADAPTER_VERSION),
        "kling-videos-text2video@host-video-v1",
        "lib.kling_backend_base:KlingBackendBase._submit_task",
    ),
    PaidAsyncSubmitFamily(
        SubmitRouteKey("kling", "videos.image2video", HOST_VIDEO_ADAPTER_VERSION),
        "kling-videos-image2video@host-video-v1",
        "lib.kling_backend_base:KlingBackendBase._submit_task",
    ),
    PaidAsyncSubmitFamily(
        SubmitRouteKey("kling", "videos.multi-image2video", HOST_VIDEO_ADAPTER_VERSION),
        "kling-videos-multi-image2video@host-video-v1",
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
    # Built-in MiniMax video runs the declarative runtime under its own provider id.
    PaidAsyncSubmitFamily(
        SubmitRouteKey("minimax", "declarative-video-submit", HOST_VIDEO_ADAPTER_VERSION),
        "minimax-declarative-video-submit@host-video-v1",
        "lib.custom_provider.declarative_backend:DeclarativeVideoBackend._submit",
    ),
    PaidAsyncSubmitFamily(
        SubmitRouteKey(CUSTOM_PROVIDER_FAMILY, "declarative-video-submit", HOST_VIDEO_ADAPTER_VERSION),
        "custom-*-declarative-video-submit@host-video-v1",
        "lib.custom_provider.declarative_backend:DeclarativeVideoBackend._submit",
    ),
)


#: M8-C spatial analysis routes: one synchronous vision call per attempt. Kept apart from the
#: frozen paid video inventory so its recorded release evidence stays unchanged.
SPATIAL_SUBMIT_FAMILIES = (
    PaidAsyncSubmitFamily(
        SubmitRouteKey("gemini", "gemini-generate", HOST_SPATIAL_ADAPTER_VERSION),
        "gemini-generate-spatial@host-spatial-v1",
        "server.services.spatial_execution:text_backend_spatial_vision",
    ),
)

#: Local deterministic FFmpeg projection renders (M8-E): no spend, but the same M7 attempt custody.
FORMAT_RENDER_SUBMIT_FAMILIES = (
    PaidAsyncSubmitFamily(
        SubmitRouteKey("local-ffmpeg", "format-projection", HOST_FORMAT_ADAPTER_VERSION),
        "local-ffmpeg-format-projection@host-format-v1",
        "server.services.format_render:FormatRenderService.render",
    ),
)

_ALL_SUBMIT_FAMILIES = PAID_ASYNC_SUBMIT_FAMILIES + SPATIAL_SUBMIT_FAMILIES + FORMAT_RENDER_SUBMIT_FAMILIES

#: Built-in video provider ids (backend spec registry) -> the provider id their backend submits as.
#: Every built-in ``(provider, "video")`` spec must appear here; a new one fails the inventory test.
BUILTIN_VIDEO_SUBMIT_PROVIDER: dict[str, str] = {
    "agnes": "agnes",
    "ark": "ark",
    "ark-agent-plan": "ark",
    "dashscope": "dashscope",
    "gemini-aistudio": "gemini",
    "gemini-vertex": "gemini",
    "grok": "grok",
    "kling": "kling",
    "minimax": "minimax",
    "openai": "openai",
    "vidu": "vidu",
}


def _normalized_provider_id(provider_id: str) -> str:
    # Deliberately duplicates lib.custom_provider.CUSTOM_PROVIDER_PREFIX's "custom-" literal
    # instead of importing it: lib.video_backends.execution_adapter reaches this module, and
    # lib.video_backends must not depend on lib.custom_provider (import-linter layering).
    return CUSTOM_PROVIDER_FAMILY if provider_id.startswith("custom-") else provider_id


def _family_by_key(key: SubmitRouteKey) -> PaidAsyncSubmitFamily | None:
    return next((family for family in _ALL_SUBMIT_FAMILIES if family.key == key), None)


def discovered_submit_families() -> frozenset[SubmitRouteKey]:
    return frozenset(family.key for family in _ALL_SUBMIT_FAMILIES)


def registered_submit_families() -> frozenset[SubmitRouteKey]:
    registered: set[SubmitRouteKey] = set()
    for family in _ALL_SUBMIT_FAMILIES:
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
    for family in _ALL_SUBMIT_FAMILIES:
        try:
            resolved = _resolve_symbol(family.submit_symbol)
        except (AttributeError, ImportError, ValueError):
            resolved = None
        if not callable(resolved) or family.key not in registered:
            problems.append(f"M7_SUBMIT_ROUTE_UNBOUND:{family.submit_symbol}")

    document = json.loads(DEFAULT_REGISTRY_PATH.read_text())
    expected_refs = {family.capability_profile_ref for family in _ALL_SUBMIT_FAMILIES}
    actual_refs = {entry["ref"] for entry in document["profiles"]}
    problems.extend(f"M7_SUBMIT_ROUTE_STALE:{ref}" for ref in sorted(actual_refs - expected_refs))
    return problems


__all__ = [
    "BUILTIN_VIDEO_SUBMIT_PROVIDER",
    "CUSTOM_PROVIDER_FAMILY",
    "FORMAT_RENDER_SUBMIT_FAMILIES",
    "HOST_FORMAT_ADAPTER_VERSION",
    "HOST_SPATIAL_ADAPTER_VERSION",
    "HOST_VIDEO_ADAPTER_VERSION",
    "PAID_ASYNC_SUBMIT_FAMILIES",
    "SPATIAL_SUBMIT_FAMILIES",
    "PaidAsyncSubmitFamily",
    "SubmitRouteKey",
    "SubmitRouteUnboundError",
    "discovered_submit_families",
    "registered_submit_families",
    "require_submit_route",
    "submit_route_inventory_problems",
]
