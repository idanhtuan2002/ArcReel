"""Audiobook jobs (ADR-0159): a committed story spoken with the project's narration voice into audiobook files.

One job per project, story run and preset at a time, in this process. The files live under the project's
``output/audiobook/<run_id>-<preset>/``; a job started again reuses every segment already spoken there.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lib.audio_backends.base import AudioSynthesisRequest
from lib.audiobook import PRESETS, parse_manuscript, render_audiobook
from lib.backend_assembly.assembler import assemble_backend
from lib.config.resolver import ConfigResolver
from lib.music_bed import MusicCue, MusicUnavailable, music_service_from_env
from lib.narration_delivery import synthesis_text
from lib.project_manager import ProjectManager

logger = logging.getLogger(__name__)

#: Files a finished job offers, by kind.
FILES = {"m4b": "audiobook.m4b", "mp3": "audiobook.mp3", "mp4": "audiobook.mp4", "chapters": "chapters.txt"}
_BED_SECONDS = 180.0
#: The synthesis language name some audio backends take, by the project's source language.
LANGUAGE_NAMES = {"vi": "Vietnamese", "en": "English", "zh": "Chinese"}
_BED_BPM = {"standard": 72, "sleep": 56}


class AudiobookRefused(ValueError):
    """The request cannot start a job; the code names why."""


@dataclass
class AudiobookJob:
    run_id: str
    preset: str
    state: str = "running"
    done: int = 0
    total: int = 0
    error: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    duration: float | None = None
    files: list[str] = field(default_factory=list)


def output_dir(projects: ProjectManager, project_name: str, run_id: str, preset: str) -> Path:
    return projects.get_project_path(project_name) / "output" / "audiobook" / f"{run_id}-{preset}"


def _cover(project_dir: Path) -> Path | None:
    """The first storyboard of the project's film, if it has one."""
    boards = sorted((project_dir / "storyboards").glob("*.png")) if (project_dir / "storyboards").is_dir() else []
    return boards[0] if boards else None


class AudiobookJobs:
    def __init__(self, projects: ProjectManager, sessions: Any) -> None:
        self._projects = projects
        self._sessions = sessions
        self._jobs: dict[tuple[str, str, str, str], AudiobookJob] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def status(self, user_id: str, project_name: str, run_id: str) -> list[dict[str, Any]]:
        """Every preset's job of this story: running or finished in this process, or finished on disk before."""
        found: dict[str, dict[str, Any]] = {}
        for preset in PRESETS:
            job = self._jobs.get((user_id, project_name, run_id, preset))
            if job is not None:
                found[preset] = asdict(job)
                continue
            work = output_dir(self._projects, project_name, run_id, preset)
            files = [kind for kind, name in FILES.items() if (work / name).is_file()]
            if "m4b" in files:
                found[preset] = asdict(AudiobookJob(run_id=run_id, preset=preset, state="done", files=files))
        return list(found.values())

    async def start(
        self, *, user_id: str, project_name: str, run_id: str, preset: str, manuscript: bytes
    ) -> dict[str, Any]:
        if preset not in PRESETS:
            raise AudiobookRefused("UNKNOWN_PRESET")
        book = parse_manuscript(manuscript.decode("utf-8"))
        if not book.chapters:
            raise AudiobookRefused("EMPTY_MANUSCRIPT")
        key = (user_id, project_name, run_id, preset)
        current = self._jobs.get(key)
        if current is not None and current.state == "running":
            return asdict(current)
        job = AudiobookJob(run_id=run_id, preset=preset)
        self._jobs[key] = job
        task = asyncio.create_task(self._run(job, project_name, book))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return asdict(job)

    async def _run(self, job: AudiobookJob, project_name: str, book: Any) -> None:
        preset = PRESETS[job.preset]
        project = self._projects.load_project(project_name)
        project_dir = self._projects.get_project_path(project_name)
        work = output_dir(self._projects, project_name, job.run_id, job.preset)
        try:
            async with ConfigResolver(self._sessions).session() as resolver:
                route = await resolver.resolve_audio_backend(project, None)
                voice = await resolver.resolve_narration_voice(project)
                backend = await assemble_backend(
                    provider_id=route.provider_id, media_type="audio", model_id=route.model_id, resolver=resolver
                )
            model_id = getattr(backend, "model", None) or route.model_id

            async def speak(text: str, path: Path) -> None:
                await backend.synthesize(
                    AudioSynthesisRequest(
                        text=synthesis_text(text, model_id),
                        output_path=path,
                        voice=voice,
                        language_type=LANGUAGE_NAMES.get(str(project.get("source_language") or "vi"), "Vietnamese"),
                    )
                )

            music: Path | None = None
            service = music_service_from_env()
            if service is not None:
                cue = MusicCue(caption=preset.music_caption, bpm=_BED_BPM[preset.name], seconds=_BED_SECONDS)
                try:
                    music = await service.render(cue, work / f"bed-{cue.digest()}.wav")
                except MusicUnavailable as error:
                    logger.warning("audiobook music bed skipped: %s", error)

            def progress(done: int, total: int) -> None:
                job.done, job.total = done, total

            result = await render_audiobook(
                book,
                work,
                speak=speak,
                voice_key=f"{route.provider_id}/{model_id}/{voice}",
                preset=preset,
                music=music,
                cover=_cover(project_dir),
                on_progress=progress,
            )
            job.duration = round(result.duration, 1)
            job.files = [kind for kind, name in FILES.items() if (work / name).is_file()]
            job.state = "done"
        except Exception as error:  # a failed job reports its error; spoken segments stay cached for a re-run
            logger.exception("audiobook job failed")
            job.state, job.error = "failed", f"{type(error).__name__}: {error}"[:300]


__all__ = ["FILES", "AudiobookJob", "AudiobookJobs", "AudiobookRefused", "output_dir"]
