"""Media-route probes and the launch record, started from the run panel and run on this host.

Reviewers are trusted by configuration (ADR-0169) and have no qualification job. The receipt directory and the launch
evidence are host settings (``ARCREEL_REVIEWER_RECEIPTS``, ``ARCREEL_LAUNCH_EVIDENCE``), never request input. Probe jobs
run in this process; a restart ends a running job.
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
from lib.project_manager import ProjectManager
from r2.automation.profiles import resolve_launch_profile, route_digest
from r2.contracts.automation import ModelRoute
from server.production_run.composition import ProjectPolicyResolver
from server.production_run.media_probe import MEDIA_ROLES, RECEIPTS_ENV, probe_evidence, probe_media_route
from server.production_run.qualification import build_record

EVIDENCE_ENV = "ARCREEL_LAUNCH_EVIDENCE"


type Sessions = async_sessionmaker[AsyncSession]


class QualificationRefused(ValueError):
    """A qualification the host cannot start or record; the code names why."""


@dataclass
class ProbeJob:
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
    """The media-route probe jobs of this host, one per project and media role at a time."""

    def __init__(
        self,
        sessions: Sessions,
        projects: ProjectManager,
        *,
        routes: Callable[[str], Awaitable[list[ModelRoute]]] | None = None,
    ) -> None:
        self._sessions, self._projects = sessions, projects
        self._project_routes = routes or self._policy_routes
        self._jobs: dict[tuple[str, str, str], ProbeJob] = {}
        #: Route digests with a media probe in flight on this host, whoever started it.
        self._probing: set[str] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    async def wait(self) -> None:
        """Until every running job has ended."""
        while self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

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
        launch_recorded = False
        if settings:
            async with self._sessions() as session:
                launch = await LaunchQualificationRepository(session).current(
                    user_id=user_id, project_name=project_name, launch_profile_id=launch_profile_id
                )
            launch_recorded = launch is not None and launch.profile_digest == digest
        return {
            "receipts_configured": _path(RECEIPTS_ENV) is not None,
            "evidence_configured": _path(EVIDENCE_ENV) is not None,
            "launch_recorded": launch_recorded,
            "media": await self._media_status(user_id, project_name) if settings else [],
        }

    async def _media_routes(self, project_name: str) -> tuple[list[ModelRoute], tuple[str, ...]]:
        """The project's image/video/audio routes and the ``(provider, model)`` pairs its launch profile names."""
        _, launch_profile_id = self._scope(project_name)
        launch = resolve_launch_profile(launch_profile_id)
        pinned = {"image": launch.image_route, "video": launch.video_route, "audio": launch.audio_route}
        routes = [route for route in await self._project_routes(project_name) if route.role in MEDIA_ROLES]
        return routes, tuple(r.role for r in routes if (r.provider_id, r.model_id) == pinned[r.role])

    async def _media_status(self, user_id: str, project_name: str) -> list[dict[str, Any]]:
        try:
            routes, pinned = await self._media_routes(project_name)
        except QualificationRefused:
            return []
        receipts = _path(RECEIPTS_ENV)
        rows = []
        for route in routes:
            evidence = probe_evidence(receipts, route)
            job = self._jobs.get((user_id, project_name, route.role))
            rows.append(
                {
                    "role": route.role,
                    "provider_id": route.provider_id,
                    "model_id": route.model_id,
                    "profile_route": route.role in pinned,
                    "probe": None
                    if evidence is None
                    else {key: evidence.get(key) for key in ("passed", "problem", "error", "recorded_at")},
                    "job": None if job is None else job.__dict__.copy(),
                }
            )
        return rows

    async def start_media_probes(self, *, user_id: str, project_name: str) -> dict[str, Any]:
        """Probe every media route that is neither the launch profile's own nor already probed, one after another."""
        receipts = _path(RECEIPTS_ENV)
        if receipts is None:
            raise QualificationRefused("PROBE_RECEIPTS_NOT_CONFIGURED")
        _, launch_profile_id = self._scope(project_name)
        launch = resolve_launch_profile(launch_profile_id)
        routes, pinned = await self._media_routes(project_name)

        def needed(route: ModelRoute) -> bool:
            evidence = probe_evidence(receipts, route)
            return (
                route.role not in pinned
                and (evidence is None or evidence.get("passed") is not True)
                and route_digest(route) not in self._probing
            )

        pending = [route for route in routes if needed(route)]
        # Jobs are registered before any await, so a second start sees them running and probes nothing twice.
        jobs = []
        for route in pending:
            job = ProbeJob(role=route.role, model_identity=route.model_identity, total=1)
            self._jobs[(user_id, project_name, route.role)] = job
            self._probing.add(route_digest(route))
            jobs.append((job, route))
        if not jobs:
            return await self.status(user_id=user_id, project_name=project_name)

        async def run() -> None:
            try:
                voice = await ConfigResolver(self._sessions).resolve_narration_voice(
                    self._projects.load_project(project_name)
                )
            except Exception as error:
                for job, route in jobs:
                    job.state, job.error = "failed", type(error).__name__
                    self._probing.discard(route_digest(route))
                return
            for job, route in jobs:
                try:
                    evidence = await probe_media_route(
                        self._sessions,
                        route=route,
                        receipts=receipts,
                        voice=voice,
                        width=launch.width,
                        height=launch.height,
                        user_id=user_id,
                    )
                    job.qualified, job.done, job.state = bool(evidence["passed"]), 1, "done"
                    job.error = evidence.get("problem")
                except Exception as error:
                    job.state, job.error = "failed", type(error).__name__
                finally:
                    self._probing.discard(route_digest(route))

        task = asyncio.create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return await self.status(user_id=user_id, project_name=project_name)

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
