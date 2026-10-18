"""Durable story run state on the real task table: locked transitions, attempt sink, usage rows, recovery.

Runs on PostgreSQL when DATABASE_URL points at one (per-test schema), otherwise on a WAL SQLite file; the
concurrency cases need independent connections, which both provide.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.api_call import ApiCall
from lib.db.repositories.task_repo import STORY_RUN_TASK_TYPE, StoryRunStateConflict, TaskRepository
from lib.db.repositories.usage_repo import UsageRepository
from server.story_authoring.contracts import AttemptKind, StoryFailureCode, StoryLimits, StoryScope
from server.story_authoring.generation import StoryStepError
from server.story_authoring.runtime import (
    AttemptState,
    RevisionOutcome,
    RunPhase,
    RunStateStore,
    StoryAttemptSink,
    new_run_state,
    promote,
    recover_run,
    require,
    set_phase,
)

type Factory = async_sessionmaker[AsyncSession]

SCOPE = StoryScope(user_id="default", project_name="story-test", actor_id="default")
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def _limits(**overrides) -> StoryLimits:
    fields = {"input_tokens_max": 1_000_000, "output_tokens_max": 200_000, "wall_clock_max_seconds": 36_000}
    fields.update(overrides)
    return StoryLimits(**fields)


async def _run(factory: Factory, **limits) -> RunStateStore:
    async with factory() as session:
        task = await TaskRepository(session).enqueue(
            project_name=SCOPE.project_name,
            task_type=STORY_RUN_TASK_TYPE,
            media_type="text",
            resource_id="run",
        )
    store = RunStateStore(factory, task_id=task["task_id"])
    await store.initialize(new_run_state(run_id=task["task_id"], limits=_limits(**limits), now=NOW))
    return store


def _sink(store: RunStateStore, factory: Factory) -> StoryAttemptSink:
    return StoryAttemptSink(store=store, session_factory=factory, provider_id="custom-ollama", model_id="ornith-32k:9b")


async def _reserve(sink: StoryAttemptSink, step: str = "s", kind=AttemptKind.GENERATE) -> str:
    return await sink.reserve(
        scope=SCOPE,
        step_id=step,
        kind=kind,
        request_digest="sha256:" + "a" * 64,
        reserved_input_tokens=1000,
        reserved_output_tokens=500,
    )


async def _usage_row(factory: Factory, attempt_id: str) -> ApiCall:
    async with factory() as session:
        return (await session.execute(select(ApiCall).where(ApiCall.request_id == attempt_id))).scalar_one()


async def test_concurrent_reservations_never_exceed_the_call_ceiling(concurrent_session_factory: Factory):
    store = await _run(concurrent_session_factory, generate_calls_max=5)
    sinks = [
        _sink(RunStateStore(concurrent_session_factory, task_id=store.task_id), concurrent_session_factory)
        for _ in range(12)
    ]

    outcomes = await asyncio.gather(*(_reserve(sink, f"s{i}") for i, sink in enumerate(sinks)), return_exceptions=True)

    granted = [o for o in outcomes if isinstance(o, str)]
    refused = [o for o in outcomes if isinstance(o, StoryStepError)]
    assert len(granted) == 5
    assert len(refused) == 7
    assert {e.code for e in refused} <= {StoryFailureCode.BUDGET_EXHAUSTED, StoryFailureCode.RUN_NOT_RUNNING}
    state = await store.load()
    assert state.usage.generate_calls == 5
    assert len(state.attempts) == 5
    assert state.phase is RunPhase.BLOCKED_BUDGET


async def test_an_attempt_is_recorded_in_the_run_and_as_a_local_usage_row(concurrent_session_factory: Factory):
    store = await _run(concurrent_session_factory)
    sink = _sink(store, concurrent_session_factory)

    attempt = await _reserve(sink)
    await sink.dispatched(attempt)
    await sink.completed(attempt, input_tokens=900, output_tokens=321, done_reason="stop", duration_ms=12_000)

    state = await store.load()
    record = state.attempt(attempt)
    assert record.state is AttemptState.COMPLETED
    assert (state.usage.input_tokens, state.usage.output_tokens, state.usage.model_milliseconds) == (900, 321, 12_000)
    row = await _usage_row(concurrent_session_factory, attempt)
    assert row.id == record.ledger_call_id
    assert (row.status, row.currency, row.cost_amount, row.input_tokens, row.output_tokens) == (
        "success",
        "LOCAL",
        0.0,
        900,
        321,
    )
    assert (row.task_id, row.call_type, row.provider) == (store.task_id, "text", "custom-ollama")


async def test_a_local_usage_row_never_enters_money_totals(concurrent_session_factory: Factory):
    store = await _run(concurrent_session_factory)
    sink = _sink(store, concurrent_session_factory)
    attempt = await _reserve(sink)
    await sink.dispatched(attempt)
    await sink.completed(attempt, input_tokens=900, output_tokens=321, done_reason="stop", duration_ms=1)

    async with concurrent_session_factory() as session:
        stats = await UsageRepository(session).get_stats(project_name=SCOPE.project_name)

    assert stats["cost_by_currency"] == {}


async def test_a_run_stopped_before_dispatch_sends_nothing(concurrent_session_factory: Factory):
    store = await _run(concurrent_session_factory)
    sink = _sink(store, concurrent_session_factory)
    attempt = await _reserve(sink)
    await store.apply(lambda s: (set_phase(s, RunPhase.DISCARDED), None))

    with pytest.raises(StoryStepError) as caught:
        await sink.dispatched(attempt)

    assert caught.value.code is StoryFailureCode.RUN_NOT_RUNNING
    state = await store.load()
    assert state.attempt(attempt).state is AttemptState.FAILED
    assert state.usage.generate_calls == 0
    assert (await _usage_row(concurrent_session_factory, attempt)).status == "failed"


async def test_restart_recovery_settles_interrupted_attempts_and_their_usage_rows(concurrent_session_factory: Factory):
    store = await _run(concurrent_session_factory)
    sink = _sink(store, concurrent_session_factory)
    in_flight = await _reserve(sink, "in-flight")
    await sink.dispatched(in_flight)
    # A crash after the usage row was opened but before the dispatch was recorded in the run.
    crashed = await _reserve(sink, "crashed")
    async with concurrent_session_factory() as session:
        await UsageRepository(session).start_call(
            project_name=SCOPE.project_name, call_type="text", model="m", task_id=store.task_id, request_id=crashed
        )

    state, problems = await recover_run(store, session_factory=concurrent_session_factory, blob_exists=lambda _: True)

    assert problems == ()
    assert state.attempt(in_flight).state is AttemptState.UNKNOWN
    assert state.attempt(crashed).state is AttemptState.FAILED
    assert state.attempt(crashed).failure_code is StoryFailureCode.NOT_DISPATCHED
    assert (state.usage.generate_calls, state.usage.input_tokens) == (1, 1000)
    assert (await _usage_row(concurrent_session_factory, in_flight)).status == "failed"
    assert (await _usage_row(concurrent_session_factory, crashed)).status == "failed"
    again, _ = await recover_run(store, session_factory=concurrent_session_factory, blob_exists=lambda _: True)
    assert again.state_version == state.state_version


async def test_two_results_with_the_same_expectations_promote_exactly_once(concurrent_session_factory: Factory):
    store = await _run(concurrent_session_factory)
    state, _ = await store.apply(lambda s: (require(s, node_id="scene_draft[1,1]", fingerprint="f1"), None))
    snapshot = state.node("scene_draft[1,1]")

    def promotion(revision_id: str):
        return lambda s: promote(
            s,
            revision_id=revision_id,
            node_id="scene_draft[1,1]",
            digest="sha256:" + revision_id[-1] * 64,
            fingerprint="f1",
            attempt_id=None,
            expected_head_revision_id=snapshot.head_revision_id,
            generation_epoch=snapshot.generation_epoch,
            now=NOW,
        )

    second_store = RunStateStore(concurrent_session_factory, task_id=store.task_id)
    results = await asyncio.gather(store.apply(promotion("r2")), second_store.apply(promotion("r1")))

    assert sorted(promoted for _, promoted in results) == [False, True]
    final = await store.load()
    head = final.node("scene_draft[1,1]").head_revision_id
    assert head in {"r1", "r2"}
    stale = ({"r1", "r2"} - {head}).pop()
    assert final.revisions[stale].outcome is RevisionOutcome.STALE_RESULT


async def test_a_cancelled_run_task_refuses_every_state_change(concurrent_session_factory: Factory):
    store = await _run(concurrent_session_factory)
    async with concurrent_session_factory() as session:
        await TaskRepository(session).cancel_task(store.task_id)

    with pytest.raises(StoryRunStateConflict):
        await store.apply(lambda s: (set_phase(s, RunPhase.DISCARDED), None))


async def test_a_finished_generation_keeps_its_run_state_writable(concurrent_session_factory: Factory):
    store = await _run(concurrent_session_factory)
    async with concurrent_session_factory() as session:
        repo = TaskRepository(session)
        await repo.claim_next("text")
        await repo.mark_succeeded(store.task_id, {})

    state, _ = await store.apply(lambda s: (set_phase(s, RunPhase.READY_FOR_APPROVAL), None))

    assert state.phase is RunPhase.READY_FOR_APPROVAL
