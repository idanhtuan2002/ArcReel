"""The queue accepts a caller-chosen R2 task ID under command replay and dedupes only the same fingerprint."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.generation_queue import R2_SHOT_GENERATION_TASK_TYPE, ActiveTaskRequestConflict, GenerationQueue

type Factory = async_sessionmaker[AsyncSession]


async def _enqueue(queue: GenerationQueue, *, command_id: str, fingerprint: str, task_id: str | None):
    return await queue.enqueue_task(
        project_name="demo",
        task_type=R2_SHOT_GENERATION_TASK_TYPE,
        media_type="video",
        resource_id="take:shot-1",
        payload={"submit_fingerprint": fingerprint},
        provider_id="dashscope",
        command_id=command_id,
        actor_scope="default",
        command_digest="sha256:" + command_id.encode().hex().ljust(64, "0")[:64],
        task_id=task_id,
    )


@pytest.mark.asyncio
async def test_caller_task_id_replay_and_fingerprint_dedupe(session_factory: Factory, monkeypatch) -> None:
    queue = GenerationQueue(session_factory=session_factory)
    monkeypatch.setattr(queue, "assert_project_migration_ok", _allow)

    first = await _enqueue(queue, command_id="cmd-1", fingerprint="fp-1", task_id="r2shot-a")
    replay = await _enqueue(queue, command_id="cmd-1", fingerprint="fp-1", task_id="r2shot-a")
    same_request = await _enqueue(queue, command_id="cmd-2", fingerprint="fp-1", task_id="r2shot-b")

    assert first["task_id"] == "r2shot-a"
    assert replay["task_id"] == "r2shot-a"
    assert same_request["task_id"] == "r2shot-a"
    assert same_request["deduped"] is True
    with pytest.raises(ActiveTaskRequestConflict):
        await _enqueue(queue, command_id="cmd-3", fingerprint="fp-2", task_id="r2shot-c")


@pytest.mark.asyncio
async def test_a_caller_task_id_needs_command_replay(session_factory: Factory, monkeypatch) -> None:
    queue = GenerationQueue(session_factory=session_factory)
    monkeypatch.setattr(queue, "assert_project_migration_ok", _allow)

    with pytest.raises(ValueError, match="requires command replay"):
        await queue.enqueue_task(
            project_name="demo",
            task_type=R2_SHOT_GENERATION_TASK_TYPE,
            media_type="video",
            resource_id="take:shot-1",
            payload={"submit_fingerprint": "fp-1"},
            provider_id="dashscope",
            task_id="r2shot-a",
        )


async def _allow(_project_name: str) -> None:
    return None
