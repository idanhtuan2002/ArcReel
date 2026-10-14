"""Format projection renders as bounded M7 attempts with evidence rows (M8-E E2)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.formats import FormatRenderModel
from lib.db.models.host_hardening import ExecutionAttemptModel
from lib.db.repositories.formats import FormatRepository
from r2.advanced_creative.errors import FormatConflictError
from r2.advanced_creative.formats import ReframeKind, build_plan
from server.services.execution_attempts import build_attempt_submitter
from server.services.format_render import FormatRenderFailedError, FormatRenderService, ffmpeg_available, file_digest
from tests.integration.r2.advanced_creative.test_format_render import make_source, plan_for, probe
from tests.unit.r2.advanced_creative.test_formats import overlay

type Factory = async_sessionmaker[AsyncSession]

pytestmark = pytest.mark.skipif(not ffmpeg_available(), reason="needs ffmpeg and ffprobe")

USER = "default"
PROJECT = "demo"


def render_service(factory: Factory, *, ffmpeg: str = "ffmpeg") -> FormatRenderService:
    return FormatRenderService(
        factory,
        submitter_for=lambda session, user_id, project_name: build_attempt_submitter(
            session, user_id=user_id, project_name=project_name, usage_binder=None
        ),
        ffmpeg=ffmpeg,
    )


async def _store_plan(
    factory: Factory, source: Path, *, plan_id: str = "plan-1", kind: ReframeKind = ReframeKind.PAD, size=(1280, 720)
) -> str:
    base = plan_for(1080, 1080, kind, source=size)
    plan = build_plan(
        plan_id=plan_id,
        source_master_id="episode_video:1@v1",
        source_master_digest=file_digest(source),
        profile=base.output_profile,
        overlay=base.overlay_constraints,
        decisions=base.reframe_decisions,
    )
    async with factory() as session:
        repository = FormatRepository(session)
        await repository.put_profile(user_id=USER, project_name=PROJECT, profile=plan.output_profile)
        await repository.put_overlay(user_id=USER, project_name=PROJECT, overlay=overlay())
        await repository.create_plan(user_id=USER, project_name=PROJECT, plan=plan)
        await session.commit()
    return plan.plan_id


async def _attempts(factory: Factory) -> list[str]:
    async with factory() as session:
        return [row.state for row in (await session.scalars(select(ExecutionAttemptModel))).all()]


async def _evidence(factory: Factory) -> list[FormatRenderModel]:
    async with factory() as session:
        return list((await session.scalars(select(FormatRenderModel))).all())


async def test_a_render_is_a_succeeded_m7_attempt_with_evidence_and_replays(
    session_factory: Factory, tmp_path: Path
) -> None:
    source = make_source(tmp_path / "master.mp4")
    plan_id = await _store_plan(session_factory, source)
    service = render_service(session_factory)

    first = await service.render(
        user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=source, command_id="r-1"
    )
    assert not first.replayed
    assert first.artifact_path == tmp_path / "formats" / f"{first.artifact_digest.removeprefix('sha256:')}.mp4"
    video = next(s for s in probe(first.artifact_path)["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1080)
    assert await _attempts(session_factory) == ["SUCCEEDED"]
    [evidence] = await _evidence(session_factory)
    assert (evidence.execution_id, evidence.command_id, evidence.artifact_digest) == (
        first.execution_id,
        "r-1",
        first.artifact_digest,
    )

    again = await service.render(
        user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=source, command_id="r-1"
    )
    assert (again.replayed, again.execution_id) == (True, first.execution_id)
    other_plan = await _store_plan(session_factory, source, plan_id="plan-2", kind=ReframeKind.COVER_CENTER)
    with pytest.raises(FormatConflictError, match="another plan"):
        await service.render(
            user_id=USER,
            project_name=PROJECT,
            project_dir=tmp_path,
            plan_id=other_plan,
            source=source,
            command_id="r-1",
        )


async def test_only_the_bound_master_bytes_render(session_factory: Factory, tmp_path: Path) -> None:
    source = make_source(tmp_path / "master.mp4")
    plan_id = await _store_plan(session_factory, source)
    other = make_source(tmp_path / "other.mp4", seconds=1)

    with pytest.raises(FormatConflictError, match="not the master"):
        await render_service(session_factory).render(
            user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=other, command_id="r-1"
        )
    assert await _attempts(session_factory) == []


async def test_a_failed_render_is_an_m7_failure_and_a_new_command_retries(
    session_factory: Factory, tmp_path: Path
) -> None:
    source = make_source(tmp_path / "master.mp4")
    plan_id = await _store_plan(session_factory, source)
    failing = tmp_path / "failing-ffmpeg"
    failing.write_text(
        '#!/bin/sh\nif [ "$1" = "-version" ]; then exec ffmpeg -version; fi\necho "$* boom" >&2\nexit 3\n'
    )
    failing.chmod(0o755)

    with pytest.raises(FormatRenderFailedError, match="FAILED_BEFORE_ACCEPTANCE"):
        await render_service(session_factory, ffmpeg=str(failing)).render(
            user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=source, command_id="r-1"
        )
    assert await _attempts(session_factory) == ["FAILED_BEFORE_ACCEPTANCE"]
    assert await _evidence(session_factory) == []
    assert not list((tmp_path / "formats").glob(".*"))

    retried = await render_service(session_factory).render(
        user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=source, command_id="r-2"
    )
    assert sorted(await _attempts(session_factory)) == ["FAILED_BEFORE_ACCEPTANCE", "SUCCEEDED"]
    assert [row.execution_id for row in await _evidence(session_factory)] == [retried.execution_id]


async def test_a_lost_output_needs_a_new_command_which_repairs_the_store(
    session_factory: Factory, tmp_path: Path
) -> None:
    source = make_source(tmp_path / "master.mp4")
    plan_id = await _store_plan(session_factory, source)
    service = render_service(session_factory)
    first = await service.render(
        user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=source, command_id="r-1"
    )
    first.artifact_path.write_bytes(b"corrupted")

    with pytest.raises(FormatConflictError, match="new command"):
        await service.render(
            user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=source, command_id="r-1"
        )
    rebuilt = await service.render(
        user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=source, command_id="r-2"
    )
    assert rebuilt.artifact_digest == first.artifact_digest
    assert file_digest(rebuilt.artifact_path) == first.artifact_digest


async def test_cancellation_kills_ffmpeg_and_leaves_no_output(session_factory: Factory, tmp_path: Path) -> None:
    source = make_source(tmp_path / "master.mp4", seconds=20, width=1920, height=1080)
    plan_id = await _store_plan(session_factory, source, plan_id="plan-long", size=(1920, 1080))

    task = asyncio.create_task(
        render_service(session_factory).render(
            user_id=USER, project_name=PROJECT, project_dir=tmp_path, plan_id=plan_id, source=source, command_id="r-1"
        )
    )
    await asyncio.sleep(1.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # The attempt keeps M7's in-flight state for recovery; no evidence and no file remain.
    assert await _attempts(session_factory) == ["SUBMITTING"]
    assert await _evidence(session_factory) == []
    assert not list((tmp_path / "formats").glob("*"))
