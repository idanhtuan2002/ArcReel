"""Technical validation measures the rendered projection (M8-E E3)."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.formats import FormatRepository
from r2.advanced_creative.errors import FormatConflictError
from r2.advanced_creative.formats import Box, ReframeKind, build_plan, reframe_decision
from server.services.format_render import FormatRenderService, ffmpeg_available, file_digest
from server.services.format_validation import FormatValidationService
from tests.integration.r2.advanced_creative.test_format_render import make_source
from tests.unit.r2.advanced_creative.test_formats import overlay, profile

type Factory = async_sessionmaker[AsyncSession]

pytestmark = pytest.mark.skipif(not ffmpeg_available(), reason="needs ffmpeg and ffprobe")

USER = "default"
PROJECT = "demo"


async def _render(factory: Factory, tmp_path: Path, *, regions=(), subject: Box | None = None, audio: bool = True):
    source = make_source(tmp_path / "master.mp4", audio=audio)
    target = profile(1080, 1080, profile_ref="square@1")
    decision = reframe_decision(
        decision_id="r1",
        kind=ReframeKind.PAD,
        source_size=(1280, 720),
        profile=target,
        focal=None,
        subject=subject,
        rationale="keep all",
    )
    plan = build_plan(
        plan_id="plan-1",
        source_master_id="episode_video:1@v1",
        source_master_digest=file_digest(source),
        profile=target,
        overlay=overlay(regions),
        decisions=(decision,),
    )
    async with factory() as session:
        repository = FormatRepository(session)
        await repository.put_profile(user_id=USER, project_name=PROJECT, profile=target)
        await repository.put_overlay(user_id=USER, project_name=PROJECT, overlay=overlay(regions))
        await repository.create_plan(user_id=USER, project_name=PROJECT, plan=plan)
        await session.commit()
    result = await FormatRenderService(factory).render(
        user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id="plan-1", source=source
    )
    return source, result


def _rows(report) -> dict:
    return {row.model_dump()["name"]: row.model_dump() for row in report.checks}


async def test_a_clean_render_passes_every_measured_check(session_factory: Factory, tmp_path: Path) -> None:
    source, result = await _render(session_factory, tmp_path)
    report = await FormatValidationService(session_factory).validate(
        user_id=USER, project_name=PROJECT, project_dir=tmp_path, execution_id=result.execution_id, source=source
    )

    rows = _rows(report)
    assert report.passed
    assert rows["dimensions"]["observed"] == "1080x1080"
    assert rows["ratio"]["observed"] == "1:1"
    assert rows["fps"]["observed"] == "30"
    assert rows["audio"]["observed"] == ["aac"]
    assert rows["decode"]["observed"] == 0
    assert report.artifact_digest == result.artifact_digest
    # Validating the same render again appends nothing new.
    again = await FormatValidationService(session_factory).validate(
        user_id=USER, project_name=PROJECT, project_dir=tmp_path, execution_id=result.execution_id, source=source
    )
    assert again == report


async def test_a_ui_region_over_the_subject_fails_the_overlay_check(session_factory: Factory, tmp_path: Path) -> None:
    subject = Box(Fraction(2, 5), Fraction(1, 4), Fraction(3, 5), Fraction(3, 4))
    over_face = {"kind": "ui", "x0": "2/5", "y0": "2/5", "x1": "3/5", "y1": "3/5"}
    source, result = await _render(session_factory, tmp_path, regions=[over_face], subject=subject)
    report = await FormatValidationService(session_factory).validate(
        user_id=USER, project_name=PROJECT, project_dir=tmp_path, execution_id=result.execution_id, source=source
    )

    rows = _rows(report)
    assert not report.passed
    assert rows["overlay"]["verdict"] == "FAIL"
    assert rows["overlay"]["observed"] == ["ui region 0 covers subject"]
    assert rows["dimensions"]["verdict"] == "PASS"


async def test_a_changed_artifact_or_another_source_is_refused(session_factory: Factory, tmp_path: Path) -> None:
    source, result = await _render(session_factory, tmp_path, audio=False)
    other = make_source(tmp_path / "other.mp4", seconds=1)
    service = FormatValidationService(session_factory)
    with pytest.raises(FormatConflictError, match="not the master"):
        await service.validate(
            user_id=USER, project_name=PROJECT, project_dir=tmp_path, execution_id=result.execution_id, source=other
        )
    result.artifact_path.write_bytes(b"tampered")
    with pytest.raises(FormatConflictError, match="changed"):
        await service.validate(
            user_id=USER, project_name=PROJECT, project_dir=tmp_path, execution_id=result.execution_id, source=source
        )
