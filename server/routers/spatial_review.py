"""M8-C human steps: LOCATION binding creation, frame review, pair decision and typed spatial promotion.

Every route requires an interactive session JWT; the scope (user, project, principal) comes from that
session and the path, never from the body. Review, decision and promotion also need the activated
governance grant reader (ADR-0103) and are unavailable without it; each service checks the current
grant itself under its own locks. Services are built per request with the project's own directory.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field

from lib.api_errors import ApiError, ConflictError, NotFoundError, ServiceUnavailableError, UnprocessableError
from lib.db import async_session_factory
from lib.db.repositories.production_binding import ProductionBindingIntegrityError
from lib.db.repositories.spatial_review import SpatialReviewIntegrityError, SpatialReviewRepository
from lib.project_manager import get_project_manager
from r2.advanced_creative.errors import CommandConflictError, ExplorationNotFoundError, M8Error
from r2.contracts.advanced_creative import M8ContractModel, PromotionAuthorization
from r2.contracts.production_binding_authority import BindingCreateCommandV1, BindingCreateResultV1, FrameReceiptRefV1
from r2.contracts.production_target import TargetVersionRef
from r2.contracts.review_evidence import ReviewAcknowledgmentV1, ReviewRole, ReviewSnapshotV1
from r2.contracts.spatial_pair import PairDecisionCommandV2, PairDecisionResultV2, PairReviewObservationsV1, PairViewV1
from r2.contracts.spatial_promotion import SpatialPromotionPreviewV2, SpatialPromotionReceiptV2
from r2.production_binding.spatial_promotion import spatial_preview_v2_digest
from server.auth import InteractiveUser
from server.services.governance_grants import CurrentShowrunnerGrantReader
from server.services.location_binding import BindingSourceConflictError, LocationBindingCreationService
from server.services.spatial_pair_current_v2 import SpatialPairV2UnavailableError
from server.services.spatial_pair_decision import PairSourceConflictError
from server.services.spatial_pair_decision_v2 import SpatialPairDecisionServiceV2
from server.services.spatial_promotion import SpatialPreviewCommand, SpatialPromotionService
from server.services.spatial_review_session import SpatialReviewSessionService, SpatialReviewSourceConflictError

router = APIRouter()

REVIEW_UNAVAILABLE = "m8_spatial_review_unavailable"
REVIEW_FORBIDDEN = "m8_spatial_review_forbidden"
REVIEW_SESSION_UNAVAILABLE = "m8_spatial_review_session_unavailable"
SPATIAL_SOURCE_CONFLICT = "m8_spatial_source_conflict"
SPATIAL_REQUEST_INVALID = "m8_spatial_request_invalid"

_SOURCE_CONFLICTS = (
    BindingSourceConflictError,
    ProductionBindingIntegrityError,
    SpatialReviewSourceConflictError,
    PairSourceConflictError,
    SpatialPairV2UnavailableError,
)


def governance_grants(request: Request) -> CurrentShowrunnerGrantReader:
    """The activated grant reader; review, decision and promotion are unavailable without it."""
    grants = getattr(request.app.state, "governance_grants", None)
    if grants is None:
        raise ServiceUnavailableError(REVIEW_UNAVAILABLE)
    return grants


Grants = Annotated[CurrentShowrunnerGrantReader, Depends(governance_grants)]


def _project_dir(project_name: str) -> Path:
    return get_project_manager().get_project_path(project_name)


def _api_error(error: Exception) -> ApiError:
    if isinstance(error, PermissionError):
        return ApiError(REVIEW_FORBIDDEN, status_code=403)
    if isinstance(error, SpatialReviewIntegrityError):
        return ConflictError(REVIEW_SESSION_UNAVAILABLE)
    if isinstance(error, _SOURCE_CONFLICTS):
        return ConflictError(SPATIAL_SOURCE_CONFLICT)
    if isinstance(error, ExplorationNotFoundError):
        return NotFoundError(error.code)
    if isinstance(error, M8Error):
        return ConflictError(error.code)
    return UnprocessableError(SPATIAL_REQUEST_INVALID)


async def _run[T](operation: Callable[[], Awaitable[T]]) -> T:
    try:
        return await operation()
    except (M8Error, PermissionError, ValueError) as error:
        # ValueError covers the services' conflict errors and a command that fails validation.
        raise _api_error(error) from error


class CreateBindingRequest(M8ContractModel):
    command_id: str = Field(min_length=1, max_length=255)
    expected_target_ref: TargetVersionRef
    ordered_frame_receipts: tuple[FrameReceiptRefV1, FrameReceiptRefV1]


class CreateReviewSessionRequest(M8ContractModel):
    target_id: str = Field(min_length=1, max_length=255)


class AcknowledgeFrameRequest(M8ContractModel):
    attempt_id: str = Field(min_length=1, max_length=255)
    role: ReviewRole
    png_digest: str
    decoded: bool


class PairDecisionRequest(M8ContractModel):
    """The V2 pair command the reviewer was shown, without its scope or the server-owned evidence digest."""

    command_id: str = Field(min_length=1, max_length=255)
    review_session_id: str
    expected_scene_ref: TargetVersionRef
    expected_target_ref: TargetVersionRef
    binding_id: str
    expected_binding_version: int = Field(ge=1)
    expected_envelope_digest: str
    expected_core_digest: str
    views: tuple[PairViewV1, PairViewV1]
    decision: Literal["APPROVE", "REJECT"]
    observations: PairReviewObservationsV1


class CreateSpatialPreviewRequest(M8ContractModel):
    command_id: str = Field(min_length=1, max_length=255)
    candidate_id: str = Field(min_length=1, max_length=255)
    candidate_revision: int = Field(ge=1)
    target_id: str = Field(min_length=1, max_length=255)
    expected_binding_version: int = Field(ge=1)
    selected_assertion_ids: tuple[str, ...] = Field(min_length=1)


class SpatialPreviewResponse(M8ContractModel):
    """The preview and the digest a promotion authorization must name to approve exactly it."""

    preview: SpatialPromotionPreviewV2
    preview_digest: str


class PromoteSpatialRequest(M8ContractModel):
    command_id: str = Field(min_length=1, max_length=255)
    preview_id: str
    preview_digest: str
    expected_candidate_head_version: int = Field(ge=1)


@router.post("/projects/{project_name}/m8/spatial/bindings")
async def create_binding(project_name: str, req: CreateBindingRequest, user: InteractiveUser) -> BindingCreateResultV1:
    """Bind two exact frame receipts of approved masters to one Take Shot as its LOCATION binding."""

    async def operation() -> BindingCreateResultV1:
        command = BindingCreateCommandV1.model_validate(
            req.model_dump(mode="json") | {"user_id": user.id, "project_name": project_name, "principal": user.sub}
        )
        service = LocationBindingCreationService(
            session_factory=async_session_factory, project_dir=_project_dir(project_name)
        )
        return (await service.create(command)).result

    return await _run(operation)


def _review(project_name: str, grants: CurrentShowrunnerGrantReader) -> SpatialReviewSessionService:
    return SpatialReviewSessionService(
        session_factory=async_session_factory, project_dir=_project_dir(project_name), grants=grants
    )


@router.post("/projects/{project_name}/m8/spatial/review-sessions")
async def create_review_session(
    project_name: str, req: CreateReviewSessionRequest, user: InteractiveUser, grants: Grants
) -> ReviewSnapshotV1:
    """Open a short-lived review of the target's current binding frames for this reviewer."""

    async def operation() -> ReviewSnapshotV1:
        return await _review(project_name, grants).create(
            user_id=user.id, project_name=project_name, principal=user.sub, target_id=req.target_id
        )

    return await _run(operation)


@router.get("/projects/{project_name}/m8/spatial/review-sessions/{session_id}/frames/{role}")
async def fetch_review_frame(
    project_name: str, session_id: str, role: ReviewRole, user: InteractiveUser, grants: Grants
) -> Response:
    """Serve one reviewed frame's exact PNG bytes and record the delivery."""

    async def operation() -> Response:
        png, delivery = await _review(project_name, grants).fetch_frame(
            user_id=user.id, project_name=project_name, principal=user.sub, session_id=session_id, role=role
        )
        return Response(
            content=png,
            media_type="image/png",
            headers={
                "Cache-Control": "no-store",
                "X-Review-Attempt-Id": delivery.attempt_id,
                "X-Review-Png-Digest": delivery.png_digest,
            },
        )

    return await _run(operation)


@router.post("/projects/{project_name}/m8/spatial/review-sessions/{session_id}/acknowledgments")
async def acknowledge_review_frame(
    project_name: str, session_id: str, req: AcknowledgeFrameRequest, user: InteractiveUser, grants: Grants
) -> ReviewAcknowledgmentV1:
    """Record that the reviewer's client decoded the delivered frame and checked its digest."""

    async def operation() -> ReviewAcknowledgmentV1:
        return await _review(project_name, grants).acknowledge_frame(
            user_id=user.id,
            project_name=project_name,
            principal=user.sub,
            session_id=session_id,
            attempt_id=req.attempt_id,
            role=req.role,
            png_digest=req.png_digest,
            decoded=req.decoded,
        )

    return await _run(operation)


@router.post("/projects/{project_name}/m8/spatial/pair-decisions")
async def decide_pair(
    project_name: str, req: PairDecisionRequest, user: InteractiveUser, grants: Grants
) -> PairDecisionResultV2:
    """APPROVE or REJECT the reviewed MASTER/REVERSE pair; the decision binds the stored review evidence."""

    async def operation() -> PairDecisionResultV2:
        async with async_session_factory() as session, session.begin():
            _evidence, evidence_digest = await SpatialReviewRepository(session).read_complete(
                user_id=user.id, project_name=project_name, principal=user.sub, session_id=req.review_session_id
            )
        command = PairDecisionCommandV2.model_validate(
            req.model_dump(mode="json")
            | {
                "user_id": user.id,
                "project_name": project_name,
                "principal": user.sub,
                "review_evidence_digest": evidence_digest,
            }
        )
        service = SpatialPairDecisionServiceV2(
            session_factory=async_session_factory, project_dir=_project_dir(project_name), grants=grants
        )
        return await service.decide(command, authenticated_user=user)

    return await _run(operation)


def _promotion(project_name: str, grants: CurrentShowrunnerGrantReader) -> SpatialPromotionService:
    return SpatialPromotionService(
        session_factory=async_session_factory, project_dir=_project_dir(project_name), grants=grants
    )


@router.post("/projects/{project_name}/m8/spatial/promotion-previews")
async def create_spatial_preview(
    project_name: str, req: CreateSpatialPreviewRequest, user: InteractiveUser, grants: Grants
) -> SpatialPreviewResponse:
    """Derive a typed constraint-set preview from the selected VISIBLE assertions of a spatial candidate."""

    async def operation() -> SpatialPreviewResponse:
        preview = await _promotion(project_name, grants).create_preview(
            SpatialPreviewCommand(
                user_id=user.id,
                project_name=project_name,
                candidate_id=req.candidate_id,
                candidate_revision=req.candidate_revision,
                target_id=req.target_id,
                expected_binding_version=req.expected_binding_version,
                selected_assertion_ids=req.selected_assertion_ids,
                command_id=req.command_id,
            )
        )
        return SpatialPreviewResponse(
            preview=preview, preview_digest=spatial_preview_v2_digest(preview.model_dump(mode="json"))
        )

    return await _run(operation)


@router.post("/projects/{project_name}/m8/spatial/promotions")
async def promote_spatial(
    project_name: str, req: PromoteSpatialRequest, user: InteractiveUser, grants: Grants
) -> SpatialPromotionReceiptV2:
    """Promote one previewed constraint set into the next binding version, authorized by this session."""
    service = _promotion(project_name, grants)

    async def promote(authorization: PromotionAuthorization) -> SpatialPromotionReceiptV2:
        return await service.promote(
            user_id=user.id,
            project_name=project_name,
            authorization=authorization,
            expected_candidate_head_version=req.expected_candidate_head_version,
        )

    async def operation() -> SpatialPromotionReceiptV2:
        authorization = PromotionAuthorization(
            command_id=req.command_id,
            project_name=project_name,
            preview_id=req.preview_id,
            preview_digest=req.preview_digest,
            actor_id=user.id,
            actor_scope=user.id,
            decision="APPROVE",
            authorized_at=datetime.now(UTC),
        )
        try:
            return await promote(authorization)
        except CommandConflictError:
            # A retried request mints a new authorization time; replay with the stored one instead.
            stored = await service.stored_authorization(
                user_id=user.id, project_name=project_name, command_id=req.command_id
            )
            if stored is None or stored.model_copy(update={"authorized_at": authorization.authorized_at}) != (
                authorization
            ):
                raise
            return await promote(stored)

    return await _run(operation)


__all__ = ["governance_grants", "router"]
