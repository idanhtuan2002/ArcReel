"""A project's automatic production settings (the ``automation`` block of project.json), read and edited from the UI.

The editor chooses an enabled model per role and the run limits; everything a Human release owner put there by
governance (the published quality profile, resource needs, voice) is kept as it is. A route the editor leaves
unchanged keeps its registered model identity; a new Ollama model is pinned to the digest the server reports, a
Gemini model is named by its model id, and any other model by its provider kind. A model whose identity no
qualification covers is then refused by preflight, so an edit can never make an unqualified model run.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from ipaddress import ip_address
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import r2.automation.profiles as launch_profiles
import r2.contracts.quality as q
from lib.custom_provider import parse_provider_id
from lib.db.models.quality import QualityProfileHeadModel
from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from lib.db.repositories.quality import QualityProfileRepository
from lib.project_manager import ProjectManager
from r2.contracts.automation import FALLBACK_ROLES
from server.production_run.composition import DEFAULT_MAX_MODEL_CALLS, MAX_TARGET_EPISODES

Role = Literal["writer", "script", "reviewer_a", "reviewer_b", "image", "video", "audio"]
ROLE_MEDIA: dict[str, str] = {
    "writer": "text",
    "script": "text",
    "reviewer_a": "text",
    "reviewer_b": "text",
    "image": "image",
    "video": "video",
    "audio": "audio",
}
#: The most a paid route may cost per call, in minor units of the run currency.
MAX_COST_PER_CALL = 1000
OLLAMA_ENDPOINT = "ollama-chat"
#: The most fallback routes the settings hold, over all roles.
MAX_FALLBACKS = 8
LIMIT_KEYS = ("currency", "max_cost_minor_units", "max_model_calls", "max_runtime_seconds", "max_target_episodes")


class SettingsRefused(ValueError):
    """An edit the settings cannot take; the code names what is wrong."""


class RouteChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role
    provider_id: Annotated[str, StringConstraints(pattern=r"^custom-[1-9][0-9]*$")]
    model_id: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    max_cost_per_call: Annotated[int, Field(ge=1, le=MAX_COST_PER_CALL)] | None = None


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    launch_profile_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,64}$")]
    routes: list[RouteChoice] = Field(min_length=len(ROLE_MEDIA), max_length=len(ROLE_MEDIA))
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,31}$")] = "USD"
    max_cost_minor_units: Annotated[int, Field(ge=0, le=1_000_000)] = 500
    max_model_calls: Annotated[int, Field(ge=1, le=5000)] = DEFAULT_MAX_MODEL_CALLS
    max_runtime_seconds: Annotated[int, Field(ge=600, le=172_800)] = 64_800
    max_target_episodes: Annotated[int, Field(ge=1, le=MAX_TARGET_EPISODES)] = 1
    #: A published quality profile of the project; its current revision's digest is pinned. ``None`` keeps the
    #: profile the settings already name.
    profile_id: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None
    #: Models a text role falls back to, in order, when its own fails or runs out of quota (ADR-0139).
    fallbacks: list[RouteChoice] = Field(default_factory=list, max_length=MAX_FALLBACKS)


async def published_profiles(session: AsyncSession, *, user_id: str, project_name: str) -> list[dict[str, Any]]:
    """The current revision of every published quality profile; ``automatic`` when every slot is a model slot."""
    heads = (
        (await session.execute(select(QualityProfileHeadModel).filter_by(user_id=user_id, project_name=project_name)))
        .scalars()
        .all()
    )
    profiles = []
    for head in sorted(heads, key=lambda row: row.profile_id):
        if head.current_revision is None:
            continue
        profile = await QualityProfileRepository(session).get_revision(
            user_id=user_id, project_name=project_name, profile_id=head.profile_id, revision=head.current_revision
        )
        if profile is None:
            continue
        slots = [slot for requirement in profile.policy.assessment_requirements for slot in requirement.slots]
        profiles.append(
            {
                "profile_id": profile.profile_id,
                "revision": profile.revision,
                "profile_digest": profile.profile_digest,
                "automatic": bool(slots) and all(slot.assessor_class is q.AssessorClass.MODEL for slot in slots),
            }
        )
    return profiles


def launch_profile_ids() -> list[str]:
    return sorted(path.stem for path in (Path(str(launch_profiles.__file__)).parent / "launch_profiles").glob("*.json"))


def _loopback(base_url: str) -> bool:
    host = urlsplit(base_url).hostname or ""
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _view(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "configured": bool(settings),
        "has_quality_profile": bool(settings.get("profile_id") and settings.get("profile_digest")),
        "profile_id": settings.get("profile_id"),
        "launch_profile_id": settings.get("launch_profile_id", "fiction_narration_vi_v1"),
        "routes": [
            {key: route.get(key) for key in ("role", "provider_id", "model_id", "max_cost_per_call")}
            for route in settings.get("routes") or []
        ],
        "fallbacks": [
            {key: route.get(key) for key in ("role", "provider_id", "model_id", "max_cost_per_call")}
            for route in settings.get("fallbacks") or []
        ],
        **{key: settings[key] for key in LIMIT_KEYS if key in settings},
    }


async def settings_options(
    sessions: async_sessionmaker[AsyncSession], projects: ProjectManager, project_name: str, *, user_id: str
) -> dict[str, Any]:
    """The current settings, the published quality profiles and, per role, the enabled models of its media type."""
    current = projects.load_project(project_name).get("automation") or {}
    async with sessions() as session:
        profiles = await published_profiles(session, user_id=user_id, project_name=project_name)
        repository = CustomProviderRepository(session)
        providers = {provider.id: provider for provider in await repository.list_providers()}
        options: dict[str, list[dict[str, Any]]] = {}
        for role, media in ROLE_MEDIA.items():
            options[role] = [
                {
                    "provider_id": f"custom-{model.provider_id}",
                    "model_id": model.model_id,
                    "label": f"{providers[model.provider_id].display_name} · {model.display_name}",
                    "local": _loopback(providers[model.provider_id].base_url),
                }
                for model in await repository.list_enabled_models_by_media_type(media)
                if model.provider_id in providers
            ]
    return {
        "settings": _view(current),
        "options": options,
        "launch_profiles": launch_profile_ids(),
        "quality_profiles": profiles,
    }


async def ollama_identity(base_url: str, model_id: str) -> str:
    """The model pinned to the digest the Ollama server reports for it."""
    root = base_url.rstrip("/").removesuffix("/v1")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            tags = (await client.get(f"{root}/api/tags")).json()["models"]
    except (httpx.HTTPError, KeyError, ValueError):
        raise SettingsRefused("MODEL_DIGEST_UNAVAILABLE") from None
    digest = next((item.get("digest") for item in tags if item.get("name") == model_id), None)
    if not digest:
        raise SettingsRefused("MODEL_DIGEST_UNAVAILABLE")
    return f"ollama/{model_id}@sha256:{digest}"


async def save_settings(
    sessions: async_sessionmaker[AsyncSession],
    projects: ProjectManager,
    project_name: str,
    update: SettingsUpdate,
    *,
    user_id: str,
    identify_ollama: Callable[[str, str], Awaitable[str]] = ollama_identity,
) -> dict[str, Any]:
    """Write the edited settings; refuses an unknown profile, a missing role, a disabled or mistyped model, and a
    cloud model without a per-call cost ceiling."""
    update = SettingsUpdate.model_validate(update)
    if update.launch_profile_id not in launch_profile_ids():
        raise SettingsRefused("UNSUPPORTED_LAUNCH_PROFILE")
    if sorted(route.role for route in update.routes) != sorted(ROLE_MEDIA):
        raise SettingsRefused("MISSING_MODEL_ROLE")
    current = projects.load_project(project_name).get("automation") or {}
    registered = {
        (route.get("role"), route.get("provider_id"), route.get("model_id")): route.get("model_identity")
        for route in [*(current.get("routes") or []), *(current.get("fallbacks") or [])]
    }
    profile_fields: dict[str, str] = {}
    async with sessions() as session:
        if update.profile_id is not None:
            chosen = next(
                (
                    profile
                    for profile in await published_profiles(session, user_id=user_id, project_name=project_name)
                    if profile["profile_id"] == update.profile_id
                ),
                None,
            )
            if chosen is None:
                raise SettingsRefused("MISSING_PUBLISHED_PROFILE")
            profile_fields = {"profile_id": chosen["profile_id"], "profile_digest": chosen["profile_digest"]}
        repository = CustomProviderRepository(session)

        async def entry(choice: RouteChoice) -> dict[str, Any]:
            provider = await repository.get_provider(parse_provider_id(choice.provider_id))
            model = await repository.get_model_by_ids(parse_provider_id(choice.provider_id), choice.model_id)
            typed = {m.id for m in await repository.list_enabled_models_by_media_type(ROLE_MEDIA[choice.role])}
            if provider is None or model is None or model.id not in typed:
                raise SettingsRefused("PINNED_MODEL_UNAVAILABLE")
            local = _loopback(provider.base_url)
            if not local and choice.max_cost_per_call is None:
                raise SettingsRefused("UNBOUNDED_PAID_ROUTE")
            identity = registered.get((choice.role, choice.provider_id, choice.model_id))
            if identity is None:
                if model.endpoint == OLLAMA_ENDPOINT:
                    identity = await identify_ollama(provider.base_url, choice.model_id)
                elif provider.discovery_format == "google":
                    identity = f"gemini/{choice.model_id}"
                else:
                    identity = f"{provider.discovery_format}/{choice.model_id}"
            return {
                "role": choice.role,
                "provider_id": choice.provider_id,
                "model_id": choice.model_id,
                "model_identity": identity,
                "local": local,
                "paid": not local,
                **({} if local else {"max_cost_per_call": choice.max_cost_per_call}),
            }

        routes = [await entry(choice) for choice in update.routes]
        primary = {(route["role"], route["provider_id"], route["model_id"]) for route in routes}
        fallbacks = []
        for choice in update.fallbacks:
            key = (choice.role, choice.provider_id, choice.model_id)
            if choice.role not in FALLBACK_ROLES:
                raise SettingsRefused("FALLBACK_ROLE_UNSUPPORTED")
            if key in primary or key in {(f["role"], f["provider_id"], f["model_id"]) for f in fallbacks}:
                raise SettingsRefused("FALLBACK_REPEATED")
            fallbacks.append(await entry(choice))
    settings = {
        **current,
        **profile_fields,
        "launch_profile_id": update.launch_profile_id,
        "routes": routes,
        "fallbacks": fallbacks,
        "local_only": all(route["local"] for route in [*routes, *fallbacks]),
        "paid": any(route["paid"] for route in [*routes, *fallbacks]),
        "currency": update.currency,
        "max_cost_minor_units": update.max_cost_minor_units,
        "max_model_calls": update.max_model_calls,
        "max_runtime_seconds": update.max_runtime_seconds,
        "max_target_episodes": update.max_target_episodes,
    }
    projects.update_project(project_name, lambda project: project.update(automation=settings))
    return _view(settings)


__all__ = ["SettingsRefused", "SettingsUpdate", "ollama_identity", "save_settings", "settings_options"]
