"""Exact presentations to a verified render and an approved final master, through the real controller."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import sqlalchemy as sa

from lib.artifact_manifest import (
    ArtifactBasisDescriptor,
    ArtifactKey,
    ArtifactManifest,
    ProjectArtifactManifestAdapter,
    compose_video_artifact_basis,
)
from lib.db.models.host_hardening import PromotionReceiptModel
from lib.db.repositories.production_runs import ProductionRunRepository
from lib.narration_delivery import TtsSynthesisSettings, build_narration_audio_basis, canonical_narration_text
from lib.presentation_renderer import sha256_file
from lib.project_manager import ProjectManager
from lib.project_schema import CURRENT_PROJECT_SCHEMA_VERSION
from lib.speech_artifact_provenance import build_video_duration_basis, build_video_speech_basis
from lib.speech_composition import admit_script_unit
from lib.version_manager import VersionManager
from lib.video_artifact_facts import VideoArtifactCurrencyFacts
from lib.visual_artifact_provenance import build_storyboard_video_artifact_visual_basis
from r2.automation.authorization import automation_principal
from r2.contracts.automation import OwnerReceipt, RunStage, RunStatus, StageOutcome, UsageReceipt
from server.production_run.controller import ProductionController
from server.production_run.final_master_adapter import FinalMasterAdapter
from server.production_run.ports import StepPlan
from server.production_run.render_adapter import RenderAdapter
from server.services.presentation_read_model import PresentationReadModelService
from tests.integration.server.services.test_automation_grants import delegated_host as delegated_host
from tests.integration.server.services.test_automation_grants import interactive_env as interactive_env

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is required")
SEGMENTS = ("E1S01", "E1S02", "E1S03", "E1S04")
SETTINGS = TtsSynthesisSettings("openai", "tts-1", "alloy", 1.0)


class _Settings:
    async def resolve_tts_synthesis_settings(self, _project):
        return SETTINGS


def _ffmpeg(path: Path, *args: str) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", *args, str(path)], check=True)


def _narration_project(projects_root: Path, name: str) -> Path:
    project_path = projects_root / name
    for subdir in ("scripts", "storyboards", "videos", "audio", "production"):
        (project_path / subdir).mkdir(parents=True, exist_ok=True)
    items = [
        {
            "segment_id": segment,
            "duration_seconds": 8,
            "novel_text": f"Đoạn {index} của truyện.",
            "video_prompt": {"action": "Clouds move", "camera_motion": "Static"},
            "generated_assets": {
                "storyboard_image": f"storyboards/scene_{segment}.png",
                "video_clip": f"videos/scene_{segment}.mp4",
                "narration_audio": f"audio/segment_{segment}.wav",
            },
        }
        for index, segment in enumerate(SEGMENTS, start=1)
    ]
    project = {
        "title": "Demo",
        "schema_version": CURRENT_PROJECT_SCHEMA_VERSION,
        "content_mode": "narration",
        "generation_mode": "storyboard",
        "grid_storyboard": False,
        "aspect_ratio": "9:16",
        "default_duration": 8,
        "characters": {},
        "episodes": [{"episode": 1, "title": "One", "script_file": "scripts/episode_1.json"}],
    }
    (project_path / "project.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    (project_path / "scripts" / "episode_1.json").write_text(
        json.dumps({"episode": 1, "content_mode": "narration", "segments": items}, ensure_ascii=False),
        encoding="utf-8",
    )
    versions = VersionManager(project_path)
    manifest = ArtifactManifest(ProjectArtifactManifestAdapter(project_path))
    for item in items:
        segment = item["segment_id"]
        storyboard = project_path / "storyboards" / f"scene_{segment}.png"
        storyboard.write_bytes(b"storyboard-" + segment.encode())
        video = project_path / "videos" / f"scene_{segment}.mp4"
        _ffmpeg(video, "-f", "lavfi", "-i", "testsrc=size=320x568:rate=16", "-t", "8", "-pix_fmt", "yuv420p")
        audio = project_path / "audio" / f"segment_{segment}.wav"
        _ffmpeg(audio, "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=24000", "-t", "4.5")
        preparation = admit_script_unit("segments", item).preparation
        visual = build_storyboard_video_artifact_visual_basis(
            resource_id=segment,
            visual_prompt=item["video_prompt"],
            storyboard_image=storyboard,
            end_frame_image=None,
            aspect_ratio="9:16",
        )
        speech = build_video_speech_basis(preparation)
        duration = build_video_duration_basis(8)
        currency = VideoArtifactCurrencyFacts(
            episode=1,
            request_duration_seconds=8,
            visual_basis=visual,
            speech_basis=speech,
            duration_basis=duration,
            video_basis=compose_video_artifact_basis(visual=visual, speech=speech, duration=duration),
            voice_style_speakers=(),
            duration_tiers=(4, 8, 12),
            reference_image_limit=None,
            parent_version=0,
        )
        versions.add_version(
            "videos",
            segment,
            "video",
            source_file=video,
            execution_checkpoint_schema_version=3,
            execution_script_file="episode_1.json",
            execution_duration_seconds=8,
            execution_request_digest="d" * 64,
            execution_provider_media=[],
            execution_generate_audio=True,
            artifact_video_currency=currency.to_dict(),
        )
        manifest.register(
            ArtifactKey.episode_video(1, segment),
            artifact_path=f"videos/scene_{segment}.mp4",
            basis=currency.video_basis,
        )
        audio_basis = build_narration_audio_basis(preparation, SETTINGS)
        versions.add_version(
            "audio",
            segment,
            canonical_narration_text(preparation),
            source_file=audio,
            execution_script_file="episode_1.json",
            artifact_episode=1,
            artifact_audio_basis=ArtifactBasisDescriptor.from_basis(audio_basis).to_dict(),
            tts_basis_digest=audio_basis.digest,
            tts_actual_duration_seconds=4.5,
            tts_provider_id=SETTINGS.provider_id,
            tts_model_id=SETTINGS.model_id,
            tts_voice=SETTINGS.voice,
            tts_speed=SETTINGS.speed,
        )
        manifest.register(
            ArtifactKey.episode_audio(1, segment), artifact_path=f"audio/segment_{segment}.wav", basis=audio_basis
        )
    return project_path


class MediaPassed:
    owner = "media"

    async def plan(self, *, run):
        return StepPlan(
            unit_key="media",
            estimated_cost_minor_units=0,
            estimated_model_calls=0,
            estimated_tasks=0,
            estimated_runtime_seconds=1,
        )

    async def dispatch(self, intent):
        return OwnerReceipt(owner=self.owner, receipt_ref=intent.identity.command_id, digest="sha256:" + "4" * 64)

    async def inspect(self, *, intent, receipt):
        identity = intent.identity
        return StageOutcome(
            stage=identity.stage,
            generation=identity.generation,
            input_digest=identity.input_digest,
            policy_digest=identity.policy_digest,
            kind="PASS",
            receipts=(OwnerReceipt(owner="media", receipt_ref="episode:1:media@x", digest="sha256:" + "5" * 64),),
        )

    async def usage(self, *, receipt, reservation):
        return UsageReceipt(
            **{**receipt.model_dump(), "receipt_ref": "usage:" + reservation.reservation_id},
            reservation_id=reservation.reservation_id,
            currency=reservation.currency,
            cost_minor_units=0,
            model_calls=0,
            tasks=0,
            runtime_seconds=0,
            outcome="KNOWN",
        )


class RunInput:
    def __init__(self, digest: str) -> None:
        self.value = digest

    async def digest(self, *, user_id, project_name):
        return self.value


@pytest.fixture
async def render_host(delegated_host, tmp_path):
    issuer, sessions, _request, _grant, run, *_ = delegated_host
    projects_root = tmp_path / "projects"
    project_path = _narration_project(projects_root, run.project_name)
    projects = ProjectManager(projects_root)
    async with sessions() as session, session.begin():
        moved = run.model_copy(update={"stage": RunStage.MEDIA, "version": run.version + 1})
        await ProductionRunRepository(session).transition(expected=run, updated=moved, fencing_epoch=run.fencing_epoch)
    authority = issuer.authority()
    render = RenderAdapter(
        sessions,
        authority=authority,
        projects=projects,
        presentations=PresentationReadModelService(projects, settings_resolver_factory=lambda *_: _Settings()),
    )
    controller = ProductionController(
        sessions,
        adapters={
            RunStage.MEDIA: MediaPassed(),
            RunStage.RENDER: render,
            RunStage.MASTER: FinalMasterAdapter(sessions, authority=authority, projects=projects),
        },
        witness=RunInput(run.input_digest),
        poll_seconds=0,
    )
    return sessions, controller, render, run, project_path


async def _tick(sessions, controller, run):
    async with sessions() as session, session.begin():
        claimed = await ProductionRunRepository(session).claim_due(owner_id="controller", lease_seconds=120)
    assert claimed is not None
    return await controller.tick(run_id=run.run_id, owner_id="controller")


def _sources(project_path: Path) -> dict[str, str]:
    return {
        str(path.relative_to(project_path)): sha256_file(path)
        for folder in ("videos", "audio", "versions")
        if (project_path / folder).exists()
        for path in sorted((project_path / folder).rglob("*"))
        if path.is_file()
    }


async def test_exact_presentations_render_and_become_the_runs_final_master(render_host):
    sessions, controller, render, run, project_path = render_host
    before = _sources(project_path)

    assert (await _tick(sessions, controller, run)).stage is RunStage.RENDER
    rendering = await _tick(sessions, controller, run)
    assert (rendering.stage, rendering.status) == (RunStage.RENDER, RunStatus.WAITING_TASK)
    await asyncio.gather(*render._jobs.values())
    rendered = await _tick(sessions, controller, run)

    assert (rendered.stage, rendered.status, rendered.reason) == (RunStage.MASTER, RunStatus.RUNNING, None)
    assert _sources(project_path) == before
    async with sessions() as session:
        outcome = await ProductionRunRepository(session).stage_outcome(run=rendered, stage=RunStage.RENDER)
    assert outcome is not None
    [final] = outcome.receipts
    final_path = project_path / final.receipt_ref.partition("@")[2]
    manifest = json.loads(final_path.with_name("episode_1.manifest.json").read_text(encoding="utf-8"))
    assert manifest["final_sha256"] == sha256_file(final_path)
    assert abs(manifest["duration_seconds"] - 32.0) <= 0.12
    assert [unit["unit_id"] for unit in manifest["units"]] == list(SEGMENTS)

    mastered = await _tick(sessions, controller, run)
    assert (mastered.stage, mastered.status, mastered.reason) == (RunStage.QUALITY, RunStatus.RUNNING, None)
    async with sessions() as session:
        receipts = list((await session.execute(sa.select(PromotionReceiptModel))).scalars())
        master = await ProductionRunRepository(session).stage_outcome(run=mastered, stage=RunStage.MASTER)
    assert len(receipts) == 1
    assert master is not None
    assert master.receipts[0].receipt_ref.startswith("episode:1:master@")
    assert receipts[0].approval_record.startswith("auto-final:")
    entry = ProjectArtifactManifestAdapter(project_path).get_entry(ArtifactKey.episode_video(1, "auto-final-e1"))
    assert entry is not None
    assert isinstance(entry.r2, dict)
    assert entry.r2["approved_master"]["selected_by"] == automation_principal(run.run_id)


async def test_a_render_output_changed_before_mastering_never_becomes_a_master(render_host):
    sessions, controller, render, run, project_path = render_host
    await _tick(sessions, controller, run)
    await _tick(sessions, controller, run)
    await asyncio.gather(*render._jobs.values())
    rendered = await _tick(sessions, controller, run)
    async with sessions() as session:
        outcome = await ProductionRunRepository(session).stage_outcome(run=rendered, stage=RunStage.RENDER)
    final_path = project_path / outcome.receipts[0].receipt_ref.partition("@")[2]
    final_path.write_bytes(final_path.read_bytes() + b"tamper")

    blocked = await _tick(sessions, controller, run)

    assert (blocked.stage, blocked.status, blocked.reason) == (
        RunStage.MASTER,
        RunStatus.BLOCKED_CONFIGURATION,
        "RENDER_OUTPUT_CHANGED",
    )
    async with sessions() as session:
        assert (await session.execute(sa.select(PromotionReceiptModel))).first() is None
