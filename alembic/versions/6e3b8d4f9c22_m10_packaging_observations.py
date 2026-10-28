"""Persist append-only M10-B package-scoped packaging observations.

Revision ID: 6e3b8d4f9c22
Revises: 5d2a7c3e8b11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6e3b8d4f9c22"
down_revision: str | Sequence[str] | None = "5d2a7c3e8b11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "m10_packaging_observations"


def install_immutability(connection: sa.engine.Connection) -> None:
    """Install the migration-owned append-only DDL in the connection's scoped schema."""
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION m10_packaging_observation_immutable_row() RETURNS trigger
            LANGUAGE plpgsql AS $m10$
            BEGIN
                RAISE EXCEPTION 'M10_IMMUTABLE_PACKAGING_ROW' USING ERRCODE = '23514';
            END;
            $m10$
        """)
        connection.exec_driver_sql(
            f'CREATE TRIGGER "{_TABLE}_immutable" BEFORE UPDATE OR DELETE ON "{_TABLE}" '
            "FOR EACH ROW EXECUTE FUNCTION m10_packaging_observation_immutable_row()"
        )
    elif connection.dialect.name == "sqlite":
        for event, suffix in (("UPDATE", "no_update"), ("DELETE", "no_delete")):
            connection.exec_driver_sql(
                f'CREATE TRIGGER "{_TABLE}_{suffix}" BEFORE {event} ON "{_TABLE}" '
                "BEGIN SELECT RAISE(ABORT, 'M10_IMMUTABLE_PACKAGING_ROW'); END"
            )
    else:
        raise RuntimeError("M10_SCHEMA_CHANGE_REQUIRED")


def upgrade() -> None:
    measure = (
        "octet_length(CAST({} AS text))" if op.get_bind().dialect.name == "postgresql" else "length(CAST({} AS BLOB))"
    )
    op.create_table(
        _TABLE,
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("observation_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("command_id", sa.String(255), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("candidate_id", sa.String(255), nullable=False),
        sa.Column("candidate_revision", sa.Integer, nullable=False),
        sa.Column("candidate_payload_digest", sa.String(71), nullable=False),
        sa.Column("quality_run_id", sa.String(36), nullable=False),
        sa.Column("constraint_snapshot_digest", sa.String(71), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("observation_digest", sa.String(71), nullable=False),
        sa.Column("observation_json", sa.JSON, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "observation_id", name="pk_m10_packaging_observations"),
        sa.UniqueConstraint(
            "user_id", "project_name", "actor_id", "command_id", name="uq_m10_packaging_observations_command"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "candidate_id", "candidate_revision"],
            [
                "m8_candidate_revisions.user_id",
                "m8_candidate_revisions.project_name",
                "m8_candidate_revisions.candidate_id",
                "m8_candidate_revisions.revision",
            ],
            name="fk_m10_packaging_observations_revision",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("status IN ('PASS', 'FAIL')", name="ck_m10_packaging_observations_status"),
        sa.CheckConstraint(
            f"{measure.format('observation_json')} <= 1048576",
            name="ck_m10_packaging_observations_observation_json_bytes",
        ),
    )
    install_immutability(op.get_bind())


def downgrade() -> None:
    """Refuse rather than discard recorded packaging observations."""
    bind = op.get_bind()
    if bind.execute(sa.text(f"SELECT count(*) FROM {_TABLE}")).scalar_one():
        raise RuntimeError("M10_PACKAGING_HISTORY_PRESENT")
    op.drop_table(_TABLE)
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP FUNCTION m10_packaging_observation_immutable_row()"))
