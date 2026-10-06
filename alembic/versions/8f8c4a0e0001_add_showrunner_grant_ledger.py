"""Add scoped Showrunner grant heads and signed event history.

Revision ID: 8f8c4a0e0001
Revises: 8e8c4a0e0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8f8c4a0e0001"
down_revision: str | Sequence[str] | None = "8e8c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _user_id() -> sa.Column[str]:
    return sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "r2_showrunner_grant_heads",
        _user_id(),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("principal", sa.String(255), nullable=False),
        sa.Column("current_sequence", sa.Integer(), nullable=True),
        sa.Column("current_event_digest", sa.String(71), nullable=True),
        sa.PrimaryKeyConstraint("user_id", "project_name", "principal", name="pk_r2_showrunner_grant_heads"),
        sa.CheckConstraint(
            "(current_sequence IS NULL AND current_event_digest IS NULL) OR "
            "(current_sequence >= 1 AND current_event_digest IS NOT NULL)",
            name="ck_r2_showrunner_grant_heads_current_pair",
        ),
    )
    op.create_table(
        "r2_showrunner_grant_events",
        _user_id(),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("principal", sa.String(255), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("raw_event", sa.LargeBinary(), nullable=False),
        sa.Column("event_digest", sa.String(71), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("issued_at", sa.String(20), nullable=False),
        sa.Column("signer_key_id", sa.String(255), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "principal", "sequence", name="pk_r2_showrunner_grant_events"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "principal"],
            [
                "r2_showrunner_grant_heads.user_id",
                "r2_showrunner_grant_heads.project_name",
                "r2_showrunner_grant_heads.principal",
            ],
            name="fk_r2_showrunner_grant_events_head",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_r2_showrunner_grant_events_sequence"),
        sa.CheckConstraint("event_type IN ('ISSUE','REVOKE')", name="ck_r2_showrunner_grant_events_type"),
    )
    with op.batch_alter_table("r2_showrunner_grant_heads") as batch_op:
        batch_op.create_foreign_key(
            "fk_r2_showrunner_grant_heads_current",
            "r2_showrunner_grant_events",
            ["user_id", "project_name", "principal", "current_sequence"],
            ["user_id", "project_name", "principal", "sequence"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("r2_showrunner_grant_heads") as batch_op:
        batch_op.drop_constraint("fk_r2_showrunner_grant_heads_current", type_="foreignkey")
    op.drop_table("r2_showrunner_grant_events")
    op.drop_table("r2_showrunner_grant_heads")
