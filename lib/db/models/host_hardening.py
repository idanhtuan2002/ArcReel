"""Execution-identity and idempotency persistence boundary ORM models.

``execution_attempts`` is the recovery authority: ``(user_id, project_name,
task_id, attempt_no)`` is the idempotent identity of ``plan()``, and
``provider_job_id`` is a bound observation, never a second identity. Provider
observations, operator resolutions and command receipts each own a distinct
append-only evidence table so the repository can commit worker
transitions, provider facts and operator decisions through three separate
write authorities without a shared mutable row. ``project_events`` is the
durable SSE-replay authority; delivery is a projection of this table, never
the other way around.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import DEFAULT_USER_ID, Base, UserOwnedMixin

_ID = String(255)

_EXECUTION_ATTEMPT_STATES = (
    "('PLANNED','SUBMITTING','SUBMIT_OUTCOME_UNKNOWN','ACCEPTED','RUNNING','CANCEL_REQUESTED',"
    "'CANCEL_OUTCOME_UNKNOWN','SUCCEEDED','FAILED_BEFORE_ACCEPTANCE','FAILED','CANCELLED','NEEDS_OPERATOR')"
)
_TERMINAL_ATTEMPT_STATES = "('SUCCEEDED','FAILED_BEFORE_ACCEPTANCE','FAILED','CANCELLED')"
_PROVIDER_OBSERVATION_KINDS = "('ACCEPTED','RUNNING','SUCCEEDED','FAILED','CANCELLED','NOT_FOUND')"
_OPERATOR_RESOLUTION_ACTIONS = "('BIND_REMOTE_JOB','CONFIRM_NOT_SUBMITTED','CONFIRM_TERMINAL')"
_PROJECT_EVENT_TYPES = (
    "('ATTEMPT_TRANSITIONED','CANDIDATE_VERIFIED','MASTER_PROMOTED','USAGE_FINALIZED','RESYNC_REQUIRED')"
)


class ExecutionAttemptModel(UserOwnedMixin, Base):
    """One immutable execution identity plus its monotonic current state
    (spec ``AttemptSnapshot``). ``execution_id`` alone is the primary key --
    a globally opaque ID, matching the M5C/M6 append-only convention -- with a
    redundant scoped-uniqueness constraint for query safety.
    """

    __tablename__ = "execution_attempts"
    __table_args__ = (
        PrimaryKeyConstraint("execution_id", name="pk_execution_attempts"),
        UniqueConstraint("user_id", "project_name", "execution_id", name="uq_execution_attempts_scope"),
        # plan() admits at most one attempt per scoped task and attempt number.
        UniqueConstraint("user_id", "project_name", "task_id", "attempt_no", name="uq_execution_attempts_task_attempt"),
        Index("ix_execution_attempts_project_name", "project_name"),
        Index(
            "uq_execution_attempts_provider_job",
            "user_id",
            "project_name",
            "provider_job_id",
            unique=True,
            postgresql_where=text("provider_job_id IS NOT NULL"),
            sqlite_where=text("provider_job_id IS NOT NULL"),
        ),
        CheckConstraint("attempt_no >= 1", name="ck_execution_attempts_attempt_no"),
        CheckConstraint("state_version >= 1", name="ck_execution_attempts_state_version"),
        CheckConstraint("lease_token IS NULL OR lease_token >= 1", name="ck_execution_attempts_lease_token"),
        CheckConstraint(f"state IN {_EXECUTION_ATTEMPT_STATES}", name="ck_execution_attempts_state"),
        # terminal_at is set if and only if state is terminal.
        CheckConstraint(
            f"(state IN {_TERMINAL_ATTEMPT_STATES} AND terminal_at IS NOT NULL) "
            f"OR (state NOT IN {_TERMINAL_ATTEMPT_STATES} AND terminal_at IS NULL)",
            name="ck_execution_attempts_terminal_at",
        ),
    )

    execution_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)

    task_id: Mapped[str] = mapped_column(_ID, nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    request_digest: Mapped[str] = mapped_column(_ID, nullable=False)
    route_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    client_token: Mapped[str | None] = mapped_column(_ID, nullable=True)
    trace_id_at_creation: Mapped[str | None] = mapped_column(_ID, nullable=True)
    provider_job_id: Mapped[str | None] = mapped_column(_ID, nullable=True)

    state: Mapped[str] = mapped_column(String(32), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    lease_owner: Mapped[str | None] = mapped_column(_ID, nullable=True)
    lease_token: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderObservationModel(UserOwnedMixin, Base):
    """Append-only authenticated/polled provider facts for one attempt (spec
    ``PersistedProviderObservation``). ``received_seq`` is monotonic per
    ``execution_id`` and, together with ``execution_id``, is the primary key so
    PostgreSQL assigns strictly ordered local replay sequence without a
    separate counter table. Duplicate ``observation_id`` is a no-op at the
    repository layer, enforced here by the ``(execution_id, observation_id)``
    unique constraint.
    """

    __tablename__ = "provider_observations"
    __table_args__ = (
        PrimaryKeyConstraint("execution_id", "received_seq", name="pk_provider_observations"),
        UniqueConstraint("execution_id", "observation_id", name="uq_provider_observations_observation_id"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            ["execution_attempts.user_id", "execution_attempts.project_name", "execution_attempts.execution_id"],
            name="fk_provider_observations_execution_attempt",
            ondelete="RESTRICT",
        ),
        Index("ix_provider_observations_project_name", "project_name"),
        CheckConstraint("received_seq >= 1", name="ck_provider_observations_received_seq"),
        CheckConstraint(f"kind IN {_PROVIDER_OBSERVATION_KINDS}", name="ck_provider_observations_kind"),
    )

    execution_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    received_seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)

    observation_id: Mapped[str] = mapped_column(_ID, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_job_id: Mapped[str | None] = mapped_column(_ID, nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evidence_digest: Mapped[str] = mapped_column(_ID, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AttemptIntegrityIncidentModel(UserOwnedMixin, Base):
    """Conflicting-terminal-fact evidence that blocks candidate promotion and
    usage finalization until an operator resolves it (spec
    ``AttemptIntegrityIncident``)."""

    __tablename__ = "attempt_integrity_incidents"
    __table_args__ = (
        PrimaryKeyConstraint("incident_id", name="pk_attempt_integrity_incidents"),
        UniqueConstraint("user_id", "project_name", "incident_id", name="uq_attempt_integrity_incidents_scope"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            ["execution_attempts.user_id", "execution_attempts.project_name", "execution_attempts.execution_id"],
            name="fk_attempt_integrity_incidents_execution_attempt",
            ondelete="RESTRICT",
        ),
        Index("ix_attempt_integrity_incidents_execution_id", "execution_id"),
        Index("ix_attempt_integrity_incidents_project_name", "project_name"),
    )

    incident_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)

    execution_id: Mapped[str] = mapped_column(_ID, nullable=False)
    first_observation_id: Mapped[str] = mapped_column(_ID, nullable=False)
    conflicting_observation_id: Mapped[str] = mapped_column(_ID, nullable=False)
    evidence_digest: Mapped[str] = mapped_column(_ID, nullable=False)
    resolved_by_receipt_id: Mapped[str | None] = mapped_column(_ID, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OperatorResolutionReceiptModel(UserOwnedMixin, Base):
    """Closed, evidence-bearing operator decision that alone may move an
    attempt out of ``NEEDS_OPERATOR``.
    The action/resolved-state compatibility CHECK enforces the closed
    operator-action rules at the database boundary, not only in application
    code.
    """

    __tablename__ = "operator_resolution_receipts"
    __table_args__ = (
        PrimaryKeyConstraint("resolution_id", name="pk_operator_resolution_receipts"),
        UniqueConstraint("user_id", "project_name", "resolution_id", name="uq_operator_resolution_receipts_scope"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            ["execution_attempts.user_id", "execution_attempts.project_name", "execution_attempts.execution_id"],
            name="fk_operator_resolution_receipts_execution_attempt",
            ondelete="RESTRICT",
        ),
        Index("ix_operator_resolution_receipts_execution_id", "execution_id"),
        Index("ix_operator_resolution_receipts_project_name", "project_name"),
        CheckConstraint("expected_attempt_version >= 1", name="ck_operator_resolution_receipts_expected_version"),
        CheckConstraint(f"action IN {_OPERATOR_RESOLUTION_ACTIONS}", name="ck_operator_resolution_receipts_action"),
        CheckConstraint(f"resolved_state IN {_EXECUTION_ATTEMPT_STATES}", name="ck_operator_resolution_receipts_state"),
        CheckConstraint(
            f"terminal_kind IS NULL OR terminal_kind IN {_PROVIDER_OBSERVATION_KINDS}",
            name="ck_operator_resolution_receipts_terminal_kind",
        ),
        CheckConstraint(
            "(action = 'BIND_REMOTE_JOB' AND provider_job_id IS NOT NULL "
            "  AND resolved_state IN ('ACCEPTED','RUNNING')) "
            "OR (action = 'CONFIRM_NOT_SUBMITTED' AND resolved_state = 'FAILED_BEFORE_ACCEPTANCE') "
            "OR (action = 'CONFIRM_TERMINAL' AND terminal_kind IS NOT NULL "
            f"  AND resolved_state IN {_TERMINAL_ATTEMPT_STATES})",
            name="ck_operator_resolution_receipts_action_compat",
        ),
    )

    resolution_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)

    execution_id: Mapped[str] = mapped_column(_ID, nullable=False)
    expected_attempt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    operator_id: Mapped[str] = mapped_column(_ID, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    resolved_state: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_job_id: Mapped[str | None] = mapped_column(_ID, nullable=True)
    terminal_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_digest: Mapped[str] = mapped_column(_ID, nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CommandReceiptModel(UserOwnedMixin, Base):
    """Durable idempotency result for one actor-scoped mutation command (spec
    ``CommandReceipt``). ``(user_id, project_name, actor_scope, command_id)``
    is the natural primary key -- exactly the tuple
    ``CommandReceiptRepository.get_exact`` reads by.
    """

    __tablename__ = "command_receipts"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "actor_scope", "command_id", name="pk_command_receipts"),
        Index("ix_command_receipts_task_id", "task_id"),
        Index("ix_command_receipts_project_name", "project_name"),
    )

    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        server_default=DEFAULT_USER_ID,
        primary_key=True,
    )
    project_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    actor_scope: Mapped[str] = mapped_column(_ID, primary_key=True)
    command_id: Mapped[str] = mapped_column(_ID, primary_key=True)

    command_digest: Mapped[str] = mapped_column(_ID, nullable=False)
    task_id: Mapped[str] = mapped_column(_ID, nullable=False)
    result_digest: Mapped[str] = mapped_column(_ID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectEventModel(UserOwnedMixin, Base):
    """Durable tenant-scoped domain event; SSE is one delivery projection of
    this row (spec ``DurableProjectEvent``). ``event_id`` is a single global
    monotonic identity column: the SSE replay cursor compares it directly, and
    a global sequence needs no per-project counter coordination.
    """

    __tablename__ = "project_events"
    __table_args__ = (
        PrimaryKeyConstraint("event_id", name="pk_project_events"),
        UniqueConstraint("user_id", "project_name", "dedupe_key", name="uq_project_events_dedupe_key"),
        Index("ix_project_events_scope_cursor", "user_id", "project_name", "event_id"),
        CheckConstraint("payload_schema_version >= 1", name="ck_project_events_payload_schema_version"),
        CheckConstraint(f"event_type IN {_PROJECT_EVENT_TYPES}", name="ck_project_events_event_type"),
    )

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)

    task_id: Mapped[str | None] = mapped_column(_ID, nullable=True)
    execution_id: Mapped[str | None] = mapped_column(_ID, nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    state_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    public_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    trace_id: Mapped[str | None] = mapped_column(_ID, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(_ID, nullable=False)
