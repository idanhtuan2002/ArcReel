"""ADR-0122: what needs the operator across every project, in one read.

Story runs waiting for approval or stopped, production runs waiting for a review or stopped, and the work running
now (story runs, production runs, queued and running generation tasks), grouped per project. The read is bounded:
the newest ``STORY_RUNS_READ`` story runs, every production run that is not finished, and the active task counts,
so its cost does not grow with the history of thousands of projects.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from lib.db import async_session_factory
from lib.db.models.production_run import ProductionRunModel
from lib.db.models.task import Task
from lib.db.repositories.task_repo import STORY_RUN_TASK_TYPE
from lib.project_kinds import project_kind
from lib.project_manager import get_project_manager
from server.auth import CurrentUser

router = APIRouter()

STORY_RUNS_READ = 500
ITEMS_SHOWN = 200
_PHASE = re.compile(r'"phase"\s*:\s*"([A-Z_]+)"')
STORY_DECISION = frozenset({"READY_FOR_APPROVAL"})
STORY_BLOCKED = frozenset(
    {
        "BLOCKED_BUDGET",
        "BLOCKED_QUALITY",
        "BLOCKED_BINDING_MISMATCH",
        "BLOCKED_PROPAGATION",
        "MODEL_UNAVAILABLE",
        "COMMIT_BLOCKED",
        "RECOVERY_INCONSISTENT",
    }
)
STORY_RUNNING = frozenset({"RUNNING", "APPROVING", "PARTIALLY_COMMITTED"})
RUN_TERMINAL = frozenset({"SUCCEEDED", "FAILED", "FAILED_QUALITY", "CANCELLED"})
RUN_RUNNING = frozenset({"PENDING", "RUNNING", "WAITING_TASK"})
ACTIVE_TASKS = ("queued", "running")


def _lane_of_story(phase: str) -> str | None:
    if phase in STORY_DECISION:
        return "decision"
    if phase in STORY_BLOCKED:
        return "blocked"
    if phase in STORY_RUNNING:
        return "running"
    return None


def _lane_of_run(status: str) -> str | None:
    if status in RUN_TERMINAL:
        return None
    if status == "WAITING_REVIEW":
        return "decision"
    if status in RUN_RUNNING:
        return "running"
    return "blocked"


@router.get("/operations")
async def operations(user: CurrentUser) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    async with async_session_factory() as session:
        story_rows = (
            await session.execute(
                select(Task.project_name, Task.resource_id, Task.execution_checkpoint_json, Task.updated_at)
                .where(Task.task_type == STORY_RUN_TASK_TYPE, Task.user_id == user.id)
                .order_by(Task.queued_at.desc())
                .limit(STORY_RUNS_READ)
            )
        ).all()
        run_rows = (
            await session.execute(
                select(
                    ProductionRunModel.project_name,
                    ProductionRunModel.run_id,
                    ProductionRunModel.status,
                    ProductionRunModel.stage,
                ).where(
                    ProductionRunModel.user_id == user.id,
                    ProductionRunModel.status.not_in(sorted(RUN_TERMINAL)),
                )
            )
        ).all()
        task_rows = (
            await session.execute(
                select(Task.project_name, func.count())
                .where(
                    Task.user_id == user.id,
                    Task.status.in_(ACTIVE_TASKS),
                    Task.task_type != STORY_RUN_TASK_TYPE,
                )
                .group_by(Task.project_name)
            )
        ).all()
    for project, run_id, state, updated in story_rows:
        match = _PHASE.search((state or "")[:2000])
        lane = _lane_of_story(match.group(1)) if match else None
        if lane is not None:
            items.append(
                {
                    "lane": lane,
                    "kind": "story_run",
                    "project": project,
                    "run_id": run_id,
                    "state": match.group(1) if match else "",
                    "updated_at": updated.isoformat() if updated else None,
                }
            )
    for project, run_id, status, stage in run_rows:
        lane = _lane_of_run(status)
        if lane is not None:
            items.append(
                {
                    "lane": lane,
                    "kind": "production_run",
                    "project": project,
                    "run_id": run_id,
                    "state": status,
                    "stage": stage,
                }
            )
    tasks: dict[str, int] = {str(project): int(count) for project, count in task_rows}
    projects = sorted({item["project"] for item in items} | set(tasks))
    titles = await asyncio.to_thread(_titles, projects)
    for item in items:
        item["title"], item["project_kind"] = titles.get(item["project"], (item["project"], "film"))
    lanes = {lane: [i for i in items if i["lane"] == lane][:ITEMS_SHOWN] for lane in ("decision", "blocked", "running")}
    counts = {lane: sum(1 for i in items if i["lane"] == lane) for lane in lanes}
    return {
        "counts": {**counts, "tasks": sum(tasks.values())},
        "lanes": lanes,
        "tasks": [
            {"project": p, "title": titles.get(p, (p, "film"))[0], "tasks": n}
            for p, n in sorted(tasks.items(), key=lambda kv: -kv[1])
        ][:ITEMS_SHOWN],
    }


def _titles(projects: list[str]) -> dict[str, tuple[str, str]]:
    manager = get_project_manager()
    out: dict[str, tuple[str, str]] = {}
    for name in projects:
        try:
            project = manager.load_project(name)
        except Exception:
            continue
        title = project.get("title")
        out[name] = (title if isinstance(title, str) and title else name, project_kind(project))
    return out
