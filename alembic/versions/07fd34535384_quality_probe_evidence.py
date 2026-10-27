"""Persist scoped append-only M10 technical probe custody.

Revision ID: 07fd34535384
Revises: 65f53650f3a8
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "07fd34535384"
down_revision: str | Sequence[str] | None = "65f53650f3a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABLE = (
    "m10_quality_probe_invocations",
    "m10_quality_probe_results",
    "m10_quality_probe_observations",
)
_JSON_COLUMNS = {
    "m10_quality_probe_invocations": ("request_json", "route_json", "provider_request_json", "input_digests_json"),
    "m10_quality_probe_results": ("result_json",),
    "m10_quality_probe_observations": ("observation_json",),
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
            CREATE OR REPLACE FUNCTION m10_probe_immutable_row() RETURNS trigger
            LANGUAGE plpgsql AS $m10$
            BEGIN
                RAISE EXCEPTION 'M10_IMMUTABLE_PROBE_ROW' USING ERRCODE = '23514';
            END;
            $m10$
        """)
        for table in _IMMUTABLE:
            connection.exec_driver_sql(
                f'CREATE TRIGGER "{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION m10_probe_immutable_row()"
            )
    elif connection.dialect.name == "sqlite":
        for table in _IMMUTABLE:
            for event, suffix in (("UPDATE", "no_update"), ("DELETE", "no_delete")):
                connection.exec_driver_sql(
                    f'CREATE TRIGGER "{table}_{suffix}" BEFORE {event} ON "{table}" '
                    "BEGIN SELECT RAISE(ABORT, 'M10_IMMUTABLE_PROBE_ROW'); END"
                )
    else:
        raise RuntimeError("M10_SCHEMA_CHANGE_REQUIRED")


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        "m10_quality_probe_invocations",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("execution_ref", sa.String(255), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("request_json", sa.JSON, nullable=False),
        sa.Column("execution_id", sa.String(255), nullable=False),
        sa.Column("task_id", sa.String(255), nullable=False),
        sa.Column("observation_id", sa.String(36), nullable=False),
        sa.Column("route_json", sa.JSON, nullable=False),
        sa.Column("provider_request_json", sa.JSON, nullable=False),
        sa.Column("config_digest", sa.String(71), nullable=False),
        sa.Column("catalog_digest", sa.String(71), nullable=False),
        sa.Column("tool_identity_digest", sa.String(71), nullable=False),
        sa.Column("input_digests_json", sa.JSON, nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "actor_id", "execution_ref", name="pk_m10_quality_probe_invocations"
        ),
        sa.UniqueConstraint("user_id", "project_name", "execution_id", name="uq_m10_probe_invocations_execution"),
        sa.UniqueConstraint("user_id", "project_name", "observation_id", name="uq_m10_probe_invocations_observation"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            ["execution_attempts.user_id", "execution_attempts.project_name", "execution_attempts.execution_id"],
            name="fk_m10_probe_invocations_attempt",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        *_json_ceilings("m10_quality_probe_invocations", dialect),
    )
    op.create_table(
        "m10_quality_probe_results",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("execution_id", sa.String(255), nullable=False),
        sa.Column("result_digest", sa.String(71), nullable=False),
        sa.Column("measurement_digest", sa.String(71), nullable=False),
        sa.Column("result_json", sa.JSON, nullable=False),
        sa.Column("staged_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "execution_id", name="pk_m10_quality_probe_results"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            [
                "m10_quality_probe_invocations.user_id",
                "m10_quality_probe_invocations.project_name",
                "m10_quality_probe_invocations.execution_id",
            ],
            name="fk_m10_probe_results_invocation",
            ondelete="RESTRICT",
        ),
        *_json_ceilings("m10_quality_probe_results", dialect),
    )
    op.create_table(
        "m10_quality_probe_observations",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("observation_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("execution_ref", sa.String(255), nullable=False),
        sa.Column("execution_id", sa.String(255), nullable=False),
        sa.Column("observation_digest", sa.String(71), nullable=False),
        sa.Column("observation_json", sa.JSON, nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "observation_id", name="pk_m10_quality_probe_observations"),
        sa.UniqueConstraint(
            "user_id", "project_name", "actor_id", "execution_ref", name="uq_m10_probe_observations_invocation"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "actor_id", "execution_ref"],
            [
                "m10_quality_probe_invocations.user_id",
                "m10_quality_probe_invocations.project_name",
                "m10_quality_probe_invocations.actor_id",
                "m10_quality_probe_invocations.execution_ref",
            ],
            name="fk_m10_probe_observations_invocation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "observation_id"],
            [
                "m10_quality_probe_invocations.user_id",
                "m10_quality_probe_invocations.project_name",
                "m10_quality_probe_invocations.observation_id",
            ],
            name="fk_m10_probe_observations_reserved_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            [
                "m10_quality_probe_results.user_id",
                "m10_quality_probe_results.project_name",
                "m10_quality_probe_results.execution_id",
            ],
            name="fk_m10_probe_observations_result",
            ondelete="RESTRICT",
        ),
        *_json_ceilings("m10_quality_probe_observations", dialect),
    )
    install_immutability(op.get_bind())


def downgrade() -> None:
    for table in reversed(_IMMUTABLE):
        op.drop_table(table)
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("DROP FUNCTION m10_probe_immutable_row()"))
