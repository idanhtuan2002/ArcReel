"""Production runs: Start, read, Pause/Resume/Cancel, mode change and semi checkpoint review.

Reads take the authenticated user. Mutations take an interactive session; the service derives the actor, the
run's user and its automation grant, and never accepts identity or authority from the request body.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from lib.db import async_session_factory
from lib.db.repositories.autopilot import AutopilotRepository
from lib.db.repositories.production_runs import ProductionRunConflict, ProductionRunRepository
from lib.presentation_renderer import sha256_file
from lib.project_kinds import project_kind
from lib.project_manager import get_project_manager
from r2.automation.identity import policy_digest
from r2.contracts.automation import AutomationMode, Checkpoint, ReviewCommand, RunCommand, RunSnapshot, RunStatus
from r2.contracts.autopilot import FilmAutopilot, StoryAutopilot
from server.auth import CurrentUser, InteractiveUser, oauth2_scheme_optional
from server.production_run.autopilot import AutopilotScheduler
from server.production_run.autopilot_batch import BatchRefused, adopt_automation_settings, films_for_finished_stories
from server.production_run.qualification_jobs import QualificationJobs, QualificationRefused
from server.production_run.report import pending_final, run_progress, run_report, verified_final
from server.production_run.service import (
    ProductionRunRefused,
    ProductionRunService,
    policy_for_mode,
    refusal,
)
from server.production_run.settings import SettingsRefused, SettingsUpdate, save_settings, settings_options
from server.services.governance_startup import GovernanceStartupUnavailable

router = APIRouter()

Token = Annotated[str | None, Depends(oauth2_scheme_optional)]
_DIGEST = r"^sha256:[0-9a-f]{64}$"


def production_run_service(request: Request) -> ProductionRunService | None:
    """The activated service, or ``None`` while automatic production is not wired on this host."""
    return getattr(request.app.state, "production_run_service", None)


Service = Annotated[ProductionRunService | None, Depends(production_run_service)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=8, max_length=128)


class StartBody(_Body):
    mode: AutomationMode = AutomationMode.AUTO
    #: Required unless ``story_source`` is ``project`` (the story already in the project's sources, ADR-0115).
    idea: str | None = Field(default=None, min_length=1, max_length=4000)
    story_source: Literal["idea", "project", "continue", "variant"] = "idea"
    #: A variant reads this project's story (ADR-0115) and may apply a named variant profile.
    source_project: str | None = Field(default=None, min_length=1)
    variant_profile: str | None = Field(default=None, min_length=1)
    #: ADR-0116: start a book of this many chapters (a run from an idea writes its first part).
    book_chapters: int | None = Field(default=None, ge=6, le=120)
    #: ADR-0125: ``auto`` starts without an idea; the run draws its idea and settings.
    idea_mode: Literal["given", "auto"] = "given"
    targets: tuple[str, ...] = ("episode:1",)
    expected_input_digest: str = Field(pattern=_DIGEST)
    policy_digest: str = Field(pattern=_DIGEST)


class ControlBody(_Body):
    expected_version: int = Field(ge=1)
    expected_input_digest: str = Field(pattern=_DIGEST)
    policy_digest: str = Field(pattern=_DIGEST)


class ModeBody(ControlBody):
    mode: AutomationMode


class ReviewBody(_Body):
    expected_version: int = Field(ge=1)
    checkpoint: Checkpoint
    binding_digest: str = Field(pattern=_DIGEST)
    decision: Literal["APPROVE", "REJECT", "REWORK"]


def _view(run: RunSnapshot) -> dict[str, Any]:
    return {
        **run.model_dump(mode="json"),
        "policy_digest": policy_digest(run.policy),
        "mode_policy_digests": {
            mode.value: policy_digest(policy_for_mode(run.policy, mode)) for mode in AutomationMode
        },
    }


def _invalid() -> HTTPException:
    return HTTPException(status_code=422, detail={"code": "INVALID_COMMAND", "reasons": []})


def _http(error: Exception) -> HTTPException:
    status, body = refusal(error)
    return HTTPException(status_code=status, detail=body)


_REFUSALS = (ProductionRunRefused, ProductionRunConflict, PermissionError, GovernanceStartupUnavailable)


def _require(service: ProductionRunService | None) -> ProductionRunService:
    if service is None:
        raise HTTPException(
            status_code=503, detail={"code": "AUTOMATIC_PRODUCTION_NOT_ACTIVATED", "reasons": ["RELEASE_GATE_PENDING"]}
        )
    return service


@router.get("/projects/{project_name}/production-runs")
async def list_runs(project_name: str, user: CurrentUser, service: Service) -> dict[str, Any]:
    if service is None:
        async with async_session_factory() as session:
            runs = await ProductionRunRepository(session).list_for_project(user_id=user.id, project_name=project_name)
        start: dict[str, object] = {"enabled": False, "reason": "RELEASE_GATE_PENDING"}
    else:
        runs = await service.list(user_id=user.id, project_name=project_name)
        start = await service.start_offer(user_id=user.id, project_name=project_name)
    return {"start": start, "runs": [_view(run) for run in runs]}


@router.get("/projects/{project_name}/automation/readiness")
async def get_readiness(project_name: str, user: CurrentUser, service: Service) -> dict[str, Any]:
    """Whether automatic production could start for this project now, and why not."""
    try:
        return await _require(service).readiness(user_id=user.id, project_name=project_name)
    except _REFUSALS as error:
        raise _http(error) from error


_QUALIFICATIONS: dict[int, QualificationJobs] = {}


def _qualifications(service: ProductionRunService | None) -> QualificationJobs:
    """This process's qualification jobs over the session factory runs use."""
    sessions = async_session_factory if service is None else service.sessions
    return _QUALIFICATIONS.setdefault(id(sessions), QualificationJobs(sessions, get_project_manager()))


@router.get("/projects/{project_name}/automation/qualification")
async def get_qualification(project_name: str, user: CurrentUser, service: Service) -> dict[str, Any]:
    """Whether each reviewer route and the launch are qualified, and any reviewer job running on this host."""
    try:
        return await _qualifications(service).status(user_id=user.id, project_name=project_name)
    except _REFUSALS as error:
        raise _http(error) from error


@router.post("/projects/{project_name}/automation/qualification/reviewers")
async def start_reviewer_qualification(
    project_name: str, user: InteractiveUser, token: Token, service: Service
) -> dict[str, Any]:
    """Qualify both reviewer routes on this host's labeled corpus; a qualifying result is recorded."""
    try:
        await _require(service).require_showrunner(interactive_token=token, user_id=user.id, project_name=project_name)
        return await _qualifications(service).start_reviewers(user_id=user.id, project_name=project_name)
    except QualificationRefused as refused:
        raise HTTPException(status_code=409, detail={"code": str(refused), "reasons": []}) from None
    except _REFUSALS as error:
        raise _http(error) from error


@router.post("/projects/{project_name}/automation/qualification/media")
async def start_media_probes(
    project_name: str, user: InteractiveUser, token: Token, service: Service
) -> dict[str, Any]:
    """Make one checked sample through each image, video or audio route the launch profile does not name."""
    try:
        await _require(service).require_showrunner(interactive_token=token, user_id=user.id, project_name=project_name)
        return await _qualifications(service).start_media_probes(user_id=user.id, project_name=project_name)
    except QualificationRefused as refused:
        raise HTTPException(status_code=409, detail={"code": str(refused), "reasons": []}) from None
    except _REFUSALS as error:
        raise _http(error) from error


@router.post("/projects/{project_name}/automation/qualification/launch")
async def record_launch_qualification(
    project_name: str, user: InteractiveUser, token: Token, service: Service
) -> dict[str, Any]:
    """Record the launch qualification when the real preflight's only blocking reason is its absence."""
    try:
        await _require(service).require_showrunner(interactive_token=token, user_id=user.id, project_name=project_name)
        return await _qualifications(service).record_launch(user_id=user.id, project_name=project_name)
    except QualificationRefused as refused:
        raise HTTPException(status_code=409, detail={"code": str(refused), "reasons": []}) from None
    except _REFUSALS as error:
        raise _http(error) from error


@router.get("/projects/{project_name}/automation/settings")
async def get_settings(project_name: str, user: CurrentUser, service: Service) -> dict[str, Any]:
    """The project's automatic production settings and the models each role may use."""
    sessions = async_session_factory if service is None else service.sessions
    return await settings_options(sessions, get_project_manager(), project_name, user_id=user.id)


@router.put("/projects/{project_name}/automation/settings")
async def put_settings(
    project_name: str, body: SettingsUpdate, user: InteractiveUser, token: Token, service: Service, scheduler: Autopilot
) -> dict[str, Any]:
    """Replace the project's model per role and run limits; a later Start freezes them into its policy."""
    active = _require(service)
    try:
        await active.require_showrunner(interactive_token=token, user_id=user.id, project_name=project_name)
    except _REFUSALS as error:
        raise _http(error) from error
    sessions = active.sessions
    try:
        saved = await save_settings(sessions, get_project_manager(), project_name, body, user_id=user.id)
    except SettingsRefused as refused:
        raise HTTPException(status_code=422, detail={"code": str(refused), "reasons": []}) from None
    # ADR-0127: an autopilot on the project freezes the policy it was turned on with; the same Showrunner's change of
    # settings turns it on again with the new policy and the same parameters, so it does not stop on POLICY_MOVED.
    async with sessions() as session:
        delegation = await AutopilotRepository(session).current(user.id, project_name)
    if delegation is not None and delegation.state == "ENABLED":
        try:
            await active.set_autopilot(
                interactive_token=token,
                user_id=user.id,
                project_name=project_name,
                command_id=f"settings:{uuid4().hex}",
                enabled=True,
                kind=delegation.kind,
                mode=delegation.mode,
                story=delegation.story,
                film=delegation.film,
            )
        except _REFUSALS as error:
            raise _http(error) from error
        if scheduler is not None:
            scheduler.wake()
    return saved


@router.post("/projects/{project_name}/production-runs")
async def start_run(
    project_name: str, body: StartBody, user: InteractiveUser, token: Token, service: Service
) -> dict[str, Any]:
    active = _require(service)
    try:
        command = RunCommand(
            user_id=user.id,
            project_name=project_name,
            command_id=body.command_id,
            action="START",
            expected_version=0,
            expected_input_digest=body.expected_input_digest,
            policy_digest=body.policy_digest,
            mode=body.mode,
            idea=body.idea,
            targets=body.targets,
            story_source=body.story_source,
            source_project=body.source_project,
            variant_profile=body.variant_profile,
            book_chapters=body.book_chapters,
            idea_mode=body.idea_mode,
        )
    except ValueError as error:
        raise _invalid() from error
    try:
        return _view(await active.start(interactive_token=token, command=command))
    except _REFUSALS as error:
        raise _http(error) from error


@router.get("/projects/{project_name}/production-runs/{run_id}")
async def get_run(project_name: str, run_id: str, user: CurrentUser, service: Service) -> dict[str, Any]:
    if service is None:
        async with async_session_factory() as session:
            run = await ProductionRunRepository(session).get(user_id=user.id, project_name=project_name, run_id=run_id)
        if run is None:
            raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "reasons": []})
        return _view(run)
    try:
        return _view(await service.get(user_id=user.id, project_name=project_name, run_id=run_id))
    except _REFUSALS as error:
        raise _http(error) from error


async def _control(
    service: ProductionRunService | None,
    *,
    token: str | None,
    user_id: str,
    project_name: str,
    run_id: str,
    action: Literal["PAUSE", "RESUME", "CANCEL", "MODE"],
    body: ControlBody,
) -> dict[str, Any]:
    active = _require(service)
    try:
        command = RunCommand(
            user_id=user_id,
            project_name=project_name,
            run_id=run_id,
            command_id=body.command_id,
            action=action,
            expected_version=body.expected_version,
            expected_input_digest=body.expected_input_digest,
            policy_digest=body.policy_digest,
            mode=body.mode if isinstance(body, ModeBody) else AutomationMode.AUTO,
        )
    except ValueError as error:
        raise _invalid() from error
    try:
        return _view(await active.control(interactive_token=token, command=command))
    except _REFUSALS as error:
        raise _http(error) from error


@router.post("/projects/{project_name}/production-runs/{run_id}/pause")
async def pause_run(
    project_name: str, run_id: str, body: ControlBody, user: InteractiveUser, token: Token, service: Service
) -> dict[str, Any]:
    return await _control(
        service, token=token, user_id=user.id, project_name=project_name, run_id=run_id, action="PAUSE", body=body
    )


@router.post("/projects/{project_name}/production-runs/{run_id}/resume")
async def resume_run(
    project_name: str, run_id: str, body: ControlBody, user: InteractiveUser, token: Token, service: Service
) -> dict[str, Any]:
    return await _control(
        service, token=token, user_id=user.id, project_name=project_name, run_id=run_id, action="RESUME", body=body
    )


@router.post("/projects/{project_name}/production-runs/{run_id}/cancel")
async def cancel_run(
    project_name: str, run_id: str, body: ControlBody, user: InteractiveUser, token: Token, service: Service
) -> dict[str, Any]:
    return await _control(
        service, token=token, user_id=user.id, project_name=project_name, run_id=run_id, action="CANCEL", body=body
    )


@router.post("/projects/{project_name}/production-runs/{run_id}/mode")
async def change_mode(
    project_name: str, run_id: str, body: ModeBody, user: InteractiveUser, token: Token, service: Service
) -> dict[str, Any]:
    return await _control(
        service, token=token, user_id=user.id, project_name=project_name, run_id=run_id, action="MODE", body=body
    )


@router.post("/projects/{project_name}/production-runs/{run_id}/review")
async def review_run(
    project_name: str, run_id: str, body: ReviewBody, user: InteractiveUser, token: Token, service: Service
) -> dict[str, Any]:
    active = _require(service)
    try:
        command = ReviewCommand(
            user_id=user.id,
            project_name=project_name,
            run_id=run_id,
            command_id=body.command_id,
            expected_version=body.expected_version,
            checkpoint=body.checkpoint,
            binding_digest=body.binding_digest,
            decision=body.decision,
        )
    except ValueError as error:
        raise _invalid() from error
    try:
        return _view(await active.review(interactive_token=token, command=command))
    except _REFUSALS as error:
        raise _http(error) from error


@router.get("/projects/{project_name}/production-runs/{run_id}/report")
async def get_report(project_name: str, run_id: str, user: CurrentUser, service: Service) -> dict[str, Any]:
    """The run's reviewer verdicts per target and the story exceptions its automatic commit accepted."""
    sessions = async_session_factory if service is None else service.sessions
    async with sessions() as session:
        run = await ProductionRunRepository(session).get(user_id=user.id, project_name=project_name, run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "reasons": []})
    return await run_report(sessions, get_project_manager(), run)


@router.get("/projects/{project_name}/production-runs/{run_id}/progress")
async def get_progress(project_name: str, run_id: str, user: CurrentUser, service: Service) -> dict[str, Any]:
    """The run's timeline and its current stage's progress (owner tasks by status; story writing inside STORY)."""
    sessions = async_session_factory if service is None else service.sessions
    async with sessions() as session:
        run = await ProductionRunRepository(session).get(user_id=user.id, project_name=project_name, run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "reasons": []})
    return await run_progress(sessions, run, get_project_manager())


@router.get("/projects/{project_name}/production-runs/{run_id}/outputs/{episode}/final")
async def preview_final(
    project_name: str, run_id: str, episode: int, user: CurrentUser, service: Service
) -> FileResponse:
    """The verified final of one completed target, or the final a FINAL_FILM review is deciding on, for the owner's
    in-panel preview; never a public file."""
    sessions = async_session_factory if service is None else service.sessions
    async with sessions() as session:
        run = await ProductionRunRepository(session).get(user_id=user.id, project_name=project_name, run_id=run_id)
    projects = get_project_manager()
    final = await asyncio.to_thread(verified_final, projects, run, episode) if run else None
    if final is None and run is not None:
        final = await pending_final(sessions, projects, run, episode)
    if final is None:
        raise HTTPException(status_code=404, detail={"code": "OUTPUT_NOT_FOUND", "reasons": []})
    return FileResponse(final, media_type="video/mp4")


@router.get("/projects/{project_name}/production-runs/{run_id}/outputs/{episode}")
async def download_output(
    project_name: str, run_id: str, episode: int, user: CurrentUser, service: Service
) -> FileResponse:
    """The verified archive of one target of the user's succeeded run; its bytes are re-hashed before sending."""
    run: RunSnapshot | None
    if service is None:
        async with async_session_factory() as session:
            run = await ProductionRunRepository(session).get(user_id=user.id, project_name=project_name, run_id=run_id)
    else:
        try:
            run = await service.get(user_id=user.id, project_name=project_name, run_id=run_id)
        except _REFUSALS:
            run = None
    output = (
        next((o for o in run.completed_targets if o.target == f"episode:{episode}"), None)
        if run is not None and run.status is RunStatus.SUCCEEDED
        else None
    )
    if output is None:
        raise HTTPException(status_code=404, detail={"code": "OUTPUT_NOT_FOUND", "reasons": []})
    project_dir = get_project_manager().get_project_path(project_name)
    archive = (project_dir / output.export.receipt_ref.partition("@")[2]).resolve()
    if (project_dir / "production").resolve() not in archive.parents or not archive.is_file():
        raise HTTPException(status_code=409, detail={"code": "ARCHIVE_CHANGED", "reasons": []})
    if (
        archive.stat().st_size != output.archive_size
        or "sha256:" + await asyncio.to_thread(sha256_file, archive) != output.archive_digest
    ):
        raise HTTPException(status_code=409, detail={"code": "ARCHIVE_CHANGED", "reasons": []})
    return FileResponse(archive, media_type="application/zip", filename=f"{project_name}-episode-{episode}.zip")


# Autopilot (ADR-0124) ----------------------------------------------------------------------------------------------


def autopilot_scheduler(request: Request) -> AutopilotScheduler | None:
    return getattr(request.app.state, "autopilot_scheduler", None)


Autopilot = Annotated[AutopilotScheduler | None, Depends(autopilot_scheduler)]


class AutopilotBody(_Body):
    enabled: bool
    mode: AutomationMode = AutomationMode.AUTO
    story: StoryAutopilot | None = None
    film: FilmAutopilot | None = None


async def _autopilot_view(scheduler: AutopilotScheduler | None, user_id: str, project_name: str) -> dict[str, Any]:
    async with async_session_factory() as session:
        delegation = await AutopilotRepository(session).current(user_id, project_name)
    status: dict[str, Any] = {"state": "off", "run_id": None, "reason": None}
    if delegation is not None and scheduler is not None:
        state, _command = await scheduler.planner.state(delegation, preview=True)
        status = {"state": state.state, "run_id": state.run_id, "reason": state.reason}
        refused = scheduler.refusal(user_id, project_name)
        if state.state == "ready" and refused is not None:
            status = {"state": "halted", "run_id": None, "reason": refused}
    elif delegation is not None and delegation.state == "ENABLED":
        status = {"state": "waiting", "run_id": None, "reason": "RELEASE_GATE_PENDING"}
    return {
        "available": scheduler is not None,
        "delegation": None if delegation is None else delegation.model_dump(mode="json"),
        "status": status,
    }


@router.get("/projects/{project_name}/autopilot")
async def get_autopilot(project_name: str, user: CurrentUser, scheduler: Autopilot) -> dict[str, Any]:
    """The project's autopilot: whether it is on, with what, and what it does next."""
    return await _autopilot_view(scheduler, user.id, project_name)


@router.put("/projects/{project_name}/autopilot")
async def put_autopilot(
    project_name: str,
    body: AutopilotBody,
    user: InteractiveUser,
    token: Token,
    service: Service,
    scheduler: Autopilot,
) -> dict[str, Any]:
    """Turn the project's autopilot on (the Showrunner's current grant; the policy of ``mode`` is frozen) or off."""
    active = _require(service)
    try:
        project = await asyncio.to_thread(get_project_manager().load_project, project_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "reasons": []}) from None
    kind = project_kind(project)
    if body.enabled and (kind == "story") != (body.story is not None):
        raise HTTPException(status_code=422, detail={"code": "AUTOPILOT_PARAMETERS_MISMATCH", "reasons": [kind]})
    adopted: str | None = None
    if body.enabled:
        # A project created for autopilot has no production settings yet: it takes those of the most recently
        # changed configured project, which the Showrunner can change in the project's automation settings.
        try:
            adopted = await asyncio.to_thread(adopt_automation_settings, get_project_manager(), project_name)
        except BatchRefused as refused:
            raise HTTPException(status_code=409, detail={"code": refused.code, "reasons": []}) from None
    try:
        await active.set_autopilot(
            interactive_token=token,
            user_id=user.id,
            project_name=project_name,
            command_id=body.command_id,
            enabled=body.enabled,
            kind=kind,
            mode=body.mode,
            story=body.story if kind == "story" else None,
            film=(body.film or FilmAutopilot()) if kind == "film" else None,
        )
    except _REFUSALS as error:
        raise _http(error) from error
    if scheduler is not None:
        scheduler.wake()
    return {**await _autopilot_view(scheduler, user.id, project_name), "settings_from": adopted}


class FilmsBatchBody(_Body):
    #: The film project whose production settings each new film copies.
    template_project: str = Field(min_length=1, max_length=255)
    limit: int = Field(default=50, ge=1, le=500)


@router.post("/autopilot/films-for-finished-stories")
async def films_for_finished_stories_route(
    body: FilmsBatchBody, user: InteractiveUser, token: Token, service: Service, scheduler: Autopilot
) -> dict[str, Any]:
    """ADR-0124 §6: one film per finished story that no film adapts yet, in creation order, each on autopilot."""
    active = _require(service)
    if scheduler is None:
        raise HTTPException(status_code=503, detail={"code": "AUTOPILOT_NOT_ACTIVATED", "reasons": []})
    planner = scheduler.planner

    async def book_parts(story: str) -> tuple[int, int] | None:
        parts = await planner.book_parts(user.id, story)
        return None if parts is None else (parts.done, parts.total)

    async def sync_story(film: str) -> list[str]:
        return await planner.sync_story(user.id, film)

    async def enable(film: str, story: str) -> None:
        await active.set_autopilot(
            interactive_token=token,
            user_id=user.id,
            project_name=film,
            command_id=f"{body.command_id}:{story}",
            enabled=True,
            kind="film",
            mode=AutomationMode.AUTO,
            film=FilmAutopilot(),
        )

    try:
        result = await films_for_finished_stories(
            get_project_manager(),
            template_project=body.template_project,
            limit=body.limit,
            book_parts=book_parts,
            sync_story=sync_story,
            enable_autopilot=enable,
        )
    except BatchRefused as refused:
        raise HTTPException(status_code=422, detail={"code": refused.code, "reasons": []}) from None
    scheduler.wake()
    return {"created": result.created, "skipped": result.skipped}
