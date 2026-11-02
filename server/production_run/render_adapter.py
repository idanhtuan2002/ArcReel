"""``RENDER``: each target episode's exact current presentations rendered by the native renderer.

The step materializes the episode once through ``PresentationReadModelService`` (the run's ``use_tts`` rendition)
and renders that snapshot under the project's ``production/`` tree. Only verified presentations of current media
render; a raw upload or a stale selection refuses. Rendering runs off the controller lease in a background job;
the outputs are content-addressed files, so after a restart the step re-verifies finished outputs or renders
again, at most ``max_attempts`` times. The evidence for each episode is its render manifest's digest.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from pathlib import Path

from lib.db.repositories.production_runs import ProductionRunRepository
from lib.episode_target_duration import MAX_EPISODE_TARGET_DURATION, MIN_EPISODE_TARGET_DURATION
from lib.narration_delivery import USE_TTS
from lib.path_safety import safe_join
from lib.presentation_renderer import (
    RenderContract,
    RenderCue,
    RenderInput,
    RenderRefused,
    RenderUnit,
    render_presentations,
    sha256_file,
)
from lib.project_manager import ProjectManager
from lib.speech_presentation import SpeechPresentation
from r2.automation.identity import digest_value
from r2.contracts.automation import (
    BudgetReservation,
    DispatchIntent,
    OwnerReceipt,
    RunPolicy,
    RunSnapshot,
    RunStage,
    StageOutcome,
    UsageReceipt,
)
from r2.contracts.common import ensure_json_value
from server.production_run.owner_support import (
    OwnerBlocked,
    Sessions,
    current_run,
    current_subject,
    outcome,
    required_outcome,
    usage_receipt,
)
from server.production_run.ports import StepPlan
from server.production_run.text_adapter import episode_number
from server.services.automation_grants import RunAutomationAuthority
from server.services.presentation_read_model import (
    MaterializedEpisode,
    PresentationReadModelService,
    PresentationUnavailableError,
)

RENDER_OWNER = "renderer"


def render_contract(policy: RunPolicy) -> RenderContract:
    """The policy's output format; the episode length only has to fall inside the product's episode duration
    interval, since the target duration is a planning preference, not a creative limit."""
    return RenderContract(
        width=policy.width,
        height=policy.height,
        fps=policy.fps,
        min_seconds=MIN_EPISODE_TARGET_DURATION,
        max_seconds=MAX_EPISODE_TARGET_DURATION,
    )


def render_dir(run: RunSnapshot, episode: int) -> Path:
    """Project-relative output directory of one episode's render for the run's current generation."""
    return Path("production") / "automation" / run.run_id / f"g{run.generation}" / f"episode_{episode}"


def render_input(project_path: Path, episode: int, materialized: MaterializedEpisode) -> RenderInput:
    units: list[RenderUnit] = []
    for item in materialized.presentations:
        presentation = item.presentation
        if not isinstance(presentation, SpeechPresentation):
            raise RenderRefused("UNVERIFIED_PRESENTATION", item.presentation.unit_id)
        video, narration = presentation.video, presentation.narration_audio
        tracks = [video.media] + ([narration.media] if narration is not None else [])
        if presentation.selection != "current" or any(
            media.selection != "current" or media.currency != "current" for media in tracks
        ):
            raise RenderRefused("STALE_PRESENTATION", presentation.unit_id)
        if video.start_microseconds != 0:
            raise RenderRefused("INVALID_UNIT_WINDOW", presentation.unit_id)
        units.append(
            RenderUnit(
                unit_id=presentation.unit_id,
                video_path=safe_join(project_path, video.media.artifact_path),
                video_start_us=0,
                duration_us=video.duration_microseconds,
                video_audio=video.audio_enabled,
                video_gain=video.gain,
                narration_path=safe_join(project_path, narration.media.artifact_path) if narration else None,
                narration_start_us=narration.start_microseconds if narration else 0,
                narration_duration_us=narration.duration_microseconds if narration else 0,
                narration_gain=narration.gain if narration else 1.0,
                cues=tuple(
                    RenderCue(cue.start_microseconds, cue.end_microseconds, cue.text) for cue in presentation.subtitles
                ),
            )
        )
    return RenderInput(episode=episode, units=tuple(units))


class RenderAdapter:
    owner = RENDER_OWNER
    seconds_per_target = 600

    def __init__(
        self,
        sessions: Sessions,
        *,
        authority: RunAutomationAuthority,
        projects: ProjectManager,
        presentations: PresentationReadModelService | None = None,
        max_attempts: int = 2,
    ) -> None:
        self._sessions, self._authority, self._projects = sessions, authority, projects
        self._presentations = presentations or PresentationReadModelService(projects)
        self._max_attempts = max_attempts
        self._jobs: dict[str, asyncio.Task[float]] = {}

    async def plan(self, *, run: RunSnapshot) -> StepPlan:
        media = await required_outcome(self._sessions, run, RunStage.MEDIA)
        return StepPlan(
            unit_key="render",
            input_refs=media.receipts,
            estimated_cost_minor_units=0,
            estimated_model_calls=0,
            estimated_tasks=0,
            estimated_runtime_seconds=self.seconds_per_target * len(run.targets),
        )

    async def dispatch(self, intent: DispatchIntent) -> OwnerReceipt:
        digest = digest_value(
            "r2.production-render-stage.v1",
            ensure_json_value({"input_refs": [ref.model_dump(mode="json") for ref in intent.input_refs]}),
        )
        subject = await current_subject(self._sessions, intent, subject_digest=digest)
        async with self._sessions() as session, session.begin():
            await self._authority.require_locked(session, subject=subject)
        await self._start(intent, digest)
        return OwnerReceipt(owner=self.owner, receipt_ref=intent.identity.command_id, digest=digest)

    async def inspect(self, *, intent: DispatchIntent, receipt: OwnerReceipt) -> StageOutcome:
        job = self._jobs.get(intent.identity.command_id)
        if job is not None and not job.done():
            return outcome(intent, "WAIT", owner_state="RENDERING")
        if job is not None:
            self._jobs.pop(intent.identity.command_id, None)
            error = job.exception()
            if isinstance(error, RenderRefused):
                raise OwnerBlocked(f"RENDER_{error.code}")
            if isinstance(error, PresentationUnavailableError):
                raise OwnerBlocked("RENDER_PRESENTATION_UNAVAILABLE")
            if error is not None:
                raise OwnerBlocked("RENDER_FAILED")
        run = await current_run(self._sessions, intent)
        evidence = [self._verified(run, episode_number(target)) for target in run.targets]
        if all(item is not None for item in evidence):
            return outcome(
                intent, "PASS", receipts=tuple(item for item in evidence if item is not None), owner_state="RENDERED"
            )
        await self._start(intent, receipt.digest)
        return outcome(intent, "WAIT", owner_state="RENDERING")

    async def usage(self, *, receipt: OwnerReceipt, reservation: BudgetReservation) -> UsageReceipt | None:
        scope = reservation.scope
        async with self._sessions() as session:
            run = await ProductionRunRepository(session).get(
                user_id=scope.user_id, project_name=scope.project_name, run_id=scope.run_id
            )
        if run is None:
            return None
        seconds = 0.0
        for target in run.targets:
            timing = self._project_file(run, episode_number(target), "timing.json")
            if not timing.is_file():
                return None
            seconds += float(json.loads(timing.read_text(encoding="utf-8"))["render_seconds"])
        return usage_receipt(receipt, reservation, runtime_seconds=math.ceil(seconds))

    # --- helpers -------------------------------------------------------------------------------------

    async def _start(self, intent: DispatchIntent, subject_digest: str) -> None:
        key = intent.identity.command_id
        if key in self._jobs:
            return
        subject = await current_subject(self._sessions, intent, subject_digest=subject_digest)
        async with self._sessions() as session, session.begin():
            repository = ProductionRunRepository(session)
            if await repository.owner_attempts(intent=intent, sub_key="render") >= self._max_attempts:
                raise OwnerBlocked("RENDER_RETRY_LIMIT")
            await self._authority.require_locked(session, subject=subject)
            await repository.record_owner_attempt(intent=intent, sub_key="render")
        run = await current_run(self._sessions, intent)
        self._jobs[key] = asyncio.create_task(self._render_all(run))

    async def _render_all(self, run: RunSnapshot) -> float:
        project_path = self._projects.get_project_path(run.project_name)
        total = 0.0
        for target in run.targets:
            episode = episode_number(target)
            materialized = await self._presentations.materialize_episode(
                project_name=run.project_name, episode=episode, variant=USE_TTS
            )
            snapshot = render_input(project_path, episode, materialized)
            started = time.monotonic()
            output = project_path / render_dir(run, episode)
            await asyncio.to_thread(
                render_presentations, episode=snapshot, output_dir=output, contract=render_contract(run.policy)
            )
            seconds = time.monotonic() - started
            timing = output / f"episode_{episode}.timing.json"
            timing.write_text(json.dumps({"render_seconds": round(seconds, 3)}), encoding="utf-8")
            total += seconds
        return total

    def _project_file(self, run: RunSnapshot, episode: int, suffix: str) -> Path:
        return (
            self._projects.get_project_path(run.project_name) / render_dir(run, episode) / f"episode_{episode}.{suffix}"
        )

    def _verified(self, run: RunSnapshot, episode: int) -> OwnerReceipt | None:
        """Evidence for a finished render whose final and subtitles still hash to its manifest."""
        relative = render_dir(run, episode)
        root = self._projects.get_project_path(run.project_name) / relative
        manifest_path = root / f"episode_{episode}.manifest.json"
        final, subtitle = root / f"episode_{episode}.mp4", root / f"episode_{episode}.srt"
        if not (manifest_path.is_file() and final.is_file() and subtitle.is_file()):
            return None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (sha256_file(final), sha256_file(subtitle)) != (
            manifest.get("final_sha256"),
            manifest.get("subtitle_sha256"),
        ):
            raise OwnerBlocked("RENDER_OUTPUT_CHANGED")
        return OwnerReceipt(
            owner=self.owner,
            receipt_ref=f"episode:{episode}:final@{(relative / final.name).as_posix()}",
            digest="sha256:" + sha256_file(manifest_path),
        )


__all__ = ["RENDER_OWNER", "RenderAdapter", "render_contract", "render_dir", "render_input"]
