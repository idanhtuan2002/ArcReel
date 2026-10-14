"""Local FFmpeg rendering of format plans with execution records (M8-E E2)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.formats import FormatRenderModel
from lib.db.repositories.formats import FormatRepository
from r2.advanced_creative.errors import FormatConflictError
from r2.advanced_creative.formats import ReframeKind
from server.services.format_render import (
    FormatRenderBusyError,
    FormatRenderFailedError,
    FormatRenderService,
    ffmpeg_available,
    file_digest,
)
from tests.integration.r2.advanced_creative.test_format_render import make_source, plan_for, probe
from tests.unit.r2.advanced_creative.test_formats import overlay

type Factory = async_sessionmaker[AsyncSession]

pytestmark = pytest.mark.skipif(not ffmpeg_available(), reason="needs ffmpeg and ffprobe")

USER = "default"
PROJECT = "demo"


async def _store_plan(factory: Factory, source: Path, *, kind: ReframeKind = ReframeKind.PAD) -> str:
    plan = plan_for(1080, 1080, kind)
    from r2.advanced_creative.formats import build_plan

    plan = build_plan(
        plan_id="plan-1",
        source_master_id=plan.source_master_id,
        source_master_digest=file_digest(source),
        profile=plan.output_profile,
        overlay=plan.overlay_constraints,
        decisions=plan.reframe_decisions,
    )
    async with factory() as session:
        repository = FormatRepository(session)
        await repository.put_profile(user_id=USER, project_name=PROJECT, profile=plan.output_profile)
        await repository.put_overlay(user_id=USER, project_name=PROJECT, overlay=overlay())
        await repository.create_plan(user_id=USER, project_name=PROJECT, plan=plan)
        await session.commit()
    return plan.plan_id


async def test_a_render_stores_its_output_and_replays(session_factory: Factory, tmp_path: Path) -> None:
    source = make_source(tmp_path / "master.mp4")
    plan_id = await _store_plan(session_factory, source)
    service = FormatRenderService(session_factory)

    first = await service.render(
        user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=source
    )
    assert not first.replayed
    assert first.artifact_path == tmp_path / "formats" / f"{first.artifact_digest.removeprefix('sha256:')}.mp4"
    video = next(s for s in probe(first.artifact_path)["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1080)

    again = await service.render(
        user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=source
    )
    assert (again.replayed, again.execution_id, again.artifact_digest) == (
        True,
        first.execution_id,
        first.artifact_digest,
    )
    record = await service.execution(user_id=USER, project_name=PROJECT, execution_id=first.execution_id)
    assert record is not None
    assert (record.state, record.attempt, record.artifact_ref) == (
        "SUCCEEDED",
        1,
        f"formats/{first.artifact_path.name}",
    )

    # A lost output is rendered again under the same identity.
    first.artifact_path.unlink()
    rebuilt = await service.render(
        user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=source
    )
    assert (rebuilt.replayed, rebuilt.artifact_digest) == (False, first.artifact_digest)


async def test_only_the_bound_master_bytes_render(session_factory: Factory, tmp_path: Path) -> None:
    source = make_source(tmp_path / "master.mp4")
    plan_id = await _store_plan(session_factory, source)
    other = make_source(tmp_path / "other.mp4", seconds=1)

    with pytest.raises(FormatConflictError, match="not the master"):
        await FormatRenderService(session_factory).render(
            user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=other
        )


async def test_a_failed_render_is_recorded_and_may_run_again(session_factory: Factory, tmp_path: Path) -> None:
    source = make_source(tmp_path / "master.mp4")
    plan_id = await _store_plan(session_factory, source)
    failing = tmp_path / "failing-ffmpeg"
    failing.write_text('#!/bin/sh\nif [ "$1" = "-version" ]; then exec ffmpeg -version; fi\necho boom >&2\nexit 3\n')
    failing.chmod(0o755)

    with pytest.raises(FormatRenderFailedError, match="exited 3"):
        await FormatRenderService(session_factory, ffmpeg=str(failing)).render(
            user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=source
        )
    async with session_factory() as session:
        rows = (await session.execute(FormatRenderModel.__table__.select())).all()
    assert [(row.state, row.attempt) for row in rows] == [("FAILED", 1)]
    assert "boom" in rows[0].error

    result = await FormatRenderService(session_factory).render(
        user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=source
    )
    record = await FormatRenderService(session_factory).execution(
        user_id=USER, project_name=PROJECT, execution_id=result.execution_id
    )
    assert record is not None
    assert (record.state, record.attempt) == ("SUCCEEDED", 2)
    assert not list((tmp_path / "formats").glob(".*partial*"))


async def test_a_running_render_is_busy_until_it_is_stale(session_factory: Factory, tmp_path: Path) -> None:
    source = make_source(tmp_path / "master.mp4")
    plan_id = await _store_plan(session_factory, source)
    service = FormatRenderService(session_factory)
    result = await service.render(
        user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=source
    )
    async with session_factory() as session, session.begin():
        row = await session.get(FormatRenderModel, (USER, PROJECT, result.execution_id))
        assert row is not None
        row.state, row.artifact_digest, row.artifact_ref = "RUNNING", None, None
        row.started_at = datetime.now(UTC)

    with pytest.raises(FormatRenderBusyError):
        await service.render(user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=source)
    recovered = await FormatRenderService(session_factory, stale_after=timedelta(0)).render(
        user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=source
    )
    assert recovered.artifact_digest == result.artifact_digest


async def test_cancellation_kills_ffmpeg_and_records_it(session_factory: Factory, tmp_path: Path) -> None:
    source = make_source(tmp_path / "master.mp4", seconds=20, width=1920, height=1080)
    from r2.advanced_creative.formats import build_plan

    base = plan_for(1080, 1080, ReframeKind.PAD, source=(1920, 1080))
    plan = build_plan(
        plan_id="plan-long",
        source_master_id="m",
        source_master_digest=file_digest(source),
        profile=base.output_profile,
        overlay=base.overlay_constraints,
        decisions=base.reframe_decisions,
    )
    async with session_factory() as session:
        repository = FormatRepository(session)
        await repository.put_profile(user_id=USER, project_name=PROJECT, profile=plan.output_profile)
        await repository.put_overlay(user_id=USER, project_name=PROJECT, overlay=overlay())
        await repository.create_plan(user_id=USER, project_name=PROJECT, plan=plan)
        await session.commit()

    task = asyncio.create_task(
        FormatRenderService(session_factory).render(
            user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id="plan-long", source=source
        )
    )
    await asyncio.sleep(1.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with session_factory() as session:
        states = [row.state for row in (await session.execute(FormatRenderModel.__table__.select())).all()]
    assert states == ["CANCELLED"]
    assert not list((tmp_path / "formats").glob(".*partial*"))
