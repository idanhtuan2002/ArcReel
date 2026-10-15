"""M8 exploration API (plan M8-A fixed API surface, ADR-0097).

Every handler takes the user from the session and the project from the path. A request body
cannot override either. Domain failures map to the five stable M8 error keys, and a foreign
identity is reported exactly like an unknown one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Query

from lib.api_errors import ApiError, ConflictError, NotFoundError
from lib.db import async_session_factory
from lib.project_manager import get_project_manager
from r2.advanced_creative.errors import CandidateConflictError, ExplorationNotFoundError, M8Error
from r2.contracts.advanced_creative import (
    CandidateHead,
    ExplorationKind,
    ExplorationRevision,
    LineageBinding,
    M8ContractModel,
    PromotionAuthorization,
    PromotionPreview,
    PromotionReceipt,
    PromotionTarget,
)
from server.auth import CurrentUser
from server.services.advanced_creative import (
    episode_lineage,
    exploration_promotion,
    exploration_service,
    require_server_lineage,
)

router = APIRouter()


class AppendRevisionRequest(M8ContractModel):
    candidate: ExplorationRevision
    expected_head_version: int | None
    command_id: str


class ExplorationContext(M8ContractModel):
    """What a client copies into a revision it appends: the lineage and the author identity."""

    lineage: LineageBinding
    created_by: str


class CreatePromotionPreviewRequest(M8ContractModel):
    candidate_id: str
    revision: int
    target: PromotionTarget
    command_id: str


class PromoteExplorationRequest(M8ContractModel):
    authorization: PromotionAuthorization
    expected_candidate_head_version: int


def _api_error(error: M8Error) -> ApiError:
    if isinstance(error, ExplorationNotFoundError):
        return NotFoundError(error.code)
    return ConflictError(error.code)


async def _run[T](operation: Callable[[], Awaitable[T]]) -> T:
    try:
        return await operation()
    except M8Error as error:
        raise _api_error(error) from error


@router.get("/projects/{project_name}/m8/exploration/context")
async def get_context(project_name: str, user: CurrentUser, episode: int = Query(ge=1)) -> ExplorationContext:
    """The server-resolved values a revision for this episode binds (ADR-0098)."""

    async def operation() -> ExplorationContext:
        async with async_session_factory() as session:
            lineage = await episode_lineage(
                get_project_manager(), session, user_id=user.id, project_name=project_name, episode=episode
            )
        return ExplorationContext(lineage=lineage, created_by=user.id)

    return await _run(operation)


@router.post("/projects/{project_name}/m8/exploration/revisions")
async def append_revision(project_name: str, req: AppendRevisionRequest, user: CurrentUser) -> CandidateHead:
    async def operation() -> CandidateHead:
        if req.candidate.lineage.project_name != project_name or req.candidate.created_by != user.id:
            raise ExplorationNotFoundError("the revision is not in this scope")
        if req.candidate.kind is not ExplorationKind.CANVAS:
            raise CandidateConflictError("only Canvas revisions are appended by clients; others are server-prepared")
        async with async_session_factory() as session:
            await require_server_lineage(
                get_project_manager(),
                session,
                user_id=user.id,
                project_name=project_name,
                lineage=req.candidate.lineage,
            )
            return await exploration_service(session).append_revision(
                user_id=user.id,
                project_name=project_name,
                candidate=req.candidate,
                expected_head_version=req.expected_head_version,
                command_id=req.command_id,
            )

    return await _run(operation)


@router.get("/projects/{project_name}/m8/exploration/candidates/{candidate_id}")
async def get_head(project_name: str, candidate_id: str, user: CurrentUser) -> CandidateHead:
    """The candidate's current revision and CAS version, without any revision body."""

    async def operation() -> CandidateHead:
        async with async_session_factory() as session:
            return await exploration_service(session).head(
                user_id=user.id, project_name=project_name, candidate_id=candidate_id
            )

    return await _run(operation)


@router.get("/projects/{project_name}/m8/exploration/candidates/{candidate_id}/revisions/{revision}")
async def get_revision(project_name: str, candidate_id: str, revision: int, user: CurrentUser) -> ExplorationRevision:
    async def operation() -> ExplorationRevision:
        async with async_session_factory() as session:
            return await exploration_service(session).get_exact(
                user_id=user.id, project_name=project_name, candidate_id=candidate_id, revision=revision
            )

    return await _run(operation)


@router.get("/projects/{project_name}/m8/exploration/candidates/{candidate_id}/revisions")
async def list_revisions(
    project_name: str,
    candidate_id: str,
    user: CurrentUser,
    after_revision: int | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[ExplorationRevision]:
    async def operation() -> list[ExplorationRevision]:
        async with async_session_factory() as session:
            return list(
                await exploration_service(session).history(
                    user_id=user.id,
                    project_name=project_name,
                    candidate_id=candidate_id,
                    after_revision=after_revision,
                    limit=limit,
                )
            )

    return await _run(operation)


@router.post("/projects/{project_name}/m8/exploration/promotion-previews")
async def create_promotion_preview(
    project_name: str, req: CreatePromotionPreviewRequest, user: CurrentUser
) -> PromotionPreview:
    async def operation() -> PromotionPreview:
        async with async_session_factory() as session:
            return await exploration_service(session).create_preview(
                user_id=user.id,
                project_name=project_name,
                candidate_id=req.candidate_id,
                revision=req.revision,
                target=req.target,
                command_id=req.command_id,
            )

    return await _run(operation)


@router.post("/projects/{project_name}/m8/exploration/promotions")
async def promote(project_name: str, req: PromoteExplorationRequest, user: CurrentUser) -> PromotionReceipt:
    async def operation() -> PromotionReceipt:
        async with async_session_factory() as session:
            return await exploration_promotion(session).promote(
                user_id=user.id,
                project_name=project_name,
                authorization=req.authorization,
                expected_candidate_head_version=req.expected_candidate_head_version,
            )

    return await _run(operation)


__all__ = ["router"]
