"""Unit coverage for ExecutionAttemptServiceImpl's control flow:
submit classification and reconciliation policy against a fake, in-process
repository double -- no database. The real PostgreSQL-backed stack is proven
separately in tests/integration/server/services/test_execution_attempt_service.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lib.video_backends.base import AmbiguousSubmitError
from r2.contracts.execution import ProviderRequest
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
from r2.host_hardening.execution import ExecutionAttemptNotFoundError, ExecutionAttemptServiceImpl
from r2.host_hardening.transitions import fold_observation, is_legal_transition

NOW = datetime.now(UTC)
USER = "u1"
PROJECT = "demo"

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

REQUEST = ProviderRequest(
    id="req-1",
    method_decision_ref="decision-1",
    prompt_plan_ref=None,
    provider="acme-video",
    model="acme-v3",
    endpoint="submit",
    payload={},
    adapter_version="1.0.0",
)


def _capability(**overrides: object) -> ProviderCapabilityProfile:
    defaults: dict[str, object] = {
        "ref": "acme-video-v3@1.0.0",
        "provider_id": "acme-video",
        "api_version": "2026-01-01",
        "adapter_version": "1.0.0",
        "idempotency_mode": ProviderIdempotencyMode.NATIVE_TOKEN,
        "token_scope": None,
        "token_scope_value": None,
        "token_ttl_seconds": None,
        "not_found_semantics": ProviderNotFoundSemantics.NON_AUTHORITATIVE,
        "lookup_settling_window_seconds": None,
        "supports_poll": True,
        "supports_cancel": True,
        "supports_lookup": False,
        "provider_sequence_is_monotonic": False,
        "evidence_digest": "sha256:" + "a" * 64,
    }
    defaults.update(overrides)
    return ProviderCapabilityProfile(**defaults)


class _FakeRepository:
    """A minimal in-process double implementing exactly the
    ExecutionAttemptRepository surface ExecutionAttemptServiceImpl calls,
    reusing the same pure fold/legality functions the real repository does."""

    def __init__(self, *, capability_resolver=lambda ref: _capability()) -> None:
        self._rows: dict[str, AttemptSnapshot] = {}
        self._seq = 0
        self._capability_resolver = capability_resolver

    def _require(self, execution_id: str) -> AttemptSnapshot:
        snapshot = self._rows.get(execution_id)
        if snapshot is None:
            raise AssertionError(f"no fake row for {execution_id}")
        return snapshot

    async def plan(self, *, user_id: str, project_name: str, attempt: PlannedExecutionAttempt) -> AttemptSnapshot:
        del user_id, project_name
        existing = self._rows.get(attempt.execution_id)
        if existing is not None:
            return existing
        snapshot = AttemptSnapshot(
            execution_id=attempt.execution_id,
            task_id=attempt.task_id,
            attempt_no=attempt.attempt_no,
            request_digest=attempt.request_digest,
            route=attempt.route,
            client_token=attempt.client_token,
            provider_job_id=None,
            state=ExecutionAttemptState.PLANNED,
            state_version=1,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            created_at=attempt.created_at,
            updated_at=attempt.created_at,
            submitted_at=None,
            last_observed_at=None,
            terminal_at=None,
        )
        self._rows[attempt.execution_id] = snapshot
        return snapshot

    async def get_exact(self, *, user_id: str, project_name: str, execution_id: str) -> AttemptSnapshot | None:
        del user_id, project_name
        return self._rows.get(execution_id)

    async def acquire_lease(
        self,
        *,
        user_id: str,
        project_name: str,
        execution_id: str,
        expected_version: int,
        owner: str,
        expires_at: datetime,
    ) -> AttemptSnapshot:
        del user_id, project_name
        snapshot = self._require(execution_id)
        assert snapshot.state_version == expected_version
        updated = snapshot.model_copy(
            update={
                "state_version": expected_version + 1,
                "lease_owner": owner,
                "lease_token": (snapshot.lease_token or 0) + 1,
                "lease_expires_at": expires_at,
            }
        )
        self._rows[execution_id] = updated
        return updated

    async def transition_worker(
        self,
        *,
        user_id: str,
        project_name: str,
        execution_id: str,
        expected_version: int,
        expected_states: frozenset[ExecutionAttemptState],
        new_state: ExecutionAttemptState,
        fence: AttemptLeaseFence,
        reason_code: str | None = None,
    ) -> AttemptSnapshot:
        del user_id, project_name, reason_code
        snapshot = self._require(execution_id)
        assert snapshot.state_version == expected_version
        assert snapshot.state in expected_states
        assert snapshot.lease_owner == fence.owner
        assert snapshot.lease_token == fence.token
        assert is_legal_transition(snapshot.state, new_state)
        updated = snapshot.model_copy(
            update={
                "state": new_state,
                "state_version": expected_version + 1,
                "terminal_at": NOW
                if new_state
                in {
                    ExecutionAttemptState.SUCCEEDED,
                    ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE,
                    ExecutionAttemptState.FAILED,
                    ExecutionAttemptState.CANCELLED,
                }
                else None,
            }
        )
        self._rows[execution_id] = updated
        return updated

    async def apply_provider_observation(
        self,
        *,
        user_id: str,
        project_name: str,
        execution_id: str,
        expected_version: int,
        observation: ProviderObservation,
    ) -> AttemptSnapshot:
        del user_id, project_name
        snapshot = self._require(execution_id)
        assert snapshot.state_version == expected_version
        self._seq += 1
        from r2.contracts.host_hardening import PersistedProviderObservation

        persisted = PersistedProviderObservation(observation=observation, received_seq=self._seq, received_at=NOW)
        capability = self._capability_resolver(snapshot.route.capability_profile_ref)
        folded = fold_observation(snapshot, persisted, capability)
        self._rows[execution_id] = folded
        return folded

    async def resolve_operator_review(self, **kwargs: object) -> AttemptSnapshot:
        raise NotImplementedError

    async def release_lease(self, **kwargs: object) -> AttemptSnapshot:
        raise NotImplementedError


def _attempt(execution_id: str = "exec-1") -> PlannedExecutionAttempt:
    return PlannedExecutionAttempt(
        execution_id=execution_id,
        task_id="task-1",
        attempt_no=1,
        request_digest="sha256:" + "b" * 64,
        route=ROUTE,
        client_token=execution_id,
        trace_id_at_creation=None,
        created_at=NOW,
    )


class _AcceptedAdapter:
    capability_profile = _capability()

    async def submit(self, *, attempt: AttemptSnapshot, request: ProviderRequest) -> ProviderObservation:
        del attempt, request
        return ProviderObservation(
            observation_id="obs-1",
            kind=ProviderObservationKind.ACCEPTED,
            observed_at=NOW,
            provider_sequence=None,
            provider_job_id="remote-1",
            reason_code=None,
            evidence_digest="sha256:" + "c" * 64,
        )

    async def reconcile(self, attempt: AttemptSnapshot) -> ProviderObservation | None:
        raise NotImplementedError

    async def poll(self, attempt: AttemptSnapshot) -> ProviderObservation:
        raise NotImplementedError

    async def cancel(self, attempt: AttemptSnapshot) -> ProviderObservation:
        raise NotImplementedError


class _AmbiguousAdapter(_AcceptedAdapter):
    async def submit(self, *, attempt: AttemptSnapshot, request: ProviderRequest) -> ProviderObservation:
        raise AmbiguousSubmitError(provider="acme-video")


class _DefiniteFailureAdapter(_AcceptedAdapter):
    async def submit(self, *, attempt: AttemptSnapshot, request: ProviderRequest) -> ProviderObservation:
        raise RuntimeError("connection refused")


def _service(
    repo: _FakeRepository, *, capability: ProviderCapabilityProfile | None = None, adapter=None
) -> ExecutionAttemptServiceImpl:
    resolver = lambda ref: capability or _capability()  # noqa: E731
    repo._capability_resolver = resolver  # the fake's own fold must see the same capability
    return ExecutionAttemptServiceImpl(
        repo,
        capability_resolver=resolver,
        adapter_resolver=lambda route: adapter,
        owner_id_factory=lambda: "worker-1",
    )


# --- plan_and_submit: accepted receipt --------------------------------------------------


async def test_accepted_receipt_moves_to_accepted_with_job_id() -> None:
    repo = _FakeRepository()
    service = _service(repo)
    result = await service.plan_and_submit(
        user_id=USER, project_name=PROJECT, attempt=_attempt(), request=REQUEST, adapter=_AcceptedAdapter()
    )
    assert result.state is ExecutionAttemptState.ACCEPTED
    assert result.provider_job_id == "remote-1"


async def test_plan_and_submit_is_a_no_op_for_an_attempt_already_past_planned() -> None:
    repo = _FakeRepository()
    service = _service(repo)
    first = await service.plan_and_submit(
        user_id=USER, project_name=PROJECT, attempt=_attempt(), request=REQUEST, adapter=_AcceptedAdapter()
    )
    assert first.state is ExecutionAttemptState.ACCEPTED
    # A second plan_and_submit for the exact same attempt never resubmits.
    second = await service.plan_and_submit(
        user_id=USER, project_name=PROJECT, attempt=_attempt(), request=REQUEST, adapter=_DefiniteFailureAdapter()
    )
    assert second == first


# --- plan_and_submit: pre-send / ambiguous classification -------------------------------


async def test_ambiguous_submit_error_moves_to_submit_outcome_unknown() -> None:
    repo = _FakeRepository()
    service = _service(repo)
    result = await service.plan_and_submit(
        user_id=USER, project_name=PROJECT, attempt=_attempt(), request=REQUEST, adapter=_AmbiguousAdapter()
    )
    assert result.state is ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN


async def test_a_definite_pre_send_failure_moves_to_failed_before_acceptance() -> None:
    repo = _FakeRepository()
    service = _service(repo)
    result = await service.plan_and_submit(
        user_id=USER, project_name=PROJECT, attempt=_attempt(), request=REQUEST, adapter=_DefiniteFailureAdapter()
    )
    assert result.state is ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE
    assert result.terminal_at is not None


# --- reconcile: no-op outside the unknown states -----------------------------------------


async def test_reconcile_is_a_no_op_outside_the_unknown_states() -> None:
    repo = _FakeRepository()
    service = _service(repo)
    await service.plan_and_submit(
        user_id=USER, project_name=PROJECT, attempt=_attempt(), request=REQUEST, adapter=_AcceptedAdapter()
    )
    result = await service.reconcile(user_id=USER, project_name=PROJECT, execution_id="exec-1")
    assert result.state is ExecutionAttemptState.ACCEPTED
    assert result.operator_reason is None


async def test_reconcile_raises_not_found_for_an_unknown_execution_id() -> None:
    repo = _FakeRepository()
    service = _service(repo)
    with pytest.raises(ExecutionAttemptNotFoundError):
        await service.reconcile(user_id=USER, project_name=PROJECT, execution_id="no-such-exec")


async def _unknown_snapshot(repo: _FakeRepository) -> AttemptSnapshot:
    snapshot = await repo.plan(user_id=USER, project_name=PROJECT, attempt=_attempt())
    leased = await repo.acquire_lease(
        user_id=USER,
        project_name=PROJECT,
        execution_id=snapshot.execution_id,
        expected_version=snapshot.state_version,
        owner="worker-1",
        expires_at=NOW + timedelta(minutes=5),
    )
    fence = AttemptLeaseFence(owner="worker-1", token=leased.lease_token or 0)
    submitting = await repo.transition_worker(
        user_id=USER,
        project_name=PROJECT,
        execution_id=snapshot.execution_id,
        expected_version=leased.state_version,
        expected_states=frozenset({ExecutionAttemptState.PLANNED}),
        new_state=ExecutionAttemptState.SUBMITTING,
        fence=fence,
    )
    return await repo.transition_worker(
        user_id=USER,
        project_name=PROJECT,
        execution_id=snapshot.execution_id,
        expected_version=submitting.state_version,
        expected_states=frozenset({ExecutionAttemptState.SUBMITTING}),
        new_state=ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN,
        fence=fence,
    )


# --- reconcile: mode NONE pauses for the operator without calling the adapter -----------


async def test_reconcile_mode_none_pauses_for_operator_without_calling_the_adapter() -> None:
    repo = _FakeRepository()
    await _unknown_snapshot(repo)

    class _NeverCalledAdapter(_AcceptedAdapter):
        async def reconcile(self, attempt: AttemptSnapshot) -> ProviderObservation | None:
            raise AssertionError("mode NONE must never call adapter.reconcile")

    service = _service(
        repo, capability=_capability(idempotency_mode=ProviderIdempotencyMode.NONE), adapter=_NeverCalledAdapter()
    )
    result = await service.reconcile(user_id=USER, project_name=PROJECT, execution_id="exec-1")
    assert result.state is ExecutionAttemptState.NEEDS_OPERATOR
    assert result.operator_reason == "no_safe_reconciliation"


# --- reconcile: native-token replay -------------------------------------------------------


async def test_native_token_reconcile_replay_resolves_to_the_observed_state() -> None:
    repo = _FakeRepository()
    await _unknown_snapshot(repo)

    class _NativeTokenReplayAdapter(_AcceptedAdapter):
        async def reconcile(self, attempt: AttemptSnapshot) -> ProviderObservation | None:
            return ProviderObservation(
                observation_id="obs-replay",
                kind=ProviderObservationKind.ACCEPTED,
                observed_at=NOW,
                provider_sequence=None,
                provider_job_id="remote-native-1",
                reason_code=None,
                evidence_digest="sha256:" + "d" * 64,
            )

    service = _service(
        repo,
        capability=_capability(idempotency_mode=ProviderIdempotencyMode.NATIVE_TOKEN),
        adapter=_NativeTokenReplayAdapter(),
    )
    result = await service.reconcile(user_id=USER, project_name=PROJECT, execution_id="exec-1")
    assert result.state is ExecutionAttemptState.ACCEPTED
    assert result.provider_job_id == "remote-native-1"
    assert result.operator_reason is None


# --- reconcile: lookup zero / one / many --------------------------------------------------


async def test_lookup_zero_matches_reports_not_found_and_pauses_for_operator() -> None:
    repo = _FakeRepository()
    await _unknown_snapshot(repo)

    class _ZeroMatchAdapter(_AcceptedAdapter):
        async def reconcile(self, attempt: AttemptSnapshot) -> ProviderObservation | None:
            return ProviderObservation(
                observation_id="obs-not-found",
                kind=ProviderObservationKind.NOT_FOUND,
                observed_at=NOW,
                provider_sequence=None,
                provider_job_id=None,
                reason_code=None,
                evidence_digest="sha256:" + "e" * 64,
            )

    capability = _capability(
        idempotency_mode=ProviderIdempotencyMode.LOOKUP_BY_METADATA,
        supports_lookup=True,
        not_found_semantics=ProviderNotFoundSemantics.NON_AUTHORITATIVE,
    )
    service = _service(repo, capability=capability, adapter=_ZeroMatchAdapter())
    result = await service.reconcile(user_id=USER, project_name=PROJECT, execution_id="exec-1")
    assert result.state is ExecutionAttemptState.NEEDS_OPERATOR
    assert result.operator_reason == "not_found_not_authoritative"


async def test_lookup_one_match_resolves_to_the_observed_state() -> None:
    repo = _FakeRepository()
    await _unknown_snapshot(repo)

    class _OneMatchAdapter(_AcceptedAdapter):
        async def reconcile(self, attempt: AttemptSnapshot) -> ProviderObservation | None:
            return ProviderObservation(
                observation_id="obs-found",
                kind=ProviderObservationKind.RUNNING,
                observed_at=NOW,
                provider_sequence=None,
                provider_job_id="remote-lookup-1",
                reason_code=None,
                evidence_digest="sha256:" + "f" * 64,
            )

    capability = _capability(idempotency_mode=ProviderIdempotencyMode.LOOKUP_BY_METADATA, supports_lookup=True)
    service = _service(repo, capability=capability, adapter=_OneMatchAdapter())
    result = await service.reconcile(user_id=USER, project_name=PROJECT, execution_id="exec-1")
    assert result.state is ExecutionAttemptState.RUNNING
    assert result.provider_job_id == "remote-lookup-1"


async def test_lookup_many_matches_is_ambiguous_and_pauses_for_operator() -> None:
    repo = _FakeRepository()
    await _unknown_snapshot(repo)

    class _AmbiguousLookupAdapter(_AcceptedAdapter):
        async def reconcile(self, attempt: AttemptSnapshot) -> ProviderObservation | None:
            # Multiple matches: the adapter itself cannot safely pick one.
            return None

    capability = _capability(idempotency_mode=ProviderIdempotencyMode.LOOKUP_BY_METADATA, supports_lookup=True)
    service = _service(repo, capability=capability, adapter=_AmbiguousLookupAdapter())
    result = await service.reconcile(user_id=USER, project_name=PROJECT, execution_id="exec-1")
    assert result.state is ExecutionAttemptState.NEEDS_OPERATOR
    assert result.operator_reason == "ambiguous_lookup"


# --- reconcile: both NOT_FOUND settling-window policies ------------------------------------


async def test_reconcile_authoritative_not_found_after_window_reaches_failed_before_acceptance() -> None:
    repo = _FakeRepository()
    await _unknown_snapshot(repo)

    class _AuthoritativeNotFoundAdapter(_AcceptedAdapter):
        async def reconcile(self, attempt: AttemptSnapshot) -> ProviderObservation | None:
            return ProviderObservation(
                observation_id="obs-authoritative-not-found",
                kind=ProviderObservationKind.NOT_FOUND,
                observed_at=NOW,
                provider_sequence=None,
                provider_job_id=None,
                reason_code=None,
                evidence_digest="sha256:" + "1" * 64,
            )

    capability = _capability(
        idempotency_mode=ProviderIdempotencyMode.LOOKUP_BY_METADATA,
        supports_lookup=True,
        not_found_semantics=ProviderNotFoundSemantics.AUTHORITATIVE_AFTER_SETTLING_WINDOW,
        lookup_settling_window_seconds=None,  # no window declared: immediately authoritative
    )
    service = _service(repo, capability=capability, adapter=_AuthoritativeNotFoundAdapter())
    result = await service.reconcile(user_id=USER, project_name=PROJECT, execution_id="exec-1")
    assert result.state is ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE
