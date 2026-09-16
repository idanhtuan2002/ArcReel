"""Integration coverage for M7-A actor-scoped command idempotency (plan Task 5):
exact replay, concurrent duplicate races and same-key/different-digest rejection
at ``TaskRepository.enqueue()``, the call path both ``GenerationQueue.enqueue_task``
and ``server/routers/generate.py``'s ``generate_video`` invoke unchanged. The
router itself only reads ``idempotency_key``, computes ``command_digest`` and
passes both through -- the atomicity/concurrency/digest-mismatch guarantees this
file proves all live in the repository, so exercising it directly (rather than
replaying ``generate_video``'s unrelated project/script/admission pre-validation
through a full HTTP stack) is the direct, non-brittle way to prove them.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.api_errors import ConflictError
from lib.content_digest import canonical_json_digest
from lib.db.models.task import Task
from lib.db.repositories.host_hardening import CommandReceiptRepository
from lib.db.repositories.task_repo import TaskRepository
from r2.contracts.host_hardening import command_receipt_result_envelope

type Factory = async_sessionmaker[AsyncSession]

USER = "u1"
ACTOR_SCOPE = "user:u1"
PROJECT = "demo"


def _digest(**fields: object) -> str:
    return "sha256:" + canonical_json_digest(fields, allow_nan=False)


async def _skip_unless_postgres(session_factory: Factory) -> None:
    async with session_factory() as probe:
        if probe.bind.dialect.name == "sqlite":
            pytest.skip("concurrency races need real row-level locking (PostgreSQL only)")


# --- exact replay --------------------------------------------------------------------


async def test_exact_replay_returns_the_original_task_without_creating_another(db_session: AsyncSession) -> None:
    repo = TaskRepository(db_session)
    digest = _digest(task_type="video", resource_id="E1S01")

    first = await repo.enqueue(
        project_name=PROJECT,
        task_type="video",
        media_type="video",
        resource_id="E1S01",
        user_id=USER,
        command_id="cmd-1",
        actor_scope=ACTOR_SCOPE,
        command_digest=digest,
    )
    assert first["replayed"] is False

    # A different resource_id proves this is the command_id branch, not the
    # pre-existing resource-based active-task dedup (which this call would not match).
    second = await repo.enqueue(
        project_name=PROJECT,
        task_type="video",
        media_type="video",
        resource_id="E1S02",
        user_id=USER,
        command_id="cmd-1",
        actor_scope=ACTOR_SCOPE,
        command_digest=digest,
    )
    assert second["task_id"] == first["task_id"]
    assert second["replayed"] is True

    rows = (await db_session.execute(select(Task).where(Task.project_name == PROJECT))).scalars().all()
    assert len(rows) == 1


async def test_restart_replay_with_a_fresh_repository_instance_still_replays(db_session: AsyncSession) -> None:
    digest = _digest(task_type="video", resource_id="E1S01")
    first = await TaskRepository(db_session).enqueue(
        project_name=PROJECT,
        task_type="video",
        media_type="video",
        resource_id="E1S01",
        user_id=USER,
        command_id="cmd-restart",
        actor_scope=ACTOR_SCOPE,
        command_digest=digest,
    )
    # A brand new TaskRepository (as a restarted process/request would construct)
    # over the same durable session/database still finds the committed receipt.
    second = await TaskRepository(db_session).enqueue(
        project_name=PROJECT,
        task_type="video",
        media_type="video",
        resource_id="E1S01",
        user_id=USER,
        command_id="cmd-restart",
        actor_scope=ACTOR_SCOPE,
        command_digest=digest,
    )
    assert second["task_id"] == first["task_id"]
    assert second["replayed"] is True


# --- same-key, different-digest -------------------------------------------------------


async def test_same_command_id_with_a_different_digest_is_rejected(db_session: AsyncSession) -> None:
    repo = TaskRepository(db_session)
    await repo.enqueue(
        project_name=PROJECT,
        task_type="video",
        media_type="video",
        resource_id="E1S01",
        user_id=USER,
        command_id="cmd-2",
        actor_scope=ACTOR_SCOPE,
        command_digest=_digest(task_type="video", resource_id="E1S01"),
    )
    with pytest.raises(ConflictError):
        await repo.enqueue(
            project_name=PROJECT,
            task_type="video",
            media_type="video",
            resource_id="E1S99",
            user_id=USER,
            command_id="cmd-2",
            actor_scope=ACTOR_SCOPE,
            command_digest=_digest(task_type="video", resource_id="E1S99"),
        )


async def test_command_id_scope_is_per_actor(db_session: AsyncSession) -> None:
    digest = _digest(task_type="video", resource_id="E1S01")
    repo = TaskRepository(db_session)
    alice = await repo.enqueue(
        project_name=PROJECT,
        task_type="video",
        media_type="video",
        resource_id="E1S01",
        user_id=USER,
        command_id="cmd-shared",
        actor_scope="user:alice",
        command_digest=digest,
    )
    bob = await repo.enqueue(
        project_name=PROJECT,
        task_type="video",
        media_type="video",
        resource_id="E1S02",
        user_id=USER,
        command_id="cmd-shared",
        actor_scope="user:bob",
        command_digest=digest,
    )
    assert alice["task_id"] != bob["task_id"]
    assert bob["replayed"] is False


# --- opt-in: no command_id keeps pre-M7 behavior unchanged ------------------------------


async def test_omitting_command_id_keeps_the_pre_m7_resource_dedup_behavior(db_session: AsyncSession) -> None:
    repo = TaskRepository(db_session)
    first = await repo.enqueue(
        project_name=PROJECT, task_type="video", media_type="video", resource_id="E1S01", user_id=USER
    )
    second = await repo.enqueue(
        project_name=PROJECT, task_type="video", media_type="video", resource_id="E1S01", user_id=USER
    )
    assert second["task_id"] == first["task_id"]
    assert second["deduped"] is True
    assert second["replayed"] is False


async def test_partial_idempotency_arguments_are_rejected(db_session: AsyncSession) -> None:
    repo = TaskRepository(db_session)
    with pytest.raises(ValueError, match="command_id"):
        await repo.enqueue(
            project_name=PROJECT,
            task_type="video",
            media_type="video",
            resource_id="E1S01",
            user_id=USER,
            command_id="cmd-partial",
        )


# --- canonical version-1 result envelope -----------------------------------------------


async def test_result_digest_uses_the_canonical_v1_envelope(db_session: AsyncSession) -> None:
    digest = _digest(task_type="video", resource_id="E1S01")
    result = await TaskRepository(db_session).enqueue(
        project_name=PROJECT,
        task_type="video",
        media_type="video",
        resource_id="E1S01",
        user_id=USER,
        command_id="cmd-envelope",
        actor_scope=ACTOR_SCOPE,
        command_digest=digest,
    )
    receipt = await CommandReceiptRepository(db_session).get_exact(
        user_id=USER, project_name=PROJECT, actor_scope=ACTOR_SCOPE, command_id="cmd-envelope"
    )
    assert receipt is not None
    envelope = command_receipt_result_envelope(
        task_id=result["task_id"], result={"status": result["status"], "deduped": result["deduped"]}
    )
    assert envelope == {
        "schema_version": 1,
        "task_id": result["task_id"],
        "result": {"status": "queued", "deduped": False},
    }
    assert receipt.result_digest == "sha256:" + canonical_json_digest(envelope, allow_nan=False)


# --- concurrent duplicate: real PostgreSQL race ------------------------------------------


async def test_concurrent_duplicate_command_id_creates_exactly_one_task(session_factory: Factory) -> None:
    await _skip_unless_postgres(session_factory)
    barrier = asyncio.Barrier(2)
    digest = _digest(task_type="video", resource_id="E1S01")

    async def _attempt() -> dict[str, object]:
        async with session_factory() as session:
            repo = TaskRepository(session)
            await barrier.wait()
            return await repo.enqueue(
                project_name=PROJECT,
                task_type="video",
                media_type="video",
                resource_id="E1S01",
                user_id=USER,
                command_id="cmd-race",
                actor_scope=ACTOR_SCOPE,
                command_digest=digest,
            )

    results = await asyncio.wait_for(asyncio.gather(_attempt(), _attempt()), timeout=10.0)
    task_ids = {r["task_id"] for r in results}
    assert len(task_ids) == 1
    assert sorted(r["replayed"] for r in results) == [False, True]

    async with session_factory() as session:
        rows = (await session.execute(select(Task).where(Task.project_name == PROJECT))).scalars().all()
        assert len(rows) == 1
