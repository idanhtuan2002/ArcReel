"""Worker execution of an ``r2_shot_generation_v1`` task.

At claim the worker derives the admission again and requires the identical task evidence. The
``admit_and_plan_spatial_attempt`` transaction then re-reads and locks the binding snapshot, its
target and both source masters and frames, and stages the M7 ``PLANNED`` attempt with the exact
host request digest and route in the same commit. That commit is the currentness point: a head
change before it blocks planning; a change after it leaves the admitted attempt pinned to its
snapshot. The submit continues that preplanned attempt through ``AttemptSubmitter`` with the
captured provider payload; no database lock spans the provider call.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db import async_session_factory
from lib.db.base import utc_now
from lib.db.models.api_call import ApiCall
from lib.db.repositories.host_hardening import ExecutionAttemptRepository
from lib.ledger import Ledger
from lib.project_manager import get_project_manager
from lib.video_backends.base import ResumeEndpointChangedError, VideoGenerationRequest
from lib.video_backends.dashscope import DashScopeVideoBackend
from lib.video_backends.execution_adapter import host_video_route
from r2.contracts.host_hardening import (
    AttemptSnapshot,
    PlannedExecutionAttempt,
    ProviderIdempotencyMode,
    ProviderRouteSnapshot,
)
from r2.contracts.shot_generation import R2ExecutionProfileV1, R2ShotGenerationTaskV1
from r2.host_hardening.transitions import validate_exact_replay
from r2.production_intelligence.shot_identity import verify_task_evidence
from r2.production_intelligence.shot_profiles import PROFILES
from server.services.execution_attempts import build_attempt_submitter, capability_resolver
from server.services.location_binding_snapshot import CurrentLocationBindingSnapshotReader
from server.services.r2_shot_generation import (
    R2_SHOT_EVIDENCE_DIR,
    R2ShotAdmissionRefused,
    R2ShotCommand,
    configured_payload_builder,
    derive_shot_admission,
)
from server.services.r2_shot_output import seal_r2_shot_output

BackendFactory = Callable[[R2ExecutionProfileV1], Awaitable[DashScopeVideoBackend]]


def _command(evidence: R2ShotGenerationTaskV1) -> R2ShotCommand:
    return R2ShotCommand(
        user_id=evidence.user_id,
        project_name=evidence.project_name,
        target_id=evidence.target_id,
        command_id=evidence.command_id,
        expected_target_registry_version=evidence.target_registry_version,
        expected_binding_snapshot_digest=evidence.binding_snapshot_digest,
        execution_profile_ref=evidence.execution_profile_ref,
    )


async def admit_and_plan_spatial_attempt(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    project_dir: Path,
    evidence: R2ShotGenerationTaskV1,
    route: ProviderRouteSnapshot,
) -> AttemptSnapshot:
    """Recheck currentness under the shared lock order and stage the exact M7 attempt in one commit."""
    resolver = capability_resolver()
    async with session_factory() as session, session.begin():
        snapshot = await CurrentLocationBindingSnapshotReader(
            session_factory=session_factory, project_dir=project_dir
        ).read_in_session(
            session,
            user_id=evidence.user_id,
            project_name=evidence.project_name,
            target_id=evidence.target_id,
            expected_snapshot_digest=evidence.binding_snapshot_digest,
            require_approved_pair=True,
        )
        target = snapshot.body.target_versions[1]
        if (target.registry_version, target.version_digest) != (
            evidence.target_registry_version,
            evidence.target_digest,
        ):
            raise R2ShotAdmissionRefused("r2_shot_target_stale")
        repository = ExecutionAttemptRepository(session, capability_resolver=resolver)
        existing = await repository.get_for_task_attempt(
            user_id=evidence.user_id, project_name=evidence.project_name, task_id=evidence.task_id, attempt_no=1
        )
        capability = resolver(route.capability_profile_ref)
        execution_id = existing.execution_id if existing is not None else str(uuid.uuid4())
        planned = PlannedExecutionAttempt(
            execution_id=execution_id,
            task_id=evidence.task_id,
            attempt_no=1,
            request_digest=evidence.host_request_digest,
            route=route,
            client_token=execution_id if capability.idempotency_mode is ProviderIdempotencyMode.NATIVE_TOKEN else None,
            trace_id_at_creation=None,
            created_at=existing.created_at if existing is not None else utc_now(),
        )
        if existing is not None:
            validate_exact_replay(
                existing=existing,
                execution_id=planned.execution_id,
                request_digest=planned.request_digest,
                route=planned.route,
                client_token=planned.client_token,
                created_at=planned.created_at,
            )
            return existing
        return await repository.plan(user_id=evidence.user_id, project_name=evidence.project_name, attempt=planned)


async def execute_r2_shot_task(
    project_name: str,
    resource_id: str,
    payload: dict[str, Any],
    *,
    user_id: str,
    task_id: str | None,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    project_dir: Path | None = None,
    backend_for: BackendFactory = configured_payload_builder,
) -> dict[str, Any]:
    evidence = R2ShotGenerationTaskV1.model_validate(payload)
    if (evidence.task_id, evidence.user_id, evidence.project_name, evidence.target_id) != (
        task_id,
        user_id,
        project_name,
        resource_id,
    ):
        raise R2ShotAdmissionRefused("r2_shot_task_scope_mismatch")
    profile = PROFILES.get(evidence.execution_profile_ref)
    if profile is None:
        raise R2ShotAdmissionRefused("r2_shot_profile_unknown")
    verify_task_evidence(evidence, profile)
    root = project_dir or get_project_manager().get_project_path(project_name)
    backend = await backend_for(profile)

    async def same_backend(_profile: R2ExecutionProfileV1) -> DashScopeVideoBackend:
        return backend

    admission = await derive_shot_admission(
        _command(evidence), session_factory=session_factory, project_dir=root, payload_builder_for=same_backend
    )
    if admission.evidence != evidence:
        raise R2ShotAdmissionRefused("r2_shot_evidence_changed")
    route = host_video_route(
        provider_id=profile.provider_id,
        provider_model_id=profile.provider_model_id,
        backend_model_id=profile.backend_model_id,
        endpoint_id=profile.endpoint_id,
        submitted_base_url=backend.submitted_base_url,
    )
    await admit_and_plan_spatial_attempt(
        session_factory=session_factory, project_dir=root, evidence=evidence, route=route
    )

    request = admission.video_request
    ledger = Ledger(session_factory=session_factory)
    async with (
        session_factory() as attempt_session,
        ledger.record(
            project_name=project_name,
            call_type="video",
            model=profile.backend_model_id,
            provider=profile.provider_id,
            prompt=request.prompt[:500],
            resolution=profile.resolution,
            duration_seconds=profile.duration_seconds,
            aspect_ratio=profile.aspect_ratio,
            user_id=user_id,
        ) as call,
    ):
        request.attempt_submitter = build_attempt_submitter(
            attempt_session, user_id=user_id, project_name=project_name, usage_binder=ledger
        )
        request.api_call_id = call.call_id
        result = await backend.generate(request)
        call.success(result)
    output_digest = await seal_r2_shot_output(session_factory, evidence, Path(result.video_path))
    return {
        "r2_shot": {
            "task_id": evidence.task_id,
            "execution_id": request.execution_id,
            "host_request_digest": evidence.host_request_digest,
            "output_path": str(Path(result.video_path).relative_to(root)),
            "output_digest": output_digest,
        }
    }


async def _pending_call_id(
    session_factory: async_sessionmaker[AsyncSession], evidence: R2ShotGenerationTaskV1
) -> int | None:
    """The ledger call bound to this task's M7 execution, if the submit got that far."""
    async with session_factory() as session:
        attempt = await ExecutionAttemptRepository(
            session, capability_resolver=capability_resolver()
        ).get_for_task_attempt(
            user_id=evidence.user_id, project_name=evidence.project_name, task_id=evidence.task_id, attempt_no=1
        )
        if attempt is None:
            return None
        return await session.scalar(
            select(ApiCall.id).where(
                ApiCall.user_id == evidence.user_id,
                ApiCall.project_name == evidence.project_name,
                ApiCall.execution_id == attempt.execution_id,
            )
        )


async def resume_r2_shot_task(
    task: dict[str, Any],
    *,
    job_id: str,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    project_dir: Path | None = None,
    backend_for: BackendFactory = configured_payload_builder,
) -> dict[str, Any]:
    """Collect an already-submitted R2 shot job after a restart: poll and download only, never resubmit."""
    evidence = R2ShotGenerationTaskV1.model_validate(task.get("payload") or {})
    if (evidence.task_id, evidence.project_name) != (task.get("task_id"), task.get("project_name")):
        raise R2ShotAdmissionRefused("r2_shot_task_scope_mismatch")
    profile = PROFILES.get(evidence.execution_profile_ref)
    if profile is None:
        raise R2ShotAdmissionRefused("r2_shot_profile_unknown")
    verify_task_evidence(evidence, profile)
    root = project_dir or get_project_manager().get_project_path(evidence.project_name)
    backend = await backend_for(profile)
    submitted = task.get("submitted_base_url")
    if isinstance(submitted, str) and submitted and submitted != backend.submitted_base_url:
        raise ResumeEndpointChangedError(
            job_id=job_id,
            provider=profile.provider_id,
            submitted_endpoint=submitted,
            current_endpoint=backend.submitted_base_url,
        )
    request = VideoGenerationRequest(
        prompt="",
        output_path=root / R2_SHOT_EVIDENCE_DIR / evidence.task_id / "output.mp4",
        aspect_ratio=profile.aspect_ratio,
        duration_seconds=profile.duration_seconds,
        resolution=profile.resolution,
        project_name=evidence.project_name,
        task_id=evidence.task_id,
        submitted_base_url=submitted if isinstance(submitted, str) and submitted else None,
    )
    ledger = Ledger(session_factory=session_factory)
    call_id = await _pending_call_id(session_factory, evidence)
    try:
        result = await backend.resume_video(job_id, request)
    except Exception:
        if call_id is not None:
            await ledger.resume_failed(call_id=call_id)
        raise
    if call_id is not None:
        await ledger.resume_success(call_id=call_id, result=result)
    output_digest = await seal_r2_shot_output(session_factory, evidence, Path(result.video_path))
    return {
        "r2_shot": {
            "task_id": evidence.task_id,
            "provider_job_id": job_id,
            "host_request_digest": evidence.host_request_digest,
            "output_path": str(Path(result.video_path).relative_to(root)),
            "output_digest": output_digest,
        }
    }


__all__ = ["admit_and_plan_spatial_attempt", "execute_r2_shot_task", "resume_r2_shot_task"]
