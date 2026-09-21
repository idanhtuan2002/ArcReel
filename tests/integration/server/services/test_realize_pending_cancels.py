"""ExecutionAttemptServiceImpl.realize_pending_cancels (M7-C Task D3, cancel-
intent realization): the one place that actually calls a provider's cancel
endpoint for an attempt request_cancel already marked CANCEL_REQUESTED --
against a real, persisted ExecutionAttemptRepository. No real backend has
supports_cancel: true today (checked r2/provider_capabilities/registry.json),
so every fake adapter here stands in for a hypothetical future one; the
mechanism is what is under test, not any specific provider's behavior."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.host_hardening import ExecutionAttemptFencingError, ExecutionAttemptRepository
from lib.video_backends.execution_adapter import BackendCapabilityUnsupportedError
from r2.contracts.host_hardening import (
    AttemptLeaseFence,
    AttemptSnapshot,
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

# NONE idempotency (matches Kling's real profile): a failed cancel attempt's
# hand-off to reconcile() pauses for an operator immediately, letting these
# tests prove realize_pending_cancels' own branching without also needing a
# fake adapter.reconcile().
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


def _service(session: AsyncSession, *, adapter=None) -> ExecutionAttemptServiceImpl:
    return ExecutionAttemptServiceImpl(
        _repository(session),
        capability_resolver=_capability_resolver,
        adapter_resolver=lambda _route: adapter,
    )


async def _skip_unless_postgres(session_factory: Factory) -> None:
    async with session_factory() as probe:
        if probe.bind.dialect.name == "sqlite":
            pytest.skip("concurrency races need real row-level locking (PostgreSQL only)")


async def _bring_to_cancel_requested(
    session: AsyncSession, *, execution_id: str, owner: str, task_id: str = "task-1"
) -> AttemptSnapshot:
    repo = _repository(session)
    planned = await repo.plan(
        user_id=USER, project_name=PROJECT, attempt=_attempt(execution_id=execution_id, task_id=task_id)
    )
    leased = await repo.acquire_lease(
        user_id=USER,
        project_name=PROJECT,
        execution_id=planned.execution_id,
        expected_version=planned.state_version,
        owner=owner,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    fence = AttemptLeaseFence(owner=owner, token=leased.lease_token or 0)
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
            observation_id=f"obs-{execution_id}",
            kind=ProviderObservationKind.ACCEPTED,
            observed_at=REAL_NOW,
            provider_sequence=None,
            provider_job_id=f"remote-{execution_id}",
            reason_code=None,
            evidence_digest="sha256:" + "c" * 64,
        ),
    )
    return await repo.request_cancel(
        user_id=USER,
        project_name=PROJECT,
        execution_id=planned.execution_id,
        expected_version=accepted.state_version,
        actor_scope="user:alice",
        command_id=f"cancel-{execution_id}",
        command_digest="sha256:" + "1" * 64,
    )


class _UnsupportedCancelAdapter:
    async def cancel(self, attempt: AttemptSnapshot) -> ProviderObservation:
        raise BackendCapabilityUnsupportedError(f"{attempt.route.capability_profile_ref} does not support cancel")


class _AmbiguousCancelAdapter:
    async def cancel(self, attempt: AttemptSnapshot) -> ProviderObservation:
        raise RuntimeError("transport error while calling cancel")


class _SuccessfulCancelAdapter:
    async def cancel(self, attempt: AttemptSnapshot) -> ProviderObservation:
        return ProviderObservation(
            observation_id=f"obs-cancel-{attempt.execution_id}",
            kind=ProviderObservationKind.CANCELLED,
            observed_at=REAL_NOW,
            provider_sequence=None,
            provider_job_id=attempt.provider_job_id,
            reason_code=None,
            evidence_digest="sha256:" + "f" * 64,
        )


async def test_realize_pending_cancels_leaves_an_unsupported_backend_cancel_requested(
    session_factory: Factory,
) -> None:
    async with session_factory() as session:
        await _bring_to_cancel_requested(session, execution_id="exec-1", owner="worker-a")
        await session.commit()

    async with session_factory() as session:
        results = await _service(session, adapter=_UnsupportedCancelAdapter()).realize_pending_cancels()

        assert results == []
        durable = await _repository(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-1")
    assert durable is not None
    assert durable.state is ExecutionAttemptState.CANCEL_REQUESTED
    assert durable.lease_owner is None  # released, not left held forever


async def test_realize_pending_cancels_moves_an_ambiguous_failure_to_needs_operator(
    session_factory: Factory,
) -> None:
    async with session_factory() as session:
        await _bring_to_cancel_requested(session, execution_id="exec-1", owner="worker-a")
        await session.commit()

    async with session_factory() as session:
        results = await _service(session, adapter=_AmbiguousCancelAdapter()).realize_pending_cancels()

        assert len(results) == 1
        assert results[0].execution_id == "exec-1"
        assert results[0].state is ExecutionAttemptState.NEEDS_OPERATOR
        assert results[0].operator_reason == "no_safe_reconciliation"

        durable = await _repository(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-1")
    assert durable is not None
    assert durable.state is ExecutionAttemptState.NEEDS_OPERATOR


async def test_realize_pending_cancels_applies_a_successful_cancellation(session_factory: Factory) -> None:
    async with session_factory() as session:
        await _bring_to_cancel_requested(session, execution_id="exec-1", owner="worker-a")
        await session.commit()

    async with session_factory() as session:
        results = await _service(session, adapter=_SuccessfulCancelAdapter()).realize_pending_cancels()

        assert len(results) == 1
        assert results[0].execution_id == "exec-1"
        assert results[0].state is ExecutionAttemptState.CANCELLED

        durable = await _repository(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-1")
    assert durable is not None
    assert durable.state is ExecutionAttemptState.CANCELLED


async def test_realize_pending_cancels_ignores_an_accepted_attempt_with_no_cancel_request(
    session_factory: Factory,
) -> None:
    async with session_factory() as session:
        repo = _repository(session)
        planned = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt(execution_id="exec-live"))
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
                observation_id="obs-live",
                kind=ProviderObservationKind.ACCEPTED,
                observed_at=REAL_NOW,
                provider_sequence=None,
                provider_job_id="remote-live",
                reason_code=None,
                evidence_digest="sha256:" + "c" * 64,
            ),
        )
        await session.commit()

    async with session_factory() as session:
        results = await _service(session, adapter=_SuccessfulCancelAdapter()).realize_pending_cancels()

    assert results == []


async def test_realize_pending_cancels_concurrent_calls_have_exactly_one_winner(session_factory: Factory) -> None:
    await _skip_unless_postgres(session_factory)
    async with session_factory() as setup_session:
        await _bring_to_cancel_requested(setup_session, execution_id="exec-1", owner="worker-a")
        await setup_session.commit()

    barrier = asyncio.Barrier(2)

    async def _try_realize() -> list:
        async with session_factory() as session:
            await barrier.wait()
            try:
                results = await _service(session, adapter=_SuccessfulCancelAdapter()).realize_pending_cancels()
                await session.commit()
                return results
            except ExecutionAttemptFencingError:
                await session.rollback()
                return []

    all_results = await asyncio.wait_for(asyncio.gather(_try_realize(), _try_realize()), timeout=10.0)
    winners = [r for batch in all_results for r in batch]
    assert len(winners) == 1
    assert winners[0].execution_id == "exec-1"
