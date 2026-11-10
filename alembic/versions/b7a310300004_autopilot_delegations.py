"""Append-only autopilot delegation versions (ADR-0124)."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b7a310300004"
down_revision = "b7a310300003"
branch_labels = None
depends_on = None


def install_immutability(connection: sa.Connection) -> None:
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION auto_delegation_immutable() RETURNS trigger LANGUAGE plpgsql AS $auto$
            BEGIN
                RAISE EXCEPTION 'AUTOMATION_DELEGATION_IMMUTABLE' USING ERRCODE = '23514';
            END;
            $auto$
        """)
        connection.exec_driver_sql(
            'CREATE TRIGGER "auto_autopilot_delegations_immutable" BEFORE UPDATE OR DELETE '
            'ON "auto_autopilot_delegations" FOR EACH ROW EXECUTE FUNCTION auto_delegation_immutable()'
        )
    elif connection.dialect.name == "sqlite":
        for event in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f'CREATE TRIGGER "auto_autopilot_delegations_no_{event.lower()}" BEFORE {event} '
                "ON \"auto_autopilot_delegations\" BEGIN SELECT RAISE(ABORT, 'AUTOMATION_DELEGATION_IMMUTABLE'); END"
            )


def upgrade() -> None:
    op.create_table(
        "auto_autopilot_delegations",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("delegation_digest", sa.String(length=71), nullable=False),
        sa.Column("delegation_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_auto_autopilot_version"),
        sa.CheckConstraint("state IN ('ENABLED', 'DISABLED')", name="ck_auto_autopilot_state"),
        sa.CheckConstraint("kind IN ('story', 'film')", name="ck_auto_autopilot_kind"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "version"),
    )
    op.create_index("ix_auto_autopilot_state", "auto_autopilot_delegations", ["state", "user_id", "project_name"])
    install_immutability(op.get_bind())


def downgrade() -> None:
    op.drop_index("ix_auto_autopilot_state", table_name="auto_autopilot_delegations")
    op.drop_table("auto_autopilot_delegations")
