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
    with pytest.raises(FormatInvalidError, match="another size"):
        build_plan(
            plan_id="p",
            source_master_id="m",
            source_master_digest=DIGEST,
            profile=profile(1080, 1080),
            overlay=overlay(),
            decisions=plan.reframe_decisions,
        )


def test_ui_regions_collide_with_the_projected_focal_span_only() -> None:
    focal = Box(F(2, 5), F(1, 4), F(3, 5), F(3, 4))
    right_rail = {"kind": "ui", "x0": "17/20", "y0": "1/2", "x1": "1", "y1": "9/10"}
    bottom_caption = {"kind": "caption", "x0": "0", "y0": "4/5", "x1": "1", "y1": "1"}
    over_face = {"kind": "ui", "x0": "2/5", "y0": "2/5", "x1": "3/5", "y1": "3/5"}

    assert overlay_collisions(_plan([right_rail, bottom_caption], focal=focal)) == ()
    assert overlay_collisions(_plan([right_rail, over_face], focal=focal)) == ("ui region 1",)
    with pytest.raises(FormatInvalidError, match="kind"):
        _plan([{"kind": "banner", "x0": "0", "y0": "0", "x1": "1", "y1": "1"}], focal=focal)


def _technical(plan, checks, passed):
    from r2.contracts.advanced_creative import TechnicalValidationReport

    return TechnicalValidationReport(
        report_id="t1", plan_digest=plan.plan_digest, artifact_digest=DIGEST, checks=checks, passed=passed
    )


def _review(reviewer: str, failing: tuple[str, ...] = ()) -> dict:
    from r2.advanced_creative.formats import SEMANTIC_ITEMS

    return {"reviewer_id": reviewer, "items": {item: "FAIL" if item in failing else "PASS" for item in SEMANTIC_ITEMS}}


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

    plan = _plan(kind=ReframeKind.PAD)
    good = ({"name": "dimensions", "verdict": "PASS"}, {"name": "decode", "verdict": "PASS"})
    validate_technical_report(_technical(plan, good, True), plan)
    with pytest.raises(FormatInvalidError, match="exactly when"):
        validate_technical_report(_technical(plan, ({"name": "decode", "verdict": "FAIL"},), True), plan)
    with pytest.raises(FormatInvalidError, match="unique"):
        validate_technical_report(_technical(plan, good + good, True), plan)


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
