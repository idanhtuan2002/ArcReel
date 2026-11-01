"""Production runs: Start, read, Pause/Resume/Cancel, mode change and semi checkpoint review.

Reads take the authenticated user. Mutations take an interactive session; the service derives the actor, the
run's user and its automation grant, and never accepts identity or authority from the request body.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from lib.db import async_session_factory
from lib.db.repositories.production_runs import ProductionRunConflict, ProductionRunRepository
from r2.automation.identity import policy_digest
from r2.contracts.automation import AutomationMode, Checkpoint, ReviewCommand, RunCommand, RunSnapshot
from server.auth import CurrentUser, InteractiveUser, oauth2_scheme_optional
from server.production_run.service import (
    ProductionRunRefused,
    ProductionRunService,
    policy_for_mode,
    refusal,
)
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
    idea: str = Field(min_length=1, max_length=4000)
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
    decision: Literal["APPROVE", "REJECT"]


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
