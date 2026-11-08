"""The last authority check before a queued task of an automatic run executes.

An owner proves the run's grant when it submits a task, but the task runs later in a worker; a grant revoked or a
run paused or cancelled in between must stop it before any model or provider call.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.host_hardening import CommandReceiptModel
from lib.db.repositories.automation_grants import AutomationGrantRepository
from lib.db.repositories.production_runs import ProductionRunRepository
from r2.contracts.automation import RunScope, RunStatus

RUN_ACTOR_PREFIX = "production-run:"
_EXECUTABLE = {RunStatus.PENDING, RunStatus.RUNNING, RunStatus.WAITING_TASK}


class RunTaskRefused(PermissionError):
    """A queued task whose automatic run may no longer act."""


async def require_run_task_authorized(session: AsyncSession, task: dict[str, Any]) -> None:
    """Refuse a task an automatic run submitted once that run stopped or its grant is no longer active; tasks no
    run submitted pass untouched."""
    task_id = task.get("task_id")
    if not task_id:
        return
    receipts = (
        await session.execute(
            select(
                CommandReceiptModel.user_id, CommandReceiptModel.project_name, CommandReceiptModel.actor_scope
            ).where(
                CommandReceiptModel.task_id == str(task_id),
                CommandReceiptModel.actor_scope.startswith(RUN_ACTOR_PREFIX, autoescape=True),
            )
        )
    ).all()
    for user_id, project_name, actor_scope in receipts:
        scope = RunScope(user_id=user_id, project_name=project_name, run_id=actor_scope.removeprefix(RUN_ACTOR_PREFIX))
        run = await ProductionRunRepository(session).get(
            user_id=scope.user_id, project_name=scope.project_name, run_id=scope.run_id
        )
        if run is None or run.status not in _EXECUTABLE:
            raise RunTaskRefused("AUTOMATION_RUN_STOPPED")
        grant = await AutomationGrantRepository(session).head(scope)
        if grant is None or grant.state != "ACTIVE":
            raise RunTaskRefused("AUTOMATION_GRANT_REVOKED")


__all__ = ["RUN_ACTOR_PREFIX", "RunTaskRefused", "require_run_task_authorized"]
