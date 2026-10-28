"""Persist scoped M10 run-closure custody.

Revision ID: 57f67bae0cb4
Revises: 07fd34535384
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "57f67bae0cb4"
down_revision: str | Sequence[str] | None = "07fd34535384"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABLE = ("m10_quality_human_observations", "m10_quality_runs", "m10_quality_run_commands")
_JSON_COLUMNS = {
    "m10_quality_human_observations": ("observation_json",),
    "m10_quality_runs": ("run_json",),
    "m10_quality_run_commands": ("receipt_json",),
}


def _json_ceilings(table: str, dialect: str) -> list[sa.CheckConstraint]:
    measure = "octet_length(CAST({} AS text))" if dialect == "postgresql" else "length(CAST({} AS BLOB))"
    return [
        sa.CheckConstraint(f"{measure.format(column)} <= 1048576", name=f"ck_{table}_{column}_bytes")
        for column in _JSON_COLUMNS[table]
    ]


def install_immutability(connection: sa.engine.Connection) -> None:
    """Install the migration-owned append-only DDL in the connection's scoped schema."""
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION m10_run_immutable_row() RETURNS trigger
            LANGUAGE plpgsql AS $m10$
            BEGIN
                RAISE EXCEPTION 'M10_IMMUTABLE_RUN_ROW' USING ERRCODE = '23514';
            END;
            $m10$
        """)
        for table in _IMMUTABLE:
            connection.exec_driver_sql(
                f'CREATE TRIGGER "{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION m10_run_immutable_row()"
            )
    elif connection.dialect.name == "sqlite":
        for table in _IMMUTABLE:
            for event, suffix in (("UPDATE", "no_update"), ("DELETE", "no_delete")):
                connection.exec_driver_sql(
                    f'CREATE TRIGGER "{table}_{suffix}" BEFORE {event} ON "{table}" '
                    "BEGIN SELECT RAISE(ABORT, 'M10_IMMUTABLE_RUN_ROW'); END"
                )
    else:
        raise RuntimeError("M10_SCHEMA_CHANGE_REQUIRED")


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        "m10_quality_human_observations",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("observation_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("command_id", sa.String(255), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("grant_event_digest", sa.String(71), nullable=False),
        sa.Column("observation_digest", sa.String(71), nullable=False),
        sa.Column("observation_json", sa.JSON, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "observation_id", name="pk_m10_quality_human_observations"),
        sa.UniqueConstraint(
            "user_id", "project_name", "actor_id", "command_id", name="uq_m10_human_observations_command"
        ),
        *_json_ceilings("m10_quality_human_observations", dialect),
    )
    op.create_table(
        "m10_quality_runs",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("command_id", sa.String(255), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("subject_digest", sa.String(71), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("profile_revision", sa.Integer, nullable=False),
        sa.Column("run_digest", sa.String(71), nullable=False),
        sa.Column("run_json", sa.JSON, nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "run_id", name="pk_m10_quality_runs"),
        sa.UniqueConstraint("user_id", "project_name", "actor_id", "command_id", name="uq_m10_quality_runs_command"),
        *_json_ceilings("m10_quality_runs", dialect),
    )
    op.create_table(
        "m10_quality_run_commands",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("command_id", sa.String(255), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("result_ref", sa.String(255), nullable=False),
        sa.Column("result_digest", sa.String(71), nullable=False),
        sa.Column("receipt_json", sa.JSON, nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "actor_id", "operation", "command_id", name="pk_m10_quality_run_commands"
        ),
        sa.CheckConstraint(
            "operation IN ('RECORD_HUMAN_OBSERVATION', 'COMPLETE_RUN')", name="ck_m10_quality_run_commands_operation"
        ),
        *_json_ceilings("m10_quality_run_commands", dialect),
    )
    op.create_table(
        "m10_quality_run_heads",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("subject_digest", sa.String(71), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("current_run_id", sa.String(36), nullable=False),
        sa.Column("current_run_digest", sa.String(71), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "subject_digest", "profile_id", name="pk_m10_quality_run_heads"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "current_run_id"],
            ["m10_quality_runs.user_id", "m10_quality_runs.project_name", "m10_quality_runs.run_id"],
            name="fk_m10_run_heads_current",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_m10_quality_run_heads_sequence"),
    )
    install_immutability(op.get_bind())


def downgrade() -> None:
    op.drop_table("m10_quality_run_heads")
    for table in reversed(_IMMUTABLE):
        op.drop_table(table)
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("DROP FUNCTION m10_run_immutable_row()"))
