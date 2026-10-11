"""Add scoped spatial review sessions and frame-delivery evidence.

Revision ID: 901c4a0e0001
Revises: 8f8c4a0e0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "901c4a0e0001"
down_revision: str | Sequence[str] | None = "8f8c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _scope() -> tuple[sa.Column[str], sa.Column[str], sa.Column[str]]:
    return (
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("session_id", sa.String(32), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "m8_spatial_review_sessions",
        *_scope(),
        sa.Column("principal", sa.String(255), nullable=False),
        sa.Column("snapshot_body_json", sa.JSON(), nullable=False),
        sa.Column("snapshot_digest", sa.String(71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_command_digest", sa.String(71), nullable=True),
        sa.PrimaryKeyConstraint("user_id", "project_name", "session_id", name="pk_m8_spatial_review_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_m8_spatial_review_sessions_user", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("created_at < expires_at", name="ck_m8_spatial_review_sessions_window"),
    )
    op.create_table(
        "m8_spatial_review_deliveries",
        *_scope(),
        sa.Column("attempt_id", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("png_digest", sa.String(71), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "session_id", "attempt_id", name="pk_m8_spatial_review_deliveries"
        ),
        sa.UniqueConstraint(
            "user_id",
            "project_name",
            "session_id",
            "attempt_id",
            "role",
            "png_digest",
            name="uq_m8_spatial_review_deliveries_role_digest",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "session_id"],
            [
                "m8_spatial_review_sessions.user_id",
                "m8_spatial_review_sessions.project_name",
                "m8_spatial_review_sessions.session_id",
            ],
            name="fk_m8_spatial_review_deliveries_session",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("role IN ('MASTER','REVERSE')", name="ck_m8_spatial_review_deliveries_role"),
    )
    op.create_table(
        "m8_spatial_review_acknowledgments",
        *_scope(),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("attempt_id", sa.String(255), nullable=False),
        sa.Column("principal", sa.String(255), nullable=False),
        sa.Column("png_digest", sa.String(71), nullable=False),
        sa.Column("decoded", sa.Boolean(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "session_id", "role", name="pk_m8_spatial_review_acknowledgments"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "session_id", "attempt_id", "role", "png_digest"],
            [
                "m8_spatial_review_deliveries.user_id",
                "m8_spatial_review_deliveries.project_name",
                "m8_spatial_review_deliveries.session_id",
                "m8_spatial_review_deliveries.attempt_id",
                "m8_spatial_review_deliveries.role",
                "m8_spatial_review_deliveries.png_digest",
            ],
            name="fk_m8_spatial_review_acknowledgments_delivery",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("role IN ('MASTER','REVERSE')", name="ck_m8_spatial_review_acknowledgments_role"),
        sa.CheckConstraint("decoded", name="ck_m8_spatial_review_acknowledgments_decoded"),
    )


def downgrade() -> None:
    op.drop_table("m8_spatial_review_acknowledgments")
    op.drop_table("m8_spatial_review_deliveries")
    op.drop_table("m8_spatial_review_sessions")
