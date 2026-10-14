"""Profiles fail closed, reframes are explicit geometry, plans bind exact inputs (M8-E E1)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction

import pytest

from r2.advanced_creative.formats import (
    Box,
    FormatInvalidError,
    ReframeKind,
    build_plan,
    overlay_collisions,
    profile_digest,
    reframe_decision,
    reframe_geometry,
    validate_output_profile,
    verify_plan_digest,
)
from r2.contracts.advanced_creative import OutputProfile, OverlayConstraintSet

DIGEST = "sha256:" + "a" * 64
AT = datetime(2026, 10, 14, tzinfo=UTC)
F = Fraction


def profile(width: int = 1080, height: int = 1920, **changes) -> OutputProfile:
    base = {
        "profile_ref": f"tiktok-feed-{width}x{height}@1",
        "platform": "tiktok",
        "surface": "feed",
        "width": width,
        "height": height,
        "fps": Fraction(30),
        "duration_limit_seconds": Decimal(60),
        "container": "mp4",
        "video_codec": "h264",
        "audio_codec": "aac",
        "source_refs": ("tiktok-creator-guide-2026",),
        "effective_at": AT,
    }
    base.update(changes)
    return OutputProfile(**base)


def overlay(regions=(), **changes) -> OverlayConstraintSet:
    base = {
        "constraint_ref": "tiktok-feed-ui@1",
        "platform": "tiktok",
        "surface": "feed",
        "locale": "vi-VN",
        "ui_variant": "default",
        "regions": regions,
        "source_refs": ("tiktok-safe-zone-2026",),
        "effective_at": AT,
    }
    base.update(changes)
    return OverlayConstraintSet(**base)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"width": 1080, "height": 1350}, "16:9, 9:16 or 1:1"),
        ({"width": 1081, "height": 1081}, "even"),
        ({"width": 0}, "positive"),
        ({"fps": Fraction(0)}, "fps"),
        ({"video_codec": "vp9"}, "codec"),
        ({"audio_codec": "opus"}, "audio codec"),
        ({"duration_limit_seconds": Decimal(0)}, "duration"),
        ({"source_refs": ()}, "sources"),
    ],
)
def test_a_malformed_profile_fails_closed(changes: dict, message: str) -> None:
    with pytest.raises(FormatInvalidError, match=message):
        validate_output_profile(profile(**changes))


def test_the_three_v1_ratios_are_accepted_and_digests_are_exact() -> None:
    for width, height in ((1920, 1080), (1080, 1920), (1080, 1080)):
        validate_output_profile(profile(width, height))
    assert profile_digest(profile()) != profile_digest(profile(fps=Fraction(30000, 1001)))


def test_pad_letterboxes_the_whole_source_without_loss() -> None:
    geometry = reframe_geometry(
        source_width=1920, source_height=1080, target_width=1080, target_height=1920, kind=ReframeKind.PAD, focal=None
    )
    assert geometry.source_window == Box(F(0), F(0), F(1), F(1))
    assert geometry.removed_fraction == 0
    # A 16:9 frame in a 9:16 canvas fills the width and 81/256 of the height, centred.
    assert geometry.target_window == Box(F(0), F(175, 512), F(1), F(337, 512))


def test_cover_crops_the_centre_or_follows_the_focal_span() -> None:
    center = reframe_geometry(
        source_width=1920,
        source_height=1080,
        target_width=1080,
        target_height=1920,
        kind=ReframeKind.COVER_CENTER,
        focal=None,
    )
    assert center.source_window == Box(F(175, 512), F(0), F(337, 512), F(1))
    assert center.removed_fraction == F(175, 256)

    focal = Box(F(1, 20), F(1, 4), F(1, 5), F(3, 4))
    left = reframe_geometry(
        source_width=1920,
        source_height=1080,
        target_width=1080,
        target_height=1920,
        kind=ReframeKind.COVER_FOCAL,
        focal=focal,
    )
    assert left.source_window.x0 == 0
    assert left.source_window.x1 == F(81, 256)
    with pytest.raises(FormatInvalidError, match="does not fit"):
        reframe_geometry(
            source_width=1920,
            source_height=1080,
            target_width=1080,
            target_height=1920,
            kind=ReframeKind.COVER_FOCAL,
            focal=Box(F(0), F(0), F(9, 10), F(1)),
        )
    with pytest.raises(FormatInvalidError, match="focal span"):
        reframe_geometry(
            source_width=1920,
            source_height=1080,
            target_width=1080,
            target_height=1920,
            kind=ReframeKind.COVER_FOCAL,
            focal=None,
        )


def test_risk_follows_how_much_of_the_source_a_reframe_removes() -> None:
    vertical = profile()
    assert (
        reframe_decision(
            decision_id="d",
            kind=ReframeKind.PAD,
            source_size=(1920, 1080),
            profile=vertical,
            focal=None,
            rationale="keep all",
        ).semantic_risk
        == "LOW"
    )
    assert (
        reframe_decision(
            decision_id="d",
            kind=ReframeKind.COVER_CENTER,
            source_size=(1920, 1080),
            profile=vertical,
            focal=None,
            rationale="fill",
        ).semantic_risk
        == "HIGH"
    )
    square = profile(1080, 1080)
    # 16:9 into 1:1 removes 7/16 of the source; 4:3 into 1:1 removes 1/4.
    wide = reframe_decision(
        decision_id="d",
        kind=ReframeKind.COVER_CENTER,
        source_size=(1920, 1080),
        profile=square,
        focal=None,
        rationale="fill",
    )
    four_three = reframe_decision(
        decision_id="d",
        kind=ReframeKind.COVER_CENTER,
        source_size=(1440, 1080),
        profile=square,
        focal=None,
        rationale="fill",
    )
    assert (wide.semantic_risk, four_three.semantic_risk) == ("HIGH", "MEDIUM")
    with pytest.raises(FormatInvalidError, match="rationale"):
        reframe_decision(
            decision_id="d", kind=ReframeKind.PAD, source_size=(1920, 1080), profile=vertical, focal=None, rationale=" "
        )


def _plan(regions=(), focal: Box | None = None, kind: ReframeKind = ReframeKind.COVER_FOCAL, target=None):
    target = target or profile()
    decision = reframe_decision(
        decision_id="r1", kind=kind, source_size=(1920, 1080), profile=target, focal=focal, rationale="keep the speaker"
    )
    return build_plan(
        plan_id="p1",
        source_master_id="episode_video:1@v3",
        source_master_digest=DIGEST,
        profile=target,
        overlay=overlay(regions),
        decisions=(decision,),
    )


def test_a_plan_digest_binds_master_profile_overlay_and_reframe() -> None:
    focal = Box(F(2, 5), F(1, 4), F(3, 5), F(3, 4))
    plan = _plan(focal=focal)
    verify_plan_digest(plan)
    assert plan.plan_digest != _plan(focal=Box(F(2, 5), F(1, 4), F(1, 2), F(3, 4))).plan_digest
    changed_master = plan.model_copy(update={"source_master_digest": "sha256:" + "b" * 64})
    with pytest.raises(FormatInvalidError, match="digest"):
        verify_plan_digest(changed_master)
    with pytest.raises(FormatInvalidError, match="platform surface"):
        build_plan(
            plan_id="p",
            source_master_id="m",
            source_master_digest=DIGEST,
            profile=profile(),
            overlay=overlay(surface="story"),
            decisions=plan.reframe_decisions,
        )
    with pytest.raises(FormatInvalidError, match="disagree"):
        build_plan(
            plan_id="p",
            source_master_id="m",
            source_master_digest=DIGEST,
            profile=profile(1080, 1080),
            overlay=overlay(),
            decisions=plan.reframe_decisions,
        )


def test_collisions_check_subject_and_captions_for_every_kind() -> None:
    subject = Box(F(2, 5), F(1, 4), F(3, 5), F(3, 4))
    caption = Box(F(1, 4), F(17, 20), F(3, 4), F(19, 20))
    right_rail = {"kind": "ui", "x0": "17/20", "y0": "1/2", "x1": "1", "y1": "9/10"}
    over_face = {"kind": "ui", "x0": "2/5", "y0": "2/5", "x1": "3/5", "y1": "3/5"}
    bottom_bar = {"kind": "ui", "x0": "0", "y0": "11/20", "x1": "1", "y1": "13/20"}

    def plan(kind, regions, focal=None):
        target = profile()
        decision = reframe_decision(
            decision_id="r1",
            kind=kind,
            source_size=(1920, 1080),
            profile=target,
            focal=focal,
            subject=subject,
            captions=(caption,),
            rationale="fixture",
        )
        return build_plan(
            plan_id="p",
            source_master_id="m",
            source_master_digest=DIGEST,
            profile=target,
            overlay=overlay(regions),
            decisions=(decision,),
        )

    assert overlay_collisions(plan(ReframeKind.COVER_FOCAL, [right_rail], focal=subject)) == (
        "caption 0 partly cropped",
        "ui region 0 covers caption 0",
    )
    # PAD keeps everything but a UI region can still sit on the subject.
    assert overlay_collisions(plan(ReframeKind.PAD, [over_face])) == ("ui region 0 covers subject",)
    # A bar across the letterboxed band covers the caption, not the subject.
    assert "ui region 0 covers caption 0" in overlay_collisions(plan(ReframeKind.PAD, [bottom_bar]))
    assert overlay_collisions(plan(ReframeKind.COVER_CENTER, [])) == ("caption 0 partly cropped",)
    with pytest.raises(FormatInvalidError, match="kind"):
        plan(ReframeKind.PAD, [{"kind": "banner", "x0": "0", "y0": "0", "x1": "1", "y1": "1"}])


def test_a_plan_whose_spans_or_risk_disagree_with_its_kind_is_refused() -> None:
    from r2.advanced_creative.digests import digest_canonical
    from r2.advanced_creative.formats import _plan_body, validate_plan

    honest = _plan(kind=ReframeKind.COVER_CENTER)
    decision = honest.reframe_decisions[0]
    for forged_decision in (
        decision.model_copy(update={"kind": "PAD"}),
        decision.model_copy(update={"semantic_risk": "LOW"}),
    ):
        forged = honest.model_copy(update={"reframe_decisions": (forged_decision,)})
        forged = forged.model_copy(update={"plan_digest": digest_canonical(_plan_body(forged))})
        with pytest.raises(FormatInvalidError, match="disagree"):
            validate_plan(forged)
    rehashed = honest.model_copy(update={"reframe_decisions": (decision, decision)})
    rehashed = rehashed.model_copy(update={"plan_digest": digest_canonical(_plan_body(rehashed))})
    with pytest.raises(FormatInvalidError, match="exactly one"):
        validate_plan(rehashed)


def test_more_profile_and_geometry_guards() -> None:
    with pytest.raises(FormatInvalidError, match="fps"):
        validate_output_profile(profile(fps=Fraction(240)))
    with pytest.raises(FormatInvalidError, match="container"):
        validate_output_profile(profile(container="mov"))
    with pytest.raises(FormatInvalidError, match="PAD keeps"):
        reframe_geometry(
            source_width=1920,
            source_height=1080,
            target_width=1080,
            target_height=1080,
            kind=ReframeKind.PAD,
            focal=Box(F(0), F(0), F(1, 2), F(1, 2)),
        )
    with pytest.raises(FormatInvalidError, match="centred"):
        reframe_geometry(
            source_width=1920,
            source_height=1080,
            target_width=1080,
            target_height=1080,
            kind=ReframeKind.COVER_CENTER,
            focal=Box(F(0), F(0), F(1, 2), F(1, 2)),
        )
    # A portrait source into a landscape target crops vertically.
    portrait = reframe_geometry(
        source_width=1080,
        source_height=1920,
        target_width=1920,
        target_height=1080,
        kind=ReframeKind.COVER_CENTER,
        focal=None,
    )
    assert (portrait.source_window.x0, portrait.source_window.x1) == (0, 1)
    assert portrait.source_window.y1 - portrait.source_window.y0 == F(81, 256)
    # Equal ratios remove nothing either way.
    same = reframe_geometry(
        source_width=1920,
        source_height=1080,
        target_width=1280,
        target_height=720,
        kind=ReframeKind.COVER_CENTER,
        focal=None,
    )
    assert same.removed_fraction == 0


def full_checks(plan=None, **overrides) -> tuple[dict, ...]:
    """A complete, consistent technical check set for ``plan`` (every check passing)."""
    from r2.advanced_creative.formats import overlay_collisions, reduced_ratio

    plan = plan or _plan(kind=ReframeKind.PAD)
    target = plan.output_profile
    ratio = "{}:{}".format(*reduced_ratio(target.width, target.height))
    collisions = list(overlay_collisions(plan))
    rows = {
        "dimensions": {"observed": f"{target.width}x{target.height}", "expected": f"{target.width}x{target.height}"},
        "ratio": {"observed": ratio, "expected": ratio},
        "video_codec": {"observed": "h264", "expected": "h264"},
        "fps": {"observed": str(target.fps), "expected": str(target.fps)},
        "duration": {"observed": "2.000", "expected": "2.000"},
        "audio": {"observed": ["aac"], "expected": ["aac"]},
        "decode": {"observed": 0, "expected": 0},
        "overlay": {"observed": collisions, "expected": []},
    }
    for name, row in rows.items():
        row["name"] = name
        row["verdict"] = "PASS" if name != "overlay" or not collisions else "FAIL"
    rows.update(overrides)
    return tuple(rows.values())


def _technical(plan, checks, passed):
    from r2.contracts.advanced_creative import TechnicalValidationReport

    return TechnicalValidationReport(
        report_id="t1", plan_digest=plan.plan_digest, artifact_digest=DIGEST, checks=checks, passed=passed
    )


def _review(reviewer: str, failing: tuple[str, ...] = ()) -> dict:
    from r2.advanced_creative.formats import SEMANTIC_ITEMS

    return {
        "reviewer_id": reviewer,
        "grant_event_digest": "sha256:" + "a" * 64,
        "items": {item: "FAIL" if item in failing else "PASS" for item in SEMANTIC_ITEMS},
    }


def _semantic(plan, reviews, *, disagreement=False, passed=True):
    from r2.contracts.advanced_creative import SemanticParityReport

    return SemanticParityReport(
        report_id="s1",
        plan_digest=plan.plan_digest,
        source_master_digest=plan.source_master_digest,
        artifact_digest=DIGEST,
        rubric_version="format-semantic@1",
        reviews=reviews,
        material_disagreement=disagreement,
        passed=passed,
    )


def test_a_technical_report_passes_exactly_when_every_check_passes() -> None:
    from r2.advanced_creative.formats import validate_technical_report

    plan = _subject_plan()
    good = full_checks(plan)
    validate_technical_report(_technical(plan, good, True), plan)
    failing = full_checks(plan, decode={"name": "decode", "observed": 3, "expected": 0, "verdict": "FAIL"})
    validate_technical_report(_technical(plan, failing, False), plan)
    with pytest.raises(FormatInvalidError, match="exactly when"):
        validate_technical_report(_technical(plan, failing, True), plan)
    with pytest.raises(FormatInvalidError, match="unique"):
        validate_technical_report(_technical(plan, good + good[:1], True), plan)
    with pytest.raises(FormatInvalidError, match="versioned check set"):
        validate_technical_report(_technical(plan, good[:1], True), plan)
    # A report cannot agree with itself on another fps than its plan's.
    other_fps = full_checks(plan, fps={"name": "fps", "observed": "25", "expected": "25", "verdict": "PASS"})
    with pytest.raises(FormatInvalidError, match="fps expectation"):
        validate_technical_report(_technical(plan, other_fps, True), plan)
    hidden_errors = full_checks(plan, decode={"name": "decode", "observed": 2, "expected": 0, "verdict": "PASS"})
    with pytest.raises(FormatInvalidError, match="decode verdict"):
        validate_technical_report(_technical(plan, hidden_errors, True), plan)
    no_subject = _plan(kind=ReframeKind.PAD)
    with pytest.raises(FormatInvalidError, match="collision analysis"):
        validate_technical_report(_technical(no_subject, full_checks(plan), True), no_subject)
    slow = full_checks(plan, duration={"name": "duration", "observed": "2.200", "expected": "2.000", "verdict": "PASS"})
    with pytest.raises(FormatInvalidError, match="duration verdict"):
        validate_technical_report(_technical(plan, slow, True), plan)


def _subject_plan():
    target = profile()
    decision = reframe_decision(
        decision_id="r1",
        kind=ReframeKind.PAD,
        source_size=(1920, 1080),
        profile=target,
        focal=None,
        subject=Box(F(2, 5), F(1, 4), F(3, 5), F(3, 4)),
        rationale="keep all",
    )
    return build_plan(
        plan_id="p1",
        source_master_id="m@v1",
        source_master_digest=DIGEST,
        profile=target,
        overlay=overlay(),
        decisions=(decision,),
    )


def test_semantic_reports_need_two_reviewers_or_the_recorded_deviation() -> None:
    from r2.advanced_creative.formats import SINGLE_REVIEWER_DEVIATION, validate_semantic_report

    plan = _plan(kind=ReframeKind.PAD)
    assert validate_semantic_report(_semantic(plan, (_review("a"), _review("b"))), plan, deviation=None) == 2
    with pytest.raises(FormatInvalidError, match="deviation"):
        validate_semantic_report(_semantic(plan, (_review("a"),)), plan, deviation=None)
    assert validate_semantic_report(_semantic(plan, (_review("a"),)), plan, deviation=SINGLE_REVIEWER_DEVIATION) == 1

    split = (_review("a"), _review("b", failing=("captions",)))
    validate_semantic_report(_semantic(plan, split, disagreement=True, passed=False), plan, deviation=None)
    with pytest.raises(FormatInvalidError, match="disagreement"):
        validate_semantic_report(_semantic(plan, split, passed=False), plan, deviation=None)
    with pytest.raises(FormatInvalidError, match="every reviewer passes"):
        validate_semantic_report(
            _semantic(plan, (_review("a", failing=("audio",)), _review("b", failing=("audio",)))), plan, deviation=None
        )
    with pytest.raises(FormatInvalidError, match="distinct reviewer"):
        validate_semantic_report(_semantic(plan, (_review("a"), _review("a"))), plan, deviation=None)
    # A review that names no authorizing showrunner grant is refused, also under the deviation.
    ungranted = {key: value for key, value in _review("a").items() if key != "grant_event_digest"}
    with pytest.raises(FormatInvalidError, match="showrunner grant"):
        validate_semantic_report(_semantic(plan, (ungranted,)), plan, deviation=SINGLE_REVIEWER_DEVIATION)


def test_overlay_analysis_uses_the_even_pixel_crop_not_the_ideal_window() -> None:
    from r2.advanced_creative.formats import overlay_collisions, pixel_geometry

    target = profile(1080, 1080, profile_ref="square@1")
    # Centre-cropping 1282x720 to a square keeps source pixels 281..1001 ideally; the even crop keeps 280..1000.
    edge = F(1001, 1282)
    decision = reframe_decision(
        decision_id="r1",
        kind=ReframeKind.COVER_CENTER,
        source_size=(1282, 720),
        profile=target,
        focal=None,
        subject=Box(F(2, 5), F(1, 4), F(3, 5), F(3, 4)),
        captions=(Box(F(1, 2), F(4, 5), edge, F(9, 10)),),
        rationale="centre crop",
    )
    plan = build_plan(
        plan_id="p1",
        source_master_id="episode_video:1@v3",
        source_master_digest=DIGEST,
        profile=target,
        overlay=overlay(),
        decisions=(decision,),
    )
    window = decision.source_span.model_dump(mode="python")
    assert Box.parse(window).x1 == edge
    geometry = pixel_geometry(plan, source_width=1282, source_height=720)
    assert (geometry.crop_x, geometry.crop_x + geometry.crop_width) == (280, 1000)
    assert overlay_collisions(plan) == ("caption 0 partly cropped",)
