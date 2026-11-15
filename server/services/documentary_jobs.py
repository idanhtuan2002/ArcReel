"""Documentary jobs (ADR-0162): a topic becomes a sourced narration manuscript and a story source of the project.

The job researches public reference pages, writes the cited narration with the project's script text route, and
stores ``research/<slug>/`` (research pack, claim ledger, sources, evidence, manuscript, citations) and
``source/<slug>.txt`` for the film path. One job per project and topic at a time, in this process.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from lib.documentary import Documentary, DocumentaryError, make_documentary
from lib.project_manager import ProjectManager
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult, TextTaskType
from lib.text_generator import TextGenerator
from server.services.video_sources import slug
from server.story_authoring.handoff import narration_source

logger = logging.getLogger(__name__)

#: A generic client name: the reference API asks automated clients to identify themselves.
USER_AGENT = "ArcReel-documentary/1.0 (automated research client)"


@dataclass
class DocumentaryJob:
    topic: str
    language: str
    form: str = "story"
    state: str = "running"
    error: str | None = None
    source: str | None = None
    title: str | None = None
    claims: int = 0
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


async def wiki_fetch(url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
    async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": USER_AGENT}) as client:
        response = await client.get(url, params=dict(params))
        response.raise_for_status()
        return response.json()


class DocumentaryJobs:
    def __init__(self, projects: ProjectManager) -> None:
        self._projects = projects
        self._jobs: dict[tuple[str, str], DocumentaryJob] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def status(self, project_name: str) -> list[dict[str, Any]]:
        return [asdict(job) for (name, _topic), job in self._jobs.items() if name == project_name]

    async def start(
        self, *, project_name: str, topic: str, language: str, user_id: str, form: str = "story"
    ) -> dict[str, Any]:
        key = (project_name, topic.strip())
        current = self._jobs.get(key)
        if current is not None and current.state == "running":
            return asdict(current)
        job = DocumentaryJob(topic=topic.strip(), language=language, form=form)
        self._jobs[key] = job
        task = asyncio.create_task(self._run(job, project_name, user_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return asdict(job)

    async def _run(self, job: DocumentaryJob, project_name: str, user_id: str) -> None:
        try:
            generator = await TextGenerator.create(TextTaskType.SCRIPT, project_name)

            async def generate(request: TextGenerationRequest) -> TextGenerationResult:
                return await generator.generate(request, project_name, user_id=user_id)

            doc = await make_documentary(
                job.topic, language=job.language, fetch=wiki_fetch, generate=generate, form=job.form
            )
            job.title, job.claims = doc.title, len(doc.ledger.claims)
            job.source = await asyncio.to_thread(self._write, project_name, doc)
            job.state = "done"
        except DocumentaryError as error:
            job.state, job.error = "failed", str(error)
        except Exception as error:  # the job reports its failure; nothing is written
            logger.exception("documentary job failed")
            job.state, job.error = "failed", f"{type(error).__name__}: {error}"[:300]

    def _write(self, project_name: str, doc: Documentary) -> str:
        root = self._projects.get_project_path(project_name)
        name = slug(doc.title)
        sources = root / "source"
        sources.mkdir(parents=True, exist_ok=True)
        target = sources / f"{name}.txt"
        n = 2
        while target.exists():
            target = sources / f"{name}-{n}.txt"
            n += 1
        folder = root / "research" / target.stem
        folder.mkdir(parents=True, exist_ok=True)

        def dump(file: str, value: Any) -> None:
            (folder / file).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        dump("research_pack.json", doc.research_pack.model_dump(mode="json"))
        dump("claim_ledger.json", doc.ledger.model_dump(mode="json"))
        dump("sources.json", [s.model_dump(mode="json") for s in doc.sources])
        dump("evidence.json", [e.model_dump(mode="json") for e in doc.evidence])
        (folder / "manuscript.md").write_text(doc.manuscript, encoding="utf-8")
        (folder / "citations.md").write_text(doc.citations, encoding="utf-8")
        target.write_text(narration_source(doc.manuscript), encoding="utf-8")
        return f"source/{target.name}"


def research_folder(projects: ProjectManager, project_name: str, source_name: str) -> Path:
    return projects.get_project_path(project_name) / "research" / Path(source_name).stem


__all__ = ["DocumentaryJob", "DocumentaryJobs", "research_folder", "wiki_fetch"]
