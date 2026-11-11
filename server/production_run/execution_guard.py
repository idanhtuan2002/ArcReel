"""The last authority check before a queued task of an automatic run executes.

An owner proves the run's grant when it submits a task, but the task runs later in a worker; a grant revoked or
expired, an issuer's signed parent no longer current, or a run paused or cancelled in between must stop it before
any model or provider call. A task that no run submitted is untouched.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.host_hardening import CommandReceiptModel
from r2.contracts.automation import RunScope
from server.services.automation_grants import RunAutomationAuthority

RUN_ACTOR_PREFIX = "production-run:"

_AUTHORITY: RunAutomationAuthority | None = None


class RunTaskRefused(PermissionError):
    """A queued task whose automatic run may no longer act."""


def configure_run_task_authority(authority: RunAutomationAuthority | None) -> None:
    """Install (or remove) the activated authority queued run tasks are checked against; set once at startup."""
    global _AUTHORITY
    _AUTHORITY = authority


async def require_run_task_authorized(session: AsyncSession, task: dict[str, Any]) -> None:
    """Refuse a task an automatic run submitted unless that run's authority is still current; without an
    activated authority such a task never executes."""
    task_id = task.get("task_id")
    if not task_id:
        return
    async with session.begin():
        receipts = (
            await session.execute(
                select(CommandReceiptModel.user_id, CommandReceiptModel.project_name, CommandReceiptModel.actor_scope)
                .where(
                    CommandReceiptModel.task_id == str(task_id),
                    CommandReceiptModel.actor_scope.startswith(RUN_ACTOR_PREFIX, autoescape=True),
                )
                .order_by(CommandReceiptModel.created_at.desc())
                .limit(1)
            )
        ).all()
        # ADR-0129: a story task handed over to a later run follows that run; the run that submitted it first, now
        # ended, no longer decides. Only the newest run receipt is checked.
        for user_id, project_name, actor_scope in receipts:
            if _AUTHORITY is None:
                raise RunTaskRefused("AUTOMATION_GOVERNANCE_NOT_ACTIVATED")
            scope = RunScope(
                user_id=user_id, project_name=project_name, run_id=actor_scope.removeprefix(RUN_ACTOR_PREFIX)
            )
            try:
                await _AUTHORITY.require_queued_task_current(session, scope=scope)
            except PermissionError as refused:
                raise RunTaskRefused(str(refused)) from None


__all__ = ["RUN_ACTOR_PREFIX", "RunTaskRefused", "configure_run_task_authority", "require_run_task_authorized"]
