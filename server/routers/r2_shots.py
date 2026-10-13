"""R2 shot generation: queue one admitted spatial shot with its exact, immutable submit identity.

The request carries only the command ID, the expected target and binding snapshot versions and
the execution profile; the server derives the prompt, the captured provider payload and the M7
host request. An exact replay returns the same task; a changed request under the same command
conflicts.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import Field, StringConstraints

from lib.api_errors import ConflictError
from lib.db import async_session_factory
from lib.db.repositories.production_binding import ProductionBindingIntegrityError
from lib.generation_queue import R2_SHOT_GENERATION_TASK_TYPE, get_generation_queue
from lib.project_manager import get_project_manager
from lib.video_backends.dashscope import DashScopeVideoBackend
from r2.contracts.common import R2ContractModel, ensure_json_value
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.shot_generation import R2ExecutionProfileV1, R2ShotGenerationTaskV1
from r2.production_intelligence.shot_identity import shot_task_id
from server.auth import CurrentUser
from server.services.location_binding import BindingSourceConflictError
from server.services.r2_shot_generation import (
    R2ShotAdmissionRefused,
    R2ShotCommand,
    configured_payload_builder,
    derive_shot_admission,
)

router = APIRouter()

ADMISSION_REFUSED = "r2_shot_admission_refused"
AUTHORITY_STALE = "r2_shot_authority_stale"
COMMAND_CONFLICT = "r2_shot_command_conflict"

CommandId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class GenerateShotRequest(R2ContractModel):
    command_id: CommandId
    expected_target_registry_version: int = Field(ge=1)
    expected_binding_snapshot_digest: Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
    execution_profile_ref: CommandId


class GenerateShotResponse(R2ContractModel):
    task_id: str
    target_registry_version: int
    binding_snapshot_digest: str
    host_request_digest: str


PayloadBuilderFactory = Callable[[R2ExecutionProfileV1], Awaitable[DashScopeVideoBackend]]


def payload_builder() -> PayloadBuilderFactory:
    """The factory that builds the profile's configured backend; tests replace this dependency."""
    return configured_payload_builder


def _command_digest(command: R2ShotCommand) -> str:
    body: dict[str, Any] = {
        "target_id": command.target_id,
        "expected_target_registry_version": command.expected_target_registry_version,
        "expected_binding_snapshot_digest": command.expected_binding_snapshot_digest,
        "execution_profile_ref": command.execution_profile_ref,
    }
    return "sha256:" + hashlib.sha256(canonical_json_bytes(ensure_json_value(body))).hexdigest()


def _response(evidence: R2ShotGenerationTaskV1) -> GenerateShotResponse:
    return GenerateShotResponse(
        task_id=evidence.task_id,
        target_registry_version=evidence.target_registry_version,
        binding_snapshot_digest=evidence.binding_snapshot_digest,
        host_request_digest=evidence.host_request_digest,
    )


def _same_request(evidence: R2ShotGenerationTaskV1, command: R2ShotCommand) -> bool:
    return (
        evidence.target_id == command.target_id
        and evidence.target_registry_version == command.expected_target_registry_version
        and evidence.binding_snapshot_digest == command.expected_binding_snapshot_digest
        and evidence.execution_profile_ref == command.execution_profile_ref
    )


@router.post("/projects/{project_name}/r2/shots/{target_id}/generate")
async def generate_shot(
    project_name: str,
    target_id: str,
    req: GenerateShotRequest,
    user: CurrentUser,
    builder_for: Annotated[PayloadBuilderFactory, Depends(payload_builder)],
) -> GenerateShotResponse:
    command = R2ShotCommand(
        user_id=user.id,
        project_name=project_name,
        target_id=target_id,
        command_id=req.command_id,
        expected_target_registry_version=req.expected_target_registry_version,
        expected_binding_snapshot_digest=req.expected_binding_snapshot_digest,
        execution_profile_ref=req.execution_profile_ref,
    )
    queue = get_generation_queue()
    existing = await queue.get_task(shot_task_id(user_id=user.id, project_name=project_name, command_id=req.command_id))
    if existing is not None:
        evidence = R2ShotGenerationTaskV1.model_validate(existing.get("payload") or {})
        if not _same_request(evidence, command):
            raise ConflictError(COMMAND_CONFLICT)
        return _response(evidence)

    try:
        admission = await derive_shot_admission(
            command,
            session_factory=async_session_factory,
            project_dir=get_project_manager().get_project_path(project_name),
            payload_builder_for=builder_for,
        )
    except R2ShotAdmissionRefused as error:
        raise ConflictError(ADMISSION_REFUSED).with_diagnostic(list(error.reasons) or [error.code]) from error
    except (ProductionBindingIntegrityError, BindingSourceConflictError) as error:
        raise ConflictError(AUTHORITY_STALE) from error
    evidence = admission.evidence
    queued = await queue.enqueue_task(
        project_name=project_name,
        task_type=R2_SHOT_GENERATION_TASK_TYPE,
        media_type="video",
        resource_id=target_id,
        resource_type="r2_shot",
        payload=evidence.model_dump(mode="json"),
        user_id=user.id,
        provider_id=admission.profile.provider_id,
        command_id=req.command_id,
        actor_scope=user.id,
        command_digest=_command_digest(command),
        task_id=evidence.task_id,
    )
    if queued["task_id"] != evidence.task_id:
        raise ConflictError(COMMAND_CONFLICT)
    return _response(evidence)


__all__ = ["payload_builder", "router"]
