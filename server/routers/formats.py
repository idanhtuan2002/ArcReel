"""M8-E format projection API: profiles, plans, renders, technical checks, blind review, candidates.

The user comes from the session and the project from the path. Plans are built against the
server-resolved current master; renders run as M7 attempts; review packets, clips and reviews need
an interactive session, and a review packet serves its clips only to the reviewer it was opened for.
Preview and promotion of a prepared candidate use the M8 exploration routes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy import select

from lib.api_errors import ApiError, ConflictError, NotFoundError, UnprocessableError
from lib.db import async_session_factory
from lib.db.models.formats import (
    FormatPlanModel,
    FormatRenderModel,
    FormatSemanticReportModel,
    FormatTechnicalReportModel,
)
from lib.db.repositories.formats import FormatRepository
from lib.project_manager import get_project_manager
from r2.advanced_creative.digests import digest_canonical
from r2.advanced_creative.errors import ExplorationNotFoundError, FormatNotFoundError, M8Error
from r2.advanced_creative.formats import SEMANTIC_ITEMS, SEMANTIC_RUBRIC, Box, ReframeKind
from r2.contracts.advanced_creative import (
    FormatProjectionPlan,
    M8ContractModel,
    OutputProfile,
    OverlayConstraintSet,
    PromotionAuthorization,
    PromotionPreview,
    PromotionReceipt,
    PromotionTarget,
    PromotionTargetKind,
    SemanticParityReport,
    TechnicalValidationReport,
)
from server.auth import CurrentUser, InteractiveUser
from server.services.advanced_creative import exploration_promotion, exploration_service
from server.services.execution_attempts import build_attempt_submitter
from server.services.format_candidate import PreparedFormatCandidate, prepare_format_candidate
from server.services.format_plans import master_source, plan_from_master
from server.services.format_render import FormatRenderService
from server.services.format_review import FormatReviewService
from server.services.format_validation import FormatValidationService

router = APIRouter()

FORMAT_REQUEST_INVALID = "m8_format_request_invalid"


def _api_error(error: Exception) -> ApiError:
    if isinstance(error, (FormatNotFoundError, ExplorationNotFoundError)):
        return NotFoundError(error.code)
    if isinstance(error, M8Error):
        return ConflictError(error.code)
    return UnprocessableError(FORMAT_REQUEST_INVALID)


async def _run[T](operation: Callable[[], Awaitable[T]]) -> T:
    try:
        return await operation()
    except (M8Error, ValueError) as error:
        raise _api_error(error) from error


def _project_dir(project_name: str):
    return get_project_manager().get_project_path(project_name)


def _render_service() -> FormatRenderService:
    return FormatRenderService(
        async_session_factory,
        submitter_for=lambda session, user_id, project_name: build_attempt_submitter(
            session, user_id=user_id, project_name=project_name, usage_binder=None
        ),
    )


class BoxBody(M8ContractModel):
    x0: str
    y0: str
    x1: str
    y1: str

    def box(self) -> Box:
        return Box.parse(self.model_dump())


class CreatePlanRequest(M8ContractModel):
    plan_id: str = Field(min_length=1, max_length=200)
    source_artifact_key: str = Field(min_length=1, max_length=255)
    profile_ref: str = Field(min_length=1, max_length=255)
    constraint_ref: str = Field(min_length=1, max_length=255)
    kind: ReframeKind
    focal: BoxBody | None = None
    subject: BoxBody
    captions: tuple[BoxBody, ...] = ()
    rationale: str = Field(min_length=1, max_length=2000)


class RenderRequest(M8ContractModel):
    command_id: str = Field(min_length=1, max_length=255)


class RenderView(M8ContractModel):
    execution_id: str
    plan_id: str
    artifact_digest: str
    replayed: bool


class ReviewPacketView(M8ContractModel):
    packet_id: str
    rubric_version: str
    items: tuple[str, ...]


class SubmitReviewRequest(M8ContractModel):
    items: dict[str, Literal["PASS", "FAIL"]]
    note: str = Field(default="", max_length=2000)


class CandidateView(M8ContractModel):
    candidate_id: str
    revision: int
    head_version: int
    slot_key: str
    expected_target_version: int


class CreateFormatPreviewRequest(M8ContractModel):
    candidate_id: str = Field(min_length=1, max_length=255)
    revision: int = Field(ge=1)
    slot_key: str = Field(min_length=1, max_length=255)
    expected_target_version: int = Field(ge=0)
    command_id: str = Field(min_length=1, max_length=255)


class FormatPreviewView(M8ContractModel):
    preview: PromotionPreview
    preview_digest: str


class ApproveFormatPromotionRequest(M8ContractModel):
    preview_id: str = Field(min_length=1, max_length=255)
    preview_digest: str = Field(min_length=1, max_length=71)
    expected_candidate_head_version: int = Field(ge=1)
    command_id: str = Field(min_length=1, max_length=255)


class PlanSummary(M8ContractModel):
    plan: FormatProjectionPlan
    renders: tuple[RenderView, ...]
    technical: TechnicalValidationReport | None
    semantic: SemanticParityReport | None


@router.post("/projects/{project_name}/m8/formats/profiles")
async def put_profile(project_name: str, profile: OutputProfile, user: CurrentUser) -> OutputProfile:
    async def operation() -> OutputProfile:
        async with async_session_factory() as session:
            stored = await FormatRepository(session).put_profile(
                user_id=user.id, project_name=project_name, profile=profile
            )
            await session.commit()
            return stored

    return await _run(operation)


@router.post("/projects/{project_name}/m8/formats/overlays")
async def put_overlay(project_name: str, overlay: OverlayConstraintSet, user: CurrentUser) -> OverlayConstraintSet:
    async def operation() -> OverlayConstraintSet:
        async with async_session_factory() as session:
            stored = await FormatRepository(session).put_overlay(
                user_id=user.id, project_name=project_name, overlay=overlay
            )
            await session.commit()
            return stored

    return await _run(operation)


@router.post("/projects/{project_name}/m8/formats/plans")
async def create_plan(project_name: str, req: CreatePlanRequest, user: CurrentUser) -> FormatProjectionPlan:
    async def operation() -> FormatProjectionPlan:
        async with async_session_factory() as session:
            plan = await plan_from_master(
                session,
                user_id=user.id,
                project_name=project_name,
                project_dir=_project_dir(project_name),
                plan_id=req.plan_id,
                source_artifact_key=req.source_artifact_key,
                profile_ref=req.profile_ref,
                constraint_ref=req.constraint_ref,
                kind=req.kind,
                focal=None if req.focal is None else req.focal.box(),
                subject=req.subject.box(),
                captions=tuple(caption.box() for caption in req.captions),
                rationale=req.rationale,
            )
            await session.commit()
            return plan

    return await _run(operation)


@router.get("/projects/{project_name}/m8/formats/plans")
async def list_plans(project_name: str, user: CurrentUser) -> list[PlanSummary]:
    async def operation() -> list[PlanSummary]:
        async with async_session_factory() as session:
            scope = (FormatPlanModel.user_id == user.id, FormatPlanModel.project_name == project_name)
            plans = (
                await session.scalars(select(FormatPlanModel).where(*scope).order_by(FormatPlanModel.created_at.desc()))
            ).all()
            summaries = []
            for row in plans:
                renders = (
                    await session.scalars(
                        select(FormatRenderModel)
                        .where(
                            FormatRenderModel.user_id == user.id,
                            FormatRenderModel.project_name == project_name,
                            FormatRenderModel.plan_id == row.plan_id,
                        )
                        .order_by(FormatRenderModel.created_at.desc())
                    )
                ).all()
                latest = {}
                for model, contract in (
                    (FormatTechnicalReportModel, TechnicalValidationReport),
                    (FormatSemanticReportModel, SemanticParityReport),
                ):
                    report = await session.scalar(
                        select(model)
                        .where(
                            model.user_id == user.id, model.project_name == project_name, model.plan_id == row.plan_id
                        )
                        .order_by(model.sequence.desc())
                        .limit(1)
                    )
                    latest[model] = None if report is None else contract.model_validate(report.report_json)
                summaries.append(
                    PlanSummary(
                        plan=FormatProjectionPlan.model_validate(row.plan_json),
                        renders=tuple(
                            RenderView(
                                execution_id=render.execution_id,
                                plan_id=render.plan_id,
                                artifact_digest=render.artifact_digest,
                                replayed=False,
                            )
                            for render in renders
                        ),
                        technical=latest[FormatTechnicalReportModel],
                        semantic=latest[FormatSemanticReportModel],
                    )
                )
            return summaries

    return await _run(operation)


async def _source_of(user_id: str, project_name: str, plan_id: str):
    async with async_session_factory() as session:
        plan = await FormatRepository(session).get_plan(user_id=user_id, project_name=project_name, plan_id=plan_id)
        if plan is None:
            raise FormatNotFoundError("unknown format plan")
        artifact_key = plan.source_master_id.rpartition("@v")[0]
        _master, path = await master_source(
            session,
            user_id=user_id,
            project_name=project_name,
            project_dir=_project_dir(project_name),
            artifact_key=artifact_key,
        )
    return path


@router.post("/projects/{project_name}/m8/formats/plans/{plan_id}/renders")
async def render(project_name: str, plan_id: str, req: RenderRequest, user: CurrentUser) -> RenderView:
    async def operation() -> RenderView:
        source = await _source_of(user.id, project_name, plan_id)
        result = await _render_service().render(
            user_id=user.id,
            project_name=project_name,
            project_dir=_project_dir(project_name),
            plan_id=plan_id,
            source=source,
            command_id=req.command_id,
        )
        return RenderView(
            execution_id=result.execution_id,
            plan_id=plan_id,
            artifact_digest=result.artifact_digest,
            replayed=result.replayed,
        )

    return await _run(operation)


async def _render_row(user_id: str, project_name: str, execution_id: str) -> FormatRenderModel:
    async with async_session_factory() as session:
        row = await session.get(FormatRenderModel, (user_id, project_name, execution_id))
    if row is None:
        raise FormatNotFoundError("no succeeded render with this execution id")
    return row


@router.post("/projects/{project_name}/m8/formats/renders/{execution_id}/validation")
async def validate(project_name: str, execution_id: str, user: CurrentUser) -> TechnicalValidationReport:
    async def operation() -> TechnicalValidationReport:
        row = await _render_row(user.id, project_name, execution_id)
        source = await _source_of(user.id, project_name, row.plan_id)
        return await FormatValidationService(async_session_factory).validate(
            user_id=user.id,
            project_name=project_name,
            project_dir=_project_dir(project_name),
            execution_id=execution_id,
            source=source,
        )

    return await _run(operation)


@router.post("/projects/{project_name}/m8/formats/renders/{execution_id}/review-packets")
async def open_review(project_name: str, execution_id: str, user: InteractiveUser) -> ReviewPacketView:
    async def operation() -> ReviewPacketView:
        row = await _render_row(user.id, project_name, execution_id)
        source = await _source_of(user.id, project_name, row.plan_id)
        project_dir = _project_dir(project_name)
        packet = await FormatReviewService(async_session_factory).open_packet(
            user_id=user.id,
            project_name=project_name,
            project_dir=project_dir,
            execution_id=execution_id,
            source_ref=source.resolve().relative_to(project_dir.resolve()).as_posix(),
            reviewer_id=user.sub,
        )
        return ReviewPacketView(packet_id=packet.packet_id, rubric_version=SEMANTIC_RUBRIC, items=SEMANTIC_ITEMS)

    return await _run(operation)


@router.get("/projects/{project_name}/m8/formats/review-packets/{packet_id}/clips/{label}")
async def review_clip(project_name: str, packet_id: str, label: str, user: InteractiveUser) -> FileResponse:
    async def operation() -> FileResponse:
        path = await FormatReviewService(async_session_factory).clip(
            user_id=user.id,
            project_name=project_name,
            project_dir=_project_dir(project_name),
            packet_id=packet_id,
            label=label,
            reviewer_id=user.sub,
        )
        return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "no-store"})

    return await _run(operation)


@router.post("/projects/{project_name}/m8/formats/review-packets/{packet_id}/reviews")
async def submit_review(
    project_name: str, packet_id: str, req: SubmitReviewRequest, user: InteractiveUser
) -> SemanticParityReport:
    async def operation() -> SemanticParityReport:
        return await FormatReviewService(async_session_factory).submit(
            user_id=user.id,
            project_name=project_name,
            packet_id=packet_id,
            reviewer_id=user.sub,
            items=dict(req.items),
            note=req.note,
        )

    return await _run(operation)


@router.post("/projects/{project_name}/m8/formats/renders/{execution_id}/candidate")
async def prepare_candidate(project_name: str, execution_id: str, user: CurrentUser) -> CandidateView:
    async def operation() -> CandidateView:
        async with async_session_factory() as session:
            prepared: PreparedFormatCandidate = await prepare_format_candidate(
                session,
                user_id=user.id,
                project_name=project_name,
                project_dir=_project_dir(project_name),
                execution_id=execution_id,
                author=user.id,
            )
            await session.commit()
        return CandidateView(**prepared.__dict__)

    return await _run(operation)


@router.post("/projects/{project_name}/m8/formats/previews")
async def preview_promotion(project_name: str, req: CreateFormatPreviewRequest, user: CurrentUser) -> FormatPreviewView:
    """Preview promoting a prepared candidate into its format slot; the digest is what an approval binds."""

    async def operation() -> FormatPreviewView:
        async with async_session_factory() as session:
            preview = await exploration_service(session).create_preview(
                user_id=user.id,
                project_name=project_name,
                candidate_id=req.candidate_id,
                revision=req.revision,
                target=PromotionTarget(
                    kind=PromotionTargetKind.ARTIFACT_SLOT,
                    target_ref=req.slot_key,
                    expected_target_version=req.expected_target_version,
                ),
                command_id=req.command_id,
            )
        return FormatPreviewView(preview=preview, preview_digest=digest_canonical(preview))

    return await _run(operation)


@router.post("/projects/{project_name}/m8/formats/promotions")
async def approve_promotion(
    project_name: str, req: ApproveFormatPromotionRequest, user: InteractiveUser
) -> PromotionReceipt:
    """A person approves the exact preview they saw; the server records them as the authorizing actor."""

    async def operation() -> PromotionReceipt:
        authorization = PromotionAuthorization(
            command_id=req.command_id,
            project_name=project_name,
            preview_id=req.preview_id,
            preview_digest=req.preview_digest,
            # M8-A binds the actor to the scope's user; the interactive session is the human gate.
            actor_id=user.id,
            actor_scope=user.id,
            decision="APPROVE",
            authorized_at=datetime.now(UTC),
        )
        async with async_session_factory() as session:
            return await exploration_promotion(session).promote(
                user_id=user.id,
                project_name=project_name,
                authorization=authorization,
                expected_candidate_head_version=req.expected_candidate_head_version,
            )

    return await _run(operation)
