from __future__ import annotations

from datetime import UTC, datetime

import pytest

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
from r2.host_hardening.host_submit import AttemptSubmitter, ProviderSubmitReceipt
from r2.host_hardening.transitions import AttemptIdentityMismatch

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
ROUTE = ProviderRouteSnapshot(
    provider_id="acme-video",
    provider_account_ref="acct-1",
    provider_model_id="acme-v3",
    backend_model_id="acme-video-v3",
    endpoint_id="videos.create",
    submitted_base_url="https://api.acme.example/v3",
    adapter_version="1.0.0",
    capability_profile_ref="acme-video-v3@1.0.0",
)
CAPABILITY = ProviderCapabilityProfile(
    ref=ROUTE.capability_profile_ref,
    provider_id=ROUTE.provider_id,
    api_version="2026-01-01",
    adapter_version=ROUTE.adapter_version,
    idempotency_mode=ProviderIdempotencyMode.NATIVE_TOKEN,
    token_scope=None,
    token_scope_value=None,
    token_ttl_seconds=None,
    not_found_semantics=ProviderNotFoundSemantics.NON_AUTHORITATIVE,
    lookup_settling_window_seconds=None,
    supports_poll=True,
    supports_cancel=False,
    supports_lookup=False,
    provider_sequence_is_monotonic=False,
    evidence_digest="sha256:" + "a" * 64,
)
REQUEST = ProviderRequest(
    id="req-1",
    host_task_ref="task-1",
    provider=ROUTE.provider_id,
    model=ROUTE.provider_model_id,
    endpoint=ROUTE.endpoint_id or "videos.create",
    payload={"prompt": "hello"},
    adapter_version=ROUTE.adapter_version,
)


class _Repository:
    def __init__(self) -> None:
        self.snapshot: AttemptSnapshot | None = None

    async def get_for_task_attempt(self, **_: object) -> AttemptSnapshot | None:
        return self.snapshot


class _Service:
    def __init__(self, repository: _Repository) -> None:
        self.repository = repository

    async def plan_and_submit(
        self, *, attempt: PlannedExecutionAttempt, request: ProviderRequest, adapter, **_
    ) -> AttemptSnapshot:
        if self.repository.snapshot is not None:
            return self.repository.snapshot
        planned = AttemptSnapshot(
            **attempt.model_dump(exclude={"trace_id_at_creation"}),
            provider_job_id=None,
            state=ExecutionAttemptState.SUBMITTING,
            state_version=3,
            lease_owner="worker-1",
            lease_token=1,
            lease_expires_at=NOW,
            updated_at=NOW,
            submitted_at=NOW,
            last_observed_at=None,
            terminal_at=None,
        )
        observation = await adapter.submit(attempt=planned, request=request)
        accepted = planned.model_copy(
            update={
                "provider_job_id": observation.provider_job_id,
                "state": ExecutionAttemptState.ACCEPTED,
                "state_version": 4,
                "last_observed_at": observation.observed_at,
            }
        )
        self.repository.snapshot = accepted
        return accepted


async def test_submitter_reloads_attempt_one_and_never_calls_submit_twice() -> None:
    repository = _Repository()
    submitter = AttemptSubmitter(
        repository=repository,
        service=_Service(repository),
        capability_resolver=lambda _: CAPABILITY,
        user_id="u1",
        project_name="demo",
        execution_id_factory=lambda: "exec-1",
        clock=lambda: NOW,
    )
    submit_count = 0

    async def submit(attempt: AttemptSnapshot) -> ProviderSubmitReceipt[str]:
        nonlocal submit_count
        submit_count += 1
        assert attempt.client_token == "exec-1"
        return ProviderSubmitReceipt(
            observation=ProviderObservation(
                observation_id="obs-1",
                kind=ProviderObservationKind.ACCEPTED,
                observed_at=NOW,
                provider_sequence=None,
                provider_job_id="remote-1",
                reason_code=None,
                evidence_digest="sha256:" + "b" * 64,
            ),
            value="remote-1",
        )

    first = await submitter.submit(task_id="task-1", api_call_id=None, route=ROUTE, request=REQUEST, submit=submit)
    second = await submitter.submit(task_id="task-1", api_call_id=None, route=ROUTE, request=REQUEST, submit=submit)

    assert first.execution_id == second.execution_id == "exec-1"
    assert first.value == "remote-1"
    assert second.value is None
    assert submit_count == 1


async def test_submitter_rejects_route_drift_before_network() -> None:
    repository = _Repository()
    submitter = AttemptSubmitter(
        repository=repository,
        service=_Service(repository),
        capability_resolver=lambda _: CAPABILITY,
        user_id="u1",
        project_name="demo",
        execution_id_factory=lambda: "exec-1",
        clock=lambda: NOW,
    )
    called = False

    async def submit(attempt: AttemptSnapshot) -> ProviderSubmitReceipt[str]:
        nonlocal called
        called = True
        raise AssertionError(attempt)

    repository.snapshot = AttemptSnapshot(
        execution_id="exec-1",
        task_id="task-1",
        attempt_no=1,
        request_digest="sha256:" + "0" * 64,
        route=ROUTE.model_copy(update={"provider_model_id": "old-model"}),
        client_token="exec-1",
        provider_job_id=None,
        state=ExecutionAttemptState.PLANNED,
        state_version=1,
        lease_owner=None,
        lease_token=None,
        lease_expires_at=None,
        created_at=NOW,
        updated_at=NOW,
        submitted_at=None,
        last_observed_at=None,
        terminal_at=None,
    )

    with pytest.raises(AttemptIdentityMismatch):
        await submitter.submit(task_id="task-1", api_call_id=None, route=ROUTE, request=REQUEST, submit=submit)
    assert called is False
