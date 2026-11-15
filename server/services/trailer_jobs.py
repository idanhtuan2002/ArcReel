"""Trailer jobs (ADR-0164): a succeeded production run's verified finals cut into one trailer.

One job per user, project and run at a time, in this process. The trailer and its cut list live under the project's
``output/trailer/<run_id>/``; a finished trailer on disk is reported after a restart.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.production_runs import ProductionRunRepository
from lib.project_manager import ProjectManager
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult, TextTaskType
from lib.text_generator import TextGenerator
from lib.trailer import Episode, TrailerError, cut_trailer, plan_trailer, probe
from r2.contracts.automation import RunSnapshot, RunStatus
from server.production_run.render_adapter import episode_cards
from server.production_run.report import verified_final

logger = logging.getLogger(__name__)

TRAILER = "trailer.mp4"
CUTS = "trailer.json"


class TrailerRefused(ValueError):
    """The request cannot start a job; the code names why."""


@dataclass
class TrailerJob:
    run_id: str
    state: str = "running"
    error: str | None = None
    duration: float | None = None
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def trailer_dir(projects: ProjectManager, project_name: str, run_id: str) -> Path:
    return projects.get_project_path(project_name) / "output" / "trailer" / run_id


def run_episodes(projects: ProjectManager, run: RunSnapshot) -> list[tuple[int, Path]]:
    """Each completed episode of the run with its final, while the final's bytes are still the verified ones."""
    found: list[tuple[int, Path]] = []
    for output in run.completed_targets:
        prefix, _, number = output.target.partition(":")
        if prefix != "episode" or not number.isdigit():
            continue
        final = verified_final(projects, run, int(number))
        if final is not None and final.with_suffix(".srt").is_file():
            found.append((int(number), final))
    return sorted(found)


class TrailerJobs:
    def __init__(self, projects: ProjectManager, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._projects = projects
        self._sessions = sessions
        self._jobs: dict[tuple[str, str, str], TrailerJob] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def status(self, user_id: str, project_name: str, run_id: str) -> dict[str, Any] | None:
        job = self._jobs.get((user_id, project_name, run_id))
        if job is not None:
            return asdict(job)
        work = trailer_dir(self._projects, project_name, run_id)
        if (work / TRAILER).is_file() and (work / CUTS).is_file():
            cuts = json.loads((work / CUTS).read_text(encoding="utf-8"))
            return asdict(TrailerJob(run_id=run_id, state="done", duration=cuts.get("duration")))
        return None

    def file(self, project_name: str, run_id: str) -> Path | None:
        path = trailer_dir(self._projects, project_name, run_id) / TRAILER
        return path if path.is_file() else None

    async def start(self, *, user_id: str, project_name: str, run_id: str) -> dict[str, Any]:
        async with self._sessions() as session:
            run = await ProductionRunRepository(session).get(user_id=user_id, project_name=project_name, run_id=run_id)
        if run is None:
            raise TrailerRefused("RUN_NOT_FOUND")
        if run.status is not RunStatus.SUCCEEDED:
            raise TrailerRefused("RUN_NOT_SUCCEEDED")
        episodes = await asyncio.to_thread(run_episodes, self._projects, run)
        if not episodes:
            raise TrailerRefused("NO_VERIFIED_FINAL")
        key = (user_id, project_name, run_id)
        current = self._jobs.get(key)
        if current is not None and current.state == "running":
            return asdict(current)
        job = TrailerJob(run_id=run_id)
        self._jobs[key] = job
        task = asyncio.create_task(self._run(job, project_name, user_id, episodes))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return asdict(job)

    async def _run(self, job: TrailerJob, project_name: str, user_id: str, finals: list[tuple[int, Path]]) -> None:
        try:
            project = self._projects.load_project(project_name)
            project_path = self._projects.get_project_path(project_name)
            episodes: list[Episode] = []
            for number, final in finals:
                _w, _h, _fps, duration = await probe(final)
                episodes.append(
                    Episode(
                        number=number,
                        final=final,
                        duration=duration,
                        subtitles=final.with_suffix(".srt").read_text(encoding="utf-8"),
                        has_end_card=episode_cards(project, project_path, number)[1] is not None,
                    )
                )
            generator = await TextGenerator.create(TextTaskType.SCRIPT, project_name)

            async def generate(request: TextGenerationRequest) -> TextGenerationResult:
                return await generator.generate(request, project_name, user_id=user_id)

            title = str(project.get("title") or project_name)
            plan = await plan_trailer(title, episodes, generate)
            work = trailer_dir(self._projects, project_name, job.run_id)
            work.mkdir(parents=True, exist_ok=True)
            staging = work / ("." + TRAILER)
            cuts = await cut_trailer(plan, episodes, title=title, output=staging)
            _w, _h, _fps, duration = await probe(staging)
            staging.replace(work / TRAILER)
            record = {"run_id": job.run_id, "duration": duration, "plan": plan.model_dump(), "cuts": cuts}
            (work / CUTS).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            job.duration, job.state = duration, "done"
        except TrailerError as error:
            job.state, job.error = "failed", str(error)
        except Exception as error:  # the job reports its failure; no trailer is written
            logger.exception("trailer job failed")
            job.state, job.error = "failed", f"{type(error).__name__}: {error}"[:300]


__all__ = ["TrailerJob", "TrailerJobs", "TrailerRefused", "run_episodes", "trailer_dir"]
