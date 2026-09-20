"""Structural ports for the execution-identity and idempotency layer.

These pure ``Protocol`` seams import only host-hardening contracts, never a
concrete repository, session, ORM row, or clock.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from r2.contracts.execution import ProviderRequest
from r2.contracts.host_hardening import (
    AttemptLeaseFence,
    AttemptSnapshot,
    CommandReceipt,
    ExecutionAttemptState,
    MasterHeadSnapshot,
    OperatorResolutionReceipt,
    PlannedExecutionAttempt,
    PromotionReceipt,
    ProviderCapabilityProfile,
    ProviderObservation,
    ReconcileResult,
    VerifiedCandidateObject,
)


@runtime_checkable
class ExecutionAttemptRepository(Protocol):
    async def plan(self, *, user_id: str, project_name: str, attempt: PlannedExecutionAttempt) -> AttemptSnapshot: ...

    async def get_exact(self, *, user_id: str, project_name: str, execution_id: str) -> AttemptSnapshot | None: ...

    async def get_for_task_attempt(
        self,
        *,
        user_id: str,
        project_name: str,
        task_id: str,
        attempt_no: int,
    ) -> AttemptSnapshot | None: ...

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
    ) -> AttemptSnapshot: ...

    async def apply_provider_observation(
        self,
        *,
        user_id: str,
        project_name: str,
        execution_id: str,
        expected_version: int,
        observation: ProviderObservation,
    ) -> AttemptSnapshot: ...

    async def resolve_operator_review(
        self,
        *,
        user_id: str,
        project_name: str,
        execution_id: str,
        expected_version: int,
        receipt: OperatorResolutionReceipt,
    ) -> AttemptSnapshot: ...

    async def acquire_lease(
        self,
        *,
        user_id: str,
        project_name: str,
        execution_id: str,
        expected_version: int,
        owner: str,
        expires_at: datetime,
        force: bool = False,
    ) -> AttemptSnapshot: ...

    async def release_lease(
        self,
        *,
        user_id: str,
        project_name: str,
        execution_id: str,
        expected_version: int,
        fence: AttemptLeaseFence,
    ) -> AttemptSnapshot: ...

    async def list_lease_expired(
        self, *, states: frozenset[ExecutionAttemptState], before: datetime, limit: int = 100
    ) -> list[tuple[str, str, AttemptSnapshot]]: ...

    async def list_pending_cancels(self, *, limit: int = 100) -> list[tuple[str, str, AttemptSnapshot]]: ...

    async def request_cancel(
        self,
        *,
        user_id: str,
        project_name: str,
        execution_id: str,
        expected_version: int,
        actor_scope: str,
        command_id: str,
        command_digest: str,
    ) -> AttemptSnapshot: ...


@runtime_checkable
class CommandReceiptRepository(Protocol):
    async def get_exact(
        self, *, user_id: str, project_name: str, actor_scope: str, command_id: str
    ) -> CommandReceipt | None: ...

    async def add(self, *, user_id: str, project_name: str, receipt: CommandReceipt) -> None: ...


@runtime_checkable
class ProviderExecutionAdapter(Protocol):
    capability_profile: ProviderCapabilityProfile

    async def submit(self, *, attempt: AttemptSnapshot, request: ProviderRequest) -> ProviderObservation: ...

    async def reconcile(self, attempt: AttemptSnapshot) -> ProviderObservation | None: ...

    async def poll(self, attempt: AttemptSnapshot) -> ProviderObservation: ...

    async def cancel(self, attempt: AttemptSnapshot) -> ProviderObservation: ...


@runtime_checkable
class ExecutionAttemptService(Protocol):
    async def plan_and_submit(
        self,
        *,
        user_id: str,
        project_name: str,
        attempt: PlannedExecutionAttempt,
        request: ProviderRequest,
        adapter: ProviderExecutionAdapter,
    ) -> AttemptSnapshot: ...

    async def reconcile(self, *, user_id: str, project_name: str, execution_id: str) -> ReconcileResult: ...


# --- H3-H4 candidate retention: one protocol per protected reference kind ------------
# B2 supplies the real PostgreSQL-backed implementations once the master-head,
# attempt, receipt and backup-set tables exist; B1 wires the shared guard against
# these pure seams so its fault behavior is provable with fakes today.


@runtime_checkable
class MasterHeadReferenceCheck(Protocol):
    async def references_candidate(self, *, user_id: str, project_name: str, candidate_id: str) -> bool: ...


@runtime_checkable
class ActiveAttemptReferenceCheck(Protocol):
    async def has_active_attempt_for_candidate(self, *, user_id: str, project_name: str, candidate_id: str) -> bool: ...


@runtime_checkable
class RetainedReceiptReferenceCheck(Protocol):
    async def has_retained_receipt_for_candidate(
        self, *, user_id: str, project_name: str, candidate_id: str
    ) -> bool: ...


@runtime_checkable
class IncompleteBackupReferenceCheck(Protocol):
    async def has_incomplete_backup_referencing(
        self, *, user_id: str, project_name: str, candidate_id: str
    ) -> bool: ...


# --- H3-H4 atomic master promotion (B3) ------------------------------------------------


@runtime_checkable
class CandidateObjectPort(Protocol):
    async def get_exact(
        self, *, user_id: str, project_name: str, candidate_id: str
    ) -> VerifiedCandidateObject | None: ...


@runtime_checkable
class MasterAuthorityPort(Protocol):
    async def get_current(self, *, user_id: str, project_name: str, artifact_key: str) -> MasterHeadSnapshot | None: ...

    async def get_current_version(self, *, user_id: str, project_name: str, artifact_key: str) -> int: ...

    async def insert_head_version(
        self,
        *,
        user_id: str,
        project_name: str,
        master_head_version_id: str,
        snapshot: MasterHeadSnapshot,
        promoted_at: datetime,
    ) -> None: ...

    async def advance_head(
        self, *, user_id: str, project_name: str, artifact_key: str, expected_current_version: int, new_version: int
    ) -> None: ...

    async def append_promoted_event(self, *, user_id: str, project_name: str, snapshot: MasterHeadSnapshot) -> None: ...


@runtime_checkable
class PromotionReceiptPort(Protocol):
    async def get_exact(
        self, *, user_id: str, project_name: str, artifact_key: str, command_id: str
    ) -> PromotionReceipt | None: ...

    async def add(self, *, user_id: str, project_name: str, receipt: PromotionReceipt) -> None: ...


@runtime_checkable
class MasterResolver(Protocol):
    async def get_exact(self, *, user_id: str, project_name: str, artifact_key: str) -> MasterHeadSnapshot | None: ...


__all__ = [
    "ActiveAttemptReferenceCheck",
    "CandidateObjectPort",
    "CommandReceiptRepository",
    "ExecutionAttemptRepository",
    "ExecutionAttemptService",
    "IncompleteBackupReferenceCheck",
    "MasterAuthorityPort",
    "MasterHeadReferenceCheck",
    "MasterResolver",
    "PromotionReceiptPort",
    "ProviderExecutionAdapter",
    "RetainedReceiptReferenceCheck",
]
