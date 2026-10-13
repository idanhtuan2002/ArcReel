"""M8-C spatial API: derive frame receipts from approved video masters, then run one spatial analysis.

The user comes from the session and the project from the path. The vision call is the
``spatial_vision`` dependency: a Gemini text model resolved for ``SPATIAL_ANALYSIS``, whose
usage the ledger records. Each request either returns its result or writes nothing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import Field, StringConstraints

from lib.api_errors import ApiError, ConflictError, NotFoundError, ServiceUnavailableError, UnprocessableError
from lib.artifact_manifest import ArtifactKind, decode_artifact_key_parts
from lib.db import async_session_factory
from lib.db.repositories.spatial_source import _receipt_digest
from lib.project_manager import get_project_manager
from lib.providers import PROVIDER_GEMINI
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult, TextTaskType
from lib.text_backends.gemini import GeminiTextBackend
from lib.text_generator import TextGenerator
from r2.advanced_creative.errors import ExplorationNotFoundError, M8Error
from r2.contracts.advanced_creative import CandidateHead, LineageBinding, M8ContractModel
from r2.contracts.host_hardening import ProviderRouteSnapshot
from r2.host_hardening.master_resolver import MasterDivergedError
from r2.host_hardening.route_inventory import HOST_SPATIAL_ADAPTER_VERSION, SPATIAL_SUBMIT_FAMILIES
from server.auth import CurrentUser
from server.services.advanced_creative import episode_lineage
from server.services.execution_attempts import build_attempt_submitter
from server.services.master_authority import verify_masters
from server.services.spatial_execution import (
    SpatialExecutionCommand,
    SpatialExecutionService,
    SpatialExecutionUnavailableError,
    SpatialFrameRef,
    SpatialVisionCall,
    text_backend_spatial_vision,
)
from server.services.spatial_source import FrameDerivationService, FrameSourceConflictError

router = APIRouter()

SPATIAL_UNAVAILABLE = "m8_spatial_unavailable"
SPATIAL_SOURCE_CONFLICT = "m8_spatial_source_conflict"
SPATIAL_REQUEST_INVALID = "m8_spatial_request_invalid"

SceneName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
CommandId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


@dataclass(frozen=True)
class SpatialVision:
    """The route snapshot a spatial execution records, and the call that sends the two frames."""

    route: ProviderRouteSnapshot
    call: SpatialVisionCall


class LedgerVisionModel:
    """Sends the vision request through ``TextGenerator``: the ledger records its usage for the user
    and binds it to the M7 execution."""

    def __init__(self, generator: TextGenerator, *, project_name: str, user_id: str) -> None:
        self._generator = generator
        self._project_name = project_name
        self._user_id = user_id

    async def generate(self, request: TextGenerationRequest, *, execution_id: str) -> TextGenerationResult:
        return await self._generator.generate(
            request, self._project_name, user_id=self._user_id, execution_id=execution_id
        )


async def spatial_vision(project_name: str, user: CurrentUser) -> SpatialVision:
    """The configured Gemini vision model on the registered ``host-spatial-v1`` route."""
    try:
        generator = await TextGenerator.create(TextTaskType.SPATIAL_ANALYSIS, project_name)
    except (ValueError, LookupError) as error:
        raise ServiceUnavailableError(SPATIAL_UNAVAILABLE) from error
    backend = generator.backend
    if not isinstance(backend, GeminiTextBackend):
        raise ServiceUnavailableError(SPATIAL_UNAVAILABLE)
    family = SPATIAL_SUBMIT_FAMILIES[0]
    route = ProviderRouteSnapshot(
        provider_id=PROVIDER_GEMINI,
        provider_account_ref="default",
        provider_model_id=backend.model,
        backend_model_id=backend.model,
        endpoint_id=family.key.endpoint_id,
        submitted_base_url=backend.submitted_base_url,
        adapter_version=HOST_SPATIAL_ADAPTER_VERSION,
        capability_profile_ref=family.capability_profile_ref,
    )
    return SpatialVision(
        route=route,
        call=text_backend_spatial_vision(LedgerVisionModel(generator, project_name=project_name, user_id=user.id)),
    )


class DeriveFrameRequest(M8ContractModel):
    parent_artifact_key: str
    expected_master_version: int = Field(ge=1)
    decoded_frame_index: int = Field(ge=0)
    command_id: CommandId


class FrameReceiptResponse(M8ContractModel):
    receipt_id: str
    receipt_digest: str
    parent_artifact_key: str
    parent_master_version: int
    frame_content_digest: str


class SpatialSource(M8ContractModel):
    """One current approved episode-video master a frame can be derived from."""

    artifact_key: str
    shot_id: str
    master_version: int


class FrameRef(M8ContractModel):
    receipt_id: str
    receipt_digest: str


class ExecuteSpatialRequest(M8ContractModel):
    command_id: CommandId
    candidate_id: CommandId
    expected_head_version: int | None = Field(default=None, ge=1)
    episode: int = Field(ge=1)
    scene_name: SceneName
    master: FrameRef
    reverse: FrameRef


def _api_error(error: Exception) -> ApiError:
    if isinstance(error, ExplorationNotFoundError):
        return NotFoundError(error.code)
    if isinstance(error, M8Error):
        return ConflictError(error.code)
    if isinstance(error, SpatialExecutionUnavailableError):
        return ServiceUnavailableError(SPATIAL_UNAVAILABLE)
    if isinstance(error, FrameSourceConflictError):
        return ConflictError(SPATIAL_SOURCE_CONFLICT)
    return UnprocessableError(SPATIAL_REQUEST_INVALID)


async def _run[T](operation: Callable[[], Awaitable[T]]) -> T:
    try:
        return await operation()
    except (M8Error, SpatialExecutionUnavailableError, FrameSourceConflictError) as error:
        raise _api_error(error) from error
    except ValueError as error:
        raise _api_error(error) from error


@router.get("/projects/{project_name}/m8/spatial/sources")
async def list_sources(project_name: str, user: CurrentUser, episode: int = Query(ge=1)) -> list[SpatialSource]:
    """The episode's current approved video masters, verified against their projections."""
    project_dir = get_project_manager().get_project_path(project_name)
    try:
        async with async_session_factory() as session:
            heads = await verify_masters(session, user_id=user.id, project_name=project_name, project_dir=project_dir)
    except MasterDivergedError as error:
        raise ConflictError(SPATIAL_SOURCE_CONFLICT) from error
    sources: list[SpatialSource] = []
    for artifact_key, version, _candidate_id in heads:
        parts = decode_artifact_key_parts(artifact_key)
        if parts is None or parts.kind != ArtifactKind.EPISODE_VIDEO.value or parts.components[:1] != (episode,):
            continue
        sources.append(
            SpatialSource(artifact_key=artifact_key, shot_id=str(parts.components[1]), master_version=version)
        )
    return sorted(sources, key=lambda source: source.shot_id)


@router.post("/projects/{project_name}/m8/spatial/frames")
async def derive_frame(project_name: str, req: DeriveFrameRequest, user: CurrentUser) -> FrameReceiptResponse:
    """Decode one frame of the current approved video master into an immutable frame receipt."""

    async def operation() -> FrameReceiptResponse:
        service = FrameDerivationService(
            session_factory=async_session_factory,
            project_dir=get_project_manager().get_project_path(project_name),
        )
        receipt = await service.derive(
            user_id=user.id,
            project_name=project_name,
            parent_artifact_key=req.parent_artifact_key,
            expected_master_version=req.expected_master_version,
            decoded_frame_index=req.decoded_frame_index,
            command_id=req.command_id,
        )
        return FrameReceiptResponse(
            receipt_id=receipt.frame_candidate_id,
            receipt_digest=_receipt_digest(receipt),
            parent_artifact_key=receipt.identity.parent_artifact_key,
            parent_master_version=receipt.identity.parent_master_version,
            frame_content_digest=receipt.identity.frame_content_digest,
        )

    return await _run(operation)


@router.post("/projects/{project_name}/m8/spatial/executions")
async def execute_spatial(
    project_name: str,
    req: ExecuteSpatialRequest,
    user: CurrentUser,
    vision: Annotated[SpatialVision, Depends(spatial_vision)],
) -> CandidateHead:
    """Analyze a MASTER and a REVERSE frame into one evidence-bound spatial candidate revision."""

    async def operation() -> CandidateHead:
        projects = get_project_manager()
        await episode_lineage(projects, project_name, req.episode)

        async def lineage_for(name: str, episode: int) -> LineageBinding:
            return await episode_lineage(projects, name, episode)

        service = SpatialExecutionService(
            session_factory=async_session_factory,
            project_dir=projects.get_project_path(project_name),
            route=vision.route,
            vision=vision.call,
            submitter_for=lambda session, user_id, name: build_attempt_submitter(
                session, user_id=user_id, project_name=name, usage_binder=None
            ),
            lineage_for=lineage_for,
        )
        return await service.execute(
            SpatialExecutionCommand(
                user_id=user.id,
                project_name=project_name,
                command_id=req.command_id,
                candidate_id=req.candidate_id,
                expected_head_version=req.expected_head_version,
                episode=req.episode,
                scene_name=req.scene_name,
                master=SpatialFrameRef(receipt_id=req.master.receipt_id, receipt_digest=req.master.receipt_digest),
                reverse=SpatialFrameRef(receipt_id=req.reverse.receipt_id, receipt_digest=req.reverse.receipt_digest),
            )
        )

    return await _run(operation)


__all__ = ["LedgerVisionModel", "SpatialVision", "router", "spatial_vision"]
