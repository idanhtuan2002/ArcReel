"""Scoped, fenced adapter for the execution-attempt authority.

Three separate write authorities isolate worker transitions from provider facts
and operator decisions. Worker
transitions (``transition_worker``) require an unexpired owner/token lease
fence; provider observations (``apply_provider_observation``) and operator
resolutions (``resolve_operator_review``) each write through their own method
and never consult the worker lease -- a dead worker lease cannot block a real
provider fact or an operator's decision from landing. Every state-changing
method commits its attempt row, its own evidence row (observation/receipt) and
one ``ProjectEvent`` row in the same transaction, or writes nothing (a fenced
``UPDATE`` affecting zero rows raises before any evidence is added).

``state_version`` is the row's single optimistic-concurrency counter: it
advances on every accepted mutation of this row, including a lease
acquire/release that does not itself change ``state`` -- "every attempt
mutation advances one counter for the whole row, not one counter per field.

``apply_provider_observation`` takes no ``ProviderCapabilityProfile``;
``fold_observation`` needs one
only to resolve ``NOT_FOUND``'s settling-window policy, and the qualified
provider capability registry owns that policy. This repository therefore takes
a ``capability_resolver`` constructor
dependency (``Callable[[str], ProviderCapabilityProfile]``, keyed by the
attempt's own ``route.capability_profile_ref``) rather than importing a
registry directly.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.base import utc_now
from lib.db.models.host_hardening import (
    CommandReceiptModel,
    ExecutionAttemptModel,
    OperatorResolutionReceiptModel,
    ProjectEventModel,
    ProviderObservationModel,
)
from lib.db.repositories.base import rowcount
from r2.contracts.host_hardening import (
    TERMINAL_ATTEMPT_STATES,
    AttemptLeaseFence,
    AttemptSnapshot,
    CommandReceipt,
    ExecutionAttemptState,
    OperatorResolutionReceipt,
    PersistedProviderObservation,
    PlannedExecutionAttempt,
    ProjectEventType,
    ProviderCapabilityProfile,
    ProviderObservation,
    ProviderRouteSnapshot,
)
from r2.host_hardening.transitions import fold_observation, is_legal_transition, validate_exact_replay


class ExecutionAttemptIntegrityError(RuntimeError):
    """A row this repository just wrote vanished within the same transaction."""


class ExecutionAttemptFencingError(RuntimeError):
    """A fenced attempt mutation lost its expected_version/lease/state CAS."""


class ExecutionAttemptTransitionError(ValueError):
    """A requested worker transition or operator resolution is not a legal edge."""


def _stored_aware(value: datetime) -> datetime:
    """SQLite does not reliably round-trip ``tzinfo`` through ``DateTime(timezone=True)``;
    every stored timestamp here is UTC by construction, so a naive read is UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _stored_aware_or_none(value: datetime | None) -> datetime | None:
    return None if value is None else _stored_aware(value)


def _snapshot_from_row(row: ExecutionAttemptModel) -> AttemptSnapshot:
    return AttemptSnapshot(
        execution_id=row.execution_id,
        task_id=row.task_id,
        attempt_no=row.attempt_no,
        request_digest=row.request_digest,
        route=ProviderRouteSnapshot(**row.route_json),
        client_token=row.client_token,
        provider_job_id=row.provider_job_id,
        state=ExecutionAttemptState(row.state),
        state_version=row.state_version,
        lease_owner=row.lease_owner,
        lease_token=row.lease_token,
        lease_expires_at=_stored_aware_or_none(row.lease_expires_at),
        created_at=_stored_aware(row.created_at),
        updated_at=_stored_aware(row.updated_at),
        submitted_at=_stored_aware_or_none(row.submitted_at),
        last_observed_at=_stored_aware_or_none(row.last_observed_at),
        terminal_at=_stored_aware_or_none(row.terminal_at),
    )


class ExecutionAttemptRepository:
    def __init__(
        self, session: AsyncSession, *, capability_resolver: Callable[[str], ProviderCapabilityProfile]
    ) -> None:
        self.session = session
        self._capability_resolver = capability_resolver

    async def _scalar(self, stmt: Any) -> Any:
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def _insert(self, table_class: type) -> Any:
        return (
            pg_insert(table_class)
            if self.session.get_bind().dialect.name == "postgresql"
            else sqlite_insert(table_class)
        )

    async def _require_snapshot(self, *, user_id: str, project_name: str, execution_id: str) -> AttemptSnapshot:
        row = await self._scalar(
            select(ExecutionAttemptModel).where(
                ExecutionAttemptModel.user_id == user_id,
                ExecutionAttemptModel.project_name == project_name,
                ExecutionAttemptModel.execution_id == execution_id,
            )
        )
        if row is None:
            raise ExecutionAttemptIntegrityError(f"execution {execution_id!r} vanished mid-transaction")
        return _snapshot_from_row(row)

    async def _append_project_event(self, snapshot: AttemptSnapshot, *, user_id: str, project_name: str) -> None:
        self.session.add(
            ProjectEventModel(
                user_id=user_id,
                project_name=project_name,
                task_id=snapshot.task_id,
                execution_id=snapshot.execution_id,
                event_type=ProjectEventType.ATTEMPT_TRANSITIONED.value,
                state_version=snapshot.state_version,
                public_payload_json={
                    "execution_id": snapshot.execution_id,
                    "task_id": snapshot.task_id,
                    "state": snapshot.state.value,
                },
                payload_schema_version=1,
                dedupe_key=f"attempt:{snapshot.execution_id}:{snapshot.state_version}",
            )
        )
        await self.session.flush()

    # --- plan() / get_exact() -----------------------------------------------------

    async def plan(self, *, user_id: str, project_name: str, attempt: PlannedExecutionAttempt) -> AttemptSnapshot:
        stmt = self._insert(ExecutionAttemptModel).values(
            user_id=user_id,
            project_name=project_name,
            execution_id=attempt.execution_id,
            task_id=attempt.task_id,
            attempt_no=attempt.attempt_no,
            request_digest=attempt.request_digest,
            route_json=attempt.route.model_dump(mode="json"),
            client_token=attempt.client_token,
            trace_id_at_creation=attempt.trace_id_at_creation,
            provider_job_id=None,
            state=ExecutionAttemptState.PLANNED.value,
            state_version=1,
            created_at=attempt.created_at,
            updated_at=attempt.created_at,
            terminal_at=None,
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["user_id", "project_name", "task_id", "attempt_no"])
        await self.session.execute(stmt)

        row = await self._scalar(
            select(ExecutionAttemptModel)
            .where(
                ExecutionAttemptModel.user_id == user_id,
                ExecutionAttemptModel.project_name == project_name,
                ExecutionAttemptModel.task_id == attempt.task_id,
                ExecutionAttemptModel.attempt_no == attempt.attempt_no,
            )
            .with_for_update()
        )
        if row is None:
            raise ExecutionAttemptIntegrityError(
                f"execution attempt for task {attempt.task_id!r} attempt {attempt.attempt_no} "
                "vanished immediately after insert"
            )
        snapshot = _snapshot_from_row(row)
        validate_exact_replay(
            existing=snapshot,
            execution_id=attempt.execution_id,
            request_digest=attempt.request_digest,
            route=attempt.route,
            client_token=attempt.client_token,
            created_at=attempt.created_at,
        )
        return snapshot

    async def get_exact(self, *, user_id: str, project_name: str, execution_id: str) -> AttemptSnapshot | None:
        row = await self._scalar(
            select(ExecutionAttemptModel).where(
                ExecutionAttemptModel.user_id == user_id,
                ExecutionAttemptModel.project_name == project_name,
                ExecutionAttemptModel.execution_id == execution_id,
            )
        )
        return None if row is None else _snapshot_from_row(row)

    # --- worker authority -----------------------------------------------------------

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
        del reason_code  # not yet persisted anywhere; accepted for signature parity
        if not any(is_legal_transition(state, new_state) for state in expected_states):
            raise ExecutionAttemptTransitionError(
                f"{new_state} is not a legal edge from any of {sorted(s.value for s in expected_states)}"
            )
        now = utc_now()
        values: dict[str, object] = {
            "state": new_state.value,
            "state_version": expected_version + 1,
            "updated_at": now,
        }
        if new_state is ExecutionAttemptState.SUBMITTING:
            values["submitted_at"] = func.coalesce(ExecutionAttemptModel.submitted_at, now)
        values["terminal_at"] = now if new_state in TERMINAL_ATTEMPT_STATES else None

        result = await self.session.execute(
            update(ExecutionAttemptModel)
            .where(
                ExecutionAttemptModel.user_id == user_id,
                ExecutionAttemptModel.project_name == project_name,
                ExecutionAttemptModel.execution_id == execution_id,
                ExecutionAttemptModel.state_version == expected_version,
                ExecutionAttemptModel.state.in_([state.value for state in expected_states]),
                ExecutionAttemptModel.lease_owner == fence.owner,
                ExecutionAttemptModel.lease_token == fence.token,
                ExecutionAttemptModel.lease_expires_at.is_not(None),
                ExecutionAttemptModel.lease_expires_at > now,
            )
            .values(**values)
        )
        if rowcount(result) != 1:
            raise ExecutionAttemptFencingError(
                f"transition_worker lost its fence for execution {execution_id!r}: "
                f"expected_version={expected_version}, owner={fence.owner!r}, token={fence.token}"
            )
        snapshot = await self._require_snapshot(user_id=user_id, project_name=project_name, execution_id=execution_id)
        await self._append_project_event(snapshot, user_id=user_id, project_name=project_name)
        return snapshot

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
        now = utc_now()
        result = await self.session.execute(
            update(ExecutionAttemptModel)
            .where(
                ExecutionAttemptModel.user_id == user_id,
                ExecutionAttemptModel.project_name == project_name,
                ExecutionAttemptModel.execution_id == execution_id,
                ExecutionAttemptModel.state_version == expected_version,
                or_(
                    ExecutionAttemptModel.lease_owner.is_(None),
                    ExecutionAttemptModel.lease_owner == owner,
                    ExecutionAttemptModel.lease_expires_at.is_(None),
                    ExecutionAttemptModel.lease_expires_at <= now,
                ),
            )
            .values(
                state_version=expected_version + 1,
                lease_owner=owner,
                lease_token=func.coalesce(ExecutionAttemptModel.lease_token, 0) + 1,
                lease_expires_at=expires_at,
                updated_at=now,
            )
        )
        if rowcount(result) != 1:
            raise ExecutionAttemptFencingError(
                f"acquire_lease lost its fence for execution {execution_id!r}: "
                f"expected_version={expected_version}, owner={owner!r} (held by another live owner?)"
            )
        return await self._require_snapshot(user_id=user_id, project_name=project_name, execution_id=execution_id)

    async def release_lease(
        self,
        *,
        user_id: str,
        project_name: str,
        execution_id: str,
        expected_version: int,
        fence: AttemptLeaseFence,
    ) -> AttemptSnapshot:
        now = utc_now()
        result = await self.session.execute(
            update(ExecutionAttemptModel)
            .where(
                ExecutionAttemptModel.user_id == user_id,
                ExecutionAttemptModel.project_name == project_name,
                ExecutionAttemptModel.execution_id == execution_id,
                ExecutionAttemptModel.state_version == expected_version,
                ExecutionAttemptModel.lease_owner == fence.owner,
                ExecutionAttemptModel.lease_token == fence.token,
            )
            .values(
                state_version=expected_version + 1,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                updated_at=now,
            )
        )
        if rowcount(result) != 1:
            raise ExecutionAttemptFencingError(
                f"release_lease lost its fence for execution {execution_id!r}: "
                f"expected_version={expected_version}, owner={fence.owner!r}, token={fence.token}"
            )
        return await self._require_snapshot(user_id=user_id, project_name=project_name, execution_id=execution_id)

    # --- provider-observation authority ----------------------------------------------

    async def apply_provider_observation(
        self,
        *,
        user_id: str,
        project_name: str,
        execution_id: str,
        expected_version: int,
        observation: ProviderObservation,
    ) -> AttemptSnapshot:
        row = await self._scalar(
            select(ExecutionAttemptModel)
            .where(
                ExecutionAttemptModel.user_id == user_id,
                ExecutionAttemptModel.project_name == project_name,
                ExecutionAttemptModel.execution_id == execution_id,
                ExecutionAttemptModel.state_version == expected_version,
            )
            .with_for_update()
        )
        if row is None:
            raise ExecutionAttemptFencingError(
                f"apply_provider_observation: execution {execution_id!r} is not at expected_version={expected_version}"
            )
        snapshot = _snapshot_from_row(row)

        existing = await self._scalar(
            select(ProviderObservationModel).where(
                ProviderObservationModel.execution_id == execution_id,
                ProviderObservationModel.observation_id == observation.observation_id,
            )
        )
        if existing is not None:
            return snapshot  # A duplicate observation_id is an idempotent no-op.

        next_seq = (
            await self.session.execute(
                select(func.coalesce(func.max(ProviderObservationModel.received_seq), 0)).where(
                    ProviderObservationModel.execution_id == execution_id
                )
            )
        ).scalar_one() + 1
        received_at = utc_now()
        persisted = PersistedProviderObservation(
            observation=observation, received_seq=next_seq, received_at=received_at
        )

        self.session.add(
            ProviderObservationModel(
                user_id=user_id,
                project_name=project_name,
                execution_id=execution_id,
                received_seq=next_seq,
                observation_id=observation.observation_id,
                kind=observation.kind.value,
                observed_at=observation.observed_at,
                provider_sequence=observation.provider_sequence,
                provider_job_id=observation.provider_job_id,
                reason_code=observation.reason_code,
                evidence_digest=observation.evidence_digest,
                received_at=received_at,
            )
        )
        await self.session.flush()

        capability = self._capability_resolver(snapshot.route.capability_profile_ref)
        folded = fold_observation(snapshot, persisted, capability)

        if folded.state == snapshot.state and folded.provider_job_id == snapshot.provider_job_id:
            # A genuine no-op fold (out-of-order/backwards/still-unknown fact): the
            # observation evidence is still appended above; the attempt row is not.
            return snapshot

        result = await self.session.execute(
            update(ExecutionAttemptModel)
            .where(
                ExecutionAttemptModel.user_id == user_id,
                ExecutionAttemptModel.project_name == project_name,
                ExecutionAttemptModel.execution_id == execution_id,
                ExecutionAttemptModel.state_version == expected_version,
            )
            .values(
                state=folded.state.value,
                state_version=expected_version + 1,
                provider_job_id=folded.provider_job_id,
                last_observed_at=folded.last_observed_at,
                terminal_at=folded.terminal_at,
                updated_at=folded.updated_at,
            )
        )
        if rowcount(result) != 1:
            raise ExecutionAttemptFencingError(
                f"apply_provider_observation lost its fence for execution {execution_id!r} "
                f"despite holding its row lock -- expected_version={expected_version}"
            )
        new_snapshot = await self._require_snapshot(
            user_id=user_id, project_name=project_name, execution_id=execution_id
        )
        await self._append_project_event(new_snapshot, user_id=user_id, project_name=project_name)
        return new_snapshot

    # --- operator authority -----------------------------------------------------------

    async def resolve_operator_review(
        self,
        *,
        user_id: str,
        project_name: str,
        execution_id: str,
        expected_version: int,
        receipt: OperatorResolutionReceipt,
    ) -> AttemptSnapshot:
        row = await self._scalar(
            select(ExecutionAttemptModel)
            .where(
                ExecutionAttemptModel.user_id == user_id,
                ExecutionAttemptModel.project_name == project_name,
                ExecutionAttemptModel.execution_id == execution_id,
                ExecutionAttemptModel.state_version == expected_version,
            )
            .with_for_update()
        )
        if row is None:
            raise ExecutionAttemptFencingError(
                f"resolve_operator_review: execution {execution_id!r} is not at expected_version={expected_version}"
            )
        snapshot = _snapshot_from_row(row)
        if snapshot.state is not ExecutionAttemptState.NEEDS_OPERATOR:
            raise ExecutionAttemptTransitionError(
                f"execution {execution_id!r} is {snapshot.state}, not NEEDS_OPERATOR -- only NEEDS_OPERATOR "
                "accepts an operator resolution"
            )
        if not is_legal_transition(snapshot.state, receipt.resolved_state):
            raise ExecutionAttemptTransitionError(f"{receipt.resolved_state} is not a legal edge from NEEDS_OPERATOR")

        now = receipt.resolved_at
        self.session.add(
            OperatorResolutionReceiptModel(
                user_id=user_id,
                project_name=project_name,
                resolution_id=receipt.resolution_id,
                execution_id=execution_id,
                expected_attempt_version=expected_version,
                operator_id=receipt.operator_id,
                action=receipt.action.value,
                resolved_state=receipt.resolved_state.value,
                provider_job_id=receipt.provider_job_id,
                terminal_kind=receipt.terminal_kind.value if receipt.terminal_kind is not None else None,
                evidence_digest=receipt.evidence_digest,
                resolved_at=now,
            )
        )
        await self.session.flush()

        result = await self.session.execute(
            update(ExecutionAttemptModel)
            .where(
                ExecutionAttemptModel.user_id == user_id,
                ExecutionAttemptModel.project_name == project_name,
                ExecutionAttemptModel.execution_id == execution_id,
                ExecutionAttemptModel.state_version == expected_version,
            )
            .values(
                state=receipt.resolved_state.value,
                state_version=expected_version + 1,
                provider_job_id=(
                    receipt.provider_job_id
                    if receipt.provider_job_id is not None
                    else ExecutionAttemptModel.provider_job_id
                ),
                terminal_at=now if receipt.resolved_state in TERMINAL_ATTEMPT_STATES else None,
                updated_at=now,
            )
        )
        if rowcount(result) != 1:
            raise ExecutionAttemptFencingError(
                f"resolve_operator_review lost its fence for execution {execution_id!r} despite holding its "
                f"row lock -- expected_version={expected_version}"
            )
        new_snapshot = await self._require_snapshot(
            user_id=user_id, project_name=project_name, execution_id=execution_id
        )
        await self._append_project_event(new_snapshot, user_id=user_id, project_name=project_name)
        return new_snapshot


class CommandReceiptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_exact(
        self, *, user_id: str, project_name: str, actor_scope: str, command_id: str
    ) -> CommandReceipt | None:
        row = (
            await self.session.execute(
                select(CommandReceiptModel).where(
                    CommandReceiptModel.user_id == user_id,
                    CommandReceiptModel.project_name == project_name,
                    CommandReceiptModel.actor_scope == actor_scope,
                    CommandReceiptModel.command_id == command_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return CommandReceipt(
            actor_scope=row.actor_scope,
            command_id=row.command_id,
            command_digest=row.command_digest,
            task_id=row.task_id,
            result_digest=row.result_digest,
            created_at=_stored_aware(row.created_at),
        )

    async def add(self, *, user_id: str, project_name: str, receipt: CommandReceipt) -> None:
        self.session.add(
            CommandReceiptModel(
                user_id=user_id,
                project_name=project_name,
                actor_scope=receipt.actor_scope,
                command_id=receipt.command_id,
                command_digest=receipt.command_digest,
                task_id=receipt.task_id,
                result_digest=receipt.result_digest,
                created_at=receipt.created_at,
            )
        )
        await self.session.flush()
