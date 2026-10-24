"""Story runs: draft a brief for Gate A, start the run, touchpoint 2, the run lifecycle, export and hand-off.

Reads take the authenticated user. Every action that changes a run takes an interactive Human session and, in
the service, the project's Showrunner grant.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from lib.config.resolver import ConfigResolver
from lib.db import async_session_factory
from lib.project_manager import get_project_manager
from r2.narrative_lifecycle.errors import NarrativeDecisionAuthorizationError
from server.auth import CurrentUser, InteractiveUser
from server.services import workflow_planner
from server.story_authoring.authority import GrantNarrativeShowrunnerAuthority
from server.story_authoring.commit import CommitRefused
from server.story_authoring.driver import StoryBrief
from server.story_authoring.handoff import STORY_SOURCE_LANGUAGE, HandoffRefused, OnConflict
from server.story_authoring.runtime import RunState
from server.story_authoring.service import StoryActionRefused, StoryAuthoringService
from server.tool_runtime import (
    CallerContext,
    ProjectScope,
    Services,
    ToolRequest,
    UploadSourceRequest,
    upload_source,
)

router = APIRouter()


def story_service(request: Request) -> StoryAuthoringService:
    grants = getattr(request.app.state, "governance_grants", None)
    return StoryAuthoringService(
        session_factory=async_session_factory,
        authority=GrantNarrativeShowrunnerAuthority(async_session_factory, grants),
        project_dir_for=lambda name: get_project_manager().get_project_path(name),
    )


Service = Annotated[StoryAuthoringService, Depends(story_service)]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftBriefRequest(_Request):
    idea: str = Field(min_length=1, max_length=4000)
    genre: str = Field(min_length=1, max_length=200)
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    story_target_syllables: int = Field(default=9000, ge=7000, le=11000)
    judge_provider_id: str | None = Field(default=None, min_length=1)
    judge_model_id: str | None = Field(default=None, min_length=1)
    max_cost_minor_units: int = Field(default=500, ge=1, le=10_000)


class StartRunRequest(_Request):
    brief: StoryBrief
    gate_a_decision_id: str = Field(min_length=1)


class ApproveRequest(_Request):
    manifest_digest: str = Field(min_length=1)
    accepted_exceptions: list[str] = Field(default_factory=list)


class ReviseRequest(_Request):
    target: str = Field(min_length=1)
    note: str = Field(min_length=1, max_length=2000)


class SendToVideoRequest(_Request):
    command_id: str = Field(min_length=8, max_length=128)
    on_conflict: Literal["fail", "replace", "rename"] = "fail"


def _refusal(error: Exception) -> HTTPException:
    if isinstance(error, StoryActionRefused):
        return HTTPException(status_code=error.status, detail={"code": error.code, "detail": error.detail})
    if isinstance(error, CommitRefused | HandoffRefused):
        return HTTPException(status_code=409, detail={"code": error.code.value, "detail": error.detail})
    return HTTPException(status_code=403, detail={"code": "NOT_AUTHORIZED", "detail": str(error)})


REFUSALS = (StoryActionRefused, CommitRefused, HandoffRefused, NarrativeDecisionAuthorizationError)


def _view(run_id: str, brief: StoryBrief, state: RunState, offered: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "phase": state.phase.value,
        "block_reason": state.block_reason,
        "blocked_findings": [dict(f) for f in state.blocked_findings],
        "brief": brief.model_dump(mode="json"),
        "brief_digest": brief.digest(),
        "usage": state.usage.model_dump(),
        "limits": state.limits.model_dump(),
        "intents": {node: list(notes) for node, notes in state.intents.items()},
        "offered": offered,
        "handoff": state.handoff.model_dump() if state.handoff is not None else None,
    }


@router.get("/system/config/story-routes")
async def available_story_routes(_user: CurrentUser, service: Service) -> dict:
    return {"routes": await service.list_routes()}


@router.post("/projects/{project_name}/story-runs/brief")
async def draft_brief(project_name: str, req: DraftBriefRequest, _user: CurrentUser, service: Service) -> dict:
    """The brief and the digest the Human greenlights through ``POST /gates/greenlight``."""
    try:
        brief = await service.draft_brief(
            idea=req.idea,
            genre=req.genre,
            provider_id=req.provider_id,
            model_id=req.model_id,
            story_target_syllables=req.story_target_syllables,
            judge_provider_id=req.judge_provider_id,
            judge_model_id=req.judge_model_id,
            max_cost_minor_units=req.max_cost_minor_units,
        )
    except REFUSALS as error:
        raise _refusal(error) from error
    return {"project_name": project_name, "brief": brief.model_dump(mode="json"), "brief_digest": brief.digest()}


@router.post("/projects/{project_name}/story-runs")
async def start_run(project_name: str, req: StartRunRequest, user: InteractiveUser, service: Service) -> dict:
    try:
        ref = await service.start(
            user_id=user.id,
            project_name=project_name,
            principal=user.sub,
            brief=req.brief,
            gate_a_decision_id=req.gate_a_decision_id,
        )
    except REFUSALS as error:
        raise _refusal(error) from error
    return {"run_id": ref.run_id, "brief_digest": ref.brief.digest()}


@router.get("/projects/{project_name}/story-runs")
async def list_runs(project_name: str, user: CurrentUser, service: Service) -> dict:
    return {"runs": await service.list_runs(user_id=user.id, project_name=project_name)}


@router.get("/projects/{project_name}/story-runs/{run_id}")
async def get_run(project_name: str, run_id: str, user: CurrentUser, service: Service) -> dict:
    try:
        ref, state = await service.get(user_id=user.id, project_name=project_name, run_id=run_id)
    except REFUSALS as error:
        raise _refusal(error) from error
    return _view(ref.run_id, ref.brief, state, service.offered(project_name, state))


@router.get("/projects/{project_name}/story-runs/{run_id}/export")
async def export_run(project_name: str, run_id: str, user: CurrentUser, service: Service) -> Response:
    try:
        data = await service.export(user_id=user.id, project_name=project_name, run_id=run_id)
    except REFUSALS as error:
        raise _refusal(error) from error
    return Response(content=data, media_type="text/markdown; charset=utf-8")


@router.post("/projects/{project_name}/story-runs/{run_id}/approve")
async def approve_run(
    project_name: str, run_id: str, req: ApproveRequest, user: InteractiveUser, service: Service
) -> dict:
    try:
        state = await service.approve(
            user_id=user.id,
            project_name=project_name,
            run_id=run_id,
            principal=user.sub,
            manifest_digest_seen=req.manifest_digest,
            accepted_exceptions=req.accepted_exceptions,
        )
        ref, _ = await service.get(user_id=user.id, project_name=project_name, run_id=run_id)
    except REFUSALS as error:
        raise _refusal(error) from error
    return _view(ref.run_id, ref.brief, state, service.offered(project_name, state))


@router.post("/projects/{project_name}/story-runs/{run_id}/revise")
async def revise_run(
    project_name: str, run_id: str, req: ReviseRequest, user: InteractiveUser, service: Service
) -> dict:
    try:
        state = await service.revise(
            user_id=user.id,
            project_name=project_name,
            run_id=run_id,
            principal=user.sub,
            target=req.target,
            note=req.note,
        )
        ref, _ = await service.get(user_id=user.id, project_name=project_name, run_id=run_id)
    except REFUSALS as error:
        raise _refusal(error) from error
    return _view(ref.run_id, ref.brief, state, service.offered(project_name, state))


@router.post("/projects/{project_name}/story-runs/{run_id}/send-to-video")
async def send_run_to_video(
    project_name: str, run_id: str, req: SendToVideoRequest, user: InteractiveUser, service: Service
) -> dict:
    projects = get_project_manager()
    scope = ProjectScope(project_name=project_name, projects_root=projects.projects_root)
    services = Services(
        projects=projects,
        workflow_planner=workflow_planner.get_workflow_planner(projects),
        capabilities=ConfigResolver(async_session_factory),
    )

    async def upload(filename: str, content: str, on_conflict: OnConflict) -> dict[str, object]:
        outcome = await upload_source(
            ToolRequest(UploadSourceRequest(filename=filename, content=content, on_conflict=on_conflict)),
            scope,
            CallerContext(user_id=user.id, source="embedded"),
            services,
        )
        if outcome.problem is not None or outcome.value is None:
            problem = outcome.problem
            raise RuntimeError(f"{problem.code}: {problem.detail}" if problem is not None else "upload_source failed")
        return outcome.value

    try:
        record = await service.send_to_video(
            user_id=user.id,
            project_name=project_name,
            run_id=run_id,
            principal=user.sub,
            command_id=req.command_id,
            load_project=lambda: projects.load_project(project_name),
            upload=upload,
            on_conflict=req.on_conflict,
        )
    except REFUSALS as error:
        raise _refusal(error) from error

    # 故事固定以越南语写成：交接完成（含同文件恢复与已完成命令的重放）后，项目尚未登记源文语言时登记之，
    # 概述与分集按越南语处理
    def _record_language(project: dict) -> None:
        if not isinstance(project.get("source_language"), str) or not project["source_language"].strip():
            project["source_language"] = STORY_SOURCE_LANGUAGE

    projects.update_project(project_name, _record_language)
    return record.model_dump()


# Declared last: the path also matches the named actions above.
Action = Literal["resume", "abort", "retry", "discard", "withdraw"]


@router.post("/projects/{project_name}/story-runs/{run_id}/{action}")
async def run_action(project_name: str, run_id: str, action: Action, user: InteractiveUser, service: Service) -> dict:
    handlers = {
        "resume": service.resume,
        "abort": service.abort,
        "retry": service.retry,
        "discard": service.discard,
        "withdraw": service.withdraw,
    }
    try:
        state = await handlers[action](user_id=user.id, project_name=project_name, run_id=run_id, principal=user.sub)
        ref, _ = await service.get(user_id=user.id, project_name=project_name, run_id=run_id)
    except REFUSALS as error:
        raise _refusal(error) from error
    return _view(ref.run_id, ref.brief, state, service.offered(project_name, state))
