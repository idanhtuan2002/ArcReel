"""ExecutionRecoveryScheduler (M7-C Task D4): the live-process wiring around
reconcile_expired/realize_pending_cancels. Uses the real capability registry
(every profile is idempotency_mode=NONE, supports_cancel=false today) and the
default_to_unsupported adapter fallback -- see the module's own docstring for
why that is behaviorally exact for everything currently registered, not a
shortcut."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.host_hardening import ExecutionAttemptRepository
from r2.contracts.host_hardening import (
    AttemptLeaseFence,
    ExecutionAttemptState,
    PlannedExecutionAttempt,
    ProviderCapabilityProfile,
    ProviderObservation,
    ProviderObservationKind,
    ProviderRouteSnapshot,
)
from r2.host_hardening.provider_capabilities import DEFAULT_REGISTRY_PATH, load_capability_profile
from server.services.execution_recovery_scheduler import ExecutionRecoveryScheduler

type Factory = async_sessionmaker[AsyncSession]

USER = "u1"
PROJECT = "demo"
REAL_NOW = datetime.now(UTC)

ROUTE = ProviderRouteSnapshot(
    provider_id="kling",
    provider_account_ref="default",
    provider_model_id="kling-v2-5-turbo",
    backend_model_id="kling-v2-5-turbo",
    endpoint_id="videos.text2video",
    submitted_base_url="https://api-beijing.klingai.com/v1",
    adapter_version="host-video-v1",
    capability_profile_ref="kling-videos-text2video@host-video-v1",
)


def _capability_resolver(ref: str) -> ProviderCapabilityProfile:
    return load_capability_profile(ref, registry_path=DEFAULT_REGISTRY_PATH)


def _repo(session: AsyncSession) -> ExecutionAttemptRepository:
    return ExecutionAttemptRepository(session, capability_resolver=_capability_resolver)


def _attempt(execution_id: str, task_id: str) -> PlannedExecutionAttempt:
    return PlannedExecutionAttempt(
        execution_id=execution_id,
        task_id=task_id,
        attempt_no=1,
        request_digest="sha256:" + "b" * 64,
        route=ROUTE,
        client_token=execution_id,
        trace_id_at_creation=None,
        created_at=REAL_NOW,
    )


async def test_scan_once_recovers_a_dead_submitting_attempt(session_factory: Factory) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        repo = _repo(session)
        planned = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt("exec-1", "task-1"))
        leased = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=planned.state_version,
            owner="dead-worker",
            expires_at=now + timedelta(milliseconds=50),
        )
        await repo.transition_worker(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=leased.state_version,
            expected_states=frozenset({ExecutionAttemptState.PLANNED}),
            new_state=ExecutionAttemptState.SUBMITTING,
            fence=AttemptLeaseFence(owner="dead-worker", token=leased.lease_token or 0),
        )
        await session.commit()

    await asyncio.sleep(0.2)

    scheduler = ExecutionRecoveryScheduler(session_factory=session_factory)
    await scheduler.scan_once()

    async with session_factory() as session:
        durable = await _repo(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-1")
    assert durable is not None
    # NONE idempotency -> reconcile() pauses for an operator, never a blind resubmit.
    assert durable.state is ExecutionAttemptState.NEEDS_OPERATOR


async def test_scan_once_leaves_an_unsupported_cancel_request_pending(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        planned = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt("exec-2", "task-2"))
        leased = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=planned.state_version,
            owner="worker-a",
            expires_at=REAL_NOW + timedelta(minutes=5),
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
        accepted = await repo.apply_provider_observation(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=submitting.state_version,
            observation=ProviderObservation(
                observation_id="obs-2",
                kind=ProviderObservationKind.ACCEPTED,
                observed_at=REAL_NOW,
                provider_sequence=None,
                provider_job_id="remote-2",
                reason_code=None,
                evidence_digest="sha256:" + "c" * 64,
            ),
        )
        await repo.request_cancel(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=accepted.state_version,
            actor_scope="user:alice",
            command_id="cancel-2",
            command_digest="sha256:" + "1" * 64,
        )
        await session.commit()

    scheduler = ExecutionRecoveryScheduler(session_factory=session_factory)
    await scheduler.scan_once()

    async with session_factory() as session:
        durable = await _repo(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-2")
    assert durable is not None
    # Kling declares supports_cancel: false; the fallback adapter raises the
    # same BackendCapabilityUnsupportedError a real one would, so the intent
    # is left recorded rather than silently dropped or falsely resolved.
    assert durable.state is ExecutionAttemptState.CANCEL_REQUESTED


async def test_start_and_stop_run_at_least_one_scan(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        planned = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt("exec-3", "task-3"))
        leased = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=planned.state_version,
            owner="dead-worker",
            expires_at=datetime.now(UTC) + timedelta(milliseconds=50),
        )
        await repo.transition_worker(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=leased.state_version,
            expected_states=frozenset({ExecutionAttemptState.PLANNED}),
            new_state=ExecutionAttemptState.SUBMITTING,
            fence=AttemptLeaseFence(owner="dead-worker", token=leased.lease_token or 0),
        )
        await session.commit()

    await asyncio.sleep(0.2)

    scheduler = ExecutionRecoveryScheduler(session_factory=session_factory, interval_seconds=0.05)
    await scheduler.start()
    try:
        for _ in range(50):
            async with session_factory() as session:
                durable = await _repo(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-3")
            if durable is not None and durable.state is not ExecutionAttemptState.SUBMITTING:
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("scheduler did not process the dead attempt in time")
    finally:
        await scheduler.stop()

    assert durable is not None
    assert durable.state is ExecutionAttemptState.NEEDS_OPERATOR
