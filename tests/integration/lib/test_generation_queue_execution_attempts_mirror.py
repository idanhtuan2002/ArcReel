"""GenerationQueue.mark_task_succeeded/failed/cancelled mirror their outcome
into execution_attempts (M7-C bookkeeping) -- the legacy orphan handler
(ADR 0007) makes every real restart-recovery decision and never touches
execution_attempts itself, so without this mirror that table goes stale the
moment a real crash happens. This never changes the task row's own outcome
or any existing GenerationQueue return value -- see lib/generation_queue.py's
_mirror_terminal_outcome_to_execution_attempts docstring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.base import DEFAULT_USER_ID
from lib.db.repositories.host_hardening import ExecutionAttemptRepository
from lib.generation_queue import GenerationQueue
from r2.contracts.host_hardening import (
    AttemptLeaseFence,
    ExecutionAttemptState,
    PlannedExecutionAttempt,
    ProviderObservation,
    ProviderObservationKind,
    ProviderRouteSnapshot,
)
from r2.host_hardening.provider_capabilities import DEFAULT_REGISTRY_PATH, load_capability_profile

type Factory = async_sessionmaker[AsyncSession]

USER = DEFAULT_USER_ID
PROJECT = "demo"
REAL_NOW = datetime.now(UTC)

# The mirror (lib.generation_queue._mirror_terminal_outcome_to_execution_attempts)
# resolves capability through the real registry, not a caller-supplied fake, so
# this route must carry a ref that is actually registered there.
_CAPABILITY_REF = "kling-videos-text2video@host-video-v1"

ROUTE = ProviderRouteSnapshot(
    provider_id="kling",
    provider_account_ref="default",
    provider_model_id="kling-v2-5-turbo",
    backend_model_id="kling-v2-5-turbo",
    endpoint_id="videos.text2video",
    submitted_base_url="https://api-beijing.klingai.com/v1",
    adapter_version="host-video-v1",
    capability_profile_ref=_CAPABILITY_REF,
)


def _capability_resolver(ref: str):
    return load_capability_profile(ref, registry_path=DEFAULT_REGISTRY_PATH)


def _repo(session: AsyncSession) -> ExecutionAttemptRepository:
    return ExecutionAttemptRepository(session, capability_resolver=_capability_resolver)


async def _bring_to_accepted(session: AsyncSession, *, task_id: str, execution_id: str) -> None:
    repo = _repo(session)
    planned = await repo.plan(
        user_id=USER,
        project_name=PROJECT,
        attempt=PlannedExecutionAttempt(
            execution_id=execution_id,
            task_id=task_id,
            attempt_no=1,
            request_digest="sha256:" + "b" * 64,
            route=ROUTE,
            client_token=execution_id,
            trace_id_at_creation=None,
            created_at=REAL_NOW,
        ),
    )
    leased = await repo.acquire_lease(
        user_id=USER,
        project_name=PROJECT,
        execution_id=planned.execution_id,
        expected_version=planned.state_version,
        owner="worker-a",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    fence = AttemptLeaseFence(owner="worker-a", token=leased.lease_token or 0)
    submitting = await repo.transition_worker(
        user_id=USER,
        project_name=PROJECT,
        execution_id=planned.execution_id,
        expected_version=leased.state_version,
        expected_states=frozenset({ExecutionAttemptState.PLANNED}),
        new_state=ExecutionAttemptState.SUBMITTING,
        fence=fence,
    )
    await repo.apply_provider_observation(
        user_id=USER,
        project_name=PROJECT,
        execution_id=planned.execution_id,
        expected_version=submitting.state_version,
        observation=ProviderObservation(
            observation_id=f"obs-{execution_id}",
            kind=ProviderObservationKind.ACCEPTED,
            observed_at=REAL_NOW,
            provider_sequence=None,
            provider_job_id=f"remote-{execution_id}",
            reason_code=None,
            evidence_digest="sha256:" + "c" * 64,
        ),
    )


async def _enqueue(queue: GenerationQueue, *, task_id_hint: str) -> str:
    task = await queue.enqueue_task(
        project_name=PROJECT,
        task_type="video",
        media_type="video",
        resource_id=task_id_hint,
        user_id=USER,
    )
    task_id = task["task_id"]
    running = await queue.claim_next_task(media_type="video")
    assert running is not None
    assert running["task_id"] == task_id
    return task_id


async def test_mark_task_succeeded_mirrors_to_execution_attempts(session_factory: Factory) -> None:
    queue = GenerationQueue(session_factory=session_factory)
    task_id = await _enqueue(queue, task_id_hint="res-1")
    async with session_factory() as session:
        await _bring_to_accepted(session, task_id=task_id, execution_id="exec-1")
        await session.commit()

    await queue.mark_task_succeeded(task_id, {"ok": True})

    async with session_factory() as session:
        snapshot = await _repo(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-1")
    assert snapshot is not None
    assert snapshot.state is ExecutionAttemptState.SUCCEEDED


async def test_mark_task_failed_mirrors_to_execution_attempts(session_factory: Factory) -> None:
    queue = GenerationQueue(session_factory=session_factory)
    task_id = await _enqueue(queue, task_id_hint="res-2")
    async with session_factory() as session:
        await _bring_to_accepted(session, task_id=task_id, execution_id="exec-2")
        await session.commit()

    await queue.mark_task_failed(task_id, "boom")

    async with session_factory() as session:
        snapshot = await _repo(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-2")
    assert snapshot is not None
    assert snapshot.state is ExecutionAttemptState.FAILED


async def test_mark_task_cancelled_mirrors_to_execution_attempts(session_factory: Factory) -> None:
    queue = GenerationQueue(session_factory=session_factory)
    task_id = await _enqueue(queue, task_id_hint="res-3")
    async with session_factory() as session:
        await _bring_to_accepted(session, task_id=task_id, execution_id="exec-3")
        await session.commit()
    await queue.cancel_task(task_id)

    await queue.mark_task_cancelled(task_id, cancelled_by="user")

    async with session_factory() as session:
        snapshot = await _repo(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-3")
    assert snapshot is not None
    assert snapshot.state is ExecutionAttemptState.CANCELLED


async def test_mirror_is_a_no_op_when_no_execution_attempt_exists(session_factory: Factory) -> None:
    """Every non-video task, and any video task never wired to an attempt
    submitter, has no execution_attempts row at all -- the mirror must be a
    silent no-op, never an error, for the overwhelming majority of tasks."""
    queue = GenerationQueue(session_factory=session_factory)
    task_id = await _enqueue(queue, task_id_hint="res-4")

    rows = await queue.mark_task_succeeded(task_id, {"ok": True})

    assert rows == 1


async def test_mirror_does_not_reopen_an_already_terminal_attempt(session_factory: Factory) -> None:
    queue = GenerationQueue(session_factory=session_factory)
    task_id = await _enqueue(queue, task_id_hint="res-5")
    async with session_factory() as session:
        await _bring_to_accepted(session, task_id=task_id, execution_id="exec-5")
        await session.commit()

    await queue.mark_task_succeeded(task_id, {"ok": True})
    async with session_factory() as session:
        before = await _repo(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-5")
    assert before is not None
    assert before.state is ExecutionAttemptState.SUCCEEDED
    version_after_first_mirror = before.state_version

    # A later, spurious second call (e.g. a retried worker callback) must not
    # attempt to fold a second observation onto an already-terminal attempt.
    await queue._mirror_terminal_outcome_to_execution_attempts(task_id, ProviderObservationKind.FAILED)

    async with session_factory() as session:
        after = await _repo(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-5")
    assert after is not None
    assert after.state is ExecutionAttemptState.SUCCEEDED
    assert after.state_version == version_after_first_mirror
