"""H7 secret-canary coverage (M7-D Task D2, spec section 9): a real recovery
scan must correlate an attempt's durable IDs across logs and spans while
never leaking the raw provider job ID anywhere outside the execution
repository. Reuses the ambiguous-cancel-failure scenario proven in
test_realize_pending_cancels.py::test_realize_pending_cancels_moves_an_ambiguous_failure_to_needs_operator
-- the one reachable path in this registry (all profiles are NONE-idempotency
today) where a recovered attempt's ReconcileResult carries a real,
already-accepted provider_job_id -- with a planted canary standing in for a
real secret-like provider job ID."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.host_hardening import ExecutionAttemptRepository, ProjectEventRepository
from r2.contracts.host_hardening import (
    AttemptLeaseFence,
    AttemptSnapshot,
    ExecutionAttemptState,
    PlannedExecutionAttempt,
    ProviderCapabilityProfile,
    ProviderObservation,
    ProviderObservationKind,
    ProviderRouteSnapshot,
)
from r2.host_hardening.provider_capabilities import DEFAULT_REGISTRY_PATH, load_capability_profile
from server.services.execution_attempts import AdapterRegistry
from server.services.execution_recovery_scheduler import ExecutionRecoveryScheduler
from server.telemetry import configure_test_tracer, public_job_ref

type Factory = async_sessionmaker[AsyncSession]

USER = "u1"
PROJECT = "demo"
REAL_NOW = datetime.now(UTC)
CANARY_PROVIDER_JOB_ID = "canary-secret-provider-job-id-do-not-leak-9f3a"

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


class _AmbiguousCancelAdapter:
    """A cancel() that fails with a transport-style error, never
    BackendCapabilityUnsupportedError -- the one adapter outcome that makes
    realize_pending_cancels fold to CANCEL_OUTCOME_UNKNOWN -> NEEDS_OPERATOR
    via reconcile(), carrying the attempt's already-accepted provider_job_id
    forward into the returned ReconcileResult. submit/reconcile/poll are never
    called on this path; they exist only to satisfy ProviderExecutionAdapter."""

    def __init__(self, capability_profile: ProviderCapabilityProfile) -> None:
        self.capability_profile = capability_profile

    async def submit(self, *, attempt: AttemptSnapshot, request: object) -> ProviderObservation:
        raise NotImplementedError

    async def reconcile(self, attempt: AttemptSnapshot) -> ProviderObservation | None:
        raise NotImplementedError

    async def poll(self, attempt: AttemptSnapshot) -> ProviderObservation:
        raise NotImplementedError

    async def cancel(self, attempt: AttemptSnapshot) -> ProviderObservation:
        raise RuntimeError("transport error while calling cancel")


def _capability_resolver(ref: str) -> ProviderCapabilityProfile:
    return load_capability_profile(ref, registry_path=DEFAULT_REGISTRY_PATH)


def _repo(session: AsyncSession) -> ExecutionAttemptRepository:
    return ExecutionAttemptRepository(session, capability_resolver=_capability_resolver)


async def test_ambiguous_cancel_failure_correlates_without_leaking_the_raw_job_id(
    session_factory: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    async with session_factory() as session:
        repo = _repo(session)
        planned = await repo.plan(
            user_id=USER,
            project_name=PROJECT,
            attempt=PlannedExecutionAttempt(
                execution_id="exec-canary",
                task_id="task-canary",
                attempt_no=1,
                request_digest="sha256:" + "b" * 64,
                route=ROUTE,
                client_token="exec-canary",
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
        accepted = await repo.apply_provider_observation(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=submitting.state_version,
            observation=ProviderObservation(
                observation_id="obs-canary",
                kind=ProviderObservationKind.ACCEPTED,
                observed_at=REAL_NOW,
                provider_sequence=None,
                provider_job_id=CANARY_PROVIDER_JOB_ID,
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
            command_id="cancel-canary",
            command_digest="sha256:" + "1" * 64,
        )
        await session.commit()

    exporter = configure_test_tracer()
    adapter_registry: AdapterRegistry = {
        ROUTE.capability_profile_ref: _AmbiguousCancelAdapter(_capability_resolver(ROUTE.capability_profile_ref))
    }
    with caplog.at_level(logging.DEBUG):
        scheduler = ExecutionRecoveryScheduler(session_factory=session_factory, adapter_registry=adapter_registry)
        await scheduler.scan_once()

    async with session_factory() as session:
        durable = await _repo(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-canary")
    assert durable is not None
    assert durable.state is ExecutionAttemptState.NEEDS_OPERATOR

    spans = exporter.get_finished_spans()
    assert spans, "expected at least one span from the recovery scan"

    for span in spans:
        for value in (span.attributes or {}).values():
            assert CANARY_PROVIDER_JOB_ID not in str(value)
    assert CANARY_PROVIDER_JOB_ID not in caplog.text

    cancel_spans = [s for s in spans if s.name == "host_hardening.realize_pending_cancel"]
    assert cancel_spans, "expected a realize_pending_cancel span for the canary attempt"
    matching = [s for s in cancel_spans if (s.attributes or {}).get("execution_id") == "exec-canary"]
    assert matching, "expected the canary execution to be correlated by execution_id"
    span_attributes = matching[0].attributes or {}
    assert span_attributes.get("provider_job_ref") == public_job_ref(CANARY_PROVIDER_JOB_ID)

    async with session_factory() as session:
        events = await ProjectEventRepository(session).replay_after(
            user_id=USER, project_name=PROJECT, cursor=None, limit=100
        )
    assert events, "expected durable project events for this execution"
    for event in events:
        assert CANARY_PROVIDER_JOB_ID not in str(event.public_payload)
