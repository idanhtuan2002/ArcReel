"""Persist scoped M10 Human disposition custody.

Revision ID: bed415be3608
Revises: 57f67bae0cb4
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "bed415be3608"
down_revision: str | Sequence[str] | None = "57f67bae0cb4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABLE = (
    "m10_disposition_authorizations",
    "m10_quality_dispositions",
    "m10_disposition_commands",
    "m10_disposition_outbox",
)
_JSON_COLUMNS = {
    "m10_disposition_authorizations": ("lease_json",),
    "m10_quality_dispositions": ("disposition_json",),
    "m10_disposition_commands": ("receipt_json",),
    "m10_disposition_outbox": ("event_json",),
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
            CREATE OR REPLACE FUNCTION m10_disposition_immutable_row() RETURNS trigger
            LANGUAGE plpgsql AS $m10$
            BEGIN
                RAISE EXCEPTION 'M10_IMMUTABLE_DISPOSITION_ROW' USING ERRCODE = '23514';
            END;
            $m10$
        """)
        for table in _IMMUTABLE:
            connection.exec_driver_sql(
                f'CREATE TRIGGER "{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION m10_disposition_immutable_row()"
            )
    elif connection.dialect.name == "sqlite":
        for table in _IMMUTABLE:
            for event, suffix in (("UPDATE", "no_update"), ("DELETE", "no_delete")):
                connection.exec_driver_sql(
                    f'CREATE TRIGGER "{table}_{suffix}" BEFORE {event} ON "{table}" '
                    "BEGIN SELECT RAISE(ABORT, 'M10_IMMUTABLE_DISPOSITION_ROW'); END"
                )
    else:
        raise RuntimeError("M10_SCHEMA_CHANGE_REQUIRED")


def _user() -> sa.Column:
    return sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        "m10_disposition_authorizations",
        _user(),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("authorization_id", sa.String(255), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("command_id", sa.String(255), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("subject_digest", sa.String(71), nullable=False),
        sa.Column("grant_sequence", sa.Integer, nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("admit_not_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_json", sa.JSON, nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "authorization_id", name="pk_m10_disposition_authorizations"
        ),
        sa.CheckConstraint("grant_sequence >= 1", name="ck_m10_disposition_authorizations_grant"),
        sa.CheckConstraint("admit_not_after > issued_at", name="ck_m10_disposition_authorizations_window"),
        *_json_ceilings("m10_disposition_authorizations", dialect),
    )
    op.create_table(
        "m10_quality_dispositions",
        _user(),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("disposition_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("command_id", sa.String(255), nullable=False),
        sa.Column("authorization_id", sa.String(255), nullable=False),
        sa.Column("subject_digest", sa.String(71), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("quality_run_id", sa.String(36), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("disposition_digest", sa.String(71), nullable=False),
        sa.Column("disposition_json", sa.JSON, nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "disposition_id", name="pk_m10_quality_dispositions"),
        sa.UniqueConstraint("user_id", "project_name", "actor_id", "command_id", name="uq_m10_dispositions_command"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "authorization_id"],
            [
                "m10_disposition_authorizations.user_id",
                "m10_disposition_authorizations.project_name",
                "m10_disposition_authorizations.authorization_id",
            ],
            name="fk_m10_dispositions_authorization",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("decision IN ('PASS', 'REWORK', 'WAIVE')", name="ck_m10_dispositions_decision"),
        *_json_ceilings("m10_quality_dispositions", dialect),
    )
    op.create_table(
        "m10_disposition_commands",
        _user(),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("command_id", sa.String(255), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("result_ref", sa.String(36), nullable=False),
        sa.Column("result_digest", sa.String(71), nullable=False),
        sa.Column("receipt_json", sa.JSON, nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "actor_id", "command_id", name="pk_m10_disposition_commands"
        ),
        *_json_ceilings("m10_disposition_commands", dialect),
    )
    op.create_table(
        "m10_disposition_outbox",
        _user(),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("disposition_id", sa.String(36), nullable=False),
        sa.Column("event_json", sa.JSON, nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "disposition_id", name="pk_m10_disposition_outbox"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "disposition_id"],
            [
                "m10_quality_dispositions.user_id",
                "m10_quality_dispositions.project_name",
                "m10_quality_dispositions.disposition_id",
            ],
            name="fk_m10_disposition_outbox_disposition",
            ondelete="RESTRICT",
        ),
        *_json_ceilings("m10_disposition_outbox", dialect),
    )
    op.create_table(
        "m10_disposition_heads",
        _user(),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("subject_digest", sa.String(71), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("current_disposition_id", sa.String(36), nullable=False),
        sa.Column("current_digest", sa.String(71), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "subject_digest", "profile_id", name="pk_m10_disposition_heads"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "current_disposition_id"],
            [
                "m10_quality_dispositions.user_id",
                "m10_quality_dispositions.project_name",
                "m10_quality_dispositions.disposition_id",
            ],
            name="fk_m10_disposition_heads_current",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("version >= 1", name="ck_m10_disposition_heads_version"),
    )
    install_immutability(op.get_bind())


def downgrade() -> None:
    op.drop_table("m10_disposition_heads")
    for table in reversed(_IMMUTABLE):
        op.drop_table(table)
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("DROP FUNCTION m10_disposition_immutable_row()"))
