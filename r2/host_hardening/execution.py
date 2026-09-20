"""Attempt planning, submit classification, and reconciliation policy.

``ExecutionAttemptServiceImpl.plan_and_submit`` reuses the codebase's existing
pre-send/ambiguous-submit classification rather than inventing a parallel one:
``lib.video_backends.base.AmbiguousSubmitError`` already marks exactly the
"request may have reached the provider before this local error occurred"
case (``submit_post``'s own docstring: "请求可能已被服务端处理"), which is
the ``SUBMIT_OUTCOME_UNKNOWN`` trigger. Any other
exception from ``adapter.submit`` -- a definite pre-send transport failure or
a definite provider-side rejection -- means the attempt was never accepted, so
it CASes to ``FAILED_BEFORE_ACCEPTANCE`` instead.

Both ``plan_and_submit`` and ``reconcile`` match the spec's normative
``ExecutionAttemptService`` signatures exactly (ports.py); the repository, a
provider-capability resolver and an adapter resolver (for ``reconcile``, which
receives no adapter argument -- a recovery scan does not already hold one) are
constructor dependencies, mirroring the repository's ``capability_resolver``
pattern.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import uuid4

from lib.db.base import utc_now
from lib.db.repositories.host_hardening import ExecutionAttemptFencingError, ExecutionAttemptRepository
from lib.video_backends.base import AmbiguousSubmitError
from r2.contracts.execution import ProviderRequest
from r2.contracts.host_hardening import (
    AttemptLeaseFence,
    AttemptSnapshot,
    ExecutionAttemptState,
    PlannedExecutionAttempt,
    ProviderCapabilityProfile,
    ProviderIdempotencyMode,
    ProviderObservationKind,
    ProviderRouteSnapshot,
    ReconcileResult,
)
from r2.host_hardening.ports import ProviderExecutionAdapter

DEFAULT_LEASE_TTL_SECONDS = 300
_NEEDS_OPERATOR_NO_SAFE_RECONCILIATION = "no_safe_reconciliation"
_NEEDS_OPERATOR_AMBIGUOUS_LOOKUP = "ambiguous_lookup"
_NEEDS_OPERATOR_NOT_FOUND_NOT_AUTHORITATIVE = "not_found_not_authoritative"
_NEEDS_OPERATOR_CONFLICTING_FACT = "conflicting_terminal_fact"

# H5 recovery scan (M7-C): a worker that dies mid-flight leaves its attempt
# SUBMITTING with a lease that will expire and never be renewed. The outcome is
# unknown either way -- the network call may or may not have reached the
# provider -- so it maps to its existing *_OUTCOME_UNKNOWN state, never
# straight to a terminal one.
#
# CANCEL_REQUESTED is deliberately NOT here. Unlike SUBMITTING (always entered
# by transition_worker under a live worker lease that then expires if that
# worker dies before finishing its own provider call), CANCEL_REQUESTED's only
# production writer is request_cancel -- an unfenced, external cancel-intent
# authority (lib.db.repositories.host_hardening) that never attempts a provider
# call and never touches the lease at all. Treating its (always-stale, since
# nothing ever renews it) lease as "a worker died mid-call" would fold it
# straight to CANCEL_OUTCOME_UNKNOWN without ever actually calling the
# provider's cancel endpoint. Realizing a fresh cancel intent -- calling
# adapter.cancel() for the first time -- is a distinct operation from
# reconciling an ambiguous one, and belongs to the recovery poller (a later
# task), not this state-remap table.
RECOVERABLE_EXPIRED_STATES: dict[ExecutionAttemptState, ExecutionAttemptState] = {
    ExecutionAttemptState.SUBMITTING: ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN,
}


class ExecutionAttemptNotFoundError(LookupError):
    """``reconcile`` was asked about an execution_id with no attempt in scope."""


def _default_owner_id() -> str:
    return f"exec-svc:{uuid4().hex}"


async def _no_commit() -> None:
    return None


class ExecutionAttemptServiceImpl:
    def __init__(
        self,
        repository: ExecutionAttemptRepository,
        *,
        capability_resolver: Callable[[str], ProviderCapabilityProfile],
        adapter_resolver: Callable[[ProviderRouteSnapshot], ProviderExecutionAdapter],
        owner_id_factory: Callable[[], str] = _default_owner_id,
        lease_ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
        commit: Callable[[], Awaitable[None]] = _no_commit,
    ) -> None:
        self._repository = repository
        self._capability_resolver = capability_resolver
        self._adapter_resolver = adapter_resolver
        self._owner_id_factory = owner_id_factory
        self._lease_ttl_seconds = lease_ttl_seconds
        self._commit = commit

    async def _acquire_fence(
        self, *, user_id: str, project_name: str, execution_id: str, expected_version: int
    ) -> tuple[AttemptSnapshot, AttemptLeaseFence]:
        owner = self._owner_id_factory()
        leased = await self._repository.acquire_lease(
            user_id=user_id,
            project_name=project_name,
            execution_id=execution_id,
            expected_version=expected_version,
            owner=owner,
            expires_at=utc_now() + timedelta(seconds=self._lease_ttl_seconds),
        )
        await self._commit()
        return leased, AttemptLeaseFence(owner=owner, token=leased.lease_token or 0)

    async def plan_and_submit(
        self,
        *,
        user_id: str,
        project_name: str,
        attempt: PlannedExecutionAttempt,
        request: ProviderRequest,
        adapter: ProviderExecutionAdapter,
    ) -> AttemptSnapshot:
        snapshot = await self._repository.plan(user_id=user_id, project_name=project_name, attempt=attempt)
        await self._commit()
        if snapshot.state is not ExecutionAttemptState.PLANNED:
            # Exact replay of an attempt that already progressed past planning
            # (a prior call submitted it, or a crash resumed here): idempotent,
            # never a second submit. The caller should reconcile, not resubmit.
            return snapshot

        leased, fence = await self._acquire_fence(
            user_id=user_id,
            project_name=project_name,
            execution_id=snapshot.execution_id,
            expected_version=snapshot.state_version,
        )
        submitting = await self._repository.transition_worker(
            user_id=user_id,
            project_name=project_name,
            execution_id=snapshot.execution_id,
            expected_version=leased.state_version,
            expected_states=frozenset({ExecutionAttemptState.PLANNED}),
            new_state=ExecutionAttemptState.SUBMITTING,
            fence=fence,
        )
        await self._commit()

        try:
            observation = await adapter.submit(attempt=submitting, request=request)
        except AmbiguousSubmitError:
            unknown = await self._repository.transition_worker(
                user_id=user_id,
                project_name=project_name,
                execution_id=snapshot.execution_id,
                expected_version=submitting.state_version,
                expected_states=frozenset({ExecutionAttemptState.SUBMITTING}),
                new_state=ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN,
                fence=fence,
            )
            await self._commit()
            return unknown
        except Exception:
            failed = await self._repository.transition_worker(
                user_id=user_id,
                project_name=project_name,
                execution_id=snapshot.execution_id,
                expected_version=submitting.state_version,
                expected_states=frozenset({ExecutionAttemptState.SUBMITTING}),
                new_state=ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE,
                fence=fence,
            )
            await self._commit()
            return failed

        accepted = await self._repository.apply_provider_observation(
            user_id=user_id,
            project_name=project_name,
            execution_id=snapshot.execution_id,
            expected_version=submitting.state_version,
            observation=observation,
        )
        await self._commit()
        return accepted

    async def reconcile(self, *, user_id: str, project_name: str, execution_id: str) -> ReconcileResult:
        snapshot = await self._repository.get_exact(
            user_id=user_id, project_name=project_name, execution_id=execution_id
        )
        if snapshot is None:
            raise ExecutionAttemptNotFoundError(f"no execution attempt {execution_id!r} in scope")

        if snapshot.state not in (
            ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN,
            ExecutionAttemptState.CANCEL_OUTCOME_UNKNOWN,
        ):
            # Nothing to reconcile: already resolved, or never entered an unknown
            # state. Idempotent no-op so a recovery scan may call this freely.
            return ReconcileResult(
                execution_id=execution_id,
                state=snapshot.state,
                provider_job_id=snapshot.provider_job_id,
                operator_reason=None,
            )

        capability = self._capability_resolver(snapshot.route.capability_profile_ref)

        if capability.idempotency_mode is ProviderIdempotencyMode.NONE:
            return await self._pause_for_operator(
                user_id=user_id,
                project_name=project_name,
                snapshot=snapshot,
                reason_code=_NEEDS_OPERATOR_NO_SAFE_RECONCILIATION,
            )

        adapter = self._adapter_resolver(snapshot.route)
        observation = await adapter.reconcile(snapshot)
        if observation is None:
            # No safe lookup (e.g. zero/multiple ambiguous matches): fail closed
            # to an operator pause rather than guessing.
            return await self._pause_for_operator(
                user_id=user_id,
                project_name=project_name,
                snapshot=snapshot,
                reason_code=_NEEDS_OPERATOR_AMBIGUOUS_LOOKUP,
            )

        resolved = await self._repository.apply_provider_observation(
            user_id=user_id,
            project_name=project_name,
            execution_id=execution_id,
            expected_version=snapshot.state_version,
            observation=observation,
        )
        await self._commit()
        operator_reason = None
        if resolved.state is ExecutionAttemptState.NEEDS_OPERATOR:
            # fold_observation itself chose NEEDS_OPERATOR: a non-authoritative
            # NOT_FOUND after the settling window, or a conflicting terminal fact.
            # Distinct from the adapter returning None above (no safe lookup at all).
            operator_reason = (
                _NEEDS_OPERATOR_NOT_FOUND_NOT_AUTHORITATIVE
                if observation.kind is ProviderObservationKind.NOT_FOUND
                else _NEEDS_OPERATOR_CONFLICTING_FACT
            )
        return ReconcileResult(
            execution_id=execution_id,
            state=resolved.state,
            provider_job_id=resolved.provider_job_id,
            operator_reason=operator_reason,
        )

    async def _pause_for_operator(
        self, *, user_id: str, project_name: str, snapshot: AttemptSnapshot, reason_code: str
    ) -> ReconcileResult:
        _leased, fence = await self._acquire_fence(
            user_id=user_id,
            project_name=project_name,
            execution_id=snapshot.execution_id,
            expected_version=snapshot.state_version,
        )
        result = await self._repository.transition_worker(
            user_id=user_id,
            project_name=project_name,
            execution_id=snapshot.execution_id,
            expected_version=_leased.state_version,
            expected_states=frozenset({snapshot.state}),
            new_state=ExecutionAttemptState.NEEDS_OPERATOR,
            fence=fence,
            reason_code=reason_code,
        )
        await self._commit()
        return ReconcileResult(
            execution_id=snapshot.execution_id,
            state=result.state,
            provider_job_id=result.provider_job_id,
            operator_reason=reason_code,
        )

    async def reconcile_expired(self, *, before: datetime | None = None, limit: int = 100) -> list[ReconcileResult]:
        """H5 recovery scan: find every attempt whose worker died mid-flight --
        lease expired while still ``SUBMITTING`` -- reclaim each one's lease
        under a fresh scanner-owned fence, transition it to
        ``SUBMIT_OUTCOME_UNKNOWN``, then hand it to the existing
        :meth:`reconcile` qualified-lookup path.

        A candidate whose lease another worker or scanner already reclaimed
        (a fencing race, since the exact same query can return the same row to
        two concurrent scans) is skipped, not retried -- whoever holds the
        lease now owns resolving it, and re-attempting here would just lose the
        fence again.
        """
        cutoff = before or utc_now()
        candidates = await self._repository.list_lease_expired(
            states=frozenset(RECOVERABLE_EXPIRED_STATES), before=cutoff, limit=limit
        )
        results: list[ReconcileResult] = []
        for user_id, project_name, snapshot in candidates:
            target_state = RECOVERABLE_EXPIRED_STATES[snapshot.state]
            try:
                leased, fence = await self._acquire_fence(
                    user_id=user_id,
                    project_name=project_name,
                    execution_id=snapshot.execution_id,
                    expected_version=snapshot.state_version,
                )
            except ExecutionAttemptFencingError:
                continue
            try:
                unknown = await self._repository.transition_worker(
                    user_id=user_id,
                    project_name=project_name,
                    execution_id=snapshot.execution_id,
                    expected_version=leased.state_version,
                    expected_states=frozenset({snapshot.state}),
                    new_state=target_state,
                    fence=fence,
                )
                # reconcile() below acquires its own fresh fence under a new
                # owner id; releasing this one first is what makes that
                # acquisition see an unheld lease instead of racing its own
                # still-live 300s lease under a different owner.
                released = await self._repository.release_lease(
                    user_id=user_id,
                    project_name=project_name,
                    execution_id=unknown.execution_id,
                    expected_version=unknown.state_version,
                    fence=fence,
                )
                await self._commit()
            except ExecutionAttemptFencingError:
                continue
            results.append(
                await self.reconcile(user_id=user_id, project_name=project_name, execution_id=released.execution_id)
            )
        return results


__all__ = [
    "DEFAULT_LEASE_TTL_SECONDS",
    "RECOVERABLE_EXPIRED_STATES",
    "ExecutionAttemptNotFoundError",
    "ExecutionAttemptServiceImpl",
]
