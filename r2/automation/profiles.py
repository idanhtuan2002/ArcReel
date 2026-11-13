"""Candidate launch metadata and declared qualification checks, never runtime authority."""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from r2.automation.identity import digest_value
from r2.contracts.automation import (
    AutomationContract,
    Digest,
    ExactIdentity,
    ModelRoute,
    PositiveInt,
    ReviewerQualification,
)
from r2.contracts.common import ensure_json_value

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class ImageSelection(AutomationContract):
    """Best-of-N storyboards with a ranking-only judge (ADR-0112), pinned to the judge's committed qualification."""

    candidates: Literal[2, 3]
    judge_model_identity: ExactIdentity
    judge_prompt_digest: Digest
    #: Repository-relative path of the judge's qualification evidence and that file's sha256 digest.
    qualification_evidence: ExactIdentity
    qualification_digest: Digest


class ContinuityCheck(AutomationContract):
    """Storyboards judged for continuity against their references (ADR-0134), pinned to the judge's committed
    qualification (``scripts/r2/qualify_continuity_judge.py``)."""

    judge_model_identity: ExactIdentity
    judge_prompt_digest: Digest
    #: The judge route's image cap per request; references then share one sheet (part of the prompt digest).
    max_pictures: Annotated[int, Field(ge=2, le=16)] | None = None
    #: Repository-relative path of the judge's qualification evidence and that file's sha256 digest.
    qualification_evidence: ExactIdentity
    qualification_digest: Digest


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
    #: The audio route's measured speaking rate in reading units (Vietnamese words) per second, given to the films the
    #: autopilot makes on this profile so their planned length is spoken at the voice's real pace.
    speech_rate_units_per_second: Annotated[float, Field(gt=0, le=20)] | None = None
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
    #: Absent: one storyboard per segment.
    image_selection: ImageSelection | None = None
    #: Absent: storyboards are not judged for continuity.
    continuity: ContinuityCheck | None = None


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


def _evidence_qualifies(
    evidence_path: str, digest: str, identity: str, prompt_digest: str, *, schema: str | None = None
) -> bool:
    path = (REPOSITORY_ROOT / evidence_path).resolve()
    if not path.is_relative_to(REPOSITORY_ROOT) or not path.is_file():
        return False
    data = path.read_bytes()
    if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
        return False
    try:
        evidence = json.loads(data)
    except ValueError:
        return False
    return (
        isinstance(evidence, dict)
        and (schema is None or evidence.get("schema") == schema)
        and evidence.get("qualified") is True
        and evidence.get("model_identity") == identity
        and evidence.get("prompt_digest") == prompt_digest
    )


def image_judge_is_qualified(selection: ImageSelection) -> bool:
    """The pinned evidence file exists with its pinned digest and qualifies exactly the pinned judge."""
    selection = ImageSelection.model_validate(selection)
    return _evidence_qualifies(
        selection.qualification_evidence,
        selection.qualification_digest,
        selection.judge_model_identity,
        selection.judge_prompt_digest,
    )


def continuity_judge_is_qualified(check: ContinuityCheck) -> bool:
    """The pinned continuity qualification exists with its pinned digest and qualifies exactly the pinned judge."""
    check = ContinuityCheck.model_validate(check)
    return _evidence_qualifies(
        check.qualification_evidence,
        check.qualification_digest,
        check.judge_model_identity,
        check.judge_prompt_digest,
        schema="r2.continuity-judge-qualification.v1",
    )
