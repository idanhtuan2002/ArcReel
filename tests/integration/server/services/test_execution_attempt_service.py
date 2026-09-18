"""Integration coverage for ExecutionAttemptServiceImpl against a real,
persisted ExecutionAttemptRepository. The pure control-flow
branches are proven with a fake repository in
tests/unit/r2/host_hardening/test_execution_service.py; this file proves the
same service actually persists correctly and survives a fresh service
instance (a process restart)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.repositories.host_hardening import ExecutionAttemptRepository
from lib.video_backends.base import AmbiguousSubmitError
from r2.contracts.execution import ProviderRequest
from r2.contracts.host_hardening import (
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


def _capability_resolver(ref: str) -> ProviderCapabilityProfile:
    assert ref == _CAPABILITY.ref
    return _CAPABILITY


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


def _repository(session: AsyncSession) -> ExecutionAttemptRepository:
    return ExecutionAttemptRepository(session, capability_resolver=_capability_resolver)


def _service(session: AsyncSession, *, adapter=None) -> ExecutionAttemptServiceImpl:
    return ExecutionAttemptServiceImpl(
        _repository(session),
        capability_resolver=_capability_resolver,
        adapter_resolver=lambda route: adapter,
    )


class _AcceptedAdapter:
    capability_profile = _CAPABILITY

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
        return ProviderObservation(
            observation_id="obs-reconcile",
            kind=ProviderObservationKind.SUCCEEDED,
            observed_at=NOW,
            provider_sequence=None,
            provider_job_id="remote-1",
            reason_code=None,
            evidence_digest="sha256:" + "d" * 64,
        )

    async def poll(self, attempt: AttemptSnapshot) -> ProviderObservation:
        raise NotImplementedError

    async def cancel(self, attempt: AttemptSnapshot) -> ProviderObservation:
        raise NotImplementedError


class _AmbiguousAdapter(_AcceptedAdapter):
    async def submit(self, *, attempt: AttemptSnapshot, request: ProviderRequest) -> ProviderObservation:
        raise AmbiguousSubmitError(provider="acme-video")


async def test_plan_and_submit_persists_the_accepted_attempt(db_session: AsyncSession) -> None:
    service = _service(db_session, adapter=_AcceptedAdapter())
    result = await service.plan_and_submit(
        user_id=USER, project_name=PROJECT, attempt=_attempt(), request=REQUEST, adapter=_AcceptedAdapter()
    )
    await db_session.commit()
    assert result.state is ExecutionAttemptState.ACCEPTED
    assert result.provider_job_id == "remote-1"

    # A fresh repository/service instance (a restarted process) reads the same
    # persisted truth.
    reloaded = await _repository(db_session).get_exact(
        user_id=USER, project_name=PROJECT, execution_id=result.execution_id
    )
    assert reloaded is not None
    assert reloaded.state is ExecutionAttemptState.ACCEPTED
    assert reloaded.provider_job_id == "remote-1"


async def test_ambiguous_submit_then_native_token_reconcile_resolves_to_succeeded(db_session: AsyncSession) -> None:
    submit_service = _service(db_session, adapter=_AmbiguousAdapter())
    unknown = await submit_service.plan_and_submit(
        user_id=USER, project_name=PROJECT, attempt=_attempt(), request=REQUEST, adapter=_AmbiguousAdapter()
    )
    await db_session.commit()
    assert unknown.state is ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN

    # A restarted process constructs a fresh repository/service and reconciles.
    reconcile_service = _service(db_session, adapter=_AcceptedAdapter())
    result = await reconcile_service.reconcile(user_id=USER, project_name=PROJECT, execution_id="exec-1")
    await db_session.commit()
    assert result.state is ExecutionAttemptState.SUCCEEDED
    assert result.provider_job_id == "remote-1"

    reloaded = await _repository(db_session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-1")
    assert reloaded is not None
    assert reloaded.state is ExecutionAttemptState.SUCCEEDED
    assert reloaded.terminal_at is not None


async def test_plan_and_submit_never_resubmits_after_a_restart(db_session: AsyncSession) -> None:
    first_service = _service(db_session, adapter=_AcceptedAdapter())
    first = await first_service.plan_and_submit(
        user_id=USER, project_name=PROJECT, attempt=_attempt(), request=REQUEST, adapter=_AcceptedAdapter()
    )
    await db_session.commit()

    class _FailIfCalledAdapter(_AcceptedAdapter):
        async def submit(self, *, attempt: AttemptSnapshot, request: ProviderRequest) -> ProviderObservation:
            raise AssertionError("must not resubmit an attempt already past PLANNED")

    restarted_service = _service(db_session, adapter=_FailIfCalledAdapter())
    second = await restarted_service.plan_and_submit(
        user_id=USER, project_name=PROJECT, attempt=_attempt(), request=REQUEST, adapter=_FailIfCalledAdapter()
    )
    assert second == first
