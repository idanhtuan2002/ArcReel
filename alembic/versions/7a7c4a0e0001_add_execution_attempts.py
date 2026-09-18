"""add execution attempts

Revision ID: 7a7c4a0e0001
Revises: 6c7c4a0e0002
Create Date: 2026-09-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a7c4a0e0001"
down_revision: str | Sequence[str] | None = "6c7c4a0e0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "execution_attempts",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("execution_id", sa.String(length=255), nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("request_digest", sa.String(length=255), nullable=False),
        sa.Column("route_json", sa.JSON(), nullable=False),
        sa.Column("client_token", sa.String(length=255), nullable=True),
        sa.Column("trace_id_at_creation", sa.String(length=255), nullable=True),
        sa.Column("provider_job_id", sa.String(length=255), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_token", sa.Integer(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempt_no >= 1", name="ck_execution_attempts_attempt_no"),
        sa.CheckConstraint("state_version >= 1", name="ck_execution_attempts_state_version"),
        sa.CheckConstraint("lease_token IS NULL OR lease_token >= 1", name="ck_execution_attempts_lease_token"),
        sa.CheckConstraint(f"state IN {_EXECUTION_ATTEMPT_STATES}", name="ck_execution_attempts_state"),
        sa.CheckConstraint(
            f"(state IN {_TERMINAL_ATTEMPT_STATES} AND terminal_at IS NOT NULL) "
            f"OR (state NOT IN {_TERMINAL_ATTEMPT_STATES} AND terminal_at IS NULL)",
            name="ck_execution_attempts_terminal_at",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("execution_id", name="pk_execution_attempts"),
        sa.UniqueConstraint("user_id", "project_name", "execution_id", name="uq_execution_attempts_scope"),
        sa.UniqueConstraint(
            "user_id", "project_name", "task_id", "attempt_no", name="uq_execution_attempts_task_attempt"
        ),
    )
    with op.batch_alter_table("execution_attempts", schema=None) as batch_op:
        batch_op.create_index("ix_execution_attempts_project_name", ["project_name"], unique=False)
        batch_op.create_index(
            "uq_execution_attempts_provider_job",
            ["user_id", "project_name", "provider_job_id"],
            unique=True,
            postgresql_where=sa.text("provider_job_id IS NOT NULL"),
            sqlite_where=sa.text("provider_job_id IS NOT NULL"),
        )

    with op.batch_alter_table("api_calls", schema=None) as batch_op:
        batch_op.add_column(sa.Column("execution_id", sa.String(length=255), nullable=True))
        batch_op.create_index(
            "uq_api_calls_execution_id",
            ["execution_id"],
            unique=True,
            postgresql_where=sa.text("execution_id IS NOT NULL"),
            sqlite_where=sa.text("execution_id IS NOT NULL"),
        )
        batch_op.create_foreign_key(
            "fk_api_calls_execution_attempt",
            "execution_attempts",
            ["user_id", "project_name", "execution_id"],
            ["user_id", "project_name", "execution_id"],
            ondelete="RESTRICT",
        )

    op.create_table(
        "provider_observations",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("execution_id", sa.String(length=255), nullable=False),
        sa.Column("received_seq", sa.Integer(), nullable=False),
        sa.Column("observation_id", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_sequence", sa.Integer(), nullable=True),
        sa.Column("provider_job_id", sa.String(length=255), nullable=True),
        sa.Column("reason_code", sa.String(length=255), nullable=True),
        sa.Column("evidence_digest", sa.String(length=255), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("received_seq >= 1", name="ck_provider_observations_received_seq"),
        sa.CheckConstraint(f"kind IN {_PROVIDER_OBSERVATION_KINDS}", name="ck_provider_observations_kind"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            ["execution_attempts.user_id", "execution_attempts.project_name", "execution_attempts.execution_id"],
            name="fk_provider_observations_execution_attempt",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("execution_id", "received_seq", name="pk_provider_observations"),
        sa.UniqueConstraint("execution_id", "observation_id", name="uq_provider_observations_observation_id"),
    )
    with op.batch_alter_table("provider_observations", schema=None) as batch_op:
        batch_op.create_index("ix_provider_observations_project_name", ["project_name"], unique=False)

    op.create_table(
        "attempt_integrity_incidents",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("incident_id", sa.String(length=255), nullable=False),
        sa.Column("execution_id", sa.String(length=255), nullable=False),
        sa.Column("first_observation_id", sa.String(length=255), nullable=False),
        sa.Column("conflicting_observation_id", sa.String(length=255), nullable=False),
        sa.Column("evidence_digest", sa.String(length=255), nullable=False),
        sa.Column("resolved_by_receipt_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            ["execution_attempts.user_id", "execution_attempts.project_name", "execution_attempts.execution_id"],
            name="fk_attempt_integrity_incidents_execution_attempt",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("incident_id", name="pk_attempt_integrity_incidents"),
        sa.UniqueConstraint("user_id", "project_name", "incident_id", name="uq_attempt_integrity_incidents_scope"),
    )
    with op.batch_alter_table("attempt_integrity_incidents", schema=None) as batch_op:
        batch_op.create_index("ix_attempt_integrity_incidents_execution_id", ["execution_id"], unique=False)
        batch_op.create_index("ix_attempt_integrity_incidents_project_name", ["project_name"], unique=False)

    op.create_table(
        "operator_resolution_receipts",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("resolution_id", sa.String(length=255), nullable=False),
        sa.Column("execution_id", sa.String(length=255), nullable=False),
        sa.Column("expected_attempt_version", sa.Integer(), nullable=False),
        sa.Column("operator_id", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("resolved_state", sa.String(length=32), nullable=False),
        sa.Column("provider_job_id", sa.String(length=255), nullable=True),
        sa.Column("terminal_kind", sa.String(length=32), nullable=True),
        sa.Column("evidence_digest", sa.String(length=255), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("expected_attempt_version >= 1", name="ck_operator_resolution_receipts_expected_version"),
        sa.CheckConstraint(f"action IN {_OPERATOR_RESOLUTION_ACTIONS}", name="ck_operator_resolution_receipts_action"),
        sa.CheckConstraint(
            f"resolved_state IN {_EXECUTION_ATTEMPT_STATES}", name="ck_operator_resolution_receipts_state"
        ),
        sa.CheckConstraint(
            f"terminal_kind IS NULL OR terminal_kind IN {_PROVIDER_OBSERVATION_KINDS}",
            name="ck_operator_resolution_receipts_terminal_kind",
        ),
        sa.CheckConstraint(
            "(action = 'BIND_REMOTE_JOB' AND provider_job_id IS NOT NULL "
            "  AND resolved_state IN ('ACCEPTED','RUNNING')) "
            "OR (action = 'CONFIRM_NOT_SUBMITTED' AND resolved_state = 'FAILED_BEFORE_ACCEPTANCE') "
            "OR (action = 'CONFIRM_TERMINAL' AND terminal_kind IS NOT NULL "
            f"  AND resolved_state IN {_TERMINAL_ATTEMPT_STATES})",
            name="ck_operator_resolution_receipts_action_compat",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            ["execution_attempts.user_id", "execution_attempts.project_name", "execution_attempts.execution_id"],
            name="fk_operator_resolution_receipts_execution_attempt",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("resolution_id", name="pk_operator_resolution_receipts"),
        sa.UniqueConstraint("user_id", "project_name", "resolution_id", name="uq_operator_resolution_receipts_scope"),
    )
    with op.batch_alter_table("operator_resolution_receipts", schema=None) as batch_op:
        batch_op.create_index("ix_operator_resolution_receipts_execution_id", ["execution_id"], unique=False)
        batch_op.create_index("ix_operator_resolution_receipts_project_name", ["project_name"], unique=False)

    op.create_table(
        "command_receipts",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("actor_scope", sa.String(length=255), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("command_digest", sa.String(length=255), nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=False),
        sa.Column("result_digest", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "actor_scope", "command_id", name="pk_command_receipts"),
    )
    with op.batch_alter_table("command_receipts", schema=None) as batch_op:
        batch_op.create_index("ix_command_receipts_task_id", ["task_id"], unique=False)
        batch_op.create_index("ix_command_receipts_project_name", ["project_name"], unique=False)

    op.create_table(
        "project_events",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=True),
        sa.Column("execution_id", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=True),
        sa.Column("public_payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_schema_version", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.String(length=255), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.CheckConstraint("payload_schema_version >= 1", name="ck_project_events_payload_schema_version"),
        sa.CheckConstraint(f"event_type IN {_PROJECT_EVENT_TYPES}", name="ck_project_events_event_type"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id", name="pk_project_events"),
        sa.UniqueConstraint("user_id", "project_name", "dedupe_key", name="uq_project_events_dedupe_key"),
    )
    with op.batch_alter_table("project_events", schema=None) as batch_op:
        batch_op.create_index("ix_project_events_scope_cursor", ["user_id", "project_name", "event_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("project_events", schema=None) as batch_op:
        batch_op.drop_index("ix_project_events_scope_cursor")
    op.drop_table("project_events")

    with op.batch_alter_table("command_receipts", schema=None) as batch_op:
        batch_op.drop_index("ix_command_receipts_project_name")
        batch_op.drop_index("ix_command_receipts_task_id")
    op.drop_table("command_receipts")

    with op.batch_alter_table("operator_resolution_receipts", schema=None) as batch_op:
        batch_op.drop_index("ix_operator_resolution_receipts_project_name")
        batch_op.drop_index("ix_operator_resolution_receipts_execution_id")
    op.drop_table("operator_resolution_receipts")

    with op.batch_alter_table("attempt_integrity_incidents", schema=None) as batch_op:
        batch_op.drop_index("ix_attempt_integrity_incidents_project_name")
        batch_op.drop_index("ix_attempt_integrity_incidents_execution_id")
    op.drop_table("attempt_integrity_incidents")

    with op.batch_alter_table("provider_observations", schema=None) as batch_op:
        batch_op.drop_index("ix_provider_observations_project_name")
    op.drop_table("provider_observations")

    with op.batch_alter_table("api_calls", schema=None) as batch_op:
        batch_op.drop_constraint("fk_api_calls_execution_attempt", type_="foreignkey")
        batch_op.drop_index("uq_api_calls_execution_id")
        batch_op.drop_column("execution_id")

    with op.batch_alter_table("execution_attempts", schema=None) as batch_op:
        batch_op.drop_index("uq_execution_attempts_provider_job")
        batch_op.drop_index("ix_execution_attempts_project_name")
    op.drop_table("execution_attempts")
