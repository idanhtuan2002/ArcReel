"""Video-source jobs (ADR-0161): a video URL becomes a story source of the project, ready for a variant.

The job downloads the audio, transcribes it with a Whisper model of a configured OpenAI-compatible provider (the
first enabled model whose id names ``whisper``, ``large-v3`` before ``turbo``), and writes ``source/<slug>.txt`` with
its origin in ``source_origins/<slug>.json``. One job per project and URL at a time, in this process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import tempfile
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from lib.openai_shared import create_openai_client
from lib.project_manager import ProjectManager
from lib.video_ingest import (
    IngestRefused,
    audio_chunks,
    download_audio,
    origin_record,
    source_text,
    transcribe,
)

logger = logging.getLogger(__name__)


@dataclass
class VideoSourceJob:
    url: str
    state: str = "running"
    step: str = "download"
    error: str | None = None
    source: str | None = None
    title: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def slug(title: str) -> str:
    folded = unicodedata.normalize("NFKD", title.replace("đ", "d").replace("Đ", "D"))
    ascii_text = folded.encode("ascii", "ignore").decode().lower()
    return (re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-") or "video-source")[:60]


async def whisper_route(sessions: Any) -> tuple[str, str, str]:
    """``(base_url, api_key, model_id)`` of the transcription model to use; refuses when none is configured."""
    async with sessions() as session:
        providers = await CustomProviderRepository(session).list_providers_with_models()
    candidates: list[tuple[int, str, str, str]] = []
    for provider, models in providers:
        if not provider.api_key or not provider.base_url.startswith("http"):
            continue
        for model in models:
            name = model.model_id.lower()
            if model.is_enabled and "whisper" in name:
                rank = 0 if "large-v3" in name and "turbo" not in name else 1
                candidates.append((rank, provider.base_url, provider.api_key, model.model_id))
    if not candidates:
        raise IngestRefused("NO_TRANSCRIPTION_MODEL")
    _rank, base_url, key, model_id = min(candidates, key=lambda c: c[0])
    return base_url, key, model_id


class VideoSourceJobs:
    def __init__(self, projects: ProjectManager, sessions: Any) -> None:
        self._projects = projects
        self._sessions = sessions
        self._jobs: dict[tuple[str, str], VideoSourceJob] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def status(self, project_name: str) -> list[dict[str, Any]]:
        return [asdict(job) for (name, _url), job in self._jobs.items() if name == project_name]

    async def start(self, *, project_name: str, url: str) -> dict[str, Any]:
        if not re.match(r"^https?://\S+$", url.strip()):
            raise IngestRefused("UNSUPPORTED_URL")
        key = (project_name, url.strip())
        current = self._jobs.get(key)
        if current is not None and current.state == "running":
            return asdict(current)
        job = VideoSourceJob(url=url.strip())
        self._jobs[key] = job
        task = asyncio.create_task(self._run(job, project_name))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return asdict(job)

    async def _run(self, job: VideoSourceJob, project_name: str) -> None:
        work = Path(tempfile.mkdtemp(prefix="arcreel-video-source-"))
        try:
            base_url, key, model_id = await whisper_route(self._sessions)
            audio, info = await asyncio.to_thread(download_audio, job.url, work)
            job.title = info.title
            job.step = "transcribe"
            chunks = await audio_chunks(audio, work)
            client = create_openai_client(api_key=key, base_url=base_url, max_retries=2)

            async def call(path: Path) -> dict[str, Any]:
                data = await asyncio.to_thread(path.read_bytes)
                result = await client.audio.transcriptions.create(
                    file=(path.name, data), model=model_id, response_format="verbose_json"
                )
                return result.model_dump()

            transcript = await transcribe(chunks, call)
            if not transcript.segments:
                raise IngestRefused("NO_SPEECH")
            job.step = "write"
            job.source = await asyncio.to_thread(self._write, project_name, info, transcript)
            job.state = "done"
        except IngestRefused as refused:
            job.state, job.error = "failed", str(refused)
        except Exception as error:  # the job reports its failure; nothing is written
            logger.exception("video source job failed")
            job.state, job.error = "failed", f"{type(error).__name__}: {error}"[:300]
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _write(self, project_name: str, info: Any, transcript: Any) -> str:
        root = self._projects.get_project_path(project_name)
        sources = root / "source"
        origins = root / "source_origins"
        sources.mkdir(parents=True, exist_ok=True)
        origins.mkdir(parents=True, exist_ok=True)
        name = slug(info.title)
        target = sources / f"{name}.txt"
        n = 2
        while target.exists():
            target = sources / f"{name}-{n}.txt"
            n += 1
        target.write_text(source_text(info, transcript), encoding="utf-8")
        (origins / f"{target.stem}.json").write_text(
            json.dumps(origin_record(info, transcript), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return f"source/{target.name}"


__all__ = ["VideoSourceJob", "VideoSourceJobs", "slug", "whisper_route"]
