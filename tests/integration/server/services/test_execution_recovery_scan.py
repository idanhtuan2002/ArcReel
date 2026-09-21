"""ExecutionAttemptServiceImpl.reconcile_expired (M7-C Task C3, H5 recovery
scan): finds an attempt whose worker died mid-flight (lease expired while
still SUBMITTING), reclaims it under a fresh scanner fence, marks it
SUBMIT_OUTCOME_UNKNOWN, and hands it to the existing reconcile() path -- all
against a real, persisted ExecutionAttemptRepository."""

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
    ProviderIdempotencyMode,
    ProviderNotFoundSemantics,
    ProviderObservation,
    ProviderObservationKind,
    ProviderRouteSnapshot,
)
from r2.host_hardening.execution import ExecutionAttemptServiceImpl

type Factory = async_sessionmaker[AsyncSession]

USER = "u1"
PROJECT = "demo"
REAL_NOW = datetime.now(UTC)

# acquire_lease/transition_worker check the lease's expiry against the real
# wall clock (utc_now(), not injectable), so a "the lease has expired" fixture
# must let real time actually pass rather than fake a future `before` cutoff.
_LEASE_TTL = timedelta(milliseconds=50)
_PAST_LEASE_DELAY_SECONDS = 0.2

ROUTE = ProviderRouteSnapshot(
    provider_id="acme-video",
    provider_account_ref="acct-1",
    provider_model_id="acme-v3",
    backend_model_id="acme-video-v3",
    endpoint_id="ep-1",
    submitted_base_url="https://api.acme.example/v3",
    adapter_version="1.0.0",
    capability_profile_ref="acme-video-v3@1.0.0",
)

# NONE idempotency: reconcile() has no safe lookup to perform and pauses for an
# operator immediately, letting this test prove the scanner's own hand-off to
# reconcile() without also needing a fake provider adapter.
_CAPABILITY = ProviderCapabilityProfile(
    ref="acme-video-v3@1.0.0",
    provider_id="acme-video",
    api_version="2026-01-01",
    adapter_version="1.0.0",
    idempotency_mode=ProviderIdempotencyMode.NONE,
    token_scope=None,
    token_scope_value=None,
    token_ttl_seconds=None,
    not_found_semantics=ProviderNotFoundSemantics.NON_AUTHORITATIVE,
    lookup_settling_window_seconds=None,
    supports_poll=True,
    supports_cancel=True,
    supports_lookup=False,
    provider_sequence_is_monotonic=False,
    evidence_digest="sha256:" + "a" * 64,
)


def _capability_resolver(ref: str) -> ProviderCapabilityProfile:
    assert ref == _CAPABILITY.ref
    return _CAPABILITY


def _attempt(execution_id: str = "exec-1", task_id: str = "task-1") -> PlannedExecutionAttempt:
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


def _repository(session: AsyncSession) -> ExecutionAttemptRepository:
    return ExecutionAttemptRepository(session, capability_resolver=_capability_resolver)


def _service(session: AsyncSession) -> ExecutionAttemptServiceImpl:
    return ExecutionAttemptServiceImpl(
        _repository(session),
        capability_resolver=_capability_resolver,
        adapter_resolver=lambda _route: None,
    )


async def _leave_submitting_with_an_expired_lease(
    session: AsyncSession, *, project_name: str = PROJECT, execution_id: str, owner: str
) -> None:
    repo = _repository(session)
    planned = await repo.plan(user_id=USER, project_name=project_name, attempt=_attempt(execution_id=execution_id))
    # Valid long enough for the transition_worker call right below (which also
    # requires a live lease), but short enough that a brief real sleep before
    # the scan runs leaves it genuinely expired -- no fake "before" needed.
    leased = await repo.acquire_lease(
        user_id=USER,
        project_name=project_name,
        execution_id=planned.execution_id,
        expected_version=planned.state_version,
        owner=owner,
        expires_at=datetime.now(UTC) + _LEASE_TTL,
    )
    await repo.transition_worker(
        user_id=USER,
        project_name=project_name,
        execution_id=leased.execution_id,
        expected_version=leased.state_version,
        expected_states=frozenset({ExecutionAttemptState.PLANNED}),
        new_state=ExecutionAttemptState.SUBMITTING,
        fence=AttemptLeaseFence(owner=owner, token=leased.lease_token or 0),
    )


async def test_reconcile_expired_recovers_an_attempt_whose_worker_died_mid_submit(
    session_factory: Factory,
) -> None:
    async with session_factory() as session:
        await _leave_submitting_with_an_expired_lease(session, execution_id="exec-1", owner="dead-worker")
        await session.commit()

    await asyncio.sleep(_PAST_LEASE_DELAY_SECONDS)

    async with session_factory() as session:
        results = await _service(session).reconcile_expired()

        assert len(results) == 1
        assert results[0].execution_id == "exec-1"
        assert results[0].state is ExecutionAttemptState.NEEDS_OPERATOR

        # commit is a no-op in this fixture (matches
        # test_execution_attempt_service.py's convention), so persisted state
        # is verified within the same session/transaction, not a fresh one.
        durable = await _repository(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-1")
    assert durable is not None
    assert durable.state is ExecutionAttemptState.NEEDS_OPERATOR
    assert durable.lease_owner is not None
    assert durable.lease_owner != "dead-worker"


async def test_reconcile_expired_ignores_an_attempt_with_a_live_lease(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repository(session)
        planned = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt(execution_id="exec-live"))
        leased = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=planned.state_version,
            owner="alive-worker",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await repo.transition_worker(
            user_id=USER,
            project_name=PROJECT,
            execution_id=leased.execution_id,
            expected_version=leased.state_version,
            expected_states=frozenset({ExecutionAttemptState.PLANNED}),
            new_state=ExecutionAttemptState.SUBMITTING,
            fence=AttemptLeaseFence(owner="alive-worker", token=leased.lease_token or 0),
        )
        await session.commit()

    async with session_factory() as session:
        results = await _service(session).reconcile_expired()

    assert results == []

    async with session_factory() as session:
        durable = await _repository(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-live")
    assert durable is not None
    assert durable.state is ExecutionAttemptState.SUBMITTING
    assert durable.lease_owner == "alive-worker"


async def test_reconcile_expired_recovers_multiple_attempts_across_projects(session_factory: Factory) -> None:
    async with session_factory() as session:
        await _leave_submitting_with_an_expired_lease(session, execution_id="exec-a", owner="dead-worker-1")
        await session.commit()
    async with session_factory() as session:
        await _leave_submitting_with_an_expired_lease(
            session,
            project_name="other-project",
            execution_id="exec-b",
            owner="dead-worker-2",
        )
        await session.commit()

    await asyncio.sleep(_PAST_LEASE_DELAY_SECONDS)

    async with session_factory() as session:
        results = await _service(session).reconcile_expired()

    assert {r.execution_id for r in results} == {"exec-a", "exec-b"}


async def test_reconcile_expired_never_touches_a_cancel_requested_attempt(session_factory: Factory) -> None:
    """CANCEL_REQUESTED's only production writer is the unfenced request_cancel
    authority, which never attempts a provider call and never renews the
    lease -- its lease is therefore always "expired" by construction, not
    evidence a worker died mid-cancel-attempt. reconcile_expired must not fold
    it to CANCEL_OUTCOME_UNKNOWN without ever calling the provider; realizing
    the intent is the recovery poller's job (a later task), not this scan."""
    async with session_factory() as session:
        repo = _repository(session)
        planned = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt(execution_id="exec-1"))
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
        accepted = await repo.apply_provider_observation(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=submitting.state_version,
            observation=ProviderObservation(
                observation_id="obs-1",
                kind=ProviderObservationKind.ACCEPTED,
                observed_at=REAL_NOW,
                provider_sequence=None,
                provider_job_id="remote-1",
                reason_code=None,
                evidence_digest="sha256:" + "e" * 64,
            ),
        )
        cancel_requested = await repo.request_cancel(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=accepted.state_version,
            actor_scope="user:alice",
            command_id="cancel-1",
            command_digest="sha256:" + "1" * 64,
        )
        await session.commit()

    async with session_factory() as session:
        results = await _service(session).reconcile_expired()

        assert results == []

        durable = await _repository(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-1")
    assert durable is not None
    assert durable.state is ExecutionAttemptState.CANCEL_REQUESTED
    assert durable.state_version == cancel_requested.state_version
