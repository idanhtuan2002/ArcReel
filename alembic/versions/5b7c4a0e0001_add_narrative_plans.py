"""add narrative plans

Revision ID: 5b7c4a0e0001
Revises: 5a7c4a0e0001
Create Date: 2026-09-08 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b7c4a0e0001"
down_revision: str | Sequence[str] | None = "5a7c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "narrative_plans",
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("head_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.CheckConstraint(
            "head_version IS NULL OR head_version >= 1", name="ck_narrative_plans_head_version_positive"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plan_id"),
    )
    op.create_index(op.f("ix_narrative_plans_user_id"), "narrative_plans", ["user_id"], unique=False)
    op.create_index("ix_narrative_plans_project_name", "narrative_plans", ["project_name"], unique=False)

    op.create_table(
        "narrative_plan_versions",
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("plan_revision_id", sa.String(length=255), nullable=False),
        sa.Column("parent_version", sa.Integer(), nullable=True),
        sa.Column("canon_branch_id", sa.String(length=255), nullable=False),
        sa.Column("canon_version_id", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=255), nullable=False),
        sa.Column("content_hash_algorithm", sa.String(length=64), nullable=False),
        sa.Column("content_hash_version", sa.String(length=64), nullable=False),
        sa.Column("approval_ref", sa.String(length=255), nullable=False),
        sa.Column("approved_by", sa.String(length=255), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approval_status", sa.String(length=32), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_by", sa.String(length=255), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_narrative_plan_versions_version_positive"),
        sa.CheckConstraint("approval_status IN ('APPROVED')", name="ck_narrative_plan_versions_approval_status"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["narrative_plans.plan_id"],
            name="fk_narrative_plan_versions_plan_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id", "parent_version"],
            ["narrative_plan_versions.plan_id", "narrative_plan_versions.version"],
            name="fk_narrative_plan_versions_parent",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("plan_id", "version"),
        sa.UniqueConstraint("plan_id", "version", name="uq_narrative_plan_versions_plan_version"),
        sa.UniqueConstraint("plan_revision_id", name="uq_narrative_plan_versions_plan_revision_id"),
        sa.UniqueConstraint("approval_ref", name="uq_narrative_plan_versions_approval_ref"),
    )
    op.create_index(op.f("ix_narrative_plan_versions_user_id"), "narrative_plan_versions", ["user_id"], unique=False)
    op.create_index(
        "ix_narrative_plan_versions_project_name", "narrative_plan_versions", ["project_name"], unique=False
    )
    op.create_index("ix_narrative_plan_versions_plan_id", "narrative_plan_versions", ["plan_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_narrative_plan_versions_plan_id", table_name="narrative_plan_versions")
    op.drop_index("ix_narrative_plan_versions_project_name", table_name="narrative_plan_versions")
    op.drop_index(op.f("ix_narrative_plan_versions_user_id"), table_name="narrative_plan_versions")
    op.drop_table("narrative_plan_versions")
    op.drop_index("ix_narrative_plans_project_name", table_name="narrative_plans")
    op.drop_index(op.f("ix_narrative_plans_user_id"), table_name="narrative_plans")
    op.drop_table("narrative_plans")
