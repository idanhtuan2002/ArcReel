"""A task another actor holds on the same resource makes the resource busy, never an input change."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from r2.contracts.automation import RunStage
from server.production_run import owner_tasks
from server.production_run.owner_support import OwnerBlocked
from tests.unit.server.production_run.test_text_outcomes import _intent


class _Session:
    def begin(self):
        @asynccontextmanager
        async def tx():
            yield self

        return tx()


def _sessions():
    @asynccontextmanager
    async def session():
        yield _Session()

    return session()


class _Authority:
    async def require_locked(self, session, *, subject):
        return None


async def test_an_active_task_of_another_actor_on_the_resource_blocks_as_a_busy_resource(monkeypatch):
    async def subject(sessions, intent, *, subject_digest):
        return object()

    class _Tasks:
        def __init__(self, session):
            pass

        async def enqueue(self, **kwargs):
            return {"task_id": "someone-elses-task"}

    monkeypatch.setattr(owner_tasks, "current_subject", subject)
    monkeypatch.setattr(owner_tasks, "TaskRepository", _Tasks)
    with pytest.raises(OwnerBlocked) as blocked:
        await owner_tasks.submit_task(
            _sessions,
            _Authority(),
            _intent(RunStage.ADAPTATION),
            sub_key="adaptation:1",
            task_type="text_episode_adaptation",
            resource_id="episode-1",
            payload={},
            subject_digest="sha256:" + "1" * 64,
        )
    assert blocked.value.reason == "RESOURCE_UNAVAILABLE"
