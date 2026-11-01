"""Queue tasks submitted by a production step, each under an exact replayable command.

A step's sub-command is ``<step command>:<sub key>``; its task ID is derived from that command and the queue's
command receipt replays it, so a crash between submit and the controller's next read never submits twice. A step
holds one authorization subject; every submit re-proves it against the run's current grant first. Usage is the sum of the measured provider calls and
task runtimes of exactly the step's own tasks.
"""

from __future__ import annotations

import math
import uuid
from typing import Any

from sqlalchemy import func, select

from lib.db.models.api_call import ApiCall
from lib.db.models.host_hardening import CommandReceiptModel
from lib.db.models.production_run import ProductionOwnerAttemptModel
from lib.db.models.task import Task
from lib.db.repositories.task_repo import TaskRepository
from r2.automation.identity import digest_value
from r2.contracts.automation import BudgetReservation, DispatchIntent, OwnerReceipt, UsageReceipt
from r2.contracts.common import ensure_json_value
from server.production_run.owner_support import OwnerBlocked, Sessions, current_subject, usage_receipt
from server.services.automation_grants import RunAutomationAuthority

ACTIVE = frozenset({"queued", "running", "cancelling"})
FINISHED = frozenset({"succeeded", "failed", "cancelled"})


def actor_scope(intent: DispatchIntent) -> str:
    return f"production-run:{intent.scope.run_id}"


def sub_command(intent: DispatchIntent, sub_key: str) -> str:
    return f"{intent.identity.command_id}:{sub_key}"


def command_digest(intent: DispatchIntent, *, sub_key: str, task_type: str, resource_id: str, payload: dict) -> str:
    facts = {key: value for key, value in payload.items() if key != "projects_root"}
    return digest_value(
        "r2.production-owner-task.v1",
        ensure_json_value(
            {
                "command_id": sub_command(intent, sub_key),
                "task_type": task_type,
                "resource_id": resource_id,
                "payload": facts,
            }
        ),
    )


async def find_task(sessions: Sessions, intent: DispatchIntent, sub_key: str) -> dict[str, Any] | None:
    async with sessions() as session:
        task_id = await session.scalar(
            select(CommandReceiptModel.task_id).where(
                CommandReceiptModel.user_id == intent.scope.user_id,
                CommandReceiptModel.project_name == intent.scope.project_name,
                CommandReceiptModel.actor_scope == actor_scope(intent),
                CommandReceiptModel.command_id == sub_command(intent, sub_key),
            )
        )
        if task_id is None:
            return None
        return await TaskRepository(session).get(str(task_id))


async def submit_task(
    sessions: Sessions,
    authority: RunAutomationAuthority,
    intent: DispatchIntent,
    *,
    sub_key: str,
    task_type: str,
    resource_id: str,
    payload: dict[str, Any],
    subject_digest: str,
    media_type: str = "text",
) -> str:
    """Submit (or replay) one owner task under the step's authorization subject, re-proved current first; another
    actor's active task on the same resource blocks the run."""
    digest = command_digest(intent, sub_key=sub_key, task_type=task_type, resource_id=resource_id, payload=payload)
    subject = await current_subject(sessions, intent, subject_digest=subject_digest)
    async with sessions() as session, session.begin():
        await authority.require_locked(session, subject=subject)
    command_id = sub_command(intent, sub_key)
    task_id = uuid.uuid5(uuid.NAMESPACE_URL, f"r2-production-task/{intent.scope.run_id}/{command_id}").hex
    async with sessions() as session:
        result = await TaskRepository(session).enqueue(
            project_name=intent.scope.project_name,
            task_type=task_type,
            media_type=media_type,
            resource_id=resource_id,
            payload=payload,
            source="skill",
            user_id=intent.scope.user_id,
            command_id=command_id,
            actor_scope=actor_scope(intent),
            command_digest=digest,
            task_id=task_id,
        )
    if result["task_id"] != task_id:
        raise OwnerBlocked("EXTERNAL_INPUT_CHANGED")
    return task_id


async def step_tasks(sessions: Sessions, intent: DispatchIntent) -> list[Task]:
    prefix = intent.identity.command_id + ":"
    async with sessions() as session:
        task_ids = list(
            (
                await session.execute(
                    select(CommandReceiptModel.task_id).where(
                        CommandReceiptModel.user_id == intent.scope.user_id,
                        CommandReceiptModel.project_name == intent.scope.project_name,
                        CommandReceiptModel.actor_scope == actor_scope(intent),
                        CommandReceiptModel.command_id.startswith(prefix, autoescape=True),
                    )
                )
            ).scalars()
        )
        if not task_ids:
            return []
        return list((await session.execute(select(Task).where(Task.task_id.in_(task_ids)))).scalars())


async def step_usage(
    sessions: Sessions, intent: DispatchIntent, receipt: OwnerReceipt, reservation: BudgetReservation
) -> UsageReceipt:
    """Measured usage of the step's tasks; an unfinished task, open call or foreign-currency charge is UNKNOWN."""
    return await tasks_usage(sessions, await step_tasks(sessions, intent), receipt, reservation)


async def attempt_window_tasks(sessions: Sessions, intent: DispatchIntent) -> list[Task]:
    """The project's tasks queued since the step's first write-ahead owner attempt; a run owns its project, so
    these are the tasks the step's owner actions submitted."""
    scope = intent.scope
    async with sessions() as session:
        started = await session.scalar(
            select(func.min(ProductionOwnerAttemptModel.created_at)).where(
                ProductionOwnerAttemptModel.user_id == scope.user_id,
                ProductionOwnerAttemptModel.project_name == scope.project_name,
                ProductionOwnerAttemptModel.run_id == scope.run_id,
                ProductionOwnerAttemptModel.command_id == intent.identity.command_id,
            )
        )
        if started is None:
            return []
        return list(
            (
                await session.execute(
                    select(Task).where(
                        Task.user_id == scope.user_id,
                        Task.project_name == scope.project_name,
                        Task.queued_at >= started,
                    )
                )
            ).scalars()
        )


async def tasks_usage(
    sessions: Sessions, tasks: list[Task], receipt: OwnerReceipt, reservation: BudgetReservation
) -> UsageReceipt:
    known = all(task.status in FINISHED for task in tasks)
    runtime = 0
    for task in tasks:
        if task.started_at is not None and task.finished_at is not None:
            runtime += max(0, math.ceil((task.finished_at - task.started_at).total_seconds()))
    calls: list[ApiCall] = []
    if tasks:
        async with sessions() as session:
            calls = list(
                (
                    await session.execute(select(ApiCall).where(ApiCall.task_id.in_([t.task_id for t in tasks])))
                ).scalars()
            )
    cost = 0
    for call in calls:
        if call.status == "pending":
            known = False
        amount = float(call.cost_amount or 0)
        if amount > 0:
            if call.currency != reservation.currency:
                known = False
            cost += math.ceil(amount * 100)
    return usage_receipt(
        receipt,
        reservation,
        cost_minor_units=cost,
        model_calls=len(calls),
        tasks=len(tasks),
        runtime_seconds=runtime,
        known=known,
    )


__all__ = [
    "ACTIVE",
    "FINISHED",
    "attempt_window_tasks",
    "find_task",
    "step_tasks",
    "step_usage",
    "submit_task",
    "tasks_usage",
]
