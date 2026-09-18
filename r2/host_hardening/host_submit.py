"""Attempt-bound submission for durable Host queue tasks."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from lib.db.base import utc_now
from lib.video_backends.execution_adapter import BackendExecutionAdapter, BackendExecutionFunctions
from r2.contracts.common import ensure_json_value
from r2.contracts.execution import ProviderRequest
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.host_hardening import (
    AttemptSnapshot,
    PlannedExecutionAttempt,
    ProviderCapabilityProfile,
    ProviderIdempotencyMode,
    ProviderObservation,
    ProviderRouteSnapshot,
)
from r2.host_hardening.ports import ExecutionAttemptRepository, ExecutionAttemptService
from r2.host_hardening.transitions import AttemptIdentityMismatch, validate_exact_replay

type SubmitFn[T] = Callable[[AttemptSnapshot], Awaitable[ProviderSubmitReceipt[T]]]


class UsageExecutionBinder(Protocol):
    async def bind_execution(self, *, call_id: int, execution_id: str) -> None: ...


@dataclass(frozen=True)
class ProviderSubmitReceipt[T]:
    observation: ProviderObservation
    value: T


@dataclass(frozen=True)
class AttemptSubmitResult[T]:
    execution_id: str
    snapshot: AttemptSnapshot
    value: T | None


class AttemptSubmitter:
    def __init__(
        self,
        *,
        repository: ExecutionAttemptRepository,
        service: ExecutionAttemptService,
        capability_resolver: Callable[[str], ProviderCapabilityProfile],
        user_id: str,
        project_name: str,
        usage_binder: UsageExecutionBinder | None = None,
        execution_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._service = service
        self._capability_resolver = capability_resolver
        self._user_id = user_id
        self._project_name = project_name
        self._usage_binder = usage_binder
        self._execution_id_factory = execution_id_factory
        self._clock = clock

    async def submit[T](
        self,
        *,
        task_id: str,
        api_call_id: int | None,
        route: ProviderRouteSnapshot,
        request: ProviderRequest,
        submit: SubmitFn[T],
    ) -> AttemptSubmitResult[T]:
        self._validate_request(task_id=task_id, route=route, request=request)
        capability = self._capability_resolver(route.capability_profile_ref)
        request_value = ensure_json_value(request.model_dump(mode="json"))
        request_digest = "sha256:" + hashlib.sha256(canonical_json_bytes(request_value)).hexdigest()
        existing = await self._repository.get_for_task_attempt(
            user_id=self._user_id,
            project_name=self._project_name,
            task_id=task_id,
            attempt_no=1,
        )
        planned = self._planned_attempt(
            existing=existing,
            task_id=task_id,
            request_digest=request_digest,
            route=route,
            capability=capability,
        )
        if existing is not None:
            validate_exact_replay(
                existing=existing,
                execution_id=planned.execution_id,
                request_digest=planned.request_digest,
                route=planned.route,
                client_token=planned.client_token,
                created_at=planned.created_at,
            )

        captured: ProviderSubmitReceipt[T] | None = None

        async def submit_observation(
            attempt: AttemptSnapshot, provider_request: ProviderRequest
        ) -> ProviderObservation:
            nonlocal captured
            if provider_request != request:
                raise AttemptIdentityMismatch("attempt adapter received a different provider request")
            captured = await submit(attempt)
            return captured.observation

        async def unsupported_poll(_: AttemptSnapshot) -> ProviderObservation:
            raise NotImplementedError("polling is owned by the backend adapter registered for this route")

        adapter = BackendExecutionAdapter(
            capability,
            BackendExecutionFunctions(submit=submit_observation, poll=unsupported_poll),
        )
        snapshot = await self._service.plan_and_submit(
            user_id=self._user_id,
            project_name=self._project_name,
            attempt=planned,
            request=request,
            adapter=adapter,
        )
        if api_call_id is not None and self._usage_binder is not None:
            await self._usage_binder.bind_execution(call_id=api_call_id, execution_id=snapshot.execution_id)
        return AttemptSubmitResult(
            execution_id=snapshot.execution_id,
            snapshot=snapshot,
            value=None if captured is None else captured.value,
        )

    def _planned_attempt(
        self,
        *,
        existing: AttemptSnapshot | None,
        task_id: str,
        request_digest: str,
        route: ProviderRouteSnapshot,
        capability: ProviderCapabilityProfile,
    ) -> PlannedExecutionAttempt:
        execution_id = existing.execution_id if existing is not None else self._execution_id_factory()
        client_token = execution_id if capability.idempotency_mode is ProviderIdempotencyMode.NATIVE_TOKEN else None
        return PlannedExecutionAttempt(
            execution_id=execution_id,
            task_id=task_id,
            attempt_no=1,
            request_digest=request_digest,
            route=route,
            client_token=client_token,
            trace_id_at_creation=None,
            created_at=existing.created_at if existing is not None else self._clock(),
        )

    @staticmethod
    def _validate_request(*, task_id: str, route: ProviderRouteSnapshot, request: ProviderRequest) -> None:
        expected = (
            request.host_task_ref == task_id
            and request.provider == route.provider_id
            and request.model == route.provider_model_id
            and request.adapter_version == route.adapter_version
            and (route.endpoint_id is None or request.endpoint == route.endpoint_id)
        )
        if not expected:
            raise AttemptIdentityMismatch("provider request does not match its durable task route")


__all__ = [
    "AttemptSubmitResult",
    "AttemptSubmitter",
    "ProviderSubmitReceipt",
    "SubmitFn",
    "UsageExecutionBinder",
]
