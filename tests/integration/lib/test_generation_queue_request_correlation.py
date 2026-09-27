"""GenerationQueue.enqueue_task persists the bound entry request_id on the task row."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.base import DEFAULT_USER_ID
from lib.generation_queue import GenerationQueue
from lib.request_context import bound_request_id

type Factory = async_sessionmaker[AsyncSession]


async def test_enqueue_inside_a_bound_request_persists_its_request_id(session_factory: Factory) -> None:
    queue = GenerationQueue(session_factory=session_factory)

    with bound_request_id("req-correlation-0001"):
        enqueued = await queue.enqueue_task(
            project_name="demo",
            task_type="image",
            media_type="image",
            resource_id="E1S01",
            user_id=DEFAULT_USER_ID,
        )

    task = await queue.get_task(enqueued["task_id"])
    assert task is not None
    assert task["request_id"] == "req-correlation-0001"


async def test_enqueue_without_an_entry_request_leaves_request_id_null(session_factory: Factory) -> None:
    queue = GenerationQueue(session_factory=session_factory)

    enqueued = await queue.enqueue_task(
        project_name="demo",
        task_type="image",
        media_type="image",
        resource_id="E1S02",
        user_id=DEFAULT_USER_ID,
    )

    task = await queue.get_task(enqueued["task_id"])
    assert task is not None
    assert task["request_id"] is None
