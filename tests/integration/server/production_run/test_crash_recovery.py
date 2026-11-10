"""A controller restart mid-render or after paid reviews resumes from durable owner evidence."""

from __future__ import annotations

import asyncio
import contextlib

import sqlalchemy as sa

from lib.db.models.production_run import ProductionOwnerAttemptModel
from r2.contracts.automation import RunStage, RunStatus
from server.production_run.controller import ProductionController
from server.production_run.final_master_adapter import FinalMasterAdapter
from server.production_run.quality_adapter import QualityAdapter
from server.production_run.render_adapter import RenderAdapter
from server.services.presentation_read_model import PresentationReadModelService
from tests.integration.server.production_run.test_quality_adapter import (
    Reviewer,
    _qualify,
    _tick,
)
from tests.integration.server.production_run.test_quality_adapter import quality_host as quality_host
from tests.integration.server.production_run.test_quality_adapter import story_policy as story_policy
from tests.integration.server.production_run.test_render_master_adapter import MediaPassed, RunInput, _Settings
from tests.integration.server.production_run.test_story_adapter import interactive_env as interactive_env
from tests.integration.server.production_run.test_story_adapter import story_host as story_host
from tests.integration.server.production_run.test_story_adapter import story_start as story_start


def _restarted(host, reviewer):
    """A fresh controller and adapters, as after a process restart: no in-process job survives."""
    render = RenderAdapter(
        host.sessions,
        authority=host.authority,
        projects=host.projects,
        presentations=PresentationReadModelService(host.projects, settings_resolver_factory=lambda *_: _Settings()),
    )
    quality = QualityAdapter(host.sessions, authority=host.authority, projects=host.projects, evaluator=reviewer)
    controller = ProductionController(
        host.sessions,
        adapters={
            RunStage.MEDIA: MediaPassed(),
            RunStage.RENDER: render,
            RunStage.MASTER: FinalMasterAdapter(host.sessions, authority=host.authority, projects=host.projects),
            RunStage.QUALITY: quality,
        },
        witness=RunInput(host.run.input_digest),
        poll_seconds=0,
    )
    return controller, render, quality


async def test_a_render_lost_in_a_crash_is_rendered_again_once(quality_host):
    host, controller, render, _quality, _reviewer = quality_host
    await _tick(host, controller)
    rendering = await _tick(host, controller)
    assert rendering.status is RunStatus.WAITING_TASK
    for job in render._jobs.values():
        job.cancel()
    for job in render._jobs.values():
        with contextlib.suppress(asyncio.CancelledError):
            await job

    controller, render, _ = _restarted(host, Reviewer())
    again = await _tick(host, controller)
    assert again.status is RunStatus.WAITING_TASK
    await asyncio.gather(*render._jobs.values())
    rendered = await _tick(host, controller)

    assert rendered.stage is RunStage.MASTER
    async with host.sessions() as session:
        attempts = await session.scalar(
            sa.select(sa.func.count())
            .select_from(ProductionOwnerAttemptModel)
            .where(ProductionOwnerAttemptModel.sub_key == "render")
        )
    assert attempts == 2


async def test_reviews_paid_before_a_crash_are_reused_not_bought_again(quality_host):
    host, controller, render, quality, reviewer = quality_host
    await _qualify(host)
    await _tick(host, controller)
    await _tick(host, controller)
    await asyncio.gather(*render._jobs.values())
    await _tick(host, controller)
    await _tick(host, controller)
    waiting = await _tick(host, controller)
    assert waiting.status is RunStatus.WAITING_TASK
    await asyncio.gather(*quality._jobs.values())
    assert sorted(reviewer.calls) == ["reviewer_a", "reviewer_b"]

    fresh = Reviewer()
    controller, _, _ = _restarted(host, fresh)
    passed = await _tick(host, controller)

    assert (passed.stage, passed.status) == (RunStage.PACKAGE, RunStatus.RUNNING)
    assert fresh.calls == []
