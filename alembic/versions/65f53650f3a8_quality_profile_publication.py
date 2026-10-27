"""Persist scoped immutable M10 profile publication evidence.

Revision ID: 65f53650f3a8
Revises: 918c4a0e0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

revision: str = "65f53650f3a8"
down_revision: str | Sequence[str] | None = "918c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABLE = (
    "m10_profile_publication_authorizations",
    "m10_quality_profile_revisions",
    "m10_quality_commands",
    "m10_quality_outbox",
)


def install_immutability(connection: Connection) -> None:
    """Install the migration-owned append-only DDL in the connection's scoped schema."""
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION m10_profile_immutable_row() RETURNS trigger
            LANGUAGE plpgsql AS $m10$
            BEGIN
                RAISE EXCEPTION 'M10_IMMUTABLE_PUBLICATION_ROW' USING ERRCODE = '23514';
            END;
            $m10$
        """)
        for table in _IMMUTABLE:
            connection.exec_driver_sql(
                f'CREATE TRIGGER "{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION m10_profile_immutable_row()"
            )
    elif connection.dialect.name == "sqlite":
        for table in _IMMUTABLE:
            for event, suffix in (("UPDATE", "no_update"), ("DELETE", "no_delete")):
                connection.exec_driver_sql(
                    f'CREATE TRIGGER "{table}_{suffix}" BEFORE {event} ON "{table}" '
                    "BEGIN SELECT RAISE(ABORT, 'M10_IMMUTABLE_PUBLICATION_ROW'); END"
                )
    else:
        raise RuntimeError("M10_SCHEMA_CHANGE_REQUIRED")


def upgrade() -> None:
    op.create_table(
        "m10_quality_profile_heads",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("profile_id", sa.String(255), nullable=False),
        sa.Column("current_revision", sa.Integer, nullable=True),
        sa.Column("current_digest", sa.String(71), nullable=True),
        sa.PrimaryKeyConstraint("user_id", "project_name", "profile_id", name="pk_m10_quality_profile_heads"),
        sa.CheckConstraint(
            "(current_revision IS NULL AND current_digest IS NULL) OR (current_revision IS NOT NULL AND current_revision >= 1 AND current_digest IS NOT NULL)",
            name="ck_m10_profile_heads_current_pair",
        ),
        *(
            [
                sa.ForeignKeyConstraint(
                    ["user_id", "project_name", "profile_id", "current_revision"],
                    [
                        "m10_quality_profile_revisions.user_id",
                        "m10_quality_profile_revisions.project_name",
                        "m10_quality_profile_revisions.profile_id",
                        "m10_quality_profile_revisions.revision",
                    ],
                    name="fk_m10_profile_heads_current",
                    ondelete="RESTRICT",
                    deferrable=True,
                    initially="DEFERRED",
                )
            ]
            if op.get_bind().dialect.name == "sqlite"
            else []
        ),
    )
    op.create_table(
        "m10_profile_publication_authorizations",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("authorization_id", sa.String(255), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("command_id", sa.String(255), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("subject_digest", sa.String(71), nullable=False),
        sa.Column("policy_id", sa.String(255), nullable=False),
        sa.Column("policy_version", sa.String(255), nullable=False),
        sa.Column("evidence_digest", sa.String(71), nullable=False),
        sa.Column("grant_sequence", sa.Integer, nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("admit_not_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_json", sa.JSON, nullable=False),
        sa.Column("lease_json", sa.JSON, nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "authorization_id", name="pk_m10_publication_authorizations"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "actor_id", "grant_sequence"],
            [
                "r2_showrunner_grant_events.user_id",
                "r2_showrunner_grant_events.project_name",
                "r2_showrunner_grant_events.principal",
                "r2_showrunner_grant_events.sequence",
            ],
            name="fk_m10_publication_authorizations_grant",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("action = 'PROFILE_PUBLICATION'", name="ck_m10_publication_authorizations_action"),
        sa.CheckConstraint("grant_sequence >= 1", name="ck_m10_publication_authorizations_grant_sequence"),
        sa.CheckConstraint("admit_not_after > issued_at", name="ck_m10_publication_authorizations_window"),
    )
    op.create_table(
        "m10_quality_profile_revisions",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("profile_id", sa.String(255), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("parent_revision", sa.Integer, nullable=True),
        sa.Column("authorization_id", sa.String(255), nullable=False),
        sa.Column("cohort_id", sa.String(255), nullable=False),
        sa.Column("product_surface", sa.String(255), nullable=False),
        sa.Column("policy_digest", sa.String(71), nullable=False),
        sa.Column("profile_digest", sa.String(71), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body_json", sa.JSON, nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "profile_id", "revision", name="pk_m10_quality_profile_revisions"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "profile_id"],
            [
                "m10_quality_profile_heads.user_id",
                "m10_quality_profile_heads.project_name",
                "m10_quality_profile_heads.profile_id",
            ],
            name="fk_m10_profile_revisions_head",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "profile_id", "parent_revision"],
            [
                "m10_quality_profile_revisions.user_id",
                "m10_quality_profile_revisions.project_name",
                "m10_quality_profile_revisions.profile_id",
                "m10_quality_profile_revisions.revision",
            ],
            name="fk_m10_profile_revisions_parent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "authorization_id"],
            [
                "m10_profile_publication_authorizations.user_id",
                "m10_profile_publication_authorizations.project_name",
                "m10_profile_publication_authorizations.authorization_id",
            ],
            name="fk_m10_profile_revisions_authorization",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_m10_profile_revisions_revision"),
        sa.CheckConstraint(
            "(revision = 1 AND parent_revision IS NULL) OR (revision > 1 AND parent_revision IS NOT NULL AND parent_revision = revision - 1)",
            name="ck_m10_profile_revisions_parent",
        ),
    )
    op.create_table(
        "m10_quality_commands",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("command_id", sa.String(255), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("result_profile_id", sa.String(255), nullable=False),
        sa.Column("result_revision", sa.Integer, nullable=False),
        sa.Column("result_digest", sa.String(71), nullable=False),
        sa.Column("receipt_json", sa.JSON, nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "actor_id", "operation", "command_id", name="pk_m10_quality_commands"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "result_profile_id", "result_revision"],
            [
                "m10_quality_profile_revisions.user_id",
                "m10_quality_profile_revisions.project_name",
                "m10_quality_profile_revisions.profile_id",
                "m10_quality_profile_revisions.revision",
            ],
            name="fk_m10_quality_commands_revision",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("operation = 'PUBLISH_PROFILE'", name="ck_m10_quality_commands_operation"),
        sa.CheckConstraint("result_revision >= 1", name="ck_m10_quality_commands_revision"),
    )
    op.create_table(
        "m10_quality_outbox",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("command_id", sa.String(255), nullable=False),
        sa.Column("profile_id", sa.String(255), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("profile_digest", sa.String(71), nullable=False),
        sa.Column("previous_revision", sa.Integer, nullable=True),
        sa.Column("cohort_id", sa.String(255), nullable=False),
        sa.Column("product_surface", sa.String(255), nullable=False),
        sa.Column("supersession_effect", sa.String(32), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_json", sa.JSON, nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "actor_id", "operation", "command_id", name="pk_m10_quality_outbox"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "actor_id", "operation", "command_id"],
            [
                "m10_quality_commands.user_id",
                "m10_quality_commands.project_name",
                "m10_quality_commands.actor_id",
                "m10_quality_commands.operation",
                "m10_quality_commands.command_id",
            ],
            name="fk_m10_quality_outbox_command",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("operation = 'PUBLISH_PROFILE'", name="ck_m10_quality_outbox_operation"),
        sa.CheckConstraint("revision >= 1", name="ck_m10_quality_outbox_revision"),
        sa.CheckConstraint(
            "(revision = 1 AND previous_revision IS NULL) OR (revision > 1 AND previous_revision IS NOT NULL AND previous_revision = revision - 1)",
            name="ck_m10_quality_outbox_previous",
        ),
        sa.CheckConstraint(
            "supersession_effect IN ('HISTORICAL_ONLY', 'REEVALUATE_CURRENT')",
            name="ck_m10_quality_outbox_supersession",
        ),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_m10_profile_heads_current",
            "m10_quality_profile_heads",
            "m10_quality_profile_revisions",
            ["user_id", "project_name", "profile_id", "current_revision"],
            ["user_id", "project_name", "profile_id", "revision"],
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        )
    install_immutability(op.get_bind())


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("fk_m10_profile_heads_current", "m10_quality_profile_heads", type_="foreignkey")
    else:
        with op.batch_alter_table("m10_quality_profile_heads") as batch:
            batch.drop_constraint("fk_m10_profile_heads_current", type_="foreignkey")
    for table in reversed(_IMMUTABLE):
        op.drop_table(table)
    op.drop_table("m10_quality_profile_heads")
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("DROP FUNCTION m10_profile_immutable_row()"))
