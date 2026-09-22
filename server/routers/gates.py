"""ADR-0089's four mandatory Human Gates (A-D) -- the real operator-control
surface P1 backlog item 6 adds (docs/superpowers/specs/2026-09-22-r2-p1-gate-receipt-surface-design.md).

Every endpoint requires the host's own session-JWT authentication
(``CurrentUser``, registered at the router level in server/app.py, exactly
like every other authenticated router) -- ``authenticated_principal`` is
always derived from the verified session, never caller-supplied, so an
operator cannot approve a gate as someone else.

Gate B and Gate C are thin wrappers over their existing, unmodified real
mechanisms (``AdaptationAuthorityService``, ``ProductionApprovalService``);
neither gate's own request/command shape is simplified here, because no
lighter-weight "pending items to review" read-model exists yet for either
(a real, disclosed limitation -- see the P1 evidence file). Gate C's file
path is validated to stay inside the project's own ``production/`` directory
before anything touches disk.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from lib.async_thread import run_noninterruptible_sync
from lib.db import async_session_factory
from lib.db.adaptation_uow import adaptation_uow_factory
from lib.db.repositories.gates import FinalCutReceiptRepository, GreenlightRepository, PublishApprovalRepository
from lib.project_manager import get_project_manager
from r2.adaptation.authority import AdaptationAuthorityService
from r2.adaptation.session_authority import SessionAuthenticatedShowrunnerAuthority
from r2.contracts.adaptation import ScreenplayAdmissionCommand
from r2.contracts.content_basis import ContentBasis
from r2.contracts.enums import ProductionMethod
from r2.contracts.gates import FinalCutReceipt, GateAuthorization, GreenlightDecision, PublishApprovalDecision
from r2.m3.host_integration import GoldenAHostIntegration
from r2.m3.render_plan import RenderedCutAsset
from r2.production.artifact_metadata import DependencySnapshot
from server.auth import CurrentUser

router = APIRouter()


class GreenlightRequest(BaseModel):
    source_digest: str
    action: Literal["GREENLIGHT", "REVOKE"]


class PublishApprovalRequest(BaseModel):
    deliverable_digest: str
    platform: str
    visibility: str
    action: Literal["APPROVE_PUBLISH", "REVOKE"]


class FinalCutRenderedAssetRequest(BaseModel):
    """Mirrors ``RenderedCutAsset`` exactly except ``path``, which is a
    project-relative path validated against path escape before use --
    accepting a raw filesystem path from an HTTP request body is a real
    security surface, not just a convenience."""

    method: ProductionMethod
    relative_path: str
    sha256: str
    duration_seconds: float
    execution_fingerprint: str
    tool: Literal["remotion"]
    tool_version: str
    wall_time_seconds: float
    external_provider_cost: Decimal
    source_master_refs: tuple[str, ...] = ()


class FinalCutApprovalRequest(BaseModel):
    resource_type: str
    episode: int
    target_ref: str
    content_fingerprint: str
    content_basis: ContentBasis
    direct_dependencies: list[DependencySnapshot]
    contract_version: int
    contract_schema_version: str
    produced: FinalCutRenderedAssetRequest
    approval_record: str


def _authorization(user: CurrentUser) -> GateAuthorization:
    return GateAuthorization(
        authenticated_principal=user.sub, authority_role="HUMAN_OPERATOR", authorized_at=datetime.now(UTC)
    )


@router.post("/projects/{project_name}/gates/greenlight")
async def greenlight_project(project_name: str, req: GreenlightRequest, user: CurrentUser) -> dict[str, object]:
    decision = GreenlightDecision(
        decision_id=str(uuid.uuid4()),
        user_id=user.id,
        project_name=project_name,
        source_digest=req.source_digest,
        action=req.action,
        authorization=_authorization(user),
        sequence=1,  # ignored by append(); the repository assigns the real, race-safe value
        created_at=datetime.now(UTC),
    )
    async with async_session_factory() as session:
        await GreenlightRepository(session).append(decision)
        await session.commit()
        history = await GreenlightRepository(session).list_for_project(user_id=user.id, project_name=project_name)
    return history[-1].model_dump(mode="json")


@router.post("/projects/{project_name}/gates/narrative-lock")
async def narrative_lock(
    project_name: str, command: ScreenplayAdmissionCommand, user: CurrentUser
) -> dict[str, object]:
    if command.project_name != project_name:
        raise HTTPException(status_code=400, detail="command.project_name does not match the URL path")
    # Confirmed false positive: this is the exact same construction already used throughout
    # tests/integration/r2/adaptation/conftest.py with an identical async_sessionmaker[AsyncSession] type
    # (verified via reveal_type in a minimal repro) -- basedpyright only flags it when async_session_factory
    # is imported from lib.db specifically, not when an equivalent value comes from a local test fixture.
    uow_factory = adaptation_uow_factory(async_session_factory)
    service = AdaptationAuthorityService(uow_factory, SessionAuthenticatedShowrunnerAuthority())  # pyright: ignore[reportArgumentType]
    receipt = await service.admit_screenplay_for_direction(command, authenticated_principal=user.sub)
    return receipt.model_dump(mode="json")


@router.post("/projects/{project_name}/gates/final-cut")
async def final_cut_approval(project_name: str, req: FinalCutApprovalRequest, user: CurrentUser) -> dict[str, object]:
    project_dir = get_project_manager().get_project_path(project_name)
    production_root = (project_dir / "production").resolve()
    candidate_path = (production_root / req.produced.relative_path).resolve()
    if production_root not in candidate_path.parents:
        raise HTTPException(
            status_code=400, detail="produced.relative_path escapes the project's production/ directory"
        )
    if not candidate_path.is_file():
        raise HTTPException(status_code=404, detail=f"no rendered file at {req.produced.relative_path!r}")

    produced = RenderedCutAsset(
        target_ref=req.target_ref,
        method=req.produced.method,
        path=candidate_path,
        sha256=req.produced.sha256,
        duration_seconds=req.produced.duration_seconds,
        execution_fingerprint=req.produced.execution_fingerprint,
        tool=req.produced.tool,
        tool_version=req.produced.tool_version,
        wall_time_seconds=req.produced.wall_time_seconds,
        external_provider_cost=req.produced.external_provider_cost,
        source_master_refs=req.produced.source_master_refs,
    )

    host = GoldenAHostIntegration(project_dir, resource_type=req.resource_type, episode=req.episode)

    def _stage_and_approve():
        registered = host.stage_candidate(
            target_ref=req.target_ref,
            content_fingerprint=req.content_fingerprint,
            produced=produced,
            content_basis=req.content_basis,
            direct_dependencies=req.direct_dependencies,
            contract_version=req.contract_version,
            contract_schema_version=req.contract_schema_version,
        )
        return host.approve(
            registered,
            approval_record=req.approval_record,
            selected_by=user.sub,
            selected_at=datetime.now(UTC),
        )

    approved_master = await run_noninterruptible_sync(_stage_and_approve)

    receipt = FinalCutReceipt(
        user_id=user.id,
        project_name=project_name,
        artifact_key=host.artifact_key_for(req.target_ref),
        selected_candidate_id=approved_master.selected_candidate_id,
        content_fingerprint=req.content_fingerprint,
        approval_record=req.approval_record,
        selected_by=user.sub,
        selected_at=approved_master.selected_at,
        sequence=1,  # ignored by append(); the repository assigns the real, race-safe value
    )
    async with async_session_factory() as session:
        await FinalCutReceiptRepository(session).append(receipt)
        await session.commit()

    return {"approved_master": approved_master.model_dump(mode="json"), "receipt": receipt.model_dump(mode="json")}


@router.post("/projects/{project_name}/gates/publish-approval")
async def publish_approval(project_name: str, req: PublishApprovalRequest, user: CurrentUser) -> dict[str, object]:
    decision = PublishApprovalDecision(
        decision_id=str(uuid.uuid4()),
        user_id=user.id,
        project_name=project_name,
        deliverable_digest=req.deliverable_digest,
        platform=req.platform,
        visibility=req.visibility,
        action=req.action,
        authorization=_authorization(user),
        sequence=1,  # ignored by append(); the repository assigns the real, race-safe value
        created_at=datetime.now(UTC),
    )
    async with async_session_factory() as session:
        await PublishApprovalRepository(session).append(decision)
        await session.commit()
        history = await PublishApprovalRepository(session).list_for_project(user_id=user.id, project_name=project_name)
    return history[-1].model_dump(mode="json")


@router.get("/projects/{project_name}/gates")
async def gate_history(project_name: str, user: CurrentUser) -> dict[str, object]:
    """Greenlight (A) and Publish Approval (D) full history, from this
    closure's own new tables. Narrative Lock (B) and Final Cut (C) already
    have their own real, tested query services
    (``AdaptationEvidenceService``, the host's artifact manifest) -- this
    endpoint deliberately does not duplicate a second read path for them
    (design section 6's reasoning against a unified mechanism applies to
    reads too), so their history is not included here. A real, disclosed
    limitation -- see the P1 evidence file."""
    async with async_session_factory() as session:
        greenlight_history = await GreenlightRepository(session).list_for_project(
            user_id=user.id, project_name=project_name
        )
        publish_history = await PublishApprovalRepository(session).list_for_project(
            user_id=user.id, project_name=project_name
        )
    return {
        "greenlight": [d.model_dump(mode="json") for d in greenlight_history],
        "publish_approval": [d.model_dump(mode="json") for d in publish_history],
    }


__all__ = ["router"]
