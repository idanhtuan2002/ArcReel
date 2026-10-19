"""Controlled PostgreSQL races exercise absent attempts and version fences."""

import asyncio

import pytest
from sqlalchemy import func, select, text

from lib.db.models.opportunity_acquisition import M9AcquisitionAttemptModel
from lib.db.repositories.opportunity_acquisition import OpportunityAcquisitionUnitOfWork
from r2.contracts.opportunity import AttemptState
from r2.opportunity.errors import OpportunityError, StopCode
from tests.integration.lib.db.repositories.test_opportunity_acquisition import (
    planned_attempt,
    prepare_attempt,
    stage_query,
    unit_of_work,
)
from tests.integration.r2.opportunity.test_profile_concurrency import observe_blocked


@pytest.mark.parametrize("mode", ["equal", "divergent", "collision", "foreign"])
async def test_concurrent_prepare_has_one_dispatch_winner_per_full_command_key(session_factory, mode):
    query = await stage_query(session_factory)
    first_attempt = planned_attempt(query)
    second_attempt = first_attempt
    if mode == "divergent":
        second_attempt = first_attempt.model_copy(update={"request_digest": "sha256:" + "b" * 64})
    elif mode == "foreign":
        second_attempt = first_attempt.model_copy(update={"project_name": "foreign"})
    elif mode == "collision":
        second_attempt = first_attempt.model_copy(
            update={
                "command_id": "019a0000-0000-7000-8000-000000000043",
                "attempt_id": "019a0000-0000-7000-8000-000000000044",
            }
        )
    entered, locked, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    pids = {}

    def collision_key(operation, context):
        return 7, 11

    kwargs = {"guard_key": collision_key} if mode == "collision" else {}

    async def first():
        uow = OpportunityAcquisitionUnitOfWork(session_factory, user_id="u1", project_name="show-a", **kwargs)
        async with uow.transaction() as tx:
            pids["first"] = await tx.session.scalar(text("SELECT pg_backend_pid()"))
            result = await tx.attempts.prepare(first_attempt)
            locked.set()
            await release.wait()
            return result

    async def second():
        await locked.wait()
        uow = OpportunityAcquisitionUnitOfWork(
            session_factory, user_id="u1", project_name=second_attempt.project_name, **kwargs
        )
        async with uow.transaction() as tx:
            pids["second"] = await tx.session.scalar(text("SELECT pg_backend_pid()"))
            entered.set()
            return await tx.attempts.prepare(second_attempt)

    tasks = asyncio.create_task(first()), asyncio.create_task(second())
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        await observe_blocked(session_factory, pids["second"], pids["first"])
    finally:
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
    assert results[0] == (first_attempt, True)
    if mode == "equal":
        assert results[1] == (first_attempt, False)
    elif mode == "collision":
        assert results[1] == (second_attempt, True)
    else:
        assert isinstance(results[1], OpportunityError)
        assert results[1].code == StopCode.M9_COMMAND_REPLAY_CONFLICT
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(M9AcquisitionAttemptModel)) == (
            2 if mode == "collision" else 1
        )


async def test_concurrent_running_cas_grants_dispatch_once(session_factory):
    attempt = await prepare_attempt(session_factory)
    entered, locked, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    pids = {}

    async def first():
        async with unit_of_work(session_factory).transaction() as tx:
            pids["first"] = await tx.session.scalar(text("SELECT pg_backend_pid()"))
            result = await tx.attempts.transition(attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING)
            locked.set()
            await release.wait()
            return result

    async def second():
        await locked.wait()
        async with unit_of_work(session_factory).transaction() as tx:
            pids["second"] = await tx.session.scalar(text("SELECT pg_backend_pid()"))
            entered.set()
            return await tx.attempts.transition(attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING)

    tasks = asyncio.create_task(first()), asyncio.create_task(second())
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        await observe_blocked(session_factory, pids["second"], pids["first"])
    finally:
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
    assert results[0].state == AttemptState.RUNNING
    assert results[0].attempt_version == 2
    assert isinstance(results[1], OpportunityError)
    assert results[1].code == StopCode.M9_STALE_HEAD
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.attempts.get_exact(attempt.attempt_id) == results[0]


async def test_observation_reader_does_not_hold_head_while_waiting_for_attempt_lineage(session_factory):
    from tests.integration.lib.db.repositories.test_opportunity_acquisition import stage_snapshot

    snapshot, observation = await stage_snapshot(session_factory)
    entered, release = asyncio.Event(), asyncio.Event()

    async def reader():
        async with unit_of_work(session_factory).transaction() as tx:
            original = tx.observations._validate

            async def pause_before_attempt(value):
                entered.set()
                await release.wait()
                return await original(value)

            tx.observations._validate = pause_before_attempt
            return await tx.observations.get_current(observation.observation_id)

    task = asyncio.create_task(reader())
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.session.execute(text("SET LOCAL lock_timeout='1000ms'"))
            assert await tx.attempts.get_exact(snapshot.attempt_id) is not None
            assert await tx.observations._head(observation.observation_id) is not None
    finally:
        release.set()
        results = await asyncio.gather(task, return_exceptions=True)
    assert results == [observation]


async def test_cross_snapshot_corrections_lock_both_attempts_in_identity_order(session_factory):
    from r2.opportunity.digests import digest_source_observation, digest_source_snapshot
    from tests.integration.lib.db.repositories.test_opportunity_acquisition import (
        checkpoint_fixture,
        observation_fixture,
        snapshot_fixture,
        stage_snapshot,
    )

    first_snapshot, first_observation = await stage_snapshot(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        query = await tx.queries.get_exact(first_snapshot.query_id, first_snapshot.query_revision)
        second_attempt = planned_attempt(query, command_id="019a0000-0000-7000-8000-000000000061").model_copy(
            update={"attempt_id": "019a0000-0000-7000-8000-000000000062"}
        )
        await tx.attempts.prepare(second_attempt)
        running = await tx.attempts.transition(
            second_attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING
        )
        checkpoint = await checkpoint_fixture(tx)
        await tx.pages.append(second_attempt.attempt_id, checkpoint, expected_attempt_version=2)
        second_snapshot = (await snapshot_fixture(tx, running)).model_copy(
            update={"snapshot_id": "019a0000-0000-7000-8000-000000000063"}
        )
        second_snapshot = second_snapshot.model_copy(
            update={"snapshot_digest": digest_source_snapshot(second_snapshot)}
        )
        await tx.snapshots.append(second_snapshot)
        second_observation = observation_fixture(second_snapshot).model_copy(
            update={"observation_id": "019a0000-0000-7000-8000-000000000064"}
        )
        second_observation = second_observation.model_copy(
            update={"observation_digest": digest_source_observation(second_observation)}
        )
        await tx.observations.append(second_observation, expected_head_version=None)
    corrections = []
    for original, target in ((first_observation, second_snapshot), (second_observation, first_snapshot)):
        corrected = original.model_copy(
            update={
                "revision": 2,
                "parent_revision": 1,
                "snapshot_id": target.snapshot_id,
                "snapshot_digest": target.snapshot_digest,
                "payload_integrity_ref": target.pages[0].payload_integrity_ref,
                "observed_at": target.pages[0].captured_at,
            }
        )
        corrections.append(corrected.model_copy(update={"observation_digest": digest_source_observation(corrected)}))
    entered = (asyncio.Event(), asyncio.Event())
    pids = {}

    async def writer(index):
        async with unit_of_work(session_factory).transaction() as tx:
            pids[index] = await tx.session.scalar(text("SELECT pg_backend_pid()"))
            entered[index].set()
            await tx.observations.append(corrections[index], expected_head_version=1)

    tasks = ()
    try:
        async with unit_of_work(session_factory).transaction() as gate:
            assert await gate.attempts.get_exact(first_snapshot.attempt_id) is not None
            gate_pid = await gate.session.scalar(text("SELECT pg_backend_pid()"))
            tasks = (asyncio.create_task(writer(0)), asyncio.create_task(writer(1)))
            for index in range(2):
                await asyncio.wait_for(entered[index].wait(), timeout=10)
                async with session_factory() as observer:
                    async with asyncio.timeout(10):
                        while True:
                            pending, seen = [pids[index]], set()
                            while pending:
                                pid = pending.pop()
                                if pid in seen:
                                    continue
                                seen.add(pid)
                                pending.extend(
                                    await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid})
                                )
                            if gate_pid in seen:
                                break
                            await asyncio.sleep(0)
            async with session_factory() as observer, observer.begin():
                row = await observer.scalar(
                    select(M9AcquisitionAttemptModel.attempt_id)
                    .where(
                        M9AcquisitionAttemptModel.attempt_id == second_attempt.attempt_id,
                    )
                    .with_for_update(nowait=True)
                )
                assert row == second_attempt.attempt_id
    finally:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    assert results == [None, None]
    async with unit_of_work(session_factory).transaction() as tx:
        for corrected in corrections:
            assert await tx.observations.get_current(corrected.observation_id) == corrected
