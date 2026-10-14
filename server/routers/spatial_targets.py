"""M8-C Shot targets: register them from an admitted screenplay and read each one's workflow state.

The state is read through the same verified readers the write paths use. A reader that refuses reports
its step as ``stale`` (or ``none``); this route never repairs or writes authority.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import Field
from sqlalchemy import select

from lib.api_errors import ConflictError
from lib.artifact_manifest import ArtifactKey
from lib.db import async_session_factory
from lib.db.models.production_binding import ProductionBindingHeadModel
from lib.db.models.production_target import ProductionTargetHeadModel
from lib.db.models.task import Task
from lib.db.repositories.production_binding import ProductionBindingIntegrityError
from lib.db.repositories.production_target import ProductionTargetIntegrityError
from lib.generation_queue import R2_SHOT_GENERATION_TASK_TYPE
from lib.project_manager import get_project_manager
from r2.adaptation.errors import AdaptationError
from r2.contracts.adaptation import AdmittedScreenplayRef
from r2.contracts.advanced_creative import M8ContractModel
from r2.contracts.enums import ProductionBindingTarget
from r2.contracts.production import SceneSpec, ShotSpecV2
from r2.contracts.production_target import TargetRegistrationResult, TargetVersionRef
from r2.host_hardening.master_resolver import MasterDivergedError
from r2.production_binding.digests import scoped_location_binding_id
from r2.production_intelligence.director import DirectorRouteUnavailable
from r2.target_registry.resolver import TransactionBoundTargetAuthorityResolver
from r2.target_registry.service import RegisterTakeTargetsCommand, TakeTargetRegistrationService
from server.auth import CurrentUser
from server.services.governance_grants import CurrentShowrunnerGrantReader
from server.services.location_binding import BindingSourceConflictError
from server.services.location_binding_snapshot import CurrentLocationBindingSnapshotReader
from server.services.master_authority import verify_masters
from server.services.r2_shot_approval import R2_SHOT_EPISODE
from server.services.spatial_pair_current_v2 import CurrentApprovedSpatialPairReaderV2, SpatialPairV2UnavailableError
from server.services.spatial_source import FrameSourceConflictError

router = APIRouter()

TARGET_REGISTRATION_STALE = "m8_target_registration_stale"
_SNAPSHOT_REFUSALS = (
    ProductionBindingIntegrityError,
    ProductionTargetIntegrityError,
    BindingSourceConflictError,
    FrameSourceConflictError,
)


class RegisterTargetsRequest(M8ContractModel):
    command_id: str = Field(min_length=1, max_length=255)
    admitted_screenplay_ref: AdmittedScreenplayRef


class TargetBindingState(M8ContractModel):
    status: Literal["none", "stale", "current"]
    binding_id: str | None = None
    binding_version: int | None = None
    snapshot_digest: str | None = None
    target_registry_version: int | None = None
    has_spatial_set: bool = False


class PairViewState(M8ContractModel):
    role: Literal["MASTER", "REVERSE"]
    receipt_id: str
    receipt_digest: str


class TargetPairState(M8ContractModel):
    status: Literal["unavailable", "none", "approved"]
    binding_version: int | None = None
    views: tuple[PairViewState, ...] = ()


class TargetShotState(M8ContractModel):
    task_id: str
    status: str


class ShotTargetState(M8ContractModel):
    target_ref: TargetVersionRef
    purpose: str
    target_duration: float
    location_ref: str | None
    binding: TargetBindingState
    pair: TargetPairState
    shot: TargetShotState | None
    master_version: int | None


@router.post("/projects/{project_name}/m8/spatial/target-registrations")
async def register_targets(
    project_name: str, req: RegisterTargetsRequest, user: CurrentUser
) -> TargetRegistrationResult:
    """Register the Scene and Shot targets the admitted screenplay's Take derivation yields."""
    command = RegisterTakeTargetsCommand(
        user_id=user.id,
        project_name=project_name,
        principal=user.sub,
        command_id=req.command_id,
        admitted_screenplay_ref=req.admitted_screenplay_ref,
    )
    try:
        return await TakeTargetRegistrationService(async_session_factory).register(command)
    except (AdaptationError, DirectorRouteUnavailable, ValueError) as error:
        raise ConflictError(TARGET_REGISTRATION_STALE) from error


async def _shot_ids(user_id: str, project_name: str) -> list[str]:
    async with async_session_factory() as session:
        rows = await session.scalars(
            select(ProductionTargetHeadModel.target_id)
            .where(
                ProductionTargetHeadModel.user_id == user_id,
                ProductionTargetHeadModel.project_name == project_name,
                ProductionTargetHeadModel.target_type == ProductionBindingTarget.SHOT.value,
                ProductionTargetHeadModel.current_version.is_not(None),
            )
            .order_by(ProductionTargetHeadModel.target_id)
        )
        return list(rows)


async def _has_binding(user_id: str, project_name: str, target_id: str) -> bool:
    binding_id = scoped_location_binding_id(user_id=user_id, project_name=project_name, target_id=target_id)
    async with async_session_factory() as session:
        found = await session.scalar(
            select(ProductionBindingHeadModel.binding_id).where(
                ProductionBindingHeadModel.user_id == user_id,
                ProductionBindingHeadModel.project_name == project_name,
                ProductionBindingHeadModel.binding_id == binding_id,
            )
        )
    return found is not None


async def _binding(reader: CurrentLocationBindingSnapshotReader, user_id: str, project_name: str, target_id: str):
    try:
        snapshot = await reader.read_current(user_id=user_id, project_name=project_name, target_id=target_id)
    except _SNAPSHOT_REFUSALS:
        # A Shot with no binding yet is refused like a broken one; the binding head tells them apart.
        return TargetBindingState(status="stale" if await _has_binding(user_id, project_name, target_id) else "none")
    location = snapshot.body.ordered_bindings[0]
    return TargetBindingState(
        status="current",
        binding_id=location.binding_id,
        binding_version=location.version,
        snapshot_digest=snapshot.digest,
        target_registry_version=snapshot.body.target_versions[1].registry_version,
        has_spatial_set=snapshot.spatial_set is not None,
    )


async def _pair(
    grants: CurrentShowrunnerGrantReader | None, project_dir, user_id: str, project_name: str, target_id: str
) -> TargetPairState:
    if grants is None:
        return TargetPairState(status="unavailable")
    reader = CurrentApprovedSpatialPairReaderV2(
        session_factory=async_session_factory, project_dir=project_dir, grants=grants
    )
    try:
        current = await reader.read_current(user_id=user_id, project_name=project_name, target_id=target_id)
    except (SpatialPairV2UnavailableError, PermissionError, ValueError):
        return TargetPairState(status="none")
    command = current.body.command
    return TargetPairState(
        status="approved",
        binding_version=command.expected_binding_version,
        views=tuple(
            PairViewState(role=view.role, receipt_id=view.receipt_id, receipt_digest=view.receipt_digest)
            for view in command.views
        ),
    )


async def _latest_shot(user_id: str, project_name: str, target_id: str) -> TargetShotState | None:
    async with async_session_factory() as session:
        task = await session.scalar(
            select(Task)
            .where(
                Task.user_id == user_id,
                Task.project_name == project_name,
                Task.task_type == R2_SHOT_GENERATION_TASK_TYPE,
                Task.resource_id == target_id,
            )
            .order_by(Task.queued_at.desc())
            .limit(1)
        )
    return None if task is None else TargetShotState(task_id=task.task_id, status=task.status)


async def _master_version(user_id: str, project_name: str, project_dir, target_id: str) -> int | None:
    key = ArtifactKey.episode_video(R2_SHOT_EPISODE, target_id).encode()
    try:
        async with async_session_factory() as session:
            heads = await verify_masters(
                session, user_id=user_id, project_name=project_name, project_dir=project_dir, artifact_keys=[key]
            )
    except MasterDivergedError:
        return None
    return next((version for artifact_key, version, _candidate in heads if artifact_key == key), None)


@router.get("/projects/{project_name}/m8/spatial/targets")
async def list_targets(project_name: str, user: CurrentUser, request: Request) -> list[ShotTargetState]:
    """Every current Shot target with its binding, pair, latest shot task and approved master."""
    project_dir = get_project_manager().get_project_path(project_name)
    grants: CurrentShowrunnerGrantReader | None = getattr(request.app.state, "governance_grants", None)
    snapshots = CurrentLocationBindingSnapshotReader(session_factory=async_session_factory, project_dir=project_dir)
    states: list[ShotTargetState] = []
    for target_id in await _shot_ids(user.id, project_name):
        try:
            async with async_session_factory() as session:
                current = await TransactionBoundTargetAuthorityResolver(session).resolve_current(
                    user_id=user.id,
                    project_name=project_name,
                    target_type=ProductionBindingTarget.SHOT,
                    target_id=target_id,
                )
        except (ProductionTargetIntegrityError, AdaptationError):
            continue
        if current is None or not isinstance(current.target, ShotSpecV2):
            continue
        scene = current.scene.target if current.scene is not None else None
        states.append(
            ShotTargetState(
                target_ref=current.ref,
                purpose=current.target.purpose,
                target_duration=current.target.target_duration,
                location_ref=scene.location_ref if isinstance(scene, SceneSpec) else None,
                binding=await _binding(snapshots, user.id, project_name, target_id),
                pair=await _pair(grants, project_dir, user.id, project_name, target_id),
                shot=await _latest_shot(user.id, project_name, target_id),
                master_version=await _master_version(user.id, project_name, project_dir, target_id),
            )
        )
    return states


__all__ = ["router"]
