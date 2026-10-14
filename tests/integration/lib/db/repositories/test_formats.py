"""M8-E format projection persistence on a real database (E1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from fractions import Fraction

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.formats import FormatRepository
from r2.advanced_creative.errors import FormatConflictError, FormatNotFoundError
from r2.advanced_creative.formats import (
    SINGLE_REVIEWER_DEVIATION,
    Box,
    FormatInvalidError,
    ReframeKind,
    build_plan,
    reframe_decision,
)
from r2.contracts.advanced_creative import SemanticParityReport, TechnicalValidationReport
from tests.unit.r2.advanced_creative.test_formats import DIGEST, _review, full_checks, overlay, profile

type Factory = async_sessionmaker[AsyncSession]

USER = "default"
PROJECT = "demo"
ARTIFACT = "sha256:" + "c" * 64


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 14, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


CLOCK = _Clock()


async def _call(factory: Factory, method: str, **kwargs):
    async with factory() as session:
        result = await getattr(FormatRepository(session, clock=CLOCK), method)(
            user_id=USER, project_name=kwargs.pop("project_name", PROJECT), **kwargs
        )
        await session.commit()
        return result


def _plan(plan_id: str = "p1", focal_right: Fraction = Fraction(3, 5)):
    target = profile()
    decision = reframe_decision(
        decision_id="r1",
        kind=ReframeKind.COVER_FOCAL,
        source_size=(1920, 1080),
        profile=target,
        focal=Box(Fraction(2, 5), Fraction(1, 4), focal_right, Fraction(3, 4)),
        rationale="keep the speaker",
    )
    return build_plan(
        plan_id=plan_id,
        source_master_id="episode_video:1@v3",
        source_master_digest=DIGEST,
        profile=target,
        overlay=overlay(),
        decisions=(decision,),
    )


def _technical(plan, report_id: str, passed: bool = True) -> TechnicalValidationReport:
    return TechnicalValidationReport(
        report_id=report_id,
        plan_digest=plan.plan_digest,
        artifact_digest=ARTIFACT,
        checks=full_checks(plan)
        if passed
        else full_checks(plan, decode={"name": "decode", "observed": 2, "expected": 0, "verdict": "FAIL"}),
        passed=passed,
    )


def _semantic(plan, report_id: str, reviews=None) -> SemanticParityReport:
    return SemanticParityReport(
        report_id=report_id,
        plan_digest=plan.plan_digest,
        source_master_digest=plan.source_master_digest,
        artifact_digest=ARTIFACT,
        rubric_version="format-semantic@1",
        reviews=reviews or (_review("sponsor"),),
        material_disagreement=False,
        passed=True,
    )


async def _seed(factory: Factory) -> None:
    await _call(factory, "put_profile", profile=profile())
    await _call(factory, "put_overlay", overlay=overlay())


async def test_profiles_and_overlays_are_exact_and_never_float(session_factory: Factory) -> None:
    await _seed(session_factory)
    await _seed(session_factory)
    with pytest.raises(FormatConflictError, match="profile ref"):
        await _call(session_factory, "put_profile", profile=profile(fps=Fraction(25)))
    with pytest.raises(FormatConflictError, match="overlay ref"):
        await _call(session_factory, "put_overlay", overlay=overlay(locale="en-US"))
    with pytest.raises(FormatInvalidError, match="16:9"):
        await _call(session_factory, "put_profile", profile=profile(1080, 1350))


async def test_a_plan_needs_its_stored_profile_and_overlay_and_a_verified_digest(session_factory: Factory) -> None:
    with pytest.raises(FormatNotFoundError):
        await _call(session_factory, "create_plan", plan=_plan())
    await _seed(session_factory)
    plan = _plan()
    assert await _call(session_factory, "create_plan", plan=plan) == plan
    assert await _call(session_factory, "create_plan", plan=plan) == plan
    with pytest.raises(FormatConflictError, match="plan id"):
        await _call(session_factory, "create_plan", plan=_plan(focal_right=Fraction(1, 2)))
    with pytest.raises(FormatInvalidError, match="digest"):
        await _call(
            session_factory,
            "create_plan",
            plan=plan.model_copy(update={"plan_id": "p2", "source_master_digest": "sha256:" + "d" * 64}),
        )
    assert await _call(session_factory, "get_plan", plan_id="p1", project_name="other") is None


async def test_both_planes_must_pass_for_the_same_artifact(session_factory: Factory) -> None:
    await _seed(session_factory)
    plan = await _call(session_factory, "create_plan", plan=_plan())

    await _call(session_factory, "append_technical_report", plan_id="p1", report=_technical(plan, "t1"))
    assert await _call(session_factory, "passing_reports", plan_id="p1", artifact_digest=ARTIFACT) is None
    with pytest.raises(FormatInvalidError, match="deviation"):
        await _call(
            session_factory, "append_semantic_report", plan_id="p1", report=_semantic(plan, "s1"), deviation=None
        )
    await _call(
        session_factory,
        "append_semantic_report",
        plan_id="p1",
        report=_semantic(plan, "s1"),
        deviation=SINGLE_REVIEWER_DEVIATION,
    )
    technical, semantic = await _call(session_factory, "passing_reports", plan_id="p1", artifact_digest=ARTIFACT)
    assert (technical.report_id, semantic.report_id) == ("t1", "s1")
    assert await _call(session_factory, "passing_reports", plan_id="p1", artifact_digest=DIGEST) is None

    # A later failing technical report supersedes the earlier pass.
    await _call(session_factory, "append_technical_report", plan_id="p1", report=_technical(plan, "t2", passed=False))
    assert await _call(session_factory, "passing_reports", plan_id="p1", artifact_digest=ARTIFACT) is None
    with pytest.raises(FormatConflictError, match="report id"):
        await _call(
            session_factory, "append_technical_report", plan_id="p1", report=_technical(plan, "t1", passed=False)
        )
    with pytest.raises(FormatNotFoundError):
        await _call(session_factory, "append_technical_report", plan_id="nope", report=_technical(plan, "t9"))


async def test_report_order_is_the_append_sequence_not_the_clock(session_factory: Factory) -> None:
    class Frozen:
        def __call__(self) -> datetime:
            return datetime(2026, 10, 14, tzinfo=UTC)

    async def call(method, **kwargs):
        async with session_factory() as session:
            result = await getattr(FormatRepository(session, clock=Frozen()), method)(
                user_id=USER, project_name=PROJECT, **kwargs
            )
            await session.commit()
            return result

    await _seed(session_factory)
    plan = await call("create_plan", plan=_plan())
    await call(
        "append_semantic_report", plan_id="p1", report=_semantic(plan, "s1"), deviation=SINGLE_REVIEWER_DEVIATION
    )
    # Same timestamp; a passing "z" then a failing "a": the failing one was appended later and wins.
    await call("append_technical_report", plan_id="p1", report=_technical(plan, "z"))
    await call("append_technical_report", plan_id="p1", report=_technical(plan, "a", passed=False))
    assert await call("passing_reports", plan_id="p1", artifact_digest=ARTIFACT) is None
    await call("append_technical_report", plan_id="p1", report=_technical(plan, "b"))
    assert (await call("passing_reports", plan_id="p1", artifact_digest=ARTIFACT))[0].report_id == "b"
