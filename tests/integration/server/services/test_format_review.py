"""Blind semantic review of rendered projections (M8-E E3)."""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.formats import FormatReviewPacketModel, FormatSemanticReportModel
from lib.db.repositories.formats import FormatRepository, report_digest
from r2.advanced_creative.errors import FormatConflictError, FormatNotFoundError
from r2.advanced_creative.formats import SEMANTIC_ITEMS, FormatInvalidError
from r2.contracts.advanced_creative import CanonicalJsonObject, SemanticParityReport
from server.services.format_render import ffmpeg_available, file_digest
from server.services.format_review import FormatReviewService
from server.services.format_validation import FormatValidationService, media_facts
from server.services.governance_grants import CurrentShowrunnerGrantReader, ShowrunnerGrantUnavailableError
from tests.integration.server.routers.spatial_approval_support import showrunner_grants
from tests.integration.server.services.test_format_validation import PROJECT, USER, _render

type Factory = async_sessionmaker[AsyncSession]

pytestmark = pytest.mark.skipif(not ffmpeg_available(), reason="needs ffmpeg and ffprobe")

ALL_PASS = dict.fromkeys(SEMANTIC_ITEMS, "PASS")


async def granted(factory: Factory, *principals: str) -> CurrentShowrunnerGrantReader:
    """A grant reader after importing a current showrunner grant for each principal."""
    reader = None
    for principal in principals:
        reader = await showrunner_grants(factory, user_id=USER, project_name=PROJECT, principal=principal)
    assert reader is not None
    return reader


async def _open(service: FormatReviewService, tmp_path: Path, execution_id: str, reviewer: str = "sponsor"):
    return await service.open_packet(
        user_id=USER,
        project_name=PROJECT,
        project_dir=tmp_path,
        execution_id=execution_id,
        source_ref="master.mp4",
        reviewer_id=reviewer,
    )


async def test_a_blind_packet_serves_neutral_copies_that_hide_the_projection(
    session_factory: Factory, tmp_path: Path
) -> None:
    source, result = await _render(session_factory, tmp_path)
    service = FormatReviewService(session_factory, grants=await granted(session_factory, "sponsor", "sponsor-2"))
    packet = await _open(service, tmp_path, result.execution_id)

    clips = {}
    for label in ("A", "B"):
        path, digest = await service.clip(
            user_id=USER,
            project_name=PROJECT,
            project_dir=tmp_path,
            packet_id=packet.packet_id,
            label=label,
            reviewer_id="sponsor",
        )
        assert file_digest(path) == digest
        clips[label] = path
    # Neither copy has the bytes, digest or name of a recorded file.
    recorded = {file_digest(source), result.artifact_digest}
    assert not {file_digest(path) for path in clips.values()} & recorded
    assert not any(digest.removeprefix("sha256:") in path.name for path in clips.values() for digest in recorded)
    # The copies still show the source and the projection, in the order the server drew.
    async with session_factory() as session:
        row = await session.get(FormatReviewPacketModel, (USER, PROJECT, packet.packet_id))
    assert row is not None
    assert row.grant_event_digest is not None
    sizes = {label: (await media_facts(path)).width for label, path in clips.items()}
    assert sizes[row.projection_label] == 1080
    assert sizes["B" if row.projection_label == "A" else "A"] == 1280
    # A second packet of the same render gets different copies.
    other = await _open(service, tmp_path, result.execution_id)
    other_path, _digest = await service.clip(
        user_id=USER,
        project_name=PROJECT,
        project_dir=tmp_path,
        packet_id=other.packet_id,
        label="A",
        reviewer_id="sponsor",
    )
    assert file_digest(other_path) not in {file_digest(path) for path in clips.values()}

    # Another granted reviewer cannot fetch this reviewer's clips.
    with pytest.raises(FormatNotFoundError):
        await service.clip(
            user_id=USER,
            project_name=PROJECT,
            project_dir=tmp_path,
            packet_id=packet.packet_id,
            label="A",
            reviewer_id="sponsor-2",
        )
    with pytest.raises(FormatInvalidError, match="inside the project"):
        await service.open_packet(
            user_id=USER,
            project_name=PROJECT,
            project_dir=tmp_path,
            execution_id=result.execution_id,
            source_ref="../x.mp4",
            reviewer_id="sponsor",
        )


async def test_only_a_reviewer_with_a_current_showrunner_grant_can_review(
    session_factory: Factory, tmp_path: Path
) -> None:
    _source, result = await _render(session_factory, tmp_path)
    service = FormatReviewService(session_factory, grants=await granted(session_factory, "sponsor"))
    packet = await _open(service, tmp_path, result.execution_id)

    with pytest.raises(ShowrunnerGrantUnavailableError):
        await _open(service, tmp_path, result.execution_id, reviewer="self-assigned")
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await service.submit(
            user_id=USER,
            project_name=PROJECT,
            packet_id=packet.packet_id,
            reviewer_id="self-assigned",
            items=ALL_PASS,
            note="",
        )
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(FormatReviewPacketModel))
    assert count == 1


async def test_a_single_review_binds_the_deviation_to_the_reviewers_grant(
    session_factory: Factory, tmp_path: Path
) -> None:
    _source, result = await _render(session_factory, tmp_path)
    service = FormatReviewService(session_factory, grants=await granted(session_factory, "sponsor"))
    packet = await _open(service, tmp_path, result.execution_id)

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
    async with session_factory() as session:
        row = await session.get(FormatReviewPacketModel, (USER, PROJECT, packet.packet_id))
    assert row is not None
    assert report.reviews[0].model_dump(mode="python")["grant_event_digest"] == row.grant_event_digest

    with pytest.raises(FormatConflictError, match="already has its review"):
        await service.submit(
            user_id=USER,
            project_name=PROJECT,
            packet_id=packet.packet_id,
            reviewer_id="sponsor",
            items=ALL_PASS,
            note="",
        )
    second = await _open(service, tmp_path, result.execution_id)
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
    service = FormatReviewService(session_factory, grants=await granted(session_factory, "a", "b"))
    first = await _open(service, tmp_path, result.execution_id, reviewer="a")
    second = await _open(service, tmp_path, result.execution_id, reviewer="b")

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


async def wait_for_advisory_waiter(factory: Factory) -> None:
    """Return once some backend waits on a transaction advisory lock (PostgreSQL)."""
    async with asyncio.timeout(10):
        while True:
            async with factory() as observer:
                waiting = await observer.scalar(
                    text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted")
                )
            if waiting:
                return
            await asyncio.sleep(0.01)


async def test_a_review_waits_for_a_concurrent_review_and_aggregates_it(
    concurrent_session_factory: Factory, tmp_path: Path
) -> None:
    factory = concurrent_session_factory
    async with factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("requires PostgreSQL transaction advisory locks")
    _source, result = await _render(factory, tmp_path)
    service = FormatReviewService(factory, grants=await granted(factory, "a", "b"))
    first = await _open(service, tmp_path, result.execution_id, reviewer="a")
    second = await _open(service, tmp_path, result.execution_id, reviewer="b")

    # Reviewer a's transaction holds the plan's report lock while b submits.
    async with factory() as holder, holder.begin():
        await FormatRepository(holder).lock_plan_reports(user_id=USER, project_name=PROJECT, plan_id="plan-1")
        waiter = asyncio.create_task(
            service.submit(
                user_id=USER, project_name=PROJECT, packet_id=second.packet_id, reviewer_id="b", items=ALL_PASS, note=""
            )
        )
        await wait_for_advisory_waiter(factory)
        packet = await holder.get(FormatReviewPacketModel, (USER, PROJECT, first.packet_id))
        assert packet is not None
        packet.review_json = {
            "reviewer_id": "a",
            "grant_event_digest": packet.grant_event_digest,
            "items": {**ALL_PASS, "timing": "FAIL"},
            "note": "",
        }
    report = await waiter
    assert [review.model_dump(mode="python")["reviewer_id"] for review in report.reviews] == ["a", "b"]
    assert (report.material_disagreement, report.passed) == (True, False)


def _video_stream_md5(path: Path) -> str:
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "md5", "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


async def test_review_copies_share_no_compressed_stream_with_the_recorded_files(
    session_factory: Factory, tmp_path: Path
) -> None:
    source, result = await _render(session_factory, tmp_path)
    service = FormatReviewService(session_factory, grants=await granted(session_factory, "sponsor"))
    packet = await _open(service, tmp_path, result.execution_id)
    recorded = {_video_stream_md5(source), _video_stream_md5(result.artifact_path)}
    for label in ("A", "B"):
        path, _digest = await service.clip(
            user_id=USER,
            project_name=PROJECT,
            project_dir=tmp_path,
            packet_id=packet.packet_id,
            label=label,
            reviewer_id="sponsor",
        )
        assert _video_stream_md5(path) not in recorded


async def test_a_review_recorded_without_a_grant_is_neither_evidence_nor_aggregated(
    session_factory: Factory, tmp_path: Path
) -> None:
    _source, result = await _render(session_factory, tmp_path)
    service = FormatReviewService(session_factory, grants=await granted(session_factory, "sponsor"))
    legacy = await _open(service, tmp_path, result.execution_id)
    # A review and a passing report as stored before reviews named their grant.
    legacy_review = {"reviewer_id": "sponsor", "items": {**ALL_PASS, "audio": "FAIL"}, "note": ""}
    async with session_factory() as session, session.begin():
        row = await session.get(FormatReviewPacketModel, (USER, PROJECT, legacy.packet_id))
        assert row is not None
        row.review_json = legacy_review
        plan = await FormatRepository(session).get_plan(user_id=USER, project_name=PROJECT, plan_id="plan-1")
        assert plan is not None
        report = SemanticParityReport(
            # The id an aggregation of the same reviewer had before ids covered grants.
            report_id="sem-"
            + hashlib.sha256(f"plan-1\x1f{result.artifact_digest}\x1fsponsor".encode()).hexdigest()[:32],
            plan_digest=plan.plan_digest,
            source_master_digest=plan.source_master_digest,
            artifact_digest=result.artifact_digest,
            rubric_version="format-semantic@1",
            reviews=(CanonicalJsonObject.model_validate({"reviewer_id": "sponsor", "items": ALL_PASS}),),
            material_disagreement=False,
            passed=True,
        )
        session.add(
            FormatSemanticReportModel(
                sequence=1,
                user_id=USER,
                project_name=PROJECT,
                report_id=report.report_id,
                plan_id="plan-1",
                artifact_digest=result.artifact_digest,
                report_json=report.model_dump(mode="json"),
                report_digest=report_digest(report),
                reviewer_count=1,
                deviation=None,
                passed=True,
                created_at=datetime.now(UTC),
            )
        )
    technical = await FormatValidationService(session_factory).validate(
        user_id=USER,
        project_name=PROJECT,
        project_dir=tmp_path,
        execution_id=result.execution_id,
        source=tmp_path / "master.mp4",
    )
    assert technical.passed
    async with session_factory() as session:
        assert (
            await FormatRepository(session).passing_reports(
                user_id=USER, project_name=PROJECT, plan_id="plan-1", artifact_digest=result.artifact_digest
            )
            is None
        )

    fresh = await _open(service, tmp_path, result.execution_id)
    aggregated = await service.submit(
        user_id=USER, project_name=PROJECT, packet_id=fresh.packet_id, reviewer_id="sponsor", items=ALL_PASS, note=""
    )
    assert [review.model_dump(mode="python")["reviewer_id"] for review in aggregated.reviews] == ["sponsor"]
    assert aggregated.passed
    async with session_factory() as session:
        assert (
            await FormatRepository(session).passing_reports(
                user_id=USER, project_name=PROJECT, plan_id="plan-1", artifact_digest=result.artifact_digest
            )
            is not None
        )
