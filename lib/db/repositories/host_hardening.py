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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.content_digest import canonical_json_digest
from lib.db.base import utc_now
from lib.db.models.host_hardening import (
    BackupSetMediaRefModel,
    BackupSetModel,
    CandidateObjectModel,
    CommandReceiptModel,
    ExecutionAttemptModel,
    MasterAuthorityModel,
    MasterHeadVersionModel,
    OperatorResolutionReceiptModel,
    ProjectEventModel,
    PromotionReceiptModel,
    ProviderObservationModel,
)
from lib.db.repositories.base import rowcount
from r2.contracts.host_hardening import (
    TERMINAL_ATTEMPT_STATES,
    AttemptLeaseFence,
    AttemptSnapshot,
    CommandReceipt,
    DurableProjectEvent,
    ExecutionAttemptState,
    MasterHeadSnapshot,
    OperatorResolutionReceipt,
    PersistedProviderObservation,
    PlannedExecutionAttempt,
    ProjectEventType,
    PromotionReceipt,
    ProviderCapabilityProfile,
    ProviderObservation,
    ProviderRouteSnapshot,
    VerifiedCandidateObject,
    command_receipt_result_envelope,
)
from r2.host_hardening.transitions import fold_observation, is_legal_transition, validate_exact_replay


def _is_unique_violation(exc: IntegrityError) -> bool:
    """A unique constraint hit (23505 on PostgreSQL) -- not an FK or NOT NULL failure."""
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
    if sqlstate is not None:
        return sqlstate == "23505"
    message = str(getattr(exc, "orig", None) or exc).lower()
    return "unique constraint failed" in message or "unique" in message


class ExecutionAttemptIntegrityError(RuntimeError):
    """A row this repository just wrote vanished within the same transaction."""


class ExecutionAttemptFencingError(RuntimeError):
    """A fenced attempt mutation lost its expected_version/lease/state CAS."""


class ExecutionAttemptTransitionError(ValueError):
    """A requested worker transition or operator resolution is not a legal edge."""


class CommandReceiptConflictError(RuntimeError):
    """A command_id was replayed with a different command_digest -- the same
    idempotency key reused for a materially different request."""


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

    async def get_for_task_attempt(
        self,
        *,
        user_id: str,
        project_name: str,
        task_id: str,
        attempt_no: int,
    ) -> AttemptSnapshot | None:
        row = await self._scalar(
            select(ExecutionAttemptModel).where(
                ExecutionAttemptModel.user_id == user_id,
                ExecutionAttemptModel.project_name == project_name,
                ExecutionAttemptModel.task_id == task_id,
                ExecutionAttemptModel.attempt_no == attempt_no,
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
        force: bool = False,
    ) -> AttemptSnapshot:
        now = utc_now()
        conditions: list[Any] = [
            ExecutionAttemptModel.user_id == user_id,
            ExecutionAttemptModel.project_name == project_name,
            ExecutionAttemptModel.execution_id == execution_id,
            ExecutionAttemptModel.state_version == expected_version,
        ]
        if not force:
            conditions.append(
                or_(
                    ExecutionAttemptModel.lease_owner.is_(None),
                    ExecutionAttemptModel.lease_owner == owner,
                    ExecutionAttemptModel.lease_expires_at.is_(None),
                    ExecutionAttemptModel.lease_expires_at <= now,
                )
            )
        # ``force`` drops the ownership/liveness check above but keeps the
        # state_version CAS: two concurrent forced acquires still have exactly
        # one winner, since only the first to commit still matches
        # expected_version. It exists for CANCEL_REQUESTED realization, whose
        # only writer (request_cancel) never touches the lease at all -- a
        # stale submission-phase lease still nominally "live" (its 300s TTL
        # not yet elapsed) is not evidence any real actor is using it, so
        # requiring it to look expired would arbitrarily delay a fresh cancel
        # intent for no correctness reason.
        result = await self.session.execute(
            update(ExecutionAttemptModel)
            .where(*conditions)
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

    async def list_lease_expired(
        self, *, states: frozenset[ExecutionAttemptState], before: datetime, limit: int = 100
    ) -> list[tuple[str, str, AttemptSnapshot]]:
        """Unscoped recovery-scan query (mirrors ``TaskRepository.list_orphan_tasks_on_start``):
        every attempt in *states* whose lease already expired, across every user/project,
        oldest first. Returns ``(user_id, project_name, snapshot)`` because
        :class:`AttemptSnapshot` itself is scope-neutral and a caller acting on the
        result needs the exact scope to re-acquire the lease."""

        rows = (
            await self.session.execute(
                select(ExecutionAttemptModel)
                .where(
                    ExecutionAttemptModel.state.in_([state.value for state in states]),
                    ExecutionAttemptModel.lease_expires_at.is_not(None),
                    ExecutionAttemptModel.lease_expires_at <= before,
                )
                .order_by(ExecutionAttemptModel.lease_expires_at.asc())
                .limit(limit)
            )
        ).scalars()
        return [(row.user_id, row.project_name, _snapshot_from_row(row)) for row in rows]

    async def list_pending_cancels(self, *, limit: int = 100) -> list[tuple[str, str, AttemptSnapshot]]:
        """Unscoped scan (mirrors ``list_lease_expired``): every ``CANCEL_REQUESTED``
        attempt, oldest updated first. Deliberately no lease-liveness filter --
        ``CANCEL_REQUESTED``'s only writer (``request_cancel``) never touches the
        lease, so every row is immediately realizable, not just the "expired" ones
        a lease-based filter would find."""
        rows = (
            await self.session.execute(
                select(ExecutionAttemptModel)
                .where(ExecutionAttemptModel.state == ExecutionAttemptState.CANCEL_REQUESTED.value)
                .order_by(ExecutionAttemptModel.updated_at.asc())
                .limit(limit)
            )
        ).scalars()
        return [(row.user_id, row.project_name, _snapshot_from_row(row)) for row in rows]

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

        if snapshot.state is ExecutionAttemptState.NEEDS_OPERATOR:
            # Three-authority separation (module docstring): a provider fact is
            # still recorded as evidence above, but only resolve_operator_review
            # may move an attempt out of an operator pause. fold_observation's
            # pure transition table permits this edge (an operator resolution
            # reuses the same table), so the guard belongs here, not there.
            return snapshot

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

    # --- cancel-intent authority ------------------------------------------------------
    # A fourth write authority, distinct from worker/provider/operator: an external
    # cancel request (API/user) never holds the current worker's lease, so it cannot
    # go through transition_worker. It writes intent only -- calling the provider's
    # own cancel endpoint, if any, is the recovery poller's job once it observes
    # CANCEL_REQUESTED on an attempt whose lease is gone (spec: "cancel ghi intent
    # trước, gọi provider sau").

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
    ) -> AttemptSnapshot:
        existing_receipt = await CommandReceiptRepository(self.session).get_exact(
            user_id=user_id, project_name=project_name, actor_scope=actor_scope, command_id=command_id
        )
        if existing_receipt is not None:
            if existing_receipt.command_digest != command_digest:
                raise CommandReceiptConflictError(
                    f"command {command_id!r} was already used for a different cancel request"
                )
            return await self._require_snapshot(user_id=user_id, project_name=project_name, execution_id=execution_id)

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
                f"request_cancel: execution {execution_id!r} is not at expected_version={expected_version}"
            )
        snapshot = _snapshot_from_row(row)
        if snapshot.state not in (ExecutionAttemptState.ACCEPTED, ExecutionAttemptState.RUNNING):
            raise ExecutionAttemptTransitionError(
                f"execution {execution_id!r} is {snapshot.state}, not ACCEPTED/RUNNING -- "
                "cancel intent only applies to an attempt the provider has already accepted"
            )

        now = utc_now()
        envelope = command_receipt_result_envelope(
            task_id=snapshot.task_id, result={"execution_id": execution_id, "resolved_state": "CANCEL_REQUESTED"}
        )
        receipt = CommandReceipt(
            actor_scope=actor_scope,
            command_id=command_id,
            command_digest=command_digest,
            task_id=snapshot.task_id,
            result_digest="sha256:" + canonical_json_digest(envelope, allow_nan=False),
            created_at=now,
        )
        await CommandReceiptRepository(self.session).add(user_id=user_id, project_name=project_name, receipt=receipt)
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
                state=ExecutionAttemptState.CANCEL_REQUESTED.value,
                state_version=expected_version + 1,
                updated_at=now,
            )
        )
        if rowcount(result) != 1:
            raise ExecutionAttemptFencingError(
                f"request_cancel lost its fence for execution {execution_id!r} despite holding its "
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


# --- M7-B: immutable candidates and atomic master promotion (H3-H4) -----------------


class CandidateIdentityConflictError(RuntimeError):
    """A different candidate already occupies this ``candidate_id`` with unequal bytes."""


class MasterAuthorityNotFoundError(LookupError):
    """No master authority row exists yet for this ``(user_id, project_name, artifact_key)``."""


class MasterHeadConflictError(RuntimeError):
    """A concurrent promotion already advanced this master head past ``expected_master_version``."""


class PromotionReceiptConflictError(RuntimeError):
    """A receipt already exists for this ``command_id`` with a different ``command_digest``."""


def _candidate_from_row(row: CandidateObjectModel) -> VerifiedCandidateObject:
    return VerifiedCandidateObject(
        candidate_id=row.candidate_id,
        project_name=row.project_name,
        artifact_key=row.artifact_key,
        object_ref=row.object_ref,
        byte_size=row.byte_size,
        content_digest=row.content_digest,
        media_probe_digest=row.media_probe_digest,
    )


class CandidateObjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_exact(self, *, user_id: str, project_name: str, candidate_id: str) -> VerifiedCandidateObject | None:
        row = (
            await self.session.execute(
                select(CandidateObjectModel).where(
                    CandidateObjectModel.user_id == user_id,
                    CandidateObjectModel.project_name == project_name,
                    CandidateObjectModel.candidate_id == candidate_id,
                )
            )
        ).scalar_one_or_none()
        return None if row is None else _candidate_from_row(row)

    async def list_all(self, *, user_id: str, project_name: str) -> list[VerifiedCandidateObject]:
        rows = (
            (
                await self.session.execute(
                    select(CandidateObjectModel)
                    .where(
                        CandidateObjectModel.user_id == user_id,
                        CandidateObjectModel.project_name == project_name,
                    )
                    .order_by(CandidateObjectModel.candidate_id)
                )
            )
            .scalars()
            .all()
        )
        return [_candidate_from_row(row) for row in rows]

    async def insert(
        self, *, user_id: str, project_name: str, candidate: VerifiedCandidateObject, created_at: datetime
    ) -> None:
        try:
            async with self.session.begin_nested():
                self.session.add(
                    CandidateObjectModel(
                        user_id=user_id,
                        project_name=project_name,
                        candidate_id=candidate.candidate_id,
                        artifact_key=candidate.artifact_key,
                        object_ref=candidate.object_ref,
                        byte_size=candidate.byte_size,
                        content_digest=candidate.content_digest,
                        media_probe_digest=candidate.media_probe_digest,
                        created_at=created_at,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            raise CandidateIdentityConflictError(
                f"candidate {candidate.candidate_id!r} conflicts with an existing candidate in this scope"
            ) from exc


class MasterAuthorityRepository:
    """Append-only master-head history plus its one CASed pointer.

    Optimistic, matching ``ExecutionAttemptRepository.acquire_lease`` rather
    than ``CanonRepository.lock_branch``'s ``SELECT ... FOR UPDATE``:
    ``get_current_version`` never blocks a concurrent caller, and
    ``advance_head`` moves the pointer only if it still matches
    ``expected_current_version``. ``insert_head_version`` appends immutable
    history; its unique constraint is the CAS boundary against a concurrent
    same-version write. A promotion calls ``advance_head`` first: its ``UPDATE``
    takes the authority row's write lock, the same lock ``serialized_artifacts``
    holds, so every same-slot writer takes that row before any history row.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_current_keys(self, *, user_id: str, project_name: str) -> list[str]:
        """The artifact keys of this project that have a promoted master head."""
        rows = await self.session.execute(
            select(MasterAuthorityModel.artifact_key)
            .where(
                MasterAuthorityModel.user_id == user_id,
                MasterAuthorityModel.project_name == project_name,
                MasterAuthorityModel.current_version > 0,
            )
            .order_by(MasterAuthorityModel.artifact_key)
        )
        return list(rows.scalars().all())

    async def get_current(self, *, user_id: str, project_name: str, artifact_key: str) -> MasterHeadSnapshot | None:
        authority = (
            await self.session.execute(
                select(MasterAuthorityModel).where(
                    MasterAuthorityModel.user_id == user_id,
                    MasterAuthorityModel.project_name == project_name,
                    MasterAuthorityModel.artifact_key == artifact_key,
                )
            )
        ).scalar_one_or_none()
        if authority is None or authority.current_version == 0:
            return None
        version = (
            await self.session.execute(
                select(MasterHeadVersionModel).where(
                    MasterHeadVersionModel.user_id == user_id,
                    MasterHeadVersionModel.project_name == project_name,
                    MasterHeadVersionModel.artifact_key == artifact_key,
                    MasterHeadVersionModel.master_version == authority.current_version,
                )
            )
        ).scalar_one()
        return MasterHeadSnapshot(
            artifact_key=version.artifact_key,
            master_version=version.master_version,
            candidate_id=version.candidate_id,
            object_ref=version.object_ref,
            content_digest=version.content_digest,
            approval_record=version.approval_record,
        )

    async def get_current_version(self, *, user_id: str, project_name: str, artifact_key: str) -> int:
        """Return the mutable pointer's current version, creating it at ``0`` if
        absent. Purely optimistic, like every other M7 CAS seam
        (:meth:`~lib.db.repositories.host_hardening.ExecutionAttemptRepository.acquire_lease`):
        no ``SELECT ... FOR UPDATE`` hold, so a concurrent promotion never blocks
        on this call. The actual CAS boundary is
        :meth:`insert_head_version`'s unique constraint plus :meth:`advance_head`'s
        expected-version-guarded ``UPDATE``; both fail closed, they never block.
        The create-if-absent race uses a ``SAVEPOINT`` so a losing insert only
        rolls back this call, never the caller's own earlier work in the same
        transaction.
        """

        row = (
            await self.session.execute(
                select(MasterAuthorityModel).where(
                    MasterAuthorityModel.user_id == user_id,
                    MasterAuthorityModel.project_name == project_name,
                    MasterAuthorityModel.artifact_key == artifact_key,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return row.current_version
        try:
            async with self.session.begin_nested():
                self.session.add(
                    MasterAuthorityModel(
                        user_id=user_id, project_name=project_name, artifact_key=artifact_key, current_version=0
                    )
                )
                await self.session.flush()
            return 0
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            # Lost the race to create the row: another transaction already committed
            # it first. Re-read instead of raising -- the row now exists.
            created = (
                await self.session.execute(
                    select(MasterAuthorityModel).where(
                        MasterAuthorityModel.user_id == user_id,
                        MasterAuthorityModel.project_name == project_name,
                        MasterAuthorityModel.artifact_key == artifact_key,
                    )
                )
            ).scalar_one()
            return created.current_version

    async def insert_head_version(
        self,
        *,
        user_id: str,
        project_name: str,
        master_head_version_id: str,
        snapshot: MasterHeadSnapshot,
        promoted_at: datetime,
    ) -> None:
        try:
            async with self.session.begin_nested():
                self.session.add(
                    MasterHeadVersionModel(
                        master_head_version_id=master_head_version_id,
                        user_id=user_id,
                        project_name=project_name,
                        artifact_key=snapshot.artifact_key,
                        master_version=snapshot.master_version,
                        candidate_id=snapshot.candidate_id,
                        object_ref=snapshot.object_ref,
                        content_digest=snapshot.content_digest,
                        approval_record=snapshot.approval_record,
                        promoted_at=promoted_at,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            raise MasterHeadConflictError(
                f"{snapshot.artifact_key!r} already has a version {snapshot.master_version} "
                "(concurrent promotion won the race)"
            ) from exc

    async def advance_head(
        self, *, user_id: str, project_name: str, artifact_key: str, expected_current_version: int, new_version: int
    ) -> None:
        result = await self.session.execute(
            update(MasterAuthorityModel)
            .where(
                MasterAuthorityModel.user_id == user_id,
                MasterAuthorityModel.project_name == project_name,
                MasterAuthorityModel.artifact_key == artifact_key,
                MasterAuthorityModel.current_version == expected_current_version,
            )
            .values(current_version=new_version)
        )
        if rowcount(result) != 1:
            raise MasterHeadConflictError(f"locked master authority {artifact_key!r} changed unexpectedly")

    async def append_promoted_event(self, *, user_id: str, project_name: str, snapshot: MasterHeadSnapshot) -> None:
        self.session.add(
            ProjectEventModel(
                user_id=user_id,
                project_name=project_name,
                task_id=None,
                execution_id=None,
                event_type=ProjectEventType.MASTER_PROMOTED.value,
                state_version=snapshot.master_version,
                public_payload_json={
                    "artifact_key": snapshot.artifact_key,
                    "master_version": snapshot.master_version,
                    "candidate_id": snapshot.candidate_id,
                },
                payload_schema_version=1,
                dedupe_key=f"master:{snapshot.artifact_key}:{snapshot.master_version}",
            )
        )
        await self.session.flush()


class PromotionReceiptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_exact(
        self, *, user_id: str, project_name: str, artifact_key: str, command_id: str
    ) -> PromotionReceipt | None:
        row = (
            await self.session.execute(
                select(PromotionReceiptModel).where(
                    PromotionReceiptModel.user_id == user_id,
                    PromotionReceiptModel.project_name == project_name,
                    PromotionReceiptModel.artifact_key == artifact_key,
                    PromotionReceiptModel.command_id == command_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return PromotionReceipt(
            artifact_key=row.artifact_key,
            command_id=row.command_id,
            command_digest=row.command_digest,
            candidate_id=row.candidate_id,
            master_version=row.master_version,
            approval_record=row.approval_record,
            created_at=_stored_aware(row.created_at),
        )

    async def add(self, *, user_id: str, project_name: str, receipt: PromotionReceipt) -> None:
        try:
            async with self.session.begin_nested():
                self.session.add(
                    PromotionReceiptModel(
                        user_id=user_id,
                        project_name=project_name,
                        artifact_key=receipt.artifact_key,
                        command_id=receipt.command_id,
                        command_digest=receipt.command_digest,
                        candidate_id=receipt.candidate_id,
                        master_version=receipt.master_version,
                        approval_record=receipt.approval_record,
                        created_at=receipt.created_at,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            raise PromotionReceiptConflictError(
                f"a receipt for command {receipt.command_id!r} already exists in this scope"
            ) from exc

    async def has_retained_receipt_for_candidate(self, *, user_id: str, project_name: str, candidate_id: str) -> bool:
        row = (
            await self.session.execute(
                select(PromotionReceiptModel.command_id)
                .where(
                    PromotionReceiptModel.user_id == user_id,
                    PromotionReceiptModel.project_name == project_name,
                    PromotionReceiptModel.candidate_id == candidate_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return row is not None


class BackupSetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert(self, *, user_id: str, project_name: str, backup_set_id: str, state: str, now: datetime) -> None:
        self.session.add(
            BackupSetModel(
                user_id=user_id,
                project_name=project_name,
                backup_set_id=backup_set_id,
                state=state,
                created_at=now,
                updated_at=now,
            )
        )
        await self.session.flush()

    async def add_media_ref(self, *, backup_set_id: str, candidate_id: str) -> None:
        self.session.add(BackupSetMediaRefModel(backup_set_id=backup_set_id, candidate_id=candidate_id))
        await self.session.flush()

    async def mark_state(self, *, backup_set_id: str, state: str, now: datetime) -> None:
        result = await self.session.execute(
            update(BackupSetModel)
            .where(BackupSetModel.backup_set_id == backup_set_id)
            .values(state=state, updated_at=now)
        )
        if rowcount(result) != 1:
            raise LookupError(f"no backup set {backup_set_id!r} to mark {state!r}")

    async def has_incomplete_backup_referencing(self, *, user_id: str, project_name: str, candidate_id: str) -> bool:
        row = (
            await self.session.execute(
                select(BackupSetMediaRefModel.backup_set_id)
                .join(BackupSetModel, BackupSetModel.backup_set_id == BackupSetMediaRefModel.backup_set_id)
                .where(
                    BackupSetModel.user_id == user_id,
                    BackupSetModel.project_name == project_name,
                    BackupSetMediaRefModel.candidate_id == candidate_id,
                    BackupSetModel.state.in_(("PREPARING", "COMPLETE")),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return row is not None


class MasterHeadReferenceCheckImpl:
    """Real ``MasterHeadReferenceCheck`` backed by :class:`MasterHeadVersionModel`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def references_candidate(self, *, user_id: str, project_name: str, candidate_id: str) -> bool:
        row = (
            await self.session.execute(
                select(MasterAuthorityModel.artifact_key)
                .join(
                    MasterHeadVersionModel,
                    (MasterHeadVersionModel.user_id == MasterAuthorityModel.user_id)
                    & (MasterHeadVersionModel.project_name == MasterAuthorityModel.project_name)
                    & (MasterHeadVersionModel.artifact_key == MasterAuthorityModel.artifact_key)
                    & (MasterHeadVersionModel.master_version == MasterAuthorityModel.current_version),
                )
                .where(
                    MasterAuthorityModel.user_id == user_id,
                    MasterAuthorityModel.project_name == project_name,
                    MasterHeadVersionModel.candidate_id == candidate_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return row is not None


class ActiveAttemptReferenceCheckImpl:
    """Fail-closed placeholder ``ActiveAttemptReferenceCheck``.

    ``execution_attempts`` (A2) and ``candidate_objects`` (B1/B2) were designed
    by separate packets and have no schema linkage yet -- an attempt records a
    provider route and job identity, never a ``candidate_id``. Until a later
    packet adds that linkage (e.g. when a worker records which candidate an
    in-flight attempt is producing), this check cannot honestly scope "is
    *this* candidate referenced" and always answers "yes": retention refuses to
    delete rather than silently allow a candidate an active attempt might still
    be producing. It is not a bypass -- ``CandidateRetentionPolicy`` will not
    permit deletion of anything until this predicate is replaced with a real
    scoped query.
    """

    async def has_active_attempt_for_candidate(self, *, user_id: str, project_name: str, candidate_id: str) -> bool:
        del user_id, project_name, candidate_id
        return True


# --- M7-C: durable project-event replay (H5) -------------------------------------------


def _durable_event_from_row(row: ProjectEventModel) -> DurableProjectEvent:
    return DurableProjectEvent(
        event_id=row.event_id,
        user_id=row.user_id,
        project_name=row.project_name,
        task_id=row.task_id,
        execution_id=row.execution_id,
        event_type=ProjectEventType(row.event_type),
        state_version=row.state_version,
        public_payload=row.public_payload_json,
        payload_schema_version=row.payload_schema_version,
        trace_id=row.trace_id,
        dedupe_key=row.dedupe_key,
    )


class ProjectEventRepository:
    """Read side of the M7-A ``project_events`` table (spec section 7
    ``ProjectEventRepository``). The write side lives with each authority that
    appends its own event (``ExecutionAttemptRepository``,
    ``MasterAuthorityRepository``); this repository never writes, so a reader
    can never become a shadow authority for attempt/candidate/master state.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def high_watermark(self, *, user_id: str, project_name: str) -> int:
        value = (
            await self.session.execute(
                select(func.max(ProjectEventModel.event_id)).where(
                    ProjectEventModel.user_id == user_id,
                    ProjectEventModel.project_name == project_name,
                )
            )
        ).scalar_one()
        return value or 0

    async def replay_after(
        self, *, user_id: str, project_name: str, cursor: int | None, limit: int
    ) -> list[DurableProjectEvent]:
        rows = (
            await self.session.execute(
                select(ProjectEventModel)
                .where(
                    ProjectEventModel.user_id == user_id,
                    ProjectEventModel.project_name == project_name,
                    ProjectEventModel.event_id > (cursor or 0),
                )
                .order_by(ProjectEventModel.event_id.asc())
                .limit(limit)
            )
        ).scalars()
        return [_durable_event_from_row(row) for row in rows]
