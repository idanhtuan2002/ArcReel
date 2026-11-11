"""ADR-0130: tasks set aside for a deploy come back; media lost to a restart on a free route is queued once more."""

from __future__ import annotations

import json

import sqlalchemy as sa

from lib.db.models.task import Task
from lib.db.repositories.task_repo import ACTIVE_TASK_STATUSES, PARKED_STATUS, RESTART_REQUEUE_KEY, TaskRepository


async def _task(session, *, status: str, actor: str | None = None, media: str = "image") -> str:
    repo = TaskRepository(session)
    created = await repo.enqueue(
        project_name="project",
        task_type="image",
        media_type=media,
        resource_id=f"r-{status}-{actor}",
        payload={"prompt": "p"},
        user_id="default",
        actor_scope=actor,
        command_id=None if actor is None else f"cmd-{status}",
        command_digest=None if actor is None else "sha256:" + "d" * 64,
    )
    await session.commit()
    await session.execute(sa.update(Task).where(Task.task_id == created["task_id"]).values(status=status))
    await session.commit()
    return created["task_id"]


async def test_parked_tasks_are_not_active_and_come_back_with_their_status(session_factory):
    async with session_factory() as session:
        queued = await _task(session, status="queued")
        running = await _task(session, status="running")
        done = await _task(session, status="succeeded")
        assert await TaskRepository(session).park_active() == 2
        statuses = dict((await session.execute(sa.select(Task.task_id, Task.status))).all())
        assert statuses[queued] == statuses[running] == PARKED_STATUS
        assert PARKED_STATUS not in ACTIVE_TASK_STATUSES
        assert statuses[done] == "succeeded"
        assert await TaskRepository(session).unpark() == 2
        rows = {t.task_id: t for t in (await session.execute(sa.select(Task))).scalars()}
        assert (rows[queued].status, rows[running].status) == ("queued", "running")
        assert "_parked_from" not in json.loads(rows[running].payload_json or "{}")


async def test_a_lost_media_task_of_a_free_automatic_run_is_queued_once_and_paid_or_manual_ones_are_not(
    session_factory, monkeypatch
):
    from lib.db.repositories import production_runs

    class Route:
        def __init__(self, role, local, paid):
            self.role, self.local, self.paid = role, local, paid

    class Run:
        def __init__(self, local, paid):
            self.policy = type("P", (), {"routes": (Route("image", local, paid),)})()

    runs = {"free": Run(True, False), "paid": Run(False, True)}

    async def get(self, *, user_id, project_name, run_id):
        return runs.get(run_id)

    monkeypatch.setattr(production_runs.ProductionRunRepository, "get", get)
    async with session_factory() as session:
        free = await _task(session, status="running", actor="production-run:free")
        paid = await _task(session, status="running", actor="production-run:paid")
        manual = await _task(session, status="running")
        repo = TaskRepository(session)
        assert await repo.requeue_free_restart_lost(free, media_role="image") is True
        assert await repo.requeue_free_restart_lost(paid, media_role="image") is False
        assert await repo.requeue_free_restart_lost(manual, media_role="image") is False
        row = (await session.execute(sa.select(Task).where(Task.task_id == free))).scalar_one()
        assert row.status == "queued"
        assert json.loads(row.payload_json)[RESTART_REQUEUE_KEY] is True
        # A second restart keeps the no-resend rule.
        await session.execute(sa.update(Task).where(Task.task_id == free).values(status="running"))
        await session.commit()
        assert await repo.requeue_free_restart_lost(free, media_role="image") is False
