"""Persist append-only M10-B export invocations bound to M7 attempts, and their export receipts.

Revision ID: 8a5d0f6b1e44
Revises: 7f4c9e5a0d33
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8a5d0f6b1e44"
down_revision: str | Sequence[str] | None = "7f4c9e5a0d33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("m10_export_invocations", "m10_export_receipts")


def _ceiling(table: str, column: str) -> sa.CheckConstraint:
    measure = (
        "octet_length(CAST({} AS text))" if op.get_bind().dialect.name == "postgresql" else "length(CAST({} AS BLOB))"
    )
    return sa.CheckConstraint(f"{measure.format(column)} <= 1048576", name=f"ck_{table}_{column}_bytes")


def install_immutability(connection: sa.engine.Connection) -> None:
    """Install the migration-owned append-only DDL in the connection's scoped schema."""
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION m10_export_immutable_row() RETURNS trigger
            LANGUAGE plpgsql AS $m10$
            BEGIN
                RAISE EXCEPTION 'M10_IMMUTABLE_EXPORT_ROW' USING ERRCODE = '23514';
            END;
            $m10$
        """)
        for table in _TABLES:
            connection.exec_driver_sql(
                f'CREATE TRIGGER "{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION m10_export_immutable_row()"
            )
    elif connection.dialect.name == "sqlite":
        for table in _TABLES:
            for event, suffix in (("UPDATE", "no_update"), ("DELETE", "no_delete")):
                connection.exec_driver_sql(
                    f'CREATE TRIGGER "{table}_{suffix}" BEFORE {event} ON "{table}" '
                    "BEGIN SELECT RAISE(ABORT, 'M10_IMMUTABLE_EXPORT_ROW'); END"
                )
    else:
        raise RuntimeError("M10_SCHEMA_CHANGE_REQUIRED")


def upgrade() -> None:
    op.create_table(
        "m10_export_invocations",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("execution_id", sa.String(255), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("command_id", sa.String(255), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("request_json", sa.JSON, nullable=False),
        sa.Column("selection_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(255), nullable=False),
        sa.Column("manifest_digest", sa.String(71), nullable=False),
        sa.Column("manifest_json", sa.JSON, nullable=False),
        sa.Column("identity_digest", sa.String(71), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "execution_id", name="pk_m10_export_invocations"),
        sa.UniqueConstraint(
            "user_id", "project_name", "actor_id", "command_id", name="uq_m10_export_invocations_command"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "selection_id"],
            [
                "m10_package_selections.user_id",
                "m10_package_selections.project_name",
                "m10_package_selections.selection_id",
            ],
            name="fk_m10_export_invocations_selection",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            ["execution_attempts.user_id", "execution_attempts.project_name", "execution_attempts.execution_id"],
            name="fk_m10_export_invocations_attempt",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        _ceiling("m10_export_invocations", "manifest_json"),
        _ceiling("m10_export_invocations", "request_json"),
    )
    op.create_table(
        "m10_export_receipts",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("receipt_id", sa.String(36), nullable=False),
        sa.Column("execution_id", sa.String(255), nullable=False),
        sa.Column("archive_ref", sa.String(255), nullable=False),
        sa.Column("archive_digest", sa.String(71), nullable=False),
        sa.Column("archive_byte_size", sa.BigInteger, nullable=False),
        sa.Column("receipt_digest", sa.String(71), nullable=False),
        sa.Column("receipt_json", sa.JSON, nullable=False),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "receipt_id", name="pk_m10_export_receipts"),
        sa.UniqueConstraint("user_id", "project_name", "execution_id", name="uq_m10_export_receipts_execution"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            [
                "m10_export_invocations.user_id",
                "m10_export_invocations.project_name",
                "m10_export_invocations.execution_id",
            ],
            name="fk_m10_export_receipts_invocation",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("archive_byte_size > 0", name="ck_m10_export_receipts_size"),
        _ceiling("m10_export_receipts", "receipt_json"),
    )
    install_immutability(op.get_bind())


def downgrade() -> None:
    """Refuse rather than discard export history."""
    bind = op.get_bind()
    for table in _TABLES:
        if bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one():
            raise RuntimeError("M10_EXPORT_HISTORY_PRESENT")
    for table in reversed(_TABLES):
        op.drop_table(table)
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP FUNCTION m10_export_immutable_row()"))
