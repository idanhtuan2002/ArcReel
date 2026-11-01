"""Rendered, mastered finals reviewed by two qualified model reviewers through the real controller."""

from __future__ import annotations

import asyncio

import pytest

from lib.db.repositories.production_runs import ProductionRunRepository
from lib.db.repositories.reviewer_qualifications import ReviewerQualificationRepository
from r2.automation.assessment import AssessmentFinding, ModelAssessment
from r2.contracts.automation import QualificationCase, ReviewerQualification, RunStage, RunStatus
from server.production_run.controller import ProductionController
from server.production_run.final_master_adapter import FinalMasterAdapter
from server.production_run.quality_adapter import QualityAdapter
from server.production_run.render_adapter import RenderAdapter
from server.services.presentation_read_model import PresentationReadModelService
from tests.integration.server.production_run.test_render_master_adapter import (
    MediaPassed,
    RunInput,
    _narration_project,
    _Settings,
)
from tests.integration.server.production_run.test_story_adapter import OWNER, Host
from tests.integration.server.production_run.test_story_adapter import interactive_env as interactive_env
from tests.integration.server.production_run.test_story_adapter import story_host as story_host

GOOD = dict.fromkeys(("story", "visual", "audio", "continuity", "pacing"), 4)


class Reviewer:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.answers: dict[str, dict] = {}

    async def assess(self, *, route, evidence):
        self.calls.append(route.role)
        answer = {"outcome": "COMPLETED", "language": "vi", "scores": GOOD, **self.answers.get(route.role, {})}
        return ModelAssessment.model_validate(
            {
                "reviewer_route_digest": "sha256:" + "2" * 64,
                "model_identity": route.model_identity,
                "prompt_digest": "sha256:" + "3" * 64,
                "subject_digest": evidence.subject_digest,
                "evidence_digest": "sha256:" + "4" * 64,
                **answer,
            }
        )


def _qualification(route) -> ReviewerQualification:
    cases = [
        QualificationCase(
            split=split,
            label=label,
            accepted=label == "CLEAN",
            case_digest="sha256:" + f"{index:064x}",
            receipt_ref=f"case-{index}",
            receipt_digest="sha256:" + f"{index:064x}",
        )
        for index, (split, label) in enumerate(
            (split, label)
            for split in ("CALIBRATION", "HOLDOUT")
            for label in ("CLEAN", "CRITICAL_DEFECT")
            for _ in range(10)
        )
    ]
    return ReviewerQualification(
        profile_digest="sha256:" + "a" * 64,
        launch_profile_id="fiction_narration_vi_v1",
        language="vi",
        provider_id=route.provider_id,
        model_id=route.model_id,
        model_identity=route.model_identity,
        config_digest=route.config_digest,
        prompt_digest="sha256:" + "3" * 64,
        cases=tuple(cases),
    )


@pytest.fixture
async def quality_host(story_host: Host):
    host = story_host
    projects_root = host.projects.projects_root
    _narration_project(projects_root, "project")
    async with host.sessions() as session, session.begin():
        run = await ProductionRunRepository(session).claim_due(owner_id=OWNER, lease_seconds=120)
        assert run is not None
        moved = run.model_copy(update={"stage": RunStage.MEDIA, "version": run.version + 1})
        await ProductionRunRepository(session).transition(expected=run, updated=moved, fencing_epoch=run.fencing_epoch)
    reviewer = Reviewer()
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
    return host, controller, render, quality, reviewer


async def _tick(host, controller):
    async with host.sessions() as session, session.begin():
        claimed = await ProductionRunRepository(session).claim_due(owner_id=OWNER, lease_seconds=120)
    assert claimed is not None
    return await controller.tick(run_id=host.run.run_id, owner_id=OWNER)


async def _to_quality(host, controller, render):
    await _tick(host, controller)
    await _tick(host, controller)
    await asyncio.gather(*render._jobs.values())
    await _tick(host, controller)
    mastered = await _tick(host, controller)
    assert mastered.stage is RunStage.QUALITY


async def _review(host, controller, quality):
    waiting = await _tick(host, controller)
    assert waiting.status is RunStatus.WAITING_TASK
    await asyncio.gather(*quality._jobs.values())
    return await _tick(host, controller)


async def _qualify(host):
    async with host.sessions() as session, session.begin():
        for route in host.run.policy.routes:
            if route.role in {"reviewer_a", "reviewer_b"}:
                await ReviewerQualificationRepository(session).record(_qualification(route))


async def test_two_qualified_accepting_reviews_pass_the_final(quality_host):
    host, controller, render, quality, reviewer = quality_host
    await _qualify(host)
    await _to_quality(host, controller, render)

    passed = await _review(host, controller, quality)

    assert (passed.stage, passed.status, passed.reason) == (RunStage.PACKAGE, RunStatus.RUNNING, None)
    assert sorted(reviewer.calls) == ["reviewer_a", "reviewer_b"]
    assert passed.final_evaluations == 1


async def test_reviewer_exception_never_passes_quality(quality_host):
    host, controller, render, quality, reviewer = quality_host
    await _qualify(host)
    reviewer.answers["reviewer_b"] = {"outcome": "FAILED", "language": None, "scores": {}}
    await _to_quality(host, controller, render)

    blocked = await _review(host, controller, quality)

    assert blocked.status is not RunStatus.SUCCEEDED
    assert (blocked.stage, blocked.reason) == (RunStage.QUALITY, "ASSESSOR_FAILED")


async def test_unqualified_reviewers_cannot_pass(quality_host):
    host, controller, render, quality, _reviewer = quality_host
    await _to_quality(host, controller, render)

    blocked = await _review(host, controller, quality)

    assert (blocked.stage, blocked.reason) == (RunStage.QUALITY, "REVIEWER_NOT_QUALIFIED")


async def test_both_rejecting_rework_exactly_the_named_stage(quality_host):
    host, controller, render, quality, reviewer = quality_host
    await _qualify(host)
    finding = AssessmentFinding(code="AUDIO_DRIFT", severity="MAJOR", unit_key="episode:1", repair_stage=RunStage.MEDIA)
    for role in ("reviewer_a", "reviewer_b"):
        reviewer.answers[role] = {"scores": {**GOOD, "audio": 2}, "findings": [finding.model_dump()]}
    await _to_quality(host, controller, render)

    reworked = await _review(host, controller, quality)

    assert (reworked.stage, reworked.status, reworked.generation) == (RunStage.MEDIA, RunStatus.RUNNING, 2)
    assert [(r.stage, r.unit_key, r.count) for r in reworked.repair_counts] == [(RunStage.MEDIA, "episode:1", 1)]
