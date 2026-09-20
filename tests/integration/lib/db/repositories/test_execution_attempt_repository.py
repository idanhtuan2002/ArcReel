"""Integration coverage for the fenced execution-attempt repository:
lease fencing, three separate write authorities, and real
PostgreSQL concurrent CAS."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.host_hardening import (
    CommandReceiptConflictError,
    CommandReceiptRepository,
    ExecutionAttemptFencingError,
    ExecutionAttemptRepository,
    ExecutionAttemptTransitionError,
)
from r2.contracts.host_hardening import (
    AttemptLeaseFence,
    AttemptSnapshot,
    CommandReceipt,
    ExecutionAttemptState,
    OperatorResolutionAction,
    OperatorResolutionReceipt,
    PlannedExecutionAttempt,
    ProviderCapabilityProfile,
    ProviderIdempotencyMode,
    ProviderNotFoundSemantics,
    ProviderObservation,
    ProviderObservationKind,
    ProviderRouteSnapshot,
)
from r2.host_hardening.transitions import AttemptIdentityMismatch

type Factory = async_sessionmaker[AsyncSession]

USER = "u1"
OTHER_USER = "conformance"
PROJECT = "project-a"
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
# The repository stamps lease_expires_at comparisons against the real wall clock
# (lib.db.base.utc_now()), not the fixed NOW above; every expires_at value must be
# real-time-relative or the fixed sentinel would already be "expired" by construction.
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

_CAPABILITY = ProviderCapabilityProfile(
    ref="acme-video-v3@1.0.0",
    provider_id="acme-video",
    api_version="2026-01-01",
    adapter_version="1.0.0",
    idempotency_mode=ProviderIdempotencyMode.NATIVE_TOKEN,
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


def _fake_capability_resolver(ref: str) -> ProviderCapabilityProfile:
    assert ref == _CAPABILITY.ref
    return _CAPABILITY


def _attempt(*, task_id: str = "task-1", attempt_no: int = 1, execution_id: str = "exec-1") -> PlannedExecutionAttempt:
    return PlannedExecutionAttempt(
        execution_id=execution_id,
        task_id=task_id,
        attempt_no=attempt_no,
        request_digest="sha256:" + "b" * 64,
        route=ROUTE,
        client_token=execution_id,
        trace_id_at_creation=None,
        created_at=NOW,
    )


def _repo(session: AsyncSession) -> ExecutionAttemptRepository:
    return ExecutionAttemptRepository(session, capability_resolver=_fake_capability_resolver)


async def _skip_unless_postgres(session_factory: Factory) -> None:
    async with session_factory() as probe:
        if probe.bind.dialect.name == "sqlite":
            pytest.skip("concurrency races need real row-level locking (PostgreSQL only)")


# --- plan() / get_exact() -------------------------------------------------------------


async def test_plan_is_idempotent_for_an_exact_replay(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        first = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        await session.commit()
        second = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        await session.commit()
        assert first == second


async def test_plan_rejects_a_same_key_different_digest_replay(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        await session.commit()
        mismatched = _attempt().model_copy(update={"request_digest": "sha256:" + "0" * 64})
        with pytest.raises(AttemptIdentityMismatch):
            await repo.plan(user_id=USER, project_name=PROJECT, attempt=mismatched)


async def test_a_different_attempt_no_for_the_same_task_is_a_new_attempt(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        first = await repo.plan(
            user_id=USER, project_name=PROJECT, attempt=_attempt(execution_id="exec-1", attempt_no=1)
        )
        second = await repo.plan(
            user_id=USER, project_name=PROJECT, attempt=_attempt(execution_id="exec-2", attempt_no=2)
        )
        await session.commit()
        assert first.execution_id != second.execution_id
        assert first.attempt_no == 1
        assert second.attempt_no == 2


async def test_get_exact_is_none_for_a_foreign_project_scope(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        await session.commit()
        assert await repo.get_exact(user_id=USER, project_name="other-project", execution_id="exec-1") is None
        assert await repo.get_exact(user_id=OTHER_USER, project_name=PROJECT, execution_id="exec-1") is None
        assert await repo.get_exact(user_id=USER, project_name=PROJECT, execution_id="unknown") is None


async def test_get_for_task_attempt_is_scoped_and_exact(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        expected = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        await session.commit()

        assert (
            await repo.get_for_task_attempt(
                user_id=USER,
                project_name=PROJECT,
                task_id=expected.task_id,
                attempt_no=expected.attempt_no,
            )
            == expected
        )
        assert (
            await repo.get_for_task_attempt(
                user_id=OTHER_USER,
                project_name=PROJECT,
                task_id=expected.task_id,
                attempt_no=expected.attempt_no,
            )
            is None
        )


# --- lease fencing ----------------------------------------------------------------------


async def test_transition_worker_rejects_a_stale_owner(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        snapshot = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        leased = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=snapshot.state_version,
            owner="worker-a",
            expires_at=REAL_NOW + timedelta(minutes=5),
        )
        fence = AttemptLeaseFence(owner="worker-b", token=leased.lease_token or 0)
        with pytest.raises(ExecutionAttemptFencingError):
            await repo.transition_worker(
                user_id=USER,
                project_name=PROJECT,
                execution_id=snapshot.execution_id,
                expected_version=leased.state_version,
                expected_states=frozenset({ExecutionAttemptState.PLANNED}),
                new_state=ExecutionAttemptState.SUBMITTING,
                fence=fence,
            )


async def test_reacquiring_the_same_owner_invalidates_the_old_token(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        snapshot = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        first_lease = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=snapshot.state_version,
            owner="worker-a",
            expires_at=REAL_NOW + timedelta(minutes=5),
        )
        old_token = first_lease.lease_token
        assert old_token is not None
        second_lease = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=first_lease.state_version,
            owner="worker-a",
            expires_at=REAL_NOW + timedelta(minutes=10),
        )
        assert second_lease.lease_token == old_token + 1

        stale_fence = AttemptLeaseFence(owner="worker-a", token=old_token)
        with pytest.raises(ExecutionAttemptFencingError):
            await repo.transition_worker(
                user_id=USER,
                project_name=PROJECT,
                execution_id=snapshot.execution_id,
                expected_version=second_lease.state_version,
                expected_states=frozenset({ExecutionAttemptState.PLANNED}),
                new_state=ExecutionAttemptState.SUBMITTING,
                fence=stale_fence,
            )


async def test_transition_worker_rejects_an_expired_lease(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        snapshot = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        leased = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=snapshot.state_version,
            owner="worker-a",
            expires_at=REAL_NOW - timedelta(seconds=1),  # already expired
        )
        fence = AttemptLeaseFence(owner="worker-a", token=leased.lease_token or 0)
        with pytest.raises(ExecutionAttemptFencingError):
            await repo.transition_worker(
                user_id=USER,
                project_name=PROJECT,
                execution_id=snapshot.execution_id,
                expected_version=leased.state_version,
                expected_states=frozenset({ExecutionAttemptState.PLANNED}),
                new_state=ExecutionAttemptState.SUBMITTING,
                fence=fence,
            )


async def test_acquire_lease_can_reclaim_an_expired_lease_for_a_new_owner(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        snapshot = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        expired = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=snapshot.state_version,
            owner="worker-a",
            expires_at=REAL_NOW - timedelta(seconds=1),
        )
        reclaimed = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=expired.state_version,
            owner="worker-b",
            expires_at=REAL_NOW + timedelta(minutes=5),
        )
        assert reclaimed.lease_owner == "worker-b"


async def test_acquire_lease_rejects_a_live_lease_without_force(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        snapshot = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        live = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=snapshot.state_version,
            owner="worker-a",
            expires_at=REAL_NOW + timedelta(minutes=5),
        )
        with pytest.raises(ExecutionAttemptFencingError):
            await repo.acquire_lease(
                user_id=USER,
                project_name=PROJECT,
                execution_id=snapshot.execution_id,
                expected_version=live.state_version,
                owner="worker-b",
                expires_at=REAL_NOW + timedelta(minutes=5),
            )


async def test_acquire_lease_with_force_seizes_a_live_lease(session_factory: Factory) -> None:
    """CANCEL_REQUESTED realization's use case: nothing renews a lease during
    the happy path, so a still-"live" TTL is not evidence a real actor is
    using it -- force skips that check while state_version CAS still applies."""
    async with session_factory() as session:
        repo = _repo(session)
        snapshot = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        live = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=snapshot.state_version,
            owner="worker-a",
            expires_at=REAL_NOW + timedelta(minutes=5),
        )
        seized = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=live.state_version,
            owner="worker-b",
            expires_at=REAL_NOW + timedelta(minutes=5),
            force=True,
        )
        assert seized.lease_owner == "worker-b"

        # The state_version CAS still applies under force: a stale version is
        # still rejected, not silently overwritten.
        with pytest.raises(ExecutionAttemptFencingError):
            await repo.acquire_lease(
                user_id=USER,
                project_name=PROJECT,
                execution_id=snapshot.execution_id,
                expected_version=live.state_version,
                owner="worker-c",
                expires_at=REAL_NOW + timedelta(minutes=5),
                force=True,
            )


async def test_transition_worker_happy_path_and_project_event(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        snapshot = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        leased = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=snapshot.state_version,
            owner="worker-a",
            expires_at=REAL_NOW + timedelta(minutes=5),
        )
        fence = AttemptLeaseFence(owner="worker-a", token=leased.lease_token or 0)
        submitting = await repo.transition_worker(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=leased.state_version,
            expected_states=frozenset({ExecutionAttemptState.PLANNED}),
            new_state=ExecutionAttemptState.SUBMITTING,
            fence=fence,
        )
        assert submitting.state is ExecutionAttemptState.SUBMITTING
        assert submitting.submitted_at is not None
        assert submitting.terminal_at is None


async def test_transition_worker_rejects_an_illegal_target_state(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        snapshot = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        leased = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=snapshot.state_version,
            owner="worker-a",
            expires_at=REAL_NOW + timedelta(minutes=5),
        )
        fence = AttemptLeaseFence(owner="worker-a", token=leased.lease_token or 0)
        with pytest.raises(ExecutionAttemptTransitionError):
            await repo.transition_worker(
                user_id=USER,
                project_name=PROJECT,
                execution_id=snapshot.execution_id,
                expected_version=leased.state_version,
                expected_states=frozenset({ExecutionAttemptState.PLANNED}),
                new_state=ExecutionAttemptState.SUCCEEDED,  # PLANNED -> SUCCEEDED is not a legal edge
                fence=fence,
            )


# --- provider-observation authority: works with no / a dead worker lease --------------


async def test_provider_observation_applies_while_the_worker_lease_is_dead(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        snapshot = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())

        live_lease = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=snapshot.state_version,
            owner="worker-a",
            expires_at=REAL_NOW + timedelta(minutes=5),
        )
        live_fence = AttemptLeaseFence(owner="worker-a", token=live_lease.lease_token or 0)
        submitting = await repo.transition_worker(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=live_lease.state_version,
            expected_states=frozenset({ExecutionAttemptState.PLANNED}),
            new_state=ExecutionAttemptState.SUBMITTING,
            fence=live_fence,
        )
        unknown = await repo.transition_worker(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=submitting.state_version,
            expected_states=frozenset({ExecutionAttemptState.SUBMITTING}),
            new_state=ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN,
            fence=live_fence,
        )

        # simulate the worker's lease dying (e.g. the process crashed) by granting a
        # lease that is already expired the instant it is acquired
        dead_lease = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=unknown.state_version,
            owner="worker-a",
            expires_at=REAL_NOW - timedelta(seconds=1),
        )
        dead_fence = AttemptLeaseFence(owner="worker-a", token=dead_lease.lease_token or 0)
        with pytest.raises(ExecutionAttemptFencingError):
            # confirm the lease really is dead for the worker authority
            await repo.transition_worker(
                user_id=USER,
                project_name=PROJECT,
                execution_id=snapshot.execution_id,
                expected_version=dead_lease.state_version,
                expected_states=frozenset({ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN}),
                new_state=ExecutionAttemptState.NEEDS_OPERATOR,
                fence=dead_fence,
            )

        # yet the provider-fact authority, unfenced by the worker lease, still succeeds
        observation = ProviderObservation(
            observation_id="obs-1",
            kind=ProviderObservationKind.ACCEPTED,
            observed_at=NOW,
            provider_sequence=None,
            provider_job_id="remote-1",
            reason_code=None,
            evidence_digest="sha256:" + "c" * 64,
        )
        folded = await repo.apply_provider_observation(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=dead_lease.state_version,
            observation=observation,
        )
        assert folded.state is ExecutionAttemptState.ACCEPTED
        assert folded.provider_job_id == "remote-1"


async def test_provider_observation_never_exits_a_needs_operator_pause(session_factory: Factory) -> None:
    """Only resolve_operator_review may leave NEEDS_OPERATOR (module docstring's
    three-authority separation): fold_observation's pure transition table
    legally permits NEEDS_OPERATOR -> ACCEPTED (an operator resolution reuses
    the same table), so apply_provider_observation must refuse that edge on
    its own rather than relying on no caller ever reaching it that way."""
    async with session_factory() as session:
        repo = _repo(session)
        planned = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        lease = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=planned.state_version,
            owner="worker-a",
            expires_at=REAL_NOW + timedelta(minutes=5),
        )
        fence = AttemptLeaseFence(owner="worker-a", token=lease.lease_token or 0)
        submitting = await repo.transition_worker(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=lease.state_version,
            expected_states=frozenset({ExecutionAttemptState.PLANNED}),
            new_state=ExecutionAttemptState.SUBMITTING,
            fence=fence,
        )
        unknown = await repo.transition_worker(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=submitting.state_version,
            expected_states=frozenset({ExecutionAttemptState.SUBMITTING}),
            new_state=ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN,
            fence=fence,
        )
        needs_operator = await repo.transition_worker(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=unknown.state_version,
            expected_states=frozenset({ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN}),
            new_state=ExecutionAttemptState.NEEDS_OPERATOR,
            fence=fence,
        )

        observation = ProviderObservation(
            observation_id="obs-late",
            kind=ProviderObservationKind.ACCEPTED,
            observed_at=NOW,
            provider_sequence=None,
            provider_job_id="remote-late",
            reason_code=None,
            evidence_digest="sha256:" + "d" * 64,
        )
        folded = await repo.apply_provider_observation(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=needs_operator.state_version,
            observation=observation,
        )

    assert folded.state is ExecutionAttemptState.NEEDS_OPERATOR
    assert folded.state_version == needs_operator.state_version
    assert folded.provider_job_id is None


async def test_duplicate_observation_id_is_a_no_op(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        snapshot = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        observation = ProviderObservation(
            observation_id="obs-1",
            kind=ProviderObservationKind.ACCEPTED,
            observed_at=NOW,
            provider_sequence=None,
            provider_job_id="remote-1",
            reason_code=None,
            evidence_digest="sha256:" + "c" * 64,
        )
        # move to SUBMIT_OUTCOME_UNKNOWN first via an operator-free path is not exposed
        # directly; observations may apply a direct legal edge from SUBMIT_OUTCOME_UNKNOWN,
        # so bootstrap that state with a worker transition chain.
        leased = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=snapshot.state_version,
            owner="worker-a",
            expires_at=REAL_NOW + timedelta(minutes=5),
        )
        fence = AttemptLeaseFence(owner="worker-a", token=leased.lease_token or 0)
        submitting = await repo.transition_worker(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=leased.state_version,
            expected_states=frozenset({ExecutionAttemptState.PLANNED}),
            new_state=ExecutionAttemptState.SUBMITTING,
            fence=fence,
        )
        unknown = await repo.transition_worker(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=submitting.state_version,
            expected_states=frozenset({ExecutionAttemptState.SUBMITTING}),
            new_state=ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN,
            fence=fence,
        )

        once = await repo.apply_provider_observation(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=unknown.state_version,
            observation=observation,
        )
        assert once.state is ExecutionAttemptState.ACCEPTED
        twice = await repo.apply_provider_observation(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=once.state_version,
            observation=observation,
        )
        assert twice == once


# --- operator authority -----------------------------------------------------------------


async def test_resolve_operator_review_moves_out_of_needs_operator(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        snapshot = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        leased = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=snapshot.state_version,
            owner="worker-a",
            expires_at=REAL_NOW + timedelta(minutes=5),
        )
        fence = AttemptLeaseFence(owner="worker-a", token=leased.lease_token or 0)
        submitting = await repo.transition_worker(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=leased.state_version,
            expected_states=frozenset({ExecutionAttemptState.PLANNED}),
            new_state=ExecutionAttemptState.SUBMITTING,
            fence=fence,
        )
        needs_operator = await repo.transition_worker(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=submitting.state_version,
            expected_states=frozenset({ExecutionAttemptState.SUBMITTING}),
            new_state=ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN,
            fence=fence,
        )
        needs_operator = await repo.transition_worker(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=needs_operator.state_version,
            expected_states=frozenset({ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN}),
            new_state=ExecutionAttemptState.NEEDS_OPERATOR,
            fence=fence,
        )
        receipt = OperatorResolutionReceipt(
            resolution_id="res-1",
            execution_id=snapshot.execution_id,
            expected_attempt_version=needs_operator.state_version,
            operator_id="operator-1",
            action=OperatorResolutionAction.CONFIRM_NOT_SUBMITTED,
            resolved_state=ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE,
            provider_job_id=None,
            terminal_kind=None,
            evidence_digest="sha256:" + "d" * 64,
            resolved_at=NOW,
        )
        resolved = await repo.resolve_operator_review(
            user_id=USER,
            project_name=PROJECT,
            execution_id=snapshot.execution_id,
            expected_version=needs_operator.state_version,
            receipt=receipt,
        )
        assert resolved.state is ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE
        assert resolved.terminal_at is not None


async def test_resolve_operator_review_rejects_a_non_needs_operator_attempt(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        snapshot = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        receipt = OperatorResolutionReceipt(
            resolution_id="res-1",
            execution_id=snapshot.execution_id,
            expected_attempt_version=snapshot.state_version,
            operator_id="operator-1",
            action=OperatorResolutionAction.CONFIRM_NOT_SUBMITTED,
            resolved_state=ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE,
            provider_job_id=None,
            terminal_kind=None,
            evidence_digest="sha256:" + "d" * 64,
            resolved_at=NOW,
        )
        with pytest.raises(ExecutionAttemptTransitionError):
            await repo.resolve_operator_review(
                user_id=USER,
                project_name=PROJECT,
                execution_id=snapshot.execution_id,
                expected_version=snapshot.state_version,
                receipt=receipt,
            )


# --- real PostgreSQL concurrent CAS ------------------------------------------------------


async def test_concurrent_lease_acquisition_has_exactly_one_winner(session_factory: Factory) -> None:
    await _skip_unless_postgres(session_factory)
    async with session_factory() as setup_session:
        snapshot = await _repo(setup_session).plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        await setup_session.commit()

    barrier = asyncio.Barrier(2)

    async def _try_acquire(owner: str) -> AttemptLeaseFence | Exception:
        async with session_factory() as session:
            repo = _repo(session)
            await barrier.wait()
            try:
                leased = await repo.acquire_lease(
                    user_id=USER,
                    project_name=PROJECT,
                    execution_id=snapshot.execution_id,
                    expected_version=snapshot.state_version,
                    owner=owner,
                    expires_at=REAL_NOW + timedelta(minutes=5),
                )
                await session.commit()
                return AttemptLeaseFence(owner=owner, token=leased.lease_token or 0)
            except ExecutionAttemptFencingError as exc:
                await session.rollback()
                return exc

    results = await asyncio.wait_for(
        asyncio.gather(_try_acquire("worker-a"), _try_acquire("worker-b"), return_exceptions=False), timeout=10.0
    )
    winners = [r for r in results if isinstance(r, AttemptLeaseFence)]
    losers = [r for r in results if isinstance(r, Exception)]
    assert len(winners) == 1
    assert len(losers) == 1


# --- CommandReceiptRepository ------------------------------------------------------------


async def test_command_receipt_repository_round_trips(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = CommandReceiptRepository(session)
        assert (
            await repo.get_exact(user_id=USER, project_name=PROJECT, actor_scope="user:alice", command_id="cmd-1")
            is None
        )
        receipt = CommandReceipt(
            actor_scope="user:alice",
            command_id="cmd-1",
            command_digest="sha256:" + "e" * 64,
            task_id="task-1",
            result_digest="sha256:" + "f" * 64,
            created_at=NOW,
        )
        await repo.add(user_id=USER, project_name=PROJECT, receipt=receipt)
        await session.commit()
        fetched = await repo.get_exact(user_id=USER, project_name=PROJECT, actor_scope="user:alice", command_id="cmd-1")
        assert fetched == receipt
        assert (
            await repo.get_exact(
                user_id=USER, project_name="other-project", actor_scope="user:alice", command_id="cmd-1"
            )
            is None
        )


# --- request_cancel (cancel-intent authority) ---------------------------------------------


async def _bring_to_accepted(repo: ExecutionAttemptRepository, *, execution_id: str, owner: str) -> AttemptSnapshot:
    planned = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt(execution_id=execution_id))
    leased = await repo.acquire_lease(
        user_id=USER,
        project_name=PROJECT,
        execution_id=planned.execution_id,
        expected_version=planned.state_version,
        owner=owner,
        expires_at=REAL_NOW + timedelta(minutes=5),
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
    observation = ProviderObservation(
        observation_id=f"obs-{execution_id}",
        kind=ProviderObservationKind.ACCEPTED,
        observed_at=NOW,
        provider_sequence=None,
        provider_job_id=f"remote-{execution_id}",
        reason_code=None,
        evidence_digest="sha256:" + "c" * 64,
    )
    return await repo.apply_provider_observation(
        user_id=USER,
        project_name=PROJECT,
        execution_id=planned.execution_id,
        expected_version=submitting.state_version,
        observation=observation,
    )


async def test_request_cancel_moves_an_accepted_attempt_without_a_lease(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        accepted = await _bring_to_accepted(repo, execution_id="exec-1", owner="worker-a")
        # No lease is held at all by the time the cancel request arrives -- the
        # worker that submitted it may have long since released/expired it.
        cancelled_intent = await repo.request_cancel(
            user_id=USER,
            project_name=PROJECT,
            execution_id=accepted.execution_id,
            expected_version=accepted.state_version,
            actor_scope="user:alice",
            command_id="cancel-1",
            command_digest="sha256:" + "1" * 64,
        )

    assert cancelled_intent.state is ExecutionAttemptState.CANCEL_REQUESTED
    assert cancelled_intent.state_version == accepted.state_version + 1


async def test_request_cancel_rejects_an_attempt_that_is_not_accepted_or_running(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        planned = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        with pytest.raises(ExecutionAttemptTransitionError):
            await repo.request_cancel(
                user_id=USER,
                project_name=PROJECT,
                execution_id=planned.execution_id,
                expected_version=planned.state_version,
                actor_scope="user:alice",
                command_id="cancel-1",
                command_digest="sha256:" + "1" * 64,
            )


async def test_request_cancel_exact_replay_is_idempotent(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        accepted = await _bring_to_accepted(repo, execution_id="exec-1", owner="worker-a")
        first = await repo.request_cancel(
            user_id=USER,
            project_name=PROJECT,
            execution_id=accepted.execution_id,
            expected_version=accepted.state_version,
            actor_scope="user:alice",
            command_id="cancel-1",
            command_digest="sha256:" + "1" * 64,
        )
        second = await repo.request_cancel(
            user_id=USER,
            project_name=PROJECT,
            execution_id=accepted.execution_id,
            expected_version=accepted.state_version,
            actor_scope="user:alice",
            command_id="cancel-1",
            command_digest="sha256:" + "1" * 64,
        )

    assert second.state is ExecutionAttemptState.CANCEL_REQUESTED
    assert second.state_version == first.state_version


async def test_request_cancel_rejects_a_reused_command_id_with_a_different_digest(
    session_factory: Factory,
) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        accepted = await _bring_to_accepted(repo, execution_id="exec-1", owner="worker-a")
        await repo.request_cancel(
            user_id=USER,
            project_name=PROJECT,
            execution_id=accepted.execution_id,
            expected_version=accepted.state_version,
            actor_scope="user:alice",
            command_id="cancel-1",
            command_digest="sha256:" + "1" * 64,
        )
        with pytest.raises(CommandReceiptConflictError):
            await repo.request_cancel(
                user_id=USER,
                project_name=PROJECT,
                execution_id=accepted.execution_id,
                expected_version=accepted.state_version,
                actor_scope="user:alice",
                command_id="cancel-1",
                command_digest="sha256:" + "2" * 64,
            )


async def test_request_cancel_concurrent_commands_has_exactly_one_winner(session_factory: Factory) -> None:
    await _skip_unless_postgres(session_factory)
    async with session_factory() as setup_session:
        accepted = await _bring_to_accepted(_repo(setup_session), execution_id="exec-1", owner="worker-a")
        await setup_session.commit()

    barrier = asyncio.Barrier(2)

    async def _try_cancel(command_id: str) -> AttemptSnapshot | Exception:
        async with session_factory() as session:
            await barrier.wait()
            try:
                snapshot = await _repo(session).request_cancel(
                    user_id=USER,
                    project_name=PROJECT,
                    execution_id=accepted.execution_id,
                    expected_version=accepted.state_version,
                    actor_scope="user:alice",
                    command_id=command_id,
                    command_digest="sha256:" + "1" * 64,
                )
                await session.commit()
                return snapshot
            except ExecutionAttemptFencingError as exc:
                await session.rollback()
                return exc

    results = await asyncio.wait_for(
        asyncio.gather(_try_cancel("cancel-a"), _try_cancel("cancel-b"), return_exceptions=False), timeout=10.0
    )
    winners = [r for r in results if isinstance(r, AttemptSnapshot)]
    losers = [r for r in results if isinstance(r, Exception)]
    assert len(winners) == 1
    assert len(losers) == 1


# --- list_pending_cancels ------------------------------------------------------------


async def test_list_pending_cancels_finds_a_cancel_requested_attempt_regardless_of_its_lease(
    session_factory: Factory,
) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        accepted = await _bring_to_accepted(repo, execution_id="exec-1", owner="worker-a")
        await repo.request_cancel(
            user_id=USER,
            project_name=PROJECT,
            execution_id=accepted.execution_id,
            expected_version=accepted.state_version,
            actor_scope="user:alice",
            command_id="cancel-1",
            command_digest="sha256:" + "1" * 64,
        )
        await session.commit()

    async with session_factory() as session:
        pending = await _repo(session).list_pending_cancels()

    assert len(pending) == 1
    found_user, found_project, found_snapshot = pending[0]
    assert found_user == USER
    assert found_project == PROJECT
    assert found_snapshot.execution_id == "exec-1"
    assert found_snapshot.state is ExecutionAttemptState.CANCEL_REQUESTED


async def test_list_pending_cancels_excludes_every_other_state(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        await repo.plan(
            user_id=USER,
            project_name=PROJECT,
            attempt=_attempt(task_id="task-planned", execution_id="exec-planned"),
        )
        await _bring_to_accepted(repo, execution_id="exec-accepted", owner="worker-a")
        await session.commit()

    async with session_factory() as session:
        pending = await _repo(session).list_pending_cancels()

    assert pending == []


# --- list_lease_expired (H5 recovery scan) ------------------------------------------------


async def test_list_lease_expired_finds_a_stale_submitting_attempt_across_scopes(
    session_factory: Factory,
) -> None:
    # transition_worker below re-checks the lease against the real wall clock
    # (utc_now(), not injectable), so its TTL is anchored to a freshly taken
    # timestamp here rather than the module-level REAL_NOW -- under a slow,
    # heavily parallel full-suite run, REAL_NOW (captured at import/collection
    # time) could already be more than 5 real seconds in the past by the time
    # this test body actually executes.
    now = datetime.now(UTC)
    async with session_factory() as session:
        repo = _repo(session)
        planned = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        # Live (5s ahead of `now`) when acquired and transitioned -- a real worker
        # would use a much longer TTL. The scan below uses a `before` cutoff past
        # that expiry to deterministically simulate "enough real time has since
        # passed", without an actual sleep.
        submitting_lease = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=planned.state_version,
            owner="worker-a",
            expires_at=now + timedelta(seconds=5),
        )
        await repo.transition_worker(
            user_id=USER,
            project_name=PROJECT,
            execution_id=submitting_lease.execution_id,
            expected_version=submitting_lease.state_version,
            expected_states=frozenset({ExecutionAttemptState.PLANNED}),
            new_state=ExecutionAttemptState.SUBMITTING,
            fence=AttemptLeaseFence(owner="worker-a", token=submitting_lease.lease_token or 0),
        )
        await session.commit()

    async with session_factory() as session:
        expired = await _repo(session).list_lease_expired(
            states=frozenset({ExecutionAttemptState.SUBMITTING}), before=now + timedelta(seconds=10)
        )

    assert len(expired) == 1
    found_user, found_project, found_snapshot = expired[0]
    assert found_user == USER
    assert found_project == PROJECT
    assert found_snapshot.execution_id == "exec-1"
    assert found_snapshot.state is ExecutionAttemptState.SUBMITTING


async def test_list_lease_expired_excludes_an_attempt_with_a_live_lease(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        planned = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=planned.state_version,
            owner="worker-a",
            expires_at=REAL_NOW + timedelta(minutes=5),
        )
        await session.commit()

    async with session_factory() as session:
        expired = await _repo(session).list_lease_expired(
            states=frozenset({ExecutionAttemptState.PLANNED}), before=REAL_NOW
        )

    assert expired == []


async def test_list_lease_expired_excludes_states_not_asked_for(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        planned = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
        await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=planned.state_version,
            owner="worker-a",
            expires_at=REAL_NOW - timedelta(seconds=1),
        )
        await session.commit()

    async with session_factory() as session:
        expired = await _repo(session).list_lease_expired(
            states=frozenset({ExecutionAttemptState.SUBMITTING}), before=REAL_NOW
        )

    assert expired == []
