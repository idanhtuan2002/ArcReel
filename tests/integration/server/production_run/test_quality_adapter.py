"""Rendered, mastered finals reviewed by two qualified model reviewers through the real controller."""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa

from lib.db.models.production_run import ModelObservationModel
from lib.db.models.quality_dispositions import QualityDispositionModel
from lib.db.repositories.model_observations import ModelObservationRepository
from lib.db.repositories.production_runs import ProductionRunRepository
from lib.db.repositories.quality_dispositions import QualityDispositionRepository
from lib.db.repositories.reviewer_qualifications import ReviewerQualificationRepository
from r2.automation.assessment import AssessmentFinding, ModelAssessment
from r2.automation.authorization import automation_principal
from r2.contracts.automation import QualificationCase, ReviewerQualification, RunStage, RunStatus
from server.production_run.controller import ProductionController
from server.production_run.final_master_adapter import FinalMasterAdapter
from server.production_run.packaging_adapter import ExportAdapter, PackagingAdapter
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


@pytest.fixture
def story_policy():
    """Publish the automatic quality profile the run's policy names before the run exists."""
    return _publish_profile


async def _publish_profile(sessions) -> dict:
    from server.services.quality_template import automatic_quality_policy, default_platform_constraints
    from tests.integration.lib.db.repositories.test_quality_profiles_repository import append
    from tests.unit.r2.quality.test_quality_profiles import publication_request

    policy = automatic_quality_policy(
        default_platform_constraints(
            platform_profile_id="vertical-short",
            width=576,
            height=1024,
            min_duration_ms=30000,
            max_duration_ms=60000,
            required_locales=("vi",),
        )
    )
    profile = await append(
        sessions,
        publication_request(user_id="default", project_name="project", policy=policy.model_dump(mode="json")),
    )
    return {"profile_id": profile.profile_id, "profile_digest": profile.profile_digest}


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


def _qualification(route, host) -> ReviewerQualification:
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
        profile_digest=host.run.policy.profile_digest,
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
            RunStage.PACKAGE: PackagingAdapter(host.sessions, authority=host.authority, projects=host.projects),
            RunStage.EXPORT: ExportAdapter(host.sessions, authority=host.authority, projects=host.projects),
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
                await ReviewerQualificationRepository(session).record(_qualification(route, host))


async def test_two_qualified_accepting_reviews_pass_the_final(quality_host):
    host, controller, render, quality, reviewer = quality_host
    await _qualify(host)
    await _to_quality(host, controller, render)

    passed = await _review(host, controller, quality)

    assert (passed.stage, passed.status, passed.reason) == (RunStage.PACKAGE, RunStatus.RUNNING, None)
    assert sorted(reviewer.calls) == ["reviewer_a", "reviewer_b"]
    assert passed.final_evaluations == 1
    async with host.sessions() as session:
        outcome = await ProductionRunRepository(session).stage_outcome(run=passed, stage=RunStage.QUALITY)
        assert outcome is not None
        disposition_id = outcome.receipts[0].receipt_ref.partition("@")[2]
        disposition = await QualityDispositionRepository(session).disposition(
            user_id="default", project_name="project", disposition_id=disposition_id
        )
        observations = list((await session.execute(sa.select(ModelObservationModel))).scalars())
    assert disposition is not None
    assert (disposition.decision, disposition.issuer_id) == ("PASS", automation_principal(host.run.run_id))
    assert disposition.waiver_bindings == ()
    assert len(observations) == 4


async def test_a_replayed_observation_keeps_its_first_recording_and_other_changes_conflict(quality_host):
    from datetime import UTC, datetime

    import r2.contracts.quality as q

    host, controller, render, quality, _reviewer = quality_host
    await _qualify(host)
    await _to_quality(host, controller, render)
    await _review(host, controller, quality)
    async with host.sessions() as session:
        row = (await session.execute(sa.select(ModelObservationModel))).scalars().first()
        assert row is not None
        stored = q.NarrativeObservation.model_validate_json(row.observation_json)
        profile = await _profile(host, row)
    replay = stored.model_copy(update={"observed_at": datetime.now(UTC)})
    changed = replay.model_copy(update={"status": q.ObservationStatus.FAIL})

    async with host.sessions() as session, session.begin():
        repository = ModelObservationRepository(session)
        kept = await repository.record(
            user_id="default", project_name="project", run_id=row.run_id, profile=profile, observation=replay
        )
        with pytest.raises(ValueError, match="MODEL_OBSERVATION_REPLAY_CONFLICT"):
            await repository.record(
                user_id="default", project_name="project", run_id=row.run_id, profile=profile, observation=changed
            )

    assert kept == stored


async def _profile(host, row):
    from server.production_run.quality_record import published_profile

    return await published_profile(
        host.sessions,
        user_id="default",
        project_name="project",
        profile_id=row.profile_id,
        profile_digest=row.profile_digest,
    )


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


async def test_a_review_asked_with_an_unqualified_prompt_cannot_pass(quality_host):
    host, controller, render, quality, reviewer = quality_host
    await _qualify(host)
    reviewer.answers["reviewer_a"] = {"prompt_digest": "sha256:" + "9" * 64}
    await _to_quality(host, controller, render)

    blocked = await _review(host, controller, quality)

    assert (blocked.stage, blocked.reason) == (RunStage.QUALITY, "REVIEWER_PROMPT_NOT_QUALIFIED")


def _quality_gate(monkeypatch, gate: str) -> None:
    import server.production_run.quality_adapter as quality_adapter
    from r2.automation.profiles import resolve_launch_profile

    monkeypatch.setattr(
        quality_adapter,
        "resolve_launch_profile",
        lambda profile_id: resolve_launch_profile(profile_id).model_copy(update={"quality_gate": gate}),
    )


async def test_both_rejecting_rework_exactly_the_named_stage(quality_host, monkeypatch):
    host, controller, render, quality, reviewer = quality_host
    _quality_gate(monkeypatch, "enforce")
    await _qualify(host)
    finding = AssessmentFinding(code="AUDIO_DRIFT", severity="MAJOR", unit_key="episode:1", repair_stage=RunStage.MEDIA)
    for role in ("reviewer_a", "reviewer_b"):
        reviewer.answers[role] = {"scores": {**GOOD, "audio": 2}, "findings": [finding.model_dump()]}
    await _to_quality(host, controller, render)

    reworked = await _review(host, controller, quality)

    assert (reworked.stage, reworked.status, reworked.generation) == (RunStage.MEDIA, RunStatus.RUNNING, 2)
    assert [(r.stage, r.unit_key, r.count) for r in reworked.repair_counts] == [(RunStage.MEDIA, "episode:1", 1)]
    async with host.sessions() as session:
        decisions = [row.decision for row in (await session.execute(sa.select(QualityDispositionModel))).scalars()]
    assert decisions == ["REWORK"]


async def test_a_passed_final_is_packaged_exported_and_the_run_succeeds(quality_host):
    host, controller, render, quality, _reviewer = quality_host
    await _qualify(host)
    await _to_quality(host, controller, render)
    await _review(host, controller, quality)

    packaged = await _tick(host, controller)
    succeeded = await _tick(host, controller)

    assert packaged.stage is RunStage.EXPORT
    assert succeeded.status is RunStatus.SUCCEEDED
    [output] = succeeded.completed_targets
    archive = host.projects.get_project_path("project") / output.export.receipt_ref.partition("@")[2]
    import hashlib
    import zipfile

    assert "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest() == output.archive_digest
    with zipfile.ZipFile(archive) as opened:
        assert sorted(opened.namelist()) == [
            "episode_1.mp4",
            "episode_1.srt",
            "lineage.json",
            "quality.json",
            "render_manifest.json",
        ]
        assert "sha256:" + hashlib.sha256(opened.read("episode_1.mp4")).hexdigest() == output.final_digest


async def test_a_substituted_archive_prevents_run_success(quality_host):
    host, controller, render, quality, _reviewer = quality_host
    await _qualify(host)
    await _to_quality(host, controller, render)
    await _review(host, controller, quality)
    packaged = await _tick(host, controller)
    async with host.sessions() as session:
        outcome = await ProductionRunRepository(session).stage_outcome(run=packaged, stage=RunStage.PACKAGE)
    assert outcome is not None
    archive = host.projects.get_project_path("project") / outcome.receipts[0].receipt_ref.partition("@")[2]
    archive.write_bytes(archive.read_bytes() + b"x")

    blocked = await _tick(host, controller)

    assert blocked.status is not RunStatus.SUCCEEDED
    assert (blocked.stage, blocked.reason) == (RunStage.EXPORT, "ARCHIVE_CHANGED")


async def test_a_recording_gate_exports_a_rejected_final_with_its_rework_disposition(quality_host, monkeypatch):
    import json
    import zipfile

    host, controller, render, quality, reviewer = quality_host
    _quality_gate(monkeypatch, "record")
    await _qualify(host)
    finding = AssessmentFinding(code="AUDIO_DRIFT", severity="MAJOR", unit_key="episode:1", repair_stage=RunStage.MEDIA)
    for role in ("reviewer_a", "reviewer_b"):
        reviewer.answers[role] = {"scores": {**GOOD, "audio": 2}, "findings": [finding.model_dump()]}
    await _to_quality(host, controller, render)

    reviewed = await _review(host, controller, quality)
    packaged = await _tick(host, controller)
    assert packaged.stage is RunStage.EXPORT
    succeeded = await _tick(host, controller)

    assert (reviewed.stage, reviewed.generation) == (RunStage.PACKAGE, 1)
    assert succeeded.status is RunStatus.SUCCEEDED
    [output] = succeeded.completed_targets
    assert output.quality_decision == "REWORK"
    archive = host.projects.get_project_path("project") / output.export.receipt_ref.partition("@")[2]
    with zipfile.ZipFile(archive) as opened:
        assert json.loads(opened.read("lineage.json"))["quality_decision"] == "REWORK"


async def test_a_recording_gate_still_blocks_missing_evidence(quality_host, monkeypatch):
    host, controller, render, quality, _reviewer = quality_host
    _quality_gate(monkeypatch, "record")
    await _to_quality(host, controller, render)

    blocked = await _review(host, controller, quality)

    assert blocked.status is not RunStatus.SUCCEEDED
    assert blocked.stage is RunStage.QUALITY
    assert blocked.reason == "REVIEWER_NOT_QUALIFIED"
