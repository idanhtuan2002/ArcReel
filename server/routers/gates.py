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

import hashlib
import uuid
from collections.abc import Collection, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import BinaryIO, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from lib.async_thread import run_noninterruptible_sync
from lib.candidate_store import CandidateStoreError
from lib.db import async_session_factory
from lib.db.adaptation_uow import adaptation_uow_factory
from lib.db.base import DEFAULT_USER_ID
from lib.db.repositories.gates import (
    FinalCutReceiptRepository,
    GateSequenceConflictError,
    GreenlightRepository,
    PublishApprovalRepository,
    ScriptLockRepository,
)
from lib.db.repositories.host_hardening import CandidateIdentityConflictError, MasterHeadConflictError
from lib.project_manager import get_project_manager
from r2.adaptation.authority import AdaptationAuthorityService
from r2.adaptation.session_authority import SessionAuthenticatedShowrunnerAuthority
from r2.contracts.adaptation import ScreenplayAdmissionCommand
from r2.contracts.content_basis import ContentBasis
from r2.contracts.enums import ProductionMethod
from r2.contracts.gates import (
    FinalCutReceipt,
    GateAuthorization,
    GreenlightDecision,
    PublishApprovalDecision,
    ScriptLockDecision,
)
from r2.host_hardening.master_authority import CandidateObjectConflictError, MasterDivergedError, m7_candidate_id
from r2.host_hardening.promotion import (
    CandidateArtifactMismatchError,
    PromotionExpectedVersionConflictError,
    PromotionReceiptReplayMismatchError,
)
from r2.m3.deliverables import (
    COMPOSITE_CONTRACT_TYPE,
    SourceMasterMismatchError,
    audio_decision_holds,
    composite_dependencies,
    current_deliverables,
    exportable_deliverable,
    normalize_sha256,
    sha256_file,
    verified_export_snapshot,
    write_export_copy,
)
from r2.m3.host_integration import GoldenAHostIntegration, StagedOperationConflictError, validate_m3_target_ref
from r2.m3.render_plan import RenderedCutAsset
from r2.production.artifact_metadata import DependencySnapshot
from server.auth import DOWNLOAD_TOKEN_EXPIRY_SECONDS, CurrentUser, create_download_token, verify_download_token
from server.services.master_authority import (
    MasterSupersededError,
    master_authority_unit,
    project_if_current,
    serialized_artifact,
    verify_masters,
)

router = APIRouter()
# Token-authenticated like the project ZIP export (ADR-0071): registered without the session dependency.
self_auth_router = APIRouter()


class GreenlightRequest(BaseModel):
    source_digest: str
    action: Literal["GREENLIGHT", "REVOKE"]


_SHA256_DIGEST = r"^sha256:[0-9a-f]{64}$"


class ScriptLockRequest(BaseModel):
    source_digest: str = Field(pattern=_SHA256_DIGEST)
    script_digest: str = Field(pattern=_SHA256_DIGEST)
    action: Literal["LOCK", "REVOKE"]


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
    tool: Literal["remotion", "ffmpeg"]
    tool_version: str
    wall_time_seconds: float
    external_provider_cost: Decimal
    source_master_refs: tuple[str, ...] = ()


class FinalCutApprovalRequest(BaseModel):
    resource_type: Literal["videos"]
    episode: int
    target_ref: str
    content_fingerprint: str
    content_basis: ContentBasis
    direct_dependencies: list[DependencySnapshot]
    contract_version: int
    contract_schema_version: str
    produced: FinalCutRenderedAssetRequest
    approval_record: str = Field(min_length=1)
    # Required for a COMPOSITE final and verified against its bytes (ADR-0092); shots send none.
    audio_decision: Literal["AUDIO", "MUTE"] | None = None

    @field_validator("target_ref")
    @classmethod
    def validate_target_ref(cls, value: str) -> str:
        return validate_m3_target_ref(value)


def _authorization(user: CurrentUser) -> GateAuthorization:
    return GateAuthorization(
        authenticated_principal=user.sub, authority_role="HUMAN_OPERATOR", authorized_at=datetime.now(UTC)
    )


class PostApprovalExportError(RuntimeError):
    """The selected master is durable, while its export copy still needs reconciliation."""


def _gate_c_retry_error(approval_record: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "GATE_C_RETRY_SAME_APPROVAL_RECORD",
            "approval_record": approval_record,
        },
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


@router.post("/projects/{project_name}/gates/script-lock")
async def script_lock(project_name: str, req: ScriptLockRequest, user: CurrentUser) -> dict[str, object]:
    """Gate B for a factual product (ADR-0092): lock the exact source and script revision."""
    decision = ScriptLockDecision(
        decision_id=str(uuid.uuid4()),
        user_id=user.id,
        project_name=project_name,
        source_digest=req.source_digest,
        script_digest=req.script_digest,
        action=req.action,
        authorization=_authorization(user),
        sequence=1,  # ignored by append(); the repository assigns the real, race-safe value
        created_at=datetime.now(UTC),
    )
    async with async_session_factory() as session:
        await ScriptLockRepository(session).append(decision)
        await session.commit()
        history = await ScriptLockRepository(session).list_for_project(user_id=user.id, project_name=project_name)
    return history[-1].model_dump(mode="json")


_MASTER_CONFLICTS = (
    CandidateArtifactMismatchError,
    CandidateIdentityConflictError,
    CandidateObjectConflictError,
    CandidateStoreError,
    MasterHeadConflictError,
    PromotionExpectedVersionConflictError,
    PromotionReceiptReplayMismatchError,
)


async def _require_consistent_masters(
    user_id: str, project_name: str, project_dir, artifact_keys: Collection[str] | None = None
) -> None:
    """Refuse a master-consuming request while a master it reads disagrees with its projection (ADR-0096)."""
    try:
        async with async_session_factory() as session:
            await verify_masters(
                session,
                user_id=user_id,
                project_name=project_name,
                project_dir=project_dir,
                artifact_keys=artifact_keys,
            )
    except MasterDivergedError as exc:
        raise HTTPException(status_code=409, detail=f"master_diverged: {exc}") from exc


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
    actual_sha256 = await run_noninterruptible_sync(lambda: sha256_file(candidate_path))
    if actual_sha256 != normalize_sha256(req.produced.sha256):
        raise HTTPException(status_code=400, detail="produced.sha256 does not match the rendered file")

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
    operation_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"gate-c/{user.id}/{project_name}/{req.episode}/{req.target_ref}/{req.approval_record}",
        )
    )
    # A request without an audio decision digests as it did before the field existed, so an
    # approval_record retry from before ADR-0092 still replays.
    request_digest = hashlib.sha256(
        req.model_dump_json(exclude={"audio_decision"} if req.audio_decision is None else None).encode()
    ).hexdigest()
    composite = req.produced.method is ProductionMethod.COMPOSITE
    if composite and req.direct_dependencies:
        raise HTTPException(
            status_code=400,
            detail="a COMPOSITE final's dependencies are derived from its source masters; send none",
        )
    if composite != (req.audio_decision is not None):
        raise HTTPException(
            status_code=400,
            detail="a COMPOSITE final needs audio_decision (AUDIO or MUTE); a shot approval sends none",
        )
    if composite:
        decision = req.audio_decision or ""
        try:
            holds = await run_noninterruptible_sync(lambda: audio_decision_holds(decision, candidate_path))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not holds:
            raise HTTPException(
                status_code=400,
                detail=f"audio_decision {decision} does not match the final's audio track",
            )

    if composite:
        # A composite reads its source shot masters, so those are the ones that must agree.
        source_keys = [
            host.artifact_key_for(ref.partition(":")[0])
            for ref in req.produced.source_master_refs
            if ref.partition(":")[0]
        ]
        await _require_consistent_masters(user.id, project_name, project_dir, source_keys)

    staged_dependencies: list[DependencySnapshot] = []

    def _stage():
        dependencies = (
            composite_dependencies(host, req.produced.source_master_refs) if composite else req.direct_dependencies
        )
        staged_dependencies[:] = list(dependencies)
        return host.stage_candidate(
            target_ref=req.target_ref,
            content_fingerprint=req.content_fingerprint,
            produced=produced,
            content_basis=req.content_basis,
            direct_dependencies=dependencies,
            contract_version=req.contract_version,
            contract_schema_version=req.contract_schema_version,
            contract_type=COMPOSITE_CONTRACT_TYPE if composite else "ShotSpec",
            operation_id=operation_id,
            request_digest=request_digest,
            keep_approved_semantic_state=True,
        )

    def _semantic_state():
        return host.semantic_state_for(
            target_ref=req.target_ref,
            content_fingerprint=req.content_fingerprint,
            content_basis=req.content_basis,
            direct_dependencies=staged_dependencies,
            contract_version=req.contract_version,
            contract_schema_version=req.contract_schema_version,
            contract_type=COMPOSITE_CONTRACT_TYPE if composite else "ShotSpec",
        )

    def _project_and_export(registered):
        # The candidate's semantic state and its approved master land in one manifest update.
        approved = host.approve(
            registered,
            approval_record=req.approval_record,
            selected_by=user.sub,
            selected_at=datetime.now(UTC),
            semantic_state=_semantic_state(),
        )
        try:
            export = write_export_copy(host, req.target_ref) if composite else None
        except Exception as exc:
            raise PostApprovalExportError("approved final requires export reconciliation") from exc
        return approved, export

    async def _stage_and_promote(session):
        try:
            registered = await run_noninterruptible_sync(_stage)
        except SourceMasterMismatchError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StagedOperationConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        # Every check the projection makes runs first, against the staged output.
        def _approvable_version():
            host.check_approvable(registered, _semantic_state())
            return host.staged_version(req.target_ref, registered.host_version_ref)

        try:
            version_file, staged_digest = await run_noninterruptible_sync(_approvable_version)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=f"master_conflict: {exc}") from exc
        try:
            await master_authority_unit(session, defer_commit=True).promote_staged(
                user_id=user.id,
                project_name=project_name,
                project_dir=project_root,
                artifact_key=registered.artifact_key,
                generation_candidate_id=registered.candidate.id,
                version_file=version_file,
                expected_content_digest=staged_digest,
                approval_record=req.approval_record,
                command_id=operation_id,
            )
        except _MASTER_CONFLICTS as exc:
            raise HTTPException(status_code=409, detail=f"master_conflict: {exc}") from exc
        return registered

    project_root = await run_noninterruptible_sync(project_dir.resolve)
    artifact_key = host.artifact_key_for(req.target_ref)
    # The database master head is the authority (ADR-0096). Phase 1 stages, checks and promotes in
    # one transaction under the artifact's row lock, and commits: files never run ahead of it.
    async with serialized_artifact(
        async_session_factory, user_id=user.id, project_name=project_name, artifact_key=artifact_key
    ) as session:
        registered = await _stage_and_promote(session)
    # Phase 2 projects and exports under the row lock again, only while this candidate is the head,
    # so an older approval can never overwrite a newer projection or export.
    try:
        async with async_session_factory() as session:
            approved_master, export = await project_if_current(
                session,
                user_id=user.id,
                project_name=project_name,
                artifact_key=artifact_key,
                candidate_id=m7_candidate_id(artifact_key, registered.candidate.id),
                project=lambda: run_noninterruptible_sync(lambda: _project_and_export(registered)),
            )
    except MasterSupersededError as exc:
        raise HTTPException(status_code=409, detail=f"master_superseded: {exc}") from exc
    except (PostApprovalExportError, KeyError, ValueError) as exc:
        # The head is committed; retrying the same approval_record projects and exports it.
        raise _gate_c_retry_error(req.approval_record) from exc

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
        audio_decision=req.audio_decision,
    )
    receipt_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"gate-c-receipt/{operation_id}"))
    try:
        async with async_session_factory() as session:
            repository = FinalCutReceiptRepository(session)
            stored_receipt = await repository.get_by_id(receipt_id)
            if stored_receipt is None:
                await repository.append(receipt, receipt_id=receipt_id)
                await session.commit()
                stored_receipt = await repository.get_by_id(receipt_id)
            if stored_receipt is None:
                raise RuntimeError("committed Final Cut receipt is not visible")
    except GateSequenceConflictError:
        async with async_session_factory() as session:
            stored_receipt = await FinalCutReceiptRepository(session).get_by_id(receipt_id)
        if stored_receipt is None:
            raise _gate_c_retry_error(req.approval_record) from None
    except Exception as exc:
        raise _gate_c_retry_error(req.approval_record) from exc
    if stored_receipt.model_dump(exclude={"sequence"}) != receipt.model_dump(exclude={"sequence"}):
        raise HTTPException(status_code=409, detail="approval_record is already bound to a different receipt")

    result: dict[str, object] = {
        "approved_master": approved_master.model_dump(mode="json"),
        "receipt": stored_receipt.model_dump(mode="json"),
    }
    if export is not None:
        result["export"] = {"relative_path": export.relative_path, "sha256": "sha256:" + export.sha256}
    return result


@router.post("/projects/{project_name}/gates/publish-approval")
async def publish_approval(project_name: str, req: PublishApprovalRequest, user: CurrentUser) -> dict[str, object]:
    if req.action == "APPROVE_PUBLISH":
        project_dir = get_project_manager().get_project_path(project_name)
        await _require_consistent_masters(user.id, project_name, project_dir)
        deliverable = await run_noninterruptible_sync(
            lambda: exportable_deliverable(project_dir, req.deliverable_digest)
        )
        if deliverable is None:
            raise HTTPException(
                status_code=409,
                detail="deliverable_digest is not the digest of a current Gate C-approved final and its export copy",
            )
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
        script_lock_history = await ScriptLockRepository(session).list_for_project(
            user_id=user.id, project_name=project_name
        )
    return {
        "greenlight": [d.model_dump(mode="json") for d in greenlight_history],
        "script_lock": [d.model_dump(mode="json") for d in script_lock_history],
        "publish_approval": [d.model_dump(mode="json") for d in publish_history],
    }


def _deliverable_view(project_dir) -> list[dict[str, object]]:
    return [
        {
            "episode": d.episode,
            "target_ref": d.target_ref,
            "sha256": "sha256:" + d.approved_sha256,
        }
        for d in current_deliverables(project_dir)
        if d.exportable and d.approved_sha256 is not None
    ]


@router.post("/projects/{project_name}/export/deliverable/token")
async def create_deliverable_token(project_name: str, user: CurrentUser) -> dict[str, object]:
    """Issue a short-lived download token and list the project's approved finals."""
    project_dir = get_project_manager().get_project_path(project_name)
    await _require_consistent_masters(user.id, project_name, project_dir)
    deliverables = await run_noninterruptible_sync(lambda: _deliverable_view(project_dir))
    return {
        "download_token": create_download_token(user.sub, project_name),
        "expires_in": DOWNLOAD_TOKEN_EXPIRY_SECONDS,
        "deliverables": deliverables,
    }


@self_auth_router.get("/projects/{project_name}/export/deliverable")
async def download_deliverable(
    project_name: str, download_token: str = Query(...), digest: str = Query(...)
) -> StreamingResponse:
    """Serve the export copy of the current approved final whose bytes hash to ``digest``."""
    import jwt as pyjwt

    try:
        verify_download_token(download_token, project_name)
    except pyjwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="download token expired") from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="download token does not match the project") from exc
    except pyjwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="download token invalid") from exc

    project_dir = get_project_manager().get_project_path(project_name)
    # The host resolves every authenticated subject to DEFAULT_USER_ID (server/auth.py), and the
    # database head may have moved since the token was issued.
    await _require_consistent_masters(DEFAULT_USER_ID, project_name, project_dir)
    result = await run_noninterruptible_sync(lambda: verified_export_snapshot(project_dir, digest))
    if result is None:
        raise HTTPException(status_code=404, detail="no current approved deliverable has this digest")
    deliverable, snapshot = result
    filename = f"ep{deliverable.episode}-{deliverable.target_ref}.mp4"
    return StreamingResponse(
        _snapshot_chunks(snapshot),
        media_type="video/mp4",
        headers={
            "X-Content-SHA256": "sha256:" + str(deliverable.approved_sha256),
            "Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}",
        },
    )


def _snapshot_chunks(snapshot: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := snapshot.read(1024 * 1024):
            yield chunk
    finally:
        snapshot.close()


__all__ = ["router", "self_auth_router"]
