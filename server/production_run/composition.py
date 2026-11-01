"""Host composition of automatic production: policy, preflight, adapters, controller, scheduler and service.

Nothing here activates production. ``compose_production`` builds the parts; the app wires them only when
``ARCREEL_AUTOMATIC_PRODUCTION=1`` is set at the release gate, and even then every Start passes the read-only
preflight, which refuses until the launch profile, its published Quality profile and both reviewer routes are
qualified. A project opts in through its ``automation`` settings (profile and model roles); without them no policy
resolves.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.config.resolver import ConfigResolver
from lib.db.repositories.reviewer_qualifications import ReviewerQualificationRepository
from lib.project_manager import ProjectManager
from r2.automation.profiles import resolve_launch_profile, route_digest
from r2.contracts.automation import (
    AutomationMode,
    ModelRoute,
    PreflightSnapshot,
    RunPolicy,
    RunStage,
)
from r2.contracts.quality import QualityProfileRevision
from server.production_run.assets_adapter import AssetsAdapter
from server.production_run.configuration import inspect_model_route
from server.production_run.controller import ProductionController
from server.production_run.evaluators import QualifiedEvaluator
from server.production_run.final_master_adapter import FinalMasterAdapter
from server.production_run.inputs import ProjectInputWitness
from server.production_run.media_adapter import MediaAdapter
from server.production_run.packaging_adapter import ExportAdapter, PackagingAdapter
from server.production_run.ports import OwnerAdapter
from server.production_run.preflight import ProductionPreflight
from server.production_run.quality_adapter import QualityAdapter
from server.production_run.render_adapter import RenderAdapter
from server.production_run.scheduler import ProductionScheduler
from server.production_run.service import ProductionActivation, ProductionRunRefused, ProductionRunService
from server.production_run.story_adapter import BriefAdapter, HandoffAdapter, StoryAdapter, StoryCommitAdapter
from server.production_run.text_adapter import EpisodePlanAdapter, ScriptAdapter, ScriptPlanAdapter
from server.services.automation_grants import AutomationGrantCustodian, RunAutomationAuthority
from server.story_authoring.handoff import SourceUpload
from server.story_authoring.service import StoryAuthoringService

type Sessions = async_sessionmaker[AsyncSession]
ACTIVATION_ENV = "ARCREEL_AUTOMATIC_PRODUCTION"


def activation_from_env() -> ProductionActivation:
    if os.environ.get(ACTIVATION_ENV) == "1":
        return ProductionActivation(enabled=True)
    return ProductionActivation(enabled=False, reason="RELEASE_GATE_PENDING")


def _automation(projects: ProjectManager, project_name: str) -> dict:
    settings = projects.load_project(project_name).get("automation")
    if not isinstance(settings, dict):
        raise ProductionRunRefused("AUTOMATION_NOT_CONFIGURED", 409, ("PROJECT_AUTOMATION_SETTINGS_MISSING",))
    return settings


class ProjectPolicyResolver:
    """The frozen policy of a project's ``automation`` settings with every route's configuration re-inspected."""

    def __init__(self, sessions: Sessions, *, projects: ProjectManager, resolver: ConfigResolver) -> None:
        self._sessions, self._projects, self._resolver = sessions, projects, resolver

    async def routes(self, project_name: str) -> tuple[ModelRoute, ...]:
        settings = _automation(self._projects, project_name)
        project = self._projects.load_project(project_name)
        routes = []
        async with self._sessions() as session:
            for raw in settings.get("routes") or []:
                declared = ModelRoute.model_validate(
                    {
                        "config_digest": "sha256:" + "0" * 64,
                        "local": False,
                        "paid": True,
                        "currency": settings.get("currency", "USD"),
                        "max_cost_per_call": None,
                        **raw,
                    }
                )
                try:
                    routes.append(await inspect_model_route(session, self._resolver, route=declared, project=project))
                except ValueError:
                    raise ProductionRunRefused(
                        "AUTOMATION_NOT_CONFIGURED", 409, ("PINNED_MODEL_UNAVAILABLE",)
                    ) from None
        return tuple(routes)

    async def resolve(self, *, user_id: str, project_name: str, mode: AutomationMode) -> RunPolicy:
        del user_id
        settings = _automation(self._projects, project_name)
        routes = await self.routes(project_name)
        launch = resolve_launch_profile(str(settings.get("launch_profile_id", "fiction_narration_vi_v1")))
        return RunPolicy.model_validate(
            {
                "mode": mode,
                "profile_id": settings.get("profile_id"),
                "profile_digest": settings.get("profile_digest"),
                "launch_profile_id": launch.profile_id,
                "local_only": bool(settings.get("local_only", True)),
                "routes": routes,
                "currency": settings.get("currency", "USD"),
                "max_cost_minor_units": int(settings.get("max_cost_minor_units", 500)),
                "max_model_calls": int(settings.get("max_model_calls", 1500)),
                "max_tasks": int(settings.get("max_tasks", 600)),
                "max_runtime_seconds": int(settings.get("max_runtime_seconds", 64800)),
                "route_digests": tuple(route_digest(route) for route in routes) or ("sha256:" + "0" * 64,),
                "target_duration_seconds": launch.target_duration_seconds,
                "width": launch.width,
                "height": launch.height,
                "fps": launch.fps,
                "language": launch.language,
            }
        )


class HostPreflightReader:
    """Actual project, configuration, profile, qualification and resource state; dispatches nothing."""

    def __init__(
        self,
        sessions: Sessions,
        *,
        projects: ProjectManager,
        policies: ProjectPolicyResolver,
        witness: ProjectInputWitness,
        profile_reader: Callable[[str, str, str], Awaitable[QualityProfileRevision | None]] | None = None,
        gpu_free_bytes: Callable[[], int] | None = None,
    ) -> None:
        self._sessions, self._projects, self._policies, self._witness = sessions, projects, policies, witness
        self._profile_reader = profile_reader
        self._gpu_free = gpu_free_bytes or (lambda: 0)

    async def read(self, *, user_id: str, project_name: str, policy: RunPolicy) -> PreflightSnapshot:
        project = self._projects.load_project(project_name)
        raw = project.get("automation")
        settings: dict = raw if isinstance(raw, dict) else {}
        async with self._sessions() as session:
            qualifications = await ReviewerQualificationRepository(session).qualified(
                profile_digest=policy.profile_digest,
                launch_profile_id=policy.launch_profile_id,
                language=policy.language,
            )
        profile = (
            await self._profile_reader(user_id, project_name, policy.profile_id)
            if self._profile_reader is not None
            else None
        )
        mode = str(project.get("content_mode", ""))
        return PreflightSnapshot(
            user_id=user_id,
            project_name=project_name,
            input_digest=await self._witness.digest(user_id=user_id, project_name=project_name),
            content_mode=f"fiction_{mode}" if mode in {"narration", "drama"} else mode or "unknown",
            generation_mode=str(project.get("generation_mode", "unknown")),
            language=policy.language,
            routes=await self._policies.routes(project_name),
            profile=profile,
            qualifications=qualifications,
            launch_qualification=None,
            voice_available=bool(settings.get("voice_available", False)),
            disk_free_bytes=shutil.disk_usage(self._projects.projects_root).free,
            required_disk_bytes=int(settings.get("required_disk_bytes", 0)),
            gpu_free_bytes=self._gpu_free(),
            required_gpu_bytes=int(settings.get("required_gpu_bytes", 0)),
            checked_at=datetime.now(UTC),
        )


def build_adapters(
    sessions: Sessions,
    *,
    authority: RunAutomationAuthority,
    projects: ProjectManager,
    resolver: ConfigResolver,
    stories: StoryAuthoringService,
    upload_for: Callable,
    evaluator: QualifiedEvaluator,
) -> dict[RunStage, OwnerAdapter]:
    story = {"authority": authority, "stories": stories, "projects": projects}
    text = {"authority": authority, "projects": projects, "resolver": resolver}
    owners = {"authority": authority, "projects": projects}
    return {
        RunStage.BRIEF: BriefAdapter(sessions, **story),
        RunStage.STORY: StoryAdapter(sessions, **story),
        RunStage.STORY_COMMIT: StoryCommitAdapter(sessions, **story),
        RunStage.HANDOFF: HandoffAdapter(sessions, authority=authority, projects=projects, upload_for=upload_for),
        RunStage.ASSET_ANALYSIS: AssetsAdapter(sessions, **text),
        RunStage.EPISODE_PLAN: EpisodePlanAdapter(sessions, **text),
        RunStage.SCRIPT_PLAN: ScriptPlanAdapter(sessions, **text),
        RunStage.SCRIPT: ScriptAdapter(sessions, **text),
        RunStage.MEDIA: MediaAdapter(sessions, **text),
        RunStage.RENDER: RenderAdapter(sessions, **owners),
        RunStage.MASTER: FinalMasterAdapter(sessions, **owners),
        RunStage.QUALITY: QualityAdapter(sessions, **owners, evaluator=evaluator),
        RunStage.PACKAGE: PackagingAdapter(sessions, **owners),
        RunStage.EXPORT: ExportAdapter(sessions, **owners),
    }


def compose_production(
    sessions: Sessions,
    *,
    custodian: AutomationGrantCustodian,
    projects: ProjectManager,
    resolver: ConfigResolver,
    stories: StoryAuthoringService,
    upload_for: Callable[..., SourceUpload],
    evaluator: QualifiedEvaluator,
    activation: ProductionActivation,
    owner_id: str = "production-controller",
) -> tuple[ProductionRunService, ProductionScheduler]:
    """The service and scheduler; the custodian must already be activated so its authority exists."""
    witness = ProjectInputWitness(sessions, projects=projects)
    policies = ProjectPolicyResolver(sessions, projects=projects, resolver=resolver)
    preflight = ProductionPreflight(
        HostPreflightReader(sessions, projects=projects, policies=policies, witness=witness)
    )
    controller = ProductionController(
        sessions,
        adapters=build_adapters(
            sessions,
            authority=custodian.authority(),
            projects=projects,
            resolver=resolver,
            stories=stories,
            upload_for=upload_for,
            evaluator=evaluator,
        ),
        witness=witness,
    )
    scheduler = ProductionScheduler(sessions, controller, owner_id=owner_id, lease_seconds=300)
    service = ProductionRunService(
        sessions,
        custodian=custodian,
        policies=policies,
        witness=witness,
        preflight=preflight,
        activation=activation,
        on_change=scheduler.wake,
    )
    return service, scheduler


__all__ = [
    "ACTIVATION_ENV",
    "HostPreflightReader",
    "ProjectPolicyResolver",
    "activation_from_env",
    "build_adapters",
    "compose_production",
]
