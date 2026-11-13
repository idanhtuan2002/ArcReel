"""Read-only prerequisites. A positive report neither grants authority nor reserves resources."""

from typing import Protocol

from r2.automation.identity import policy_digest
from r2.automation.profiles import (
    continuity_judge_is_qualified,
    image_judge_is_qualified,
    resolve_launch_profile,
    reviewer_is_qualified,
    route_digest,
)
from r2.contracts.automation import PreflightReport, PreflightSnapshot, RunPolicy
from r2.contracts.quality import AssessorClass
from r2.quality.digests import verify_caches
from r2.quality.errors import M10Error

_REQUIRED_ROLES = {"writer", "script", "reviewer_a", "reviewer_b", "image", "video", "audio"}


class PreflightReader(Protocol):
    async def read(self, *, user_id: str, project_name: str, policy: RunPolicy) -> PreflightSnapshot:
        """Resolve actual project/config/profile and qualified owner receipts without dispatch."""
        ...


class ProductionPreflight:
    def __init__(self, reader: PreflightReader) -> None:
        self._reader = reader

    async def check(self, *, user_id: str, project_name: str, policy: RunPolicy) -> PreflightReport:
        policy = RunPolicy.model_validate(policy)
        snapshot = PreflightSnapshot.model_validate(
            await self._reader.read(user_id=user_id, project_name=project_name, policy=policy)
        )
        reasons: list[str] = []
        try:
            launch = resolve_launch_profile(policy.launch_profile_id)
        except ValueError:
            reasons.append("UNSUPPORTED_LAUNCH_PROFILE")
            launch = None
        if (snapshot.user_id, snapshot.project_name) != (user_id, project_name):
            reasons.append("PREFLIGHT_SCOPE_MISMATCH")
        if launch is not None:
            if snapshot.content_mode != launch.content_mode:
                reasons.append("UNSUPPORTED_CONTENT_MODE")
            if snapshot.generation_mode != launch.generation_mode:
                reasons.append("UNSUPPORTED_GENERATION_MODE")
            if snapshot.language != launch.language or policy.language != launch.language:
                reasons.append("UNSUPPORTED_LANGUAGE")
            if (policy.width, policy.height, policy.fps) != (launch.width, launch.height, launch.fps):
                reasons.append("UNSUPPORTED_OUTPUT_CONTRACT")
            if launch.requires_lip_sync:
                reasons.append("DRAMA_ROUTE_NOT_QUALIFIED")
        roles = {route.role: route for route in snapshot.routes}
        if launch is not None:
            for role, expected in (
                ("image", launch.image_route),
                ("video", launch.video_route),
                ("audio", launch.audio_route),
            ):
                route = roles.get(role)
                # The profile's own route, or any route of the role whose host media probe passed.
                if (
                    route is not None
                    and (route.provider_id, route.model_id) != expected
                    and route_digest(route) not in snapshot.media_route_probes
                ):
                    reasons.append("MEDIA_ROUTE_NOT_QUALIFIED")
        if len(roles) != len(snapshot.routes) or not roles.keys() >= _REQUIRED_ROLES:
            reasons.append("MISSING_MODEL_ROLE")
        actual = tuple(route_digest(route) for route in snapshot.routes)
        if snapshot.routes != policy.routes or actual != policy.route_digests:
            reasons.append("MODEL_CONFIG_CHANGED")
        qualification = snapshot.launch_qualification
        if qualification is None:
            reasons.append("LAUNCH_PROFILE_NOT_QUALIFIED")
        elif (
            (
                qualification.user_id,
                qualification.project_name,
                qualification.launch_profile_id,
                qualification.profile_digest,
                qualification.route_digests,
            )
            != (user_id, project_name, policy.launch_profile_id, policy.profile_digest, actual)
            or snapshot.required_disk_bytes < qualification.required_disk_bytes
            or snapshot.required_gpu_bytes < qualification.required_gpu_bytes
        ):
            reasons.append("LAUNCH_QUALIFICATION_CHANGED")
        for route in snapshot.routes:
            if policy.local_only and not route.local:
                reasons.append("CLOUD_ROUTE_FORBIDDEN")
            if route.paid and (
                route.max_cost_per_call is None
                or route.max_cost_per_call <= 0
                or policy.max_cost_minor_units <= 0
                or route.currency != policy.currency
            ):
                reasons.append("UNBOUNDED_PAID_ROUTE")
        reviewers = [roles[role] for role in ("reviewer_a", "reviewer_b") if role in roles]
        writer_ids = {roles[role].model_identity for role in ("writer", "script") if role in roles}
        if (
            len(reviewers) != 2
            or len({route.model_identity for route in reviewers}) != 2
            or any(route.model_identity in writer_ids for route in reviewers)
        ):
            reasons.append("REVIEWER_INDEPENDENCE_MISSING")
        for route in reviewers:
            matches = [
                record
                for record in snapshot.qualifications
                if (
                    record.profile_digest,
                    record.launch_profile_id,
                    record.language,
                    record.provider_id,
                    record.model_id,
                    record.model_identity,
                    record.config_digest,
                )
                == (
                    policy.profile_digest,
                    policy.launch_profile_id,
                    policy.language,
                    route.provider_id,
                    route.model_id,
                    route.model_identity,
                    route.config_digest,
                )
            ]
            if len(matches) != 1 or not reviewer_is_qualified(matches[0]):
                reasons.append("MISSING_QUALIFIED_REVIEWER")
        if policy.image_candidates > 1:
            # The judge is the run's reviewer route with the launch profile's pinned identity, and it is qualified.
            selection = launch.image_selection if launch is not None else None
            judge = next(
                (
                    roles[role]
                    for role in ("reviewer_a", "reviewer_b")
                    if role in roles
                    and selection is not None
                    and roles[role].model_identity == selection.judge_model_identity
                ),
                None,
            )
            if (
                selection is None
                or judge is None
                or (policy.image_judge_identity, policy.image_judge_prompt_digest)
                != (selection.judge_model_identity, selection.judge_prompt_digest)
                or judge.model_identity != selection.judge_model_identity
                or not image_judge_is_qualified(selection)
            ):
                reasons.append("IMAGE_JUDGE_NOT_QUALIFIED")
        if policy.continuity_judge_identity is not None:
            # The continuity judge is the run's reviewer route with the launch profile's pinned identity, qualified.
            check = launch.continuity if launch is not None else None
            if (
                check is None
                or (policy.continuity_judge_identity, policy.continuity_judge_prompt_digest)
                != (check.judge_model_identity, check.judge_prompt_digest)
                or not any(
                    roles[role].model_identity == check.judge_model_identity
                    for role in ("reviewer_a", "reviewer_b")
                    if role in roles
                )
                or not continuity_judge_is_qualified(check)
            ):
                reasons.append("CONTINUITY_JUDGE_NOT_QUALIFIED")
        profile = snapshot.profile
        if profile is None:
            reasons.append("MISSING_PUBLISHED_PROFILE")
        else:
            try:
                verify_caches(profile)
            except (M10Error, ValueError, TypeError):
                reasons.append("PROFILE_INTEGRITY_INVALID")
            if (profile.user_id, profile.project_name, profile.profile_id, profile.profile_digest) != (
                user_id,
                project_name,
                policy.profile_id,
                policy.profile_digest,
            ):
                reasons.append("QUALITY_PROFILE_CHANGED")
            slots = [slot for requirement in profile.policy.assessment_requirements for slot in requirement.slots]
            if any(slot.assessor_class is AssessorClass.HUMAN for slot in slots):
                reasons.append("PROFILE_REQUIRES_HUMAN")
            model_slots = [slot for slot in slots if slot.assessor_class is AssessorClass.MODEL]
            if len(model_slots) < 2 or any(slot.required_independence_groups < 2 for slot in model_slots):
                reasons.append("PROFILE_MODEL_ASSESSMENT_INCOMPLETE")
        if not snapshot.voice_available:
            reasons.append("MISSING_VOICE")
        if snapshot.required_disk_bytes <= 0 or snapshot.required_gpu_bytes <= 0:
            reasons.append("RESOURCE_ENVELOPE_UNKNOWN")
        if snapshot.disk_free_bytes < snapshot.required_disk_bytes:
            reasons.append("INSUFFICIENT_DISK")
        if snapshot.gpu_free_bytes < snapshot.required_gpu_bytes:
            reasons.append("INSUFFICIENT_GPU")
        return PreflightReport(
            user_id=user_id,
            project_name=project_name,
            input_digest=snapshot.input_digest,
            policy_digest=policy_digest(policy),
            route_digests=actual,
            dispatch_allowed=not reasons,
            blocking_reasons=tuple(dict.fromkeys(reasons)),
            checked_at=snapshot.checked_at,
        )
