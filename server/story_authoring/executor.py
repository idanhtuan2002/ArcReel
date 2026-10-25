"""The queue executor of a ``story_authoring_run`` task.

The task's payload is the brief that Gate A approved; its resource id is the run id. One execution reconciles the
run after any restart, resolves the frozen model route against the current custom provider, and drives the run
until it is offered for approval or stops in a typed phase. Finality is the run's phase, never the task status, so
a run that waits for approval or stopped blocked returns normally. A brief with a judge route gets a second
gateway, credential and usage sink for review calls; both routes must resolve before any call.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.custom_provider import is_custom_provider, parse_provider_id
from lib.db import async_session_factory
from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from lib.db.repositories.task_repo import StoryRunStateConflict
from lib.project_manager import get_project_manager
from lib.text_backends.ollama import OllamaChatClient
from r2.host_hardening.paid_routes import PaidRouteUnqualifiedError
from server.story_authoring.artifacts import StoryBlobStore
from server.story_authoring.cloud import CloudStoryGateway, GeminiStoryClient
from server.story_authoring.contracts import StoryModelSelection
from server.story_authoring.driver import StoryBrief, StoryRunDriver
from server.story_authoring.generation import AuthoringTextGateway
from server.story_authoring.narrative import StoryIdentity
from server.story_authoring.routes import resolve_cloud_route, validate_cloud_brief
from server.story_authoring.runtime import (
    RunPhase,
    RunStateStore,
    StoryAttemptSink,
    new_run_state,
    recover_run,
    set_phase,
)

type Factory = async_sessionmaker[AsyncSession]
type ClientFactory = Callable[[str, str | None], OllamaChatClient]


class RouteUnavailable(Exception):
    """The frozen route no longer matches a configured, enabled Ollama chat model."""


async def resolve_route_credential(factory: Factory, selection: StoryModelSelection) -> str | None:
    """The provider's credential, after checking that the provider still serves exactly the frozen route."""
    if not is_custom_provider(selection.provider_id):
        try:
            resolved = await resolve_cloud_route(factory, selection.provider_id, selection.model_id)
            if resolved.selection != selection:
                raise RouteUnavailable("cloud route changed")
            return resolved.credential
        except (ValueError, PaidRouteUnqualifiedError):
            raise RouteUnavailable("cloud route is unavailable or changed") from None
    provider_db_id = parse_provider_id(selection.provider_id)
    async with factory() as session:
        repo = CustomProviderRepository(session)
        provider = await repo.get_provider(provider_db_id)
        model = await repo.get_model_by_ids(provider_db_id, selection.model_id) if provider is not None else None
    if provider is None or model is None or not model.is_enabled:
        raise RouteUnavailable(f"{selection.provider_id}/{selection.model_id} is not configured")
    if model.endpoint != selection.endpoint or provider.base_url != selection.base_url:
        raise RouteUnavailable(f"{selection.provider_id}/{selection.model_id} changed its endpoint or base URL")
    if bool(provider.api_key) != selection.has_credential:
        raise RouteUnavailable(f"{selection.provider_id} changed whether it has a credential")
    return provider.api_key or None


def _default_client(base_url: str, api_key: str | None) -> OllamaChatClient:
    return OllamaChatClient(base_url=base_url, api_key=api_key)


async def execute_story_run_task(
    project_name: str,
    resource_id: str,
    payload: dict[str, Any],
    *,
    user_id: str,
    task_id: str | None,
    session_factory: Factory = async_session_factory,
    project_dir: Path | None = None,
    client_for: ClientFactory = _default_client,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    if task_id is None:
        raise ValueError("a story run executes only as a queued task")
    brief = StoryBrief.model_validate(payload["brief"])
    identity = StoryIdentity(user_id=user_id, project_name=project_name, run_id=resource_id)
    store = RunStateStore(session_factory, task_id=task_id)
    try:
        await store.load()
    except StoryRunStateConflict:
        await store.initialize(new_run_state(run_id=resource_id, limits=brief.limits, now=clock()))
    blobs = StoryBlobStore(project_dir or get_project_manager().get_project_path(project_name))
    state, _ = await recover_run(store, session_factory=session_factory, blob_exists=blobs.exists)
    if state.phase is not RunPhase.RUNNING:
        return {"run_id": resource_id, "phase": state.phase.value}
    routes = [brief.selection] if brief.judge_selection is None else [brief.selection, brief.judge_selection]
    try:
        await validate_cloud_brief(session_factory, brief)
        keys = [await resolve_route_credential(session_factory, route) for route in routes]
    except (RouteUnavailable, ValueError, PaidRouteUnqualifiedError) as error:
        reason = str(error)
        state, _ = await store.apply(lambda s: (set_phase(s, RunPhase.MODEL_UNAVAILABLE, reason=reason), None))
        return {"run_id": resource_id, "phase": state.phase.value}

    async def revalidate() -> None:
        await validate_cloud_brief(session_factory, brief)

    gateways = []
    cloud_clients = []
    for route, key in zip(routes, keys, strict=True):
        profile = next(
            (profile for profile in brief.cloud_profiles if profile.selection_digest == route.config_digest), None
        )
        sink = StoryAttemptSink(
            store=store,
            session_factory=session_factory,
            provider_id=route.provider_id,
            model_id=route.model_id,
            clock=clock,
            price_bounds=profile.prices if profile else None,
        )
        if route.endpoint == "ollama-chat":
            gateway = AuthoringTextGateway(
                selection=route, limits=brief.limits, client=client_for(route.base_url, key), sink=sink
            )
        else:
            if not key or profile is None:
                raise RouteUnavailable("cloud brief is missing its approved profile")
            client = GeminiStoryClient(api_key=key, base_url=route.base_url)
            cloud_clients.append(client)
            gateway = CloudStoryGateway(
                selection=route, limits=brief.limits, client=client, sink=sink, revalidate=revalidate
            )
        gateways.append(gateway)
    driver = StoryRunDriver(
        identity=identity,
        brief=brief,
        store=store,
        gateway=gateways[0],
        judge_gateway=gateways[1] if len(gateways) > 1 else None,
        blobs=blobs,
        clock=clock,
    )
    try:
        state = await driver.run()
        return {"run_id": resource_id, "phase": state.phase.value}
    finally:
        for client in cloud_clients:
            await client.close()
