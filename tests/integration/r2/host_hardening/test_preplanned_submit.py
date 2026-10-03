"""A durably preplanned M7 attempt can enter the existing exact submit path."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.host_hardening import ExecutionAttemptRepository
from r2.contracts.execution import ProviderRequest
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.host_hardening import (
    ExecutionAttemptState,
    PlannedExecutionAttempt,
    ProviderObservation,
    ProviderObservationKind,
    ProviderRouteSnapshot,
)
from r2.host_hardening.execution import ExecutionAttemptServiceImpl
from r2.host_hardening.host_submit import AttemptSubmitter, ProviderSubmitReceipt
from r2.host_hardening.provider_capabilities import DEFAULT_REGISTRY_PATH, load_capability_profile
from r2.host_hardening.transitions import AttemptIdentityMismatch

type Factory = async_sessionmaker[AsyncSession]

USER = "u1"
PROJECT = "demo"
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
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
REQUEST = ProviderRequest(
    id="task-m8c:video-submit",
    host_task_ref="task-m8c",
    provider=ROUTE.provider_id,
    model=ROUTE.provider_model_id,
    endpoint=ROUTE.endpoint_id or "videos.text2video",
    payload={"prompt": "room corner", "duration_seconds": 5},
    execution_options={"r2_spatial": {"schema_version": "1", "binding_snapshot_digest": "sha256:" + "a" * 64}},
    adapter_version=ROUTE.adapter_version,
)


def _capability(ref: str):
    return load_capability_profile(ref, registry_path=DEFAULT_REGISTRY_PATH)


def _request_digest(request: ProviderRequest) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(request.model_dump(mode="json"))).hexdigest()


async def test_preplanned_attempt_resumes_through_existing_submitter_once(session_factory: Factory) -> None:
    planned = PlannedExecutionAttempt(
        execution_id="execution-m8c",
        task_id="task-m8c",
        attempt_no=1,
        request_digest=_request_digest(REQUEST),
        route=ROUTE,
        client_token=None,
        trace_id_at_creation=None,
        created_at=NOW,
    )
    async with session_factory() as session:
        repository = ExecutionAttemptRepository(session, capability_resolver=_capability)
        staged = await repository.plan(user_id=USER, project_name=PROJECT, attempt=planned)
        assert staged.state is ExecutionAttemptState.PLANNED
        await session.commit()

    submitted = 0

    async def provider_submit(_attempt) -> ProviderSubmitReceipt[str]:
        nonlocal submitted
        submitted += 1
        return ProviderSubmitReceipt(
            observation=ProviderObservation(
                observation_id="observation-m8c",
                kind=ProviderObservationKind.ACCEPTED,
                observed_at=NOW,
                provider_job_id="remote-m8c",
                evidence_digest="sha256:" + "b" * 64,
            ),
            value="remote-m8c",
        )

    async with session_factory() as session:
        repository = ExecutionAttemptRepository(session, capability_resolver=_capability)
        service = ExecutionAttemptServiceImpl(
            repository, capability_resolver=_capability, adapter_resolver=lambda _route: None, commit=session.commit
        )
        submitter = AttemptSubmitter(
            repository=repository,
            service=service,
            capability_resolver=_capability,
            user_id=USER,
            project_name=PROJECT,
        )
        changed_request = REQUEST.model_copy(update={"payload": {"prompt": "different room", "duration_seconds": 5}})
        with pytest.raises(AttemptIdentityMismatch):
            await submitter.submit(
                task_id="task-m8c", api_call_id=None, route=ROUTE, request=changed_request, submit=provider_submit
            )
        assert submitted == 0
        first = await submitter.submit(
            task_id="task-m8c", api_call_id=None, route=ROUTE, request=REQUEST, submit=provider_submit
        )
        replay = await submitter.submit(
            task_id="task-m8c", api_call_id=None, route=ROUTE, request=REQUEST, submit=provider_submit
        )

    assert first.execution_id == replay.execution_id == planned.execution_id
    assert first.value == "remote-m8c"
    assert replay.value is None
    assert submitted == 1
