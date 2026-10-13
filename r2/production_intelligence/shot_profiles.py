"""Admission of a spatial shot to an R2 execution profile, and its exact provider prompt.

Admission runs before queueing and returns refusal reason codes. The prompt projection is
deterministic: it binds Image 1 to the front (MASTER) frame and Image 2 to the reverse
(REVERSE) frame, and carries only the plan's VISIBLE spatial constraint lines.
"""

from __future__ import annotations

import hashlib

from r2.contracts import AnyShotSpec, PromptPlan
from r2.contracts.shot_generation import R2ExecutionProfileV1

WAN27_TWO_VIEW_PROFILE = R2ExecutionProfileV1(
    profile_ref="r2-wan27-r2v-two-view@1",
    capability_id="m8c-wan-two-view",
    descriptor_version="m8c-wan-two-view-v1",
    provider_id="dashscope",
    provider_model_id="wan2.7-r2v-2026-06-12",
    backend_model_id="wan2.7-r2v-2026-06-12",
    endpoint_id="video-synthesis",
    adapter_version="host-video-v1",
    capability_profile_ref="dashscope-video-synthesis@host-video-v1",
    duration_seconds=5,
    resolution="720P",
    aspect_ratio="16:9",
    watermark=False,
    seed=None,
    prompt_extend=False,
    reference_images=2,
    max_prompt_chars=5000,
)
PROFILES: dict[str, R2ExecutionProfileV1] = {WAN27_TWO_VIEW_PROFILE.profile_ref: WAN27_TWO_VIEW_PROFILE}
SPATIAL_PROMPT_PROJECTION_VERSION = "m8c-wan-two-view-prompt-v1"
IMAGE_ROLE_LINE = "Image 1 is the front view of the set. Image 2 is the reverse view of the same set."


def admission_refusals(shot: AnyShotSpec, plan: PromptPlan, profile: R2ExecutionProfileV1) -> tuple[str, ...]:
    """Every reason this shot and plan cannot run on ``profile``; empty when admitted."""
    reasons: list[str] = []
    if plan.required_controls:
        reasons.append("profile_unsupported_controls")
    if plan.reference_requirements or plan.visual_identity_constraints:
        reasons.append("profile_unsupported_identity")
    if shot.target_duration != profile.duration_seconds:
        reasons.append("profile_duration_mismatch")
    if "spatial_constraint_set" not in plan.output_requirements:
        reasons.append("profile_requires_spatial_set")
    if not reasons and len(project_spatial_prompt(plan)) > profile.max_prompt_chars:
        reasons.append("profile_prompt_too_long")
    return tuple(reasons)


def project_spatial_prompt(plan: PromptPlan) -> str:
    sections = [
        IMAGE_ROLE_LINE,
        f"Subject: {plan.subject_intent or plan.semantic_instruction}",
    ]
    if plan.composition_intent:
        sections.append(f"Composition: {plan.composition_intent}")
    if plan.camera_intent:
        sections.append(f"Camera: {plan.camera_intent}")
    if plan.environment_intent:
        sections.append("Set layout:\n" + "\n".join(f"- {line}" for line in plan.environment_intent.splitlines()))
    return "\n".join(sections)


def prompt_digest(prompt: str) -> str:
    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()


__all__ = [
    "IMAGE_ROLE_LINE",
    "PROFILES",
    "SPATIAL_PROMPT_PROJECTION_VERSION",
    "WAN27_TWO_VIEW_PROFILE",
    "admission_refusals",
    "project_spatial_prompt",
    "prompt_digest",
]
