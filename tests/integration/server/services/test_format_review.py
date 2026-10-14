"""Blind semantic review of rendered projections (M8-E E3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.formats import FormatRepository
from r2.advanced_creative.errors import FormatConflictError, FormatNotFoundError
from r2.advanced_creative.formats import SEMANTIC_ITEMS, FormatInvalidError
from server.services.format_render import ffmpeg_available, file_digest
from server.services.format_review import FormatReviewService
from tests.integration.server.services.test_format_validation import PROJECT, USER, _render

type Factory = async_sessionmaker[AsyncSession]

pytestmark = pytest.mark.skipif(not ffmpeg_available(), reason="needs ffmpeg and ffprobe")

ALL_PASS = dict.fromkeys(SEMANTIC_ITEMS, "PASS")


async def _open(factory: Factory, tmp_path: Path, execution_id: str, reviewer: str = "sponsor"):
    return await FormatReviewService(factory).open_packet(
        user_id=USER,
        project_name=PROJECT,
        project_dir=tmp_path,
        execution_id=execution_id,
        source_ref="master.mp4",
        reviewer_id=reviewer,
    )


async def test_a_blind_packet_hides_which_clip_is_the_projection(session_factory: Factory, tmp_path: Path) -> None:
    source, result = await _render(session_factory, tmp_path)
    packet = await _open(session_factory, tmp_path, result.execution_id)
    service = FormatReviewService(session_factory)

    clips = {
        label: await service.clip(
            user_id=USER,
            project_name=PROJECT,
            project_dir=tmp_path,
            packet_id=packet.packet_id,
            label=label,
            reviewer_id="sponsor",
        )
        for label in ("A", "B")
    }
    assert {file_digest(path) for path in clips.values()} == {file_digest(source), result.artifact_digest}
    assert packet.items == SEMANTIC_ITEMS
    with pytest.raises(FormatNotFoundError):
        await service.clip(
            user_id=USER,
            project_name=PROJECT,
            project_dir=tmp_path,
            packet_id=packet.packet_id,
            label="A",
            reviewer_id="someone",
        )
    with pytest.raises(FormatInvalidError, match="inside the project"):
        await service.open_packet(
            user_id=USER,
            project_name=PROJECT,
            project_dir=tmp_path,
            execution_id=result.execution_id,
            source_ref="../x.mp4",
            reviewer_id="r",
        )


async def test_a_single_review_produces_a_report_with_the_recorded_deviation(
    session_factory: Factory, tmp_path: Path
) -> None:
    _source, result = await _render(session_factory, tmp_path)
    packet = await _open(session_factory, tmp_path, result.execution_id)
    service = FormatReviewService(session_factory)

    report = await service.submit(
        user_id=USER,
        project_name=PROJECT,
        packet_id=packet.packet_id,
        reviewer_id="sponsor",
        items=ALL_PASS,
        note="same meaning",
    )
    assert (report.passed, report.material_disagreement, len(report.reviews)) == (True, False, 1)
    assert report.artifact_digest == result.artifact_digest

    with pytest.raises(FormatConflictError, match="already has its review"):
        await service.submit(
            user_id=USER,
            project_name=PROJECT,
            packet_id=packet.packet_id,
            reviewer_id="sponsor",
            items=ALL_PASS,
            note="",
        )
    second = await _open(session_factory, tmp_path, result.execution_id)
    with pytest.raises(FormatConflictError, match="already reviewed"):
        await service.submit(
            user_id=USER,
            project_name=PROJECT,
            packet_id=second.packet_id,
            reviewer_id="sponsor",
            items=ALL_PASS,
            note="",
        )
    with pytest.raises(FormatInvalidError, match="every rubric item"):
        await service.submit(
            user_id=USER,
            project_name=PROJECT,
            packet_id=second.packet_id,
            reviewer_id="sponsor",
            items={"audio": "PASS"},
            note="",
        )


async def test_two_reviewers_who_disagree_fail_the_semantic_plane(session_factory: Factory, tmp_path: Path) -> None:
    _source, result = await _render(session_factory, tmp_path)
    service = FormatReviewService(session_factory)
    first = await _open(session_factory, tmp_path, result.execution_id, reviewer="a")
    second = await _open(session_factory, tmp_path, result.execution_id, reviewer="b")

    await service.submit(
        user_id=USER, project_name=PROJECT, packet_id=first.packet_id, reviewer_id="a", items=ALL_PASS, note=""
    )
    report = await service.submit(
        user_id=USER,
        project_name=PROJECT,
        packet_id=second.packet_id,
        reviewer_id="b",
        items={**ALL_PASS, "captions": "FAIL"},
        note="caption cut",
    )
    assert (report.passed, report.material_disagreement, len(report.reviews)) == (False, True, 2)
    async with session_factory() as session:
        assert (
            await FormatRepository(session).passing_reports(
                user_id=USER, project_name=PROJECT, plan_id="plan-1", artifact_digest=result.artifact_digest
            )
            is None
        )
