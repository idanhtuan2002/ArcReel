"""Reviewer and launch qualification started from the run panel and run on this host.

The corpus, the receipt directory and the launch evidence are host settings (``ARCREEL_REVIEWER_CORPUS``,
``ARCREEL_REVIEWER_RECEIPTS``, ``ARCREEL_LAUNCH_EVIDENCE``), never request input. A reviewer job reviews the corpus
with the project's reviewer route exactly as a run would freeze it, reusing stored reviews of the same model, method
and case, and records the result only when it qualifies. Jobs run in this process; a restart ends a running job,
whose stored receipts make the next start fast. Status is read from the recorded qualifications, not from the job.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.config.resolver import ConfigResolver
from lib.db.repositories.launch_qualifications import LaunchQualificationRepository
from lib.db.repositories.reviewer_qualifications import ReviewerQualificationRepository
from lib.project_manager import ProjectManager
from r2.automation.profiles import reviewer_is_qualified
from r2.contracts.automation import ModelRoute
from server.production_run.composition import ProjectPolicyResolver
from server.production_run.evaluators import (
    OllamaReviewer,
    QualifiedEvaluator,
    prompt_digest,
    provider_base_url,
    review_method,
)
from server.production_run.gemini_reviewer import GeminiReviewer, RoutedReviewer, provider_credentials
from server.production_run.qualification import build_record, qualify

CORPUS_ENV = "ARCREEL_REVIEWER_CORPUS"
RECEIPTS_ENV = "ARCREEL_REVIEWER_RECEIPTS"
EVIDENCE_ENV = "ARCREEL_LAUNCH_EVIDENCE"
REVIEWER_ROLES = ("reviewer_a", "reviewer_b")
LANGUAGE = "vi"

type Sessions = async_sessionmaker[AsyncSession]


class QualificationRefused(ValueError):
    """A qualification the host cannot start or record; the code names why."""


@dataclass
class ReviewerJob:
    role: str
    model_identity: str
    state: str = "running"
    done: int = 0
    total: int = 0
    qualified: bool | None = None
    error: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def _path(env: str) -> Path | None:
    value = os.environ.get(env)
    return Path(value) if value else None


class QualificationJobs:
    """The reviewer qualification jobs of this host, one per project and reviewer role at a time."""

    def __init__(
        self,
        sessions: Sessions,
        projects: ProjectManager,
        *,
        evaluator: QualifiedEvaluator | None = None,
        routes: Callable[[str], Awaitable[list[ModelRoute]]] | None = None,
    ) -> None:
        self._sessions, self._projects = sessions, projects
        self._evaluator = evaluator or RoutedReviewer(
            local=OllamaReviewer(base_url_for=provider_base_url(sessions)),
            gemini=GeminiReviewer(credentials_for=provider_credentials(sessions)),
        )
        self._project_routes = routes or self._policy_routes
        self._jobs: dict[tuple[str, str, str], ReviewerJob] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    async def wait(self) -> None:
        """Until every running job has ended."""
        while self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _routes(self, project_name: str) -> list[ModelRoute]:
        return [route for route in await self._project_routes(project_name) if route.role in REVIEWER_ROLES]

    async def _policy_routes(self, project_name: str) -> list[ModelRoute]:
        policies = ProjectPolicyResolver(
            self._sessions, projects=self._projects, resolver=ConfigResolver(self._sessions)
        )
        return list(await policies.routes(project_name))

    def _scope(self, project_name: str) -> tuple[str, str]:
        settings = self._projects.load_project(project_name).get("automation") or {}
        digest = settings.get("profile_digest")
        if not digest:
            raise QualificationRefused("MISSING_PUBLISHED_PROFILE")
        return str(digest), str(settings.get("launch_profile_id", "fiction_narration_vi_v1"))

    async def status(self, *, user_id: str, project_name: str) -> dict[str, Any]:
        settings = self._projects.load_project(project_name).get("automation") or {}
        digest = settings.get("profile_digest")
        launch_profile_id = str(settings.get("launch_profile_id", "fiction_narration_vi_v1"))
        reviewers = []
        launch_recorded = False
        if settings:
            routes = await self._routes(project_name)
            async with self._sessions() as session:
                records = (
                    await ReviewerQualificationRepository(session).qualified(
                        profile_digest=str(digest), launch_profile_id=launch_profile_id, language=LANGUAGE
                    )
                    if digest
                    else ()
                )
                launch = await LaunchQualificationRepository(session).current(
                    user_id=user_id, project_name=project_name, launch_profile_id=launch_profile_id
                )
            launch_recorded = launch is not None and launch.profile_digest == digest
            for route in routes:
                method = prompt_digest(review_method(route))
                job = self._jobs.get((user_id, project_name, route.role))
                reviewers.append(
                    {
                        "role": route.role,
                        "model_identity": route.model_identity,
                        "qualified": any(
                            r.model_identity == route.model_identity and r.prompt_digest == method for r in records
                        ),
                        "job": None if job is None else job.__dict__.copy(),
                    }
                )
        return {
            "corpus_configured": _path(CORPUS_ENV) is not None and _path(RECEIPTS_ENV) is not None,
            "evidence_configured": _path(EVIDENCE_ENV) is not None,
            "reviewers": reviewers,
            "launch_recorded": launch_recorded,
        }

    async def start_reviewers(self, *, user_id: str, project_name: str) -> dict[str, Any]:
        corpus, receipts = _path(CORPUS_ENV), _path(RECEIPTS_ENV)
        if corpus is None or receipts is None or not corpus.is_file():
            raise QualificationRefused("QUALIFICATION_CORPUS_NOT_CONFIGURED")
        profile_digest, launch_profile_id = self._scope(project_name)
        routes = await self._routes(project_name)
        if len(routes) != len(REVIEWER_ROLES):
            raise QualificationRefused("MISSING_MODEL_ROLE")
        for route in routes:
            current = self._jobs.get((user_id, project_name, route.role))
            if current is not None and current.state == "running":
                continue
            job = ReviewerJob(role=route.role, model_identity=route.model_identity)
            self._jobs[(user_id, project_name, route.role)] = job
            task = asyncio.create_task(
                self._run(
                    job,
                    route,
                    corpus=corpus,
                    output=receipts / route.role,
                    profile_digest=profile_digest,
                    launch_profile_id=launch_profile_id,
                )
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return await self.status(user_id=user_id, project_name=project_name)

    async def _run(
        self,
        job: ReviewerJob,
        route: ModelRoute,
        *,
        corpus: Path,
        output: Path,
        profile_digest: str,
        launch_profile_id: str,
    ) -> None:
        def progress(done: int, total: int) -> None:
            job.done, job.total = done, total

        try:
            record = await qualify(
                corpus=corpus,
                route=route,
                evaluator=self._evaluator,
                output=output,
                profile_digest=profile_digest,
                launch_profile_id=launch_profile_id,
                language=LANGUAGE,
                stop_early=True,
                progress=progress,
            )
            job.qualified = reviewer_is_qualified(record)
            if job.qualified:
                async with self._sessions() as session, session.begin():
                    await ReviewerQualificationRepository(session).record(record)
            job.state = "done"
        except Exception as error:
            job.state, job.error = "failed", type(error).__name__

    async def record_launch(self, *, user_id: str, project_name: str) -> dict[str, Any]:
        evidence = _path(EVIDENCE_ENV)
        if evidence is None or not evidence.is_file():
            raise QualificationRefused("LAUNCH_EVIDENCE_NOT_CONFIGURED")
        record, reasons = await build_record(
            self._sessions, projects=self._projects, user_id=user_id, project_name=project_name, evidence=evidence
        )
        if record is None:
            return {"recorded": False, "reasons": list(reasons)}
        async with self._sessions() as session, session.begin():
            await LaunchQualificationRepository(session).record(record)
        return {"recorded": True, "reasons": []}


__all__ = ["QualificationJobs", "QualificationRefused"]
