"""A step's usage is known when its tasks finished; a call a dead worker left pending does not keep it unknown."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.api_call import ApiCall
from server.production_run import owner_tasks

NOW = datetime(2026, 11, 17, tzinfo=UTC)


async def _call(factory: async_sessionmaker[AsyncSession], task_id: str, *, status: str, cost: float = 0.0) -> None:
    async with factory() as session:
        session.add(
            ApiCall(
                project_name="trial",
                task_id=task_id,
                call_type="video",
                model="still-clip-local",
                status=status,
                started_at=NOW,
                cost_amount=cost,
                currency="USD",
            )
        )
        await session.commit()


def _task(task_id: str, status: str) -> Any:
    return SimpleNamespace(task_id=task_id, status=status, started_at=NOW, finished_at=NOW)


@pytest.fixture
def measured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def usage_receipt(receipt: Any, reservation: Any, **kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return kwargs

    monkeypatch.setattr(owner_tasks, "usage_receipt", usage_receipt)
    return seen


async def test_a_pending_call_of_a_finished_task_is_counted_as_recorded(
    session_factory: async_sessionmaker[AsyncSession], measured: dict[str, Any]
) -> None:
    # trial 7, 2026-11-17: the app was killed during a video batch; its calls stayed pending and every resume
    # blocked on OUTCOME_UNKNOWN although every task had finished
    await _call(session_factory, "t1", status="success")
    await _call(session_factory, "t2", status="pending")
    tasks = [_task("t1", "succeeded"), _task("t2", "failed")]

    await owner_tasks.tasks_usage(session_factory, tasks, SimpleNamespace(), SimpleNamespace(currency="USD"))

    assert measured["known"] is True
    assert measured["model_calls"] == 2


async def test_a_pending_call_of_a_running_task_keeps_the_usage_unknown(
    session_factory: async_sessionmaker[AsyncSession], measured: dict[str, Any]
) -> None:
    await _call(session_factory, "t3", status="pending")

    await owner_tasks.tasks_usage(
        session_factory, [_task("t3", "running")], SimpleNamespace(), SimpleNamespace(currency="USD")
    )

    assert measured["known"] is False
