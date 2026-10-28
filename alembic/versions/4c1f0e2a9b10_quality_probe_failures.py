"""Persist known M10 probe failures with their bounded ResourceEvidence.

Revision ID: 4c1f0e2a9b10
Revises: bed415be3608
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4c1f0e2a9b10"
down_revision: str | Sequence[str] | None = "bed415be3608"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "m10_quality_probe_failures"


def install_immutability(connection: sa.engine.Connection) -> None:
    """Install the migration-owned append-only DDL in the connection's scoped schema."""
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION m10_probe_failure_immutable_row() RETURNS trigger
            LANGUAGE plpgsql AS $m10$
            BEGIN
                RAISE EXCEPTION 'M10_IMMUTABLE_PROBE_ROW' USING ERRCODE = '23514';
            END;
            $m10$
        """)
        connection.exec_driver_sql(
            f'CREATE TRIGGER "{_TABLE}_immutable" BEFORE UPDATE OR DELETE ON "{_TABLE}" '
            "FOR EACH ROW EXECUTE FUNCTION m10_probe_failure_immutable_row()"
        )
    elif connection.dialect.name == "sqlite":
        for event, suffix in (("UPDATE", "no_update"), ("DELETE", "no_delete")):
            connection.exec_driver_sql(
                f'CREATE TRIGGER "{_TABLE}_{suffix}" BEFORE {event} ON "{_TABLE}" '
                "BEGIN SELECT RAISE(ABORT, 'M10_IMMUTABLE_PROBE_ROW'); END"
            )
    else:
        raise RuntimeError("M10_SCHEMA_CHANGE_REQUIRED")


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    measure = "octet_length(CAST({} AS text))" if dialect == "postgresql" else "length(CAST({} AS BLOB))"
    op.create_table(
        _TABLE,
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("execution_id", sa.String(255), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=False),
        sa.Column("resources_json", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("resources_digest", sa.String(71), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "execution_id", name="pk_m10_quality_probe_failures"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            [
                "m10_quality_probe_invocations.user_id",
                "m10_quality_probe_invocations.project_name",
                "m10_quality_probe_invocations.execution_id",
            ],
            name="fk_m10_probe_failures_invocation",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "error_code IN ('M10_PROBE_FAILED', 'M10_REFERENCE_INVALID', 'M10_OPERATIONAL_ENVELOPE_EXCEEDED')",
            name="ck_m10_quality_probe_failures_code",
        ),
        sa.CheckConstraint(
            "(resources_json IS NULL) = (resources_digest IS NULL)", name="ck_m10_quality_probe_failures_resources"
        ),
        sa.CheckConstraint(
            f"{measure.format('resources_json')} <= 1048576", name="ck_m10_quality_probe_failures_resources_json_bytes"
        ),
    )
    install_immutability(op.get_bind())


def downgrade() -> None:
    """Refuse rather than discard recorded failure evidence."""
    bind = op.get_bind()
    if bind.execute(sa.text(f"SELECT count(*) FROM {_TABLE}")).scalar_one():
        raise RuntimeError("M10_PROBE_FAILURE_HISTORY_PRESENT")
    op.drop_table(_TABLE)
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP FUNCTION m10_probe_failure_immutable_row()"))
