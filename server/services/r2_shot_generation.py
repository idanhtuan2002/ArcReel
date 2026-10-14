"""Admit one Take-derived spatial shot to an R2 execution profile and derive its exact submit identity.

``derive_shot_admission`` reads the current target, its LOCATION binding snapshot with the
spatial set, and both frames; it builds the prompt plan, the compiled M4 request, the provider
prompt, the captured provider payload and the M7 host request, then the task evidence. The route
persists that evidence; the worker derives it again and requires it to be identical.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.api_errors import ServiceUnavailableError
from lib.backend_assembly import assemble_backend
from lib.config.resolver import ConfigResolver
from lib.db import async_session_factory
from lib.video_backends.base import VideoGenerationRequest
from lib.video_backends.dashscope import DashScopeVideoBackend
from lib.video_backends.execution_adapter import build_host_video_request, provider_payload_digest
from r2.contracts import (
    CapabilityDescriptor,
    ExecutionDecision,
    ExecutionIdentityStability,
    ExecutionType,
    MethodDecision,
    ProductionMethod,
    PromptPlan,
    Provenance,
    ProvenanceActor,
    ProviderRequest,
    ResolvedIdentityStatus,
    ResolvedVisualIdentity,
)
from r2.contracts.enums import ProductionBindingTarget
from r2.contracts.production import ShotSpecV2
from r2.contracts.shot_generation import R2ExecutionProfileV1, R2ShotGenerationTaskV1, R2ShotSourceFrameV1
from r2.production_binding.spatial_set import spatial_constraint_set_digest
from r2.production_intelligence.prompting import DefaultPromptCompiler, PromptPlanner
from r2.production_intelligence.shot_identity import (
    compiled_request_digest,
    host_request_digest,
    prompt_plan_digest,
    shot_task_id,
    submit_fingerprint,
)
from r2.production_intelligence.shot_profiles import (
    PROFILES,
    SPATIAL_PROMPT_PROJECTION_VERSION,
    admission_refusals,
    project_spatial_prompt,
    prompt_digest,
)
from r2.production_intelligence.spatial_constraints import apply_spatial_constraints
from r2.target_registry.resolver import TransactionBoundTargetAuthorityResolver
from server.services.location_binding_snapshot import CurrentLocationBindingSnapshotReader
from server.services.spatial_frame_reader import SpatialFrameReader

R2_SHOT_EVIDENCE_DIR = Path("r2") / "shot_tasks"
BACKEND_UNAVAILABLE = "r2_shot_backend_unavailable"
_FIXED_PROVENANCE = Provenance(created_by=ProvenanceActor.SYSTEM, created_at=datetime(2026, 10, 13, tzinfo=UTC))


class ShotPayloadBuilder(Protocol):
    @property
    def model(self) -> str: ...

    def build_submit_payload(self, request: VideoGenerationRequest) -> dict[str, Any]: ...


class R2ShotAdmissionRefused(ValueError):
    """The shot cannot run on the requested profile, or its authority changed."""

    def __init__(self, code: str, reasons: tuple[str, ...] = ()) -> None:
        super().__init__(code if not reasons else f"{code}: {', '.join(reasons)}")
        self.code = code
        self.reasons = reasons


@dataclass(frozen=True)
class R2ShotCommand:
    user_id: str
    project_name: str
    target_id: str
    command_id: str
    expected_target_registry_version: int
    expected_binding_snapshot_digest: str
    execution_profile_ref: str


@dataclass(frozen=True)
class R2ShotAdmission:
    evidence: R2ShotGenerationTaskV1
    profile: R2ExecutionProfileV1
    video_request: VideoGenerationRequest
    host_request: ProviderRequest


async def configured_payload_builder(profile: R2ExecutionProfileV1) -> DashScopeVideoBackend:
    """The configured backend for the profile route; release mode refuses an unqualified route here."""
    try:
        backend = await assemble_backend(
            provider_id=profile.provider_id,
            media_type="video",
            model_id=profile.backend_model_id,
            resolver=ConfigResolver(async_session_factory),
        )
    except (ValueError, LookupError, RuntimeError) as error:
        raise ServiceUnavailableError(BACKEND_UNAVAILABLE) from error
    if not isinstance(backend, DashScopeVideoBackend):
        raise ServiceUnavailableError(BACKEND_UNAVAILABLE)
    return backend


def _descriptor(profile: R2ExecutionProfileV1) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=profile.capability_id,
        adapter_id=f"adapter:{profile.capability_id}",
        provider_id=profile.provider_id,
        execution_type=ExecutionType.API,
        supported_methods=[ProductionMethod.GENERATED_VIDEO],
        typed_features=["VIDEO_OUTPUT"],
        descriptor_source="static",
        descriptor_version=profile.descriptor_version,
        provenance=_FIXED_PROVENANCE,
    )


def _method_decision(shot: ShotSpecV2) -> MethodDecision:
    return MethodDecision(
        id=f"MD:{shot.id}",
        target_ref=shot.id,
        method=ProductionMethod.GENERATED_VIDEO,
        rationale="R2 spatial shot on a two-view execution profile",
        cost_class="paid-video",
        quality_tier=shot.quality_tier,
    )


def _execution_decision(shot: ShotSpecV2, plan: PromptPlan, profile: R2ExecutionProfileV1) -> ExecutionDecision:
    return ExecutionDecision(
        id=f"ED:{shot.id}:{profile.capability_id}",
        target_ref=shot.id,
        method_decision_ref=f"MD:{shot.id}",
        prompt_plan_ref=plan.id,
        capability_resolution_ref=profile.profile_ref,
        adapter_id=f"adapter:{profile.capability_id}",
        provider_id=profile.provider_id,
        model_or_tool_id=profile.capability_id,
        execution_type=ExecutionType.API,
        capability_descriptor_version=profile.descriptor_version,
        observation_snapshot_ref=profile.profile_ref,
        execution_identity_stability=ExecutionIdentityStability.IMMUTABLE_REVISION,
        request_semantics_hash=prompt_plan_digest(plan).removeprefix("sha256:")[:16],
        selection_policy_version=SPATIAL_PROMPT_PROJECTION_VERSION,
        provenance=_FIXED_PROVENANCE,
    )


def _pin(path: Path, data: bytes) -> None:
    """Write the evidence bytes once; a later derivation must find exactly the same bytes."""
    if path.exists():
        if path.read_bytes() != data:
            raise R2ShotAdmissionRefused("r2_shot_source_changed")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


async def derive_shot_admission(
    command: R2ShotCommand,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    project_dir: Path,
    payload_builder_for: Callable[[R2ExecutionProfileV1], Awaitable[ShotPayloadBuilder]],
) -> R2ShotAdmission:
    profile = PROFILES.get(command.execution_profile_ref)
    if profile is None:
        raise R2ShotAdmissionRefused("r2_shot_profile_unknown")
    snapshot = await CurrentLocationBindingSnapshotReader(
        session_factory=session_factory, project_dir=project_dir
    ).read_current(
        user_id=command.user_id,
        project_name=command.project_name,
        target_id=command.target_id,
        expected_snapshot_digest=command.expected_binding_snapshot_digest,
        require_approved_pair=True,
    )
    if snapshot.spatial_set is None:
        raise R2ShotAdmissionRefused("r2_shot_requires_spatial_set")
    async with session_factory() as session, session.begin():
        target = await TransactionBoundTargetAuthorityResolver(session).resolve_current(
            user_id=command.user_id,
            project_name=command.project_name,
            target_type=ProductionBindingTarget.SHOT,
            target_id=command.target_id,
        )
    if target is None or not isinstance(target.target, ShotSpecV2):
        raise R2ShotAdmissionRefused("r2_shot_target_unavailable")
    if (
        target.ref.registry_version != command.expected_target_registry_version
        or snapshot.body.target_versions[1] != target.ref
    ):
        raise R2ShotAdmissionRefused("r2_shot_target_stale")
    shot = target.target

    plan = apply_spatial_constraints(
        PromptPlanner().build(
            shot=shot,
            method_decision=_method_decision(shot),
            identity=ResolvedVisualIdentity(
                target_ref=shot.id,
                status=ResolvedIdentityStatus.RESOLVED,
                resolution_policy_version=SPATIAL_PROMPT_PROJECTION_VERSION,
            ),
        ),
        snapshot.spatial_set,
    )
    refusals = admission_refusals(shot, plan, profile)
    if refusals:
        raise R2ShotAdmissionRefused("r2_shot_profile_refused", refusals)
    compiled = DefaultPromptCompiler.for_descriptors([_descriptor(profile)]).compile(
        plan=plan, decision=_execution_decision(shot, plan, profile)
    )
    provider_prompt = project_spatial_prompt(plan)

    task_id = shot_task_id(user_id=command.user_id, project_name=command.project_name, command_id=command.command_id)
    evidence_dir = project_dir / R2_SHOT_EVIDENCE_DIR / task_id
    reader = SpatialFrameReader(session_factory=session_factory, project_dir=project_dir)
    frames: list[R2ShotSourceFrameV1] = []
    image_paths: list[Path] = []
    for index, source in enumerate(snapshot.spatial_set.ordered_sources, start=1):
        frame = await reader.read_current(
            user_id=command.user_id,
            project_name=command.project_name,
            receipt_id=source.frame_derivation_receipt_id,
            expected_receipt_digest=source.frame_derivation_receipt_digest,
        )
        if frame.receipt.identity.frame_content_digest != source.frame_content_digest:
            raise R2ShotAdmissionRefused("r2_shot_source_changed")
        path = evidence_dir / f"image{index}.png"
        await asyncio.to_thread(_pin, path, frame.png_bytes)
        image_paths.append(path)
        frames.append(
            R2ShotSourceFrameV1(
                image_index=index,  # type: ignore[arg-type]
                view=source.view,
                receipt_id=source.frame_derivation_receipt_id,
                receipt_digest=source.frame_derivation_receipt_digest,
                frame_content_digest=source.frame_content_digest,
            )
        )

    video_request = VideoGenerationRequest(
        prompt=provider_prompt,
        output_path=evidence_dir / "output.mp4",
        aspect_ratio=profile.aspect_ratio,
        duration_seconds=profile.duration_seconds,
        resolution=profile.resolution,
        reference_images=image_paths,
        prompt_extend=profile.prompt_extend,
        seed=profile.seed,
        project_name=command.project_name,
        task_id=task_id,
    )
    builder = await payload_builder_for(profile)
    if builder.model != profile.backend_model_id:
        raise R2ShotAdmissionRefused("r2_shot_backend_model_mismatch")
    captured = builder.build_submit_payload(video_request)
    set_digest = spatial_constraint_set_digest(snapshot.spatial_set.model_dump(mode="json"))
    envelope: dict[str, Any] = {
        "schema": "r2.m8.spatial.shot.envelope.v1",
        "task_id": task_id,
        "command_id": command.command_id,
        "execution_profile_ref": profile.profile_ref,
        "binding_snapshot_digest": snapshot.digest,
        "spatial_set_digests": [set_digest],
        "prompt_plan_digest": prompt_plan_digest(plan),
        "compiled_request_digest": compiled_request_digest(compiled),
        "provider_prompt_digest": prompt_digest(provider_prompt),
        "provider_payload_digest": provider_payload_digest(captured),
        "ordered_source_frames": [frame.model_dump(mode="json") for frame in frames],
    }
    video_request.captured_payload = captured
    video_request.r2_execution_options = envelope
    host_request = await build_host_video_request(
        video_request,
        provider_id=profile.provider_id,
        provider_model_id=profile.provider_model_id,
        endpoint_id=profile.endpoint_id,
    )
    body: dict[str, Any] = {
        "schema_version": "r2_shot_generation_v1",
        "user_id": command.user_id,
        "project_name": command.project_name,
        "task_id": task_id,
        "command_id": command.command_id,
        "target_type": "SHOT",
        "target_id": command.target_id,
        "target_registry_version": target.ref.registry_version,
        "target_digest": target.ref.version_digest,
        "binding_snapshot_digest": snapshot.digest,
        "spatial_set_digests": [set_digest],
        "ordered_source_frames": envelope["ordered_source_frames"],
        "execution_profile_ref": profile.profile_ref,
        "prompt_plan_digest": envelope["prompt_plan_digest"],
        "compiled_request_digest": envelope["compiled_request_digest"],
        "provider_prompt_digest": envelope["provider_prompt_digest"],
        "provider_payload_digest": envelope["provider_payload_digest"],
        "host_request_digest": host_request_digest(host_request),
    }
    body["submit_fingerprint"] = submit_fingerprint(body, profile)
    return R2ShotAdmission(
        evidence=R2ShotGenerationTaskV1.model_validate(body),
        profile=profile,
        video_request=video_request,
        host_request=host_request,
    )


__all__ = [
    "BACKEND_UNAVAILABLE",
    "R2_SHOT_EVIDENCE_DIR",
    "R2ShotAdmission",
    "R2ShotAdmissionRefused",
    "R2ShotCommand",
    "ShotPayloadBuilder",
    "configured_payload_builder",
    "derive_shot_admission",
]
