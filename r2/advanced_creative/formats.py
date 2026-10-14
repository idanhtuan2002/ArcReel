"""Governed multi-format projection: profile validation, reframe geometry and plans (spec §10).

Output profiles and overlay constraint sets are exact, versioned records; a plan names them by value
and binds one exact approved master, so nothing floats. V1 projects to exactly 16:9, 9:16 and 1:1.
A reframe is explicit: ``PAD`` letterboxes the whole source (donor ``fit="pad"``), ``COVER_CENTER``
fills and centre-crops (donor ``fit="cover"``), and ``COVER_FOCAL`` fills and positions the crop window
on a declared focal span. Every decision records its spans in normalized source/target coordinates and
a semantic risk derived from how much of the source it removes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from math import gcd

from r2.advanced_creative.digests import digest_canonical
from r2.contracts.advanced_creative import (
    CanonicalJsonObject,
    FormatProjectionPlan,
    OutputProfile,
    OverlayConstraintSet,
    ReframeDecision,
    SemanticParityReport,
    TechnicalValidationReport,
)

V1_RATIOS = frozenset({(16, 9), (9, 16), (1, 1)})
CONTAINERS = frozenset({"mp4"})
VIDEO_CODECS = frozenset({"h264"})
AUDIO_CODECS = frozenset({"aac"})
REGION_KINDS = frozenset({"ui", "caption", "safe"})
HIGH_RISK_CROP = Decimal("0.40")
MEDIUM_RISK_CROP = Decimal("0.15")


class FormatInvalidError(ValueError):
    """A profile, overlay set, reframe or plan is malformed; it fails closed."""


class ReframeKind(StrEnum):
    PAD = "PAD"
    COVER_CENTER = "COVER_CENTER"
    COVER_FOCAL = "COVER_FOCAL"


FORMAT_SLOT_PREFIX = "m8-format:"


def source_master_id(artifact_key: str, master_version: int) -> str:
    return f"{artifact_key}@v{master_version}"


def parse_source_master_id(value: str) -> tuple[str, int]:
    artifact_key, separator, version = value.rpartition("@v")
    if not separator or not artifact_key or not version.isdigit() or int(version) < 1:
        raise FormatInvalidError("a source master id is <artifact key>@v<version>")
    return artifact_key, int(version)


def format_slot_key(source_artifact_key: str, profile_ref: str) -> str:
    """The M8 slot a projection of ``source_artifact_key`` to ``profile_ref`` is promoted into."""
    return f"{FORMAT_SLOT_PREFIX}{hashlib.sha256(source_artifact_key.encode()).hexdigest()[:16]}:{profile_ref}"


def reduced_ratio(width: int, height: int) -> tuple[int, int]:
    divisor = gcd(width, height)
    return width // divisor, height // divisor


def validate_output_profile(profile: OutputProfile) -> None:
    if profile.width <= 0 or profile.height <= 0:
        raise FormatInvalidError("dimensions must be positive")
    if profile.width % 2 or profile.height % 2:
        raise FormatInvalidError("dimensions must be even for 4:2:0 video")
    if reduced_ratio(profile.width, profile.height) not in V1_RATIOS:
        raise FormatInvalidError("V1 projects only to exactly 16:9, 9:16 or 1:1")
    if profile.fps <= 0 or profile.fps > 120:
        raise FormatInvalidError("fps must be within (0, 120]")
    if profile.container not in CONTAINERS or profile.video_codec not in VIDEO_CODECS:
        raise FormatInvalidError("unsupported container or video codec")
    if profile.audio_codec is not None and profile.audio_codec not in AUDIO_CODECS:
        raise FormatInvalidError("unsupported audio codec")
    if profile.duration_limit_seconds is not None and profile.duration_limit_seconds <= 0:
        raise FormatInvalidError("a duration limit must be positive")
    if not profile.profile_ref or not profile.source_refs:
        raise FormatInvalidError("a profile names its ref and its sources")


@dataclass(frozen=True, order=True)
class Box:
    """A normalized rectangle: 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1."""

    x0: Fraction
    y0: Fraction
    x1: Fraction
    y1: Fraction

    def __post_init__(self) -> None:
        if not (0 <= self.x0 < self.x1 <= 1 and 0 <= self.y0 < self.y1 <= 1):
            raise FormatInvalidError("a box must be a normalized rectangle with positive area")

    @property
    def area(self) -> Fraction:
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    def overlaps(self, other: Box) -> bool:
        return self.x0 < other.x1 and other.x0 < self.x1 and self.y0 < other.y1 and other.y0 < self.y1

    def as_json(self) -> dict[str, str]:
        return {
            name: f"{getattr(self, name).numerator}/{getattr(self, name).denominator}"
            for name in ("x0", "y0", "x1", "y1")
        }

    @staticmethod
    def parse(value: dict[str, object]) -> Box:
        try:
            return Box(*(Fraction(str(value[name])) for name in ("x0", "y0", "x1", "y1")))
        except (KeyError, ValueError, ZeroDivisionError) as exc:
            raise FormatInvalidError("box needs x0, y0, x1, y1 fractions") from exc


def validate_overlay_set(overlay: OverlayConstraintSet) -> tuple[tuple[str, Box], ...]:
    """The overlay regions as (kind, box); every region is a named, normalized rectangle."""
    if not overlay.constraint_ref or not overlay.source_refs:
        raise FormatInvalidError("an overlay set names its ref and its sources")
    regions: list[tuple[str, Box]] = []
    for region in overlay.regions:
        body = dict(region.model_dump(mode="python"))
        kind = body.get("kind")
        if kind not in REGION_KINDS:
            raise FormatInvalidError("overlay region kind must be ui, caption or safe")
        regions.append((str(kind), Box.parse(body)))
    return tuple(regions)


def profile_digest(profile: OutputProfile) -> str:
    return digest_canonical({"contract_version": "1", "output_profile": profile})


def overlay_digest(overlay: OverlayConstraintSet) -> str:
    return digest_canonical({"contract_version": "1", "overlay_constraints": overlay})


@dataclass(frozen=True)
class Geometry:
    """Where the source lands in the target: the kept source window and the target placement."""

    source_window: Box
    target_window: Box
    removed_fraction: Fraction


def reframe_geometry(
    *,
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
    kind: ReframeKind,
    focal: Box | None,
) -> Geometry:
    if min(source_width, source_height, target_width, target_height) <= 0:
        raise FormatInvalidError("dimensions must be positive")
    source_ratio = Fraction(source_width, source_height)
    target_ratio = Fraction(target_width, target_height)
    whole = Box(Fraction(0), Fraction(0), Fraction(1), Fraction(1))
    if kind is ReframeKind.PAD:
        if focal is not None:
            raise FormatInvalidError("PAD keeps the whole source and takes no focal span")
        if source_ratio >= target_ratio:
            height = target_ratio / source_ratio
            target = Box(Fraction(0), (1 - height) / 2, Fraction(1), (1 + height) / 2)
        else:
            width = source_ratio / target_ratio
            target = Box((1 - width) / 2, Fraction(0), (1 + width) / 2, Fraction(1))
        return Geometry(source_window=whole, target_window=target, removed_fraction=Fraction(0))
    if kind is ReframeKind.COVER_FOCAL and focal is None:
        raise FormatInvalidError("COVER_FOCAL needs a focal span")
    if kind is ReframeKind.COVER_CENTER and focal is not None:
        raise FormatInvalidError("COVER_CENTER is centred and takes no focal span")
    if source_ratio >= target_ratio:
        width = target_ratio / source_ratio
        center = Fraction(1, 2) if focal is None else (focal.x0 + focal.x1) / 2
        x0 = min(max(center - width / 2, Fraction(0)), 1 - width)
        window = Box(x0, Fraction(0), x0 + width, Fraction(1))
    else:
        height = source_ratio / target_ratio
        center = Fraction(1, 2) if focal is None else (focal.y0 + focal.y1) / 2
        y0 = min(max(center - height / 2, Fraction(0)), 1 - height)
        window = Box(Fraction(0), y0, Fraction(1), y0 + height)
    if focal is not None and not (
        window.x0 <= focal.x0 and focal.x1 <= window.x1 and window.y0 <= focal.y0 and focal.y1 <= window.y1
    ):
        raise FormatInvalidError("the focal span does not fit inside the crop window")
    return Geometry(source_window=window, target_window=whole, removed_fraction=1 - window.area)


def semantic_risk(geometry: Geometry) -> str:
    removed = Decimal(geometry.removed_fraction.numerator) / Decimal(geometry.removed_fraction.denominator)
    if removed > HIGH_RISK_CROP:
        return "HIGH"
    if removed > MEDIUM_RISK_CROP:
        return "MEDIUM"
    return "LOW"


def _decision_spans(
    *,
    kind: ReframeKind,
    source_size: tuple[int, int],
    target_size: tuple[int, int],
    focal: Box | None,
    subject: Box | None,
    captions: tuple[Box, ...],
) -> tuple[dict[str, object], dict[str, object], str]:
    geometry = reframe_geometry(
        source_width=source_size[0],
        source_height=source_size[1],
        target_width=target_size[0],
        target_height=target_size[1],
        kind=kind,
        focal=focal,
    )
    source: dict[str, object] = {
        **geometry.source_window.as_json(),
        "width": source_size[0],
        "height": source_size[1],
        "captions": [caption.as_json() for caption in captions],
    }
    if focal is not None:
        source["focal"] = focal.as_json()
    if subject is not None:
        source["subject"] = subject.as_json()
    target = {**geometry.target_window.as_json(), "width": target_size[0], "height": target_size[1]}
    return source, target, semantic_risk(geometry)


def reframe_decision(
    *,
    decision_id: str,
    kind: ReframeKind,
    source_size: tuple[int, int],
    profile: OutputProfile,
    focal: Box | None,
    rationale: str,
    subject: Box | None = None,
    captions: tuple[Box, ...] = (),
) -> ReframeDecision:
    """One explicit reframe. ``focal`` positions a COVER_FOCAL crop; ``subject`` and ``captions`` are the
    source evidence every kind is checked against (the subject defaults to the focal span)."""
    if not rationale.strip():
        raise FormatInvalidError("a reframe decision states its rationale")
    source, target, risk = _decision_spans(
        kind=kind,
        source_size=source_size,
        target_size=(profile.width, profile.height),
        focal=focal,
        subject=subject or focal,
        captions=captions,
    )
    return ReframeDecision(
        decision_id=decision_id,
        kind=kind.value,
        source_span=CanonicalJsonObject.model_validate(source),
        target_span=CanonicalJsonObject.model_validate(target),
        rationale=rationale,
        semantic_risk=risk,
    )


def _plan_body(plan: FormatProjectionPlan) -> dict[str, object]:
    return {"contract_version": "1", "plan": plan.model_dump(mode="python", exclude={"plan_digest"})}


def _boxes(value: object) -> tuple[Box, ...]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, dict) for item in value):
        raise FormatInvalidError("captions are a list of boxes")
    return tuple(Box.parse(item) for item in value)


def validate_plan(plan: FormatProjectionPlan) -> None:
    """Everything a plan asserts, recomputed: profile, overlay, surface, and the reframe geometry and risk.

    A plan whose spans or risk disagree with the geometry its kind implies is refused, so a decision
    cannot claim PAD while cropping, or LOW risk while removing most of the frame.
    """
    profile = plan.output_profile
    overlay = plan.overlay_constraints
    validate_output_profile(profile)
    validate_overlay_set(overlay)
    if (overlay.platform, overlay.surface) != (profile.platform, profile.surface):
        raise FormatInvalidError("the overlay set belongs to another platform surface")
    if len(plan.reframe_decisions) != 1:
        raise FormatInvalidError("V1 projects one master with exactly one reframe decision")
    decision = plan.reframe_decisions[0]
    if not decision.rationale.strip() or not decision.decision_id:
        raise FormatInvalidError("a reframe decision states its id and rationale")
    try:
        kind = ReframeKind(decision.kind)
    except ValueError as exc:
        raise FormatInvalidError("unknown reframe kind") from exc
    source = decision.source_span.model_dump(mode="python")
    width, height = source.get("width"), source.get("height")
    if not isinstance(width, int) or not isinstance(height, int):
        raise FormatInvalidError("the source span names the source size")
    focal = Box.parse(source["focal"]) if isinstance(source.get("focal"), dict) else None
    subject = Box.parse(source["subject"]) if isinstance(source.get("subject"), dict) else None
    expected_source, expected_target, risk = _decision_spans(
        kind=kind,
        source_size=(width, height),
        target_size=(profile.width, profile.height),
        focal=focal,
        subject=subject,
        captions=_boxes(source.get("captions", [])),
    )
    if (
        CanonicalJsonObject.model_validate(expected_source) != decision.source_span
        or CanonicalJsonObject.model_validate(expected_target) != decision.target_span
        or risk != decision.semantic_risk
    ):
        raise FormatInvalidError("the reframe spans or risk disagree with the geometry of its kind")
    verify_plan_digest(plan)


def build_plan(
    *,
    plan_id: str,
    source_master_id: str,
    source_master_digest: str,
    profile: OutputProfile,
    overlay: OverlayConstraintSet,
    decisions: tuple[ReframeDecision, ...],
) -> FormatProjectionPlan:
    """A plan binding one exact master, profile, overlay set and reframe; its digest covers all of it."""
    draft = FormatProjectionPlan(
        plan_id=plan_id,
        source_master_id=source_master_id,
        source_master_digest=source_master_digest,
        output_profile=profile,
        overlay_constraints=overlay,
        reframe_decisions=decisions,
        plan_digest="sha256:" + "0" * 64,
    )
    plan = draft.model_copy(update={"plan_digest": digest_canonical(_plan_body(draft))})
    validate_plan(plan)
    return plan


def verify_plan_digest(plan: FormatProjectionPlan) -> None:
    if digest_canonical(_plan_body(plan)) != plan.plan_digest:
        raise FormatInvalidError("plan digest does not match its contents")


def _project(box: Box, window: Box, target: Box) -> Box | None:
    """``box`` (source coordinates) after cropping to ``window`` and placing in ``target``; None if cut away."""
    x0, y0 = max(box.x0, window.x0), max(box.y0, window.y0)
    x1, y1 = min(box.x1, window.x1), min(box.y1, window.y1)
    if x0 >= x1 or y0 >= y1:
        return None

    def along(value: Fraction, lo: Fraction, hi: Fraction, tlo: Fraction, thi: Fraction) -> Fraction:
        return tlo + (value - lo) / (hi - lo) * (thi - tlo)

    return Box(
        along(x0, window.x0, window.x1, target.x0, target.x1),
        along(y0, window.y0, window.y1, target.y0, target.y1),
        along(x1, window.x0, window.x1, target.x0, target.x1),
        along(y1, window.y0, window.y1, target.y0, target.y1),
    )


def overlay_collisions(plan: FormatProjectionPlan) -> tuple[str, ...]:
    """Problems the projection creates: a subject or caption cropped out or partly cut, or covered by UI.

    The subject and caption spans are source evidence independent of how the crop was positioned, so
    PAD and COVER_CENTER are checked exactly like COVER_FOCAL.
    """
    decision = plan.reframe_decisions[0]
    source = decision.source_span.model_dump(mode="python")
    window = Box.parse(source)
    target = Box.parse(decision.target_span.model_dump(mode="python"))
    ui = [
        (index, box) for index, (kind, box) in enumerate(validate_overlay_set(plan.overlay_constraints)) if kind == "ui"
    ]
    evidence: list[tuple[str, Box]] = []
    if isinstance(source.get("subject"), dict):
        evidence.append(("subject", Box.parse(source["subject"])))
    evidence += [(f"caption {index}", box) for index, box in enumerate(_boxes(source.get("captions", [])))]
    problems: list[str] = []
    for name, box in evidence:
        projected = _project(box, window, target)
        if projected is None:
            problems.append(f"{name} cropped out")
            continue
        if not (window.x0 <= box.x0 and box.x1 <= window.x1 and window.y0 <= box.y0 and box.y1 <= window.y1):
            problems.append(f"{name} partly cropped")
        problems += [f"ui region {index} covers {name}" for index, region in ui if region.overlaps(projected)]
    return tuple(problems)


SEMANTIC_RUBRIC = "format-semantic@1"
SEMANTIC_ITEMS = ("focal_subject", "action", "shot_intent", "on_screen_text", "captions", "timing", "audio")
SINGLE_REVIEWER_DEVIATION = "single_reviewer_by_sponsor_decision_2026-10-14"


TECHNICAL_CHECKS = ("dimensions", "ratio", "video_codec", "fps", "duration", "audio", "decode", "overlay")
_EXACT_CHECKS = frozenset({"dimensions", "ratio", "video_codec", "fps", "audio"})


def validate_technical_report(report: TechnicalValidationReport, plan: FormatProjectionPlan) -> None:
    """The complete versioned check set, each with observed and expected values and a verdict.

    Exact checks pass exactly when observed equals expected; the others carry the measuring rule's
    verdict. The report passes exactly when every check passes.
    """
    if report.plan_digest != plan.plan_digest:
        raise FormatInvalidError("technical report names another plan")
    rows: dict[str, dict[str, object]] = {}
    for check in report.checks:
        body = check.model_dump(mode="python")
        name = body.get("name")
        if not isinstance(name, str) or name in rows:
            raise FormatInvalidError("each check has a unique name")
        if body.get("verdict") not in ("PASS", "FAIL") or "observed" not in body or "expected" not in body:
            raise FormatInvalidError("each check has observed and expected values and a PASS/FAIL verdict")
        rows[name] = body
    if tuple(sorted(rows)) != tuple(sorted(TECHNICAL_CHECKS)):
        raise FormatInvalidError("a technical report has exactly the versioned check set")
    for name in _EXACT_CHECKS:
        row = rows[name]
        if (row["verdict"] == "PASS") != (row["observed"] == row["expected"]):
            raise FormatInvalidError(f"the {name} verdict contradicts its observation")
    if report.passed != all(row["verdict"] == "PASS" for row in rows.values()):
        raise FormatInvalidError("a technical report passes exactly when every check passes")


def validate_semantic_report(report: SemanticParityReport, plan: FormatProjectionPlan, *, deviation: str | None) -> int:
    """Reviews against the fixed rubric; returns the reviewer count.

    A review names its reviewer and gives PASS/FAIL for every rubric item. Reviewers disagree
    materially when any item's verdicts differ. The report passes only when every item of every
    review passes and nobody disagrees. Fewer than two reviewers needs the recorded deviation.
    """
    if report.plan_digest != plan.plan_digest or report.source_master_digest != plan.source_master_digest:
        raise FormatInvalidError("semantic report names another plan or master")
    if report.rubric_version != SEMANTIC_RUBRIC:
        raise FormatInvalidError("semantic report uses another rubric")
    reviewers: set[str] = set()
    per_item: dict[str, set[str]] = {item: set() for item in SEMANTIC_ITEMS}
    for review in report.reviews:
        body = review.model_dump(mode="python")
        reviewer = body.get("reviewer_id")
        if not isinstance(reviewer, str) or not reviewer or reviewer in reviewers:
            raise FormatInvalidError("each review names one distinct reviewer")
        reviewers.add(reviewer)
        items = body.get("items")
        if not isinstance(items, dict) or set(items) != set(SEMANTIC_ITEMS):
            raise FormatInvalidError("a review gives a verdict for every rubric item")
        for item, verdict in items.items():
            if verdict not in ("PASS", "FAIL"):
                raise FormatInvalidError("rubric verdicts are PASS or FAIL")
            per_item[item].add(verdict)
    if not reviewers:
        raise FormatInvalidError("a semantic report has at least one review")
    if len(reviewers) < 2 and deviation != SINGLE_REVIEWER_DEVIATION:
        raise FormatInvalidError("fewer than two reviewers needs the recorded sponsor deviation")
    disagreement = any(len(verdicts) > 1 for verdicts in per_item.values())
    if report.material_disagreement != disagreement:
        raise FormatInvalidError("material disagreement must reflect the reviews")
    passed = not disagreement and all(verdicts == {"PASS"} for verdicts in per_item.values())
    if report.passed != passed:
        raise FormatInvalidError("a semantic report passes exactly when every reviewer passes every item")
    return len(reviewers)


__all__ = [
    "FORMAT_SLOT_PREFIX",
    "SEMANTIC_ITEMS",
    "SEMANTIC_RUBRIC",
    "SINGLE_REVIEWER_DEVIATION",
    "TECHNICAL_CHECKS",
    "V1_RATIOS",
    "Box",
    "FormatInvalidError",
    "Geometry",
    "ReframeKind",
    "build_plan",
    "format_slot_key",
    "overlay_collisions",
    "overlay_digest",
    "parse_source_master_id",
    "profile_digest",
    "reduced_ratio",
    "reframe_decision",
    "reframe_geometry",
    "semantic_risk",
    "source_master_id",
    "validate_output_profile",
    "validate_overlay_set",
    "validate_plan",
    "validate_semantic_report",
    "validate_technical_report",
    "verify_plan_digest",
]
