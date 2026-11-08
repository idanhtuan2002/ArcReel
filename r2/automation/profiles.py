"""Candidate launch metadata and declared qualification checks, never runtime authority."""

from pathlib import Path
from typing import Literal

from r2.automation.identity import digest_value
from r2.contracts.automation import AutomationContract, ExactIdentity, ModelRoute, PositiveInt, ReviewerQualification
from r2.contracts.common import ensure_json_value


class LaunchProfile(AutomationContract):
    profile_id: ExactIdentity
    content_mode: Literal["fiction_narration", "fiction_drama"]
    generation_mode: Literal["storyboard"]
    language: Literal["vi"]
    width: Literal[576]
    height: Literal[1024]
    fps: Literal[24]
    video_codec: Literal["h264"]
    audio_codec: Literal["aac"]
    target_duration_seconds: PositiveInt
    image_route: tuple[ExactIdentity, ExactIdentity]
    video_route: tuple[ExactIdentity, ExactIdentity]
    audio_route: tuple[ExactIdentity, ExactIdentity]
    requires_lip_sync: bool
    support_status: Literal["CANDIDATE"]
    #: ``enforce`` exports only a final both reviewers pass; ``record`` (local plumbing profiles, whose models do not
    #: reach release quality) records the quality verdict as the final's disposition and still exports it.
    quality_gate: Literal["enforce", "record"] = "enforce"
    #: Free disk and schedulable GPU memory one run of this profile needs on the host.
    required_disk_bytes: PositiveInt
    required_gpu_bytes: PositiveInt


def resolve_launch_profile(profile_id: str) -> LaunchProfile:
    if profile_id not in {"fiction_narration_vi_v1", "fiction_drama_vi_v1"}:
        raise ValueError("UNSUPPORTED_LAUNCH_PROFILE")
    path = Path(__file__).parent / "launch_profiles" / (profile_id + ".json")
    return LaunchProfile.model_validate_json(path.read_bytes())


def route_digest(route: ModelRoute) -> str:
    route = ModelRoute.model_validate(route)
    return digest_value("r2.production-model-route.v1", ensure_json_value(route.model_dump(mode="json")))


def reviewer_is_qualified(record: ReviewerQualification) -> bool:
    """Check declared corpus results; the host reader must resolve their real owner receipts."""
    record = ReviewerQualification.model_validate(record)
    if len({case.case_digest for case in record.cases}) != len(record.cases) or len(
        {case.receipt_ref for case in record.cases}
    ) != len(record.cases):
        return False
    for split in ("CALIBRATION", "HOLDOUT"):
        clean = [case for case in record.cases if case.split == split and case.label == "CLEAN"]
        defects = [case for case in record.cases if case.split == split and case.label == "CRITICAL_DEFECT"]
        if (
            len(clean) < 10
            or len(defects) < 10
            or any(case.accepted for case in defects)
            or sum(case.accepted for case in clean) * 5 < len(clean) * 4
        ):
            return False
    return True
