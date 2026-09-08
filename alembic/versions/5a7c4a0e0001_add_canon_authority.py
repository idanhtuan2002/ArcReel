"""add canon authority

Revision ID: 5a7c4a0e0001
Revises: c04b7d93e5a1
Create Date: 2026-09-08 08:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5a7c4a0e0001"
down_revision: str | Sequence[str] | None = "c04b7d93e5a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "canon_branches",
        sa.Column("branch_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("branch_type", sa.String(length=32), nullable=False),
        sa.Column("parent_branch_id", sa.String(length=255), nullable=True),
        sa.Column("parent_version_id", sa.String(length=255), nullable=True),
        sa.Column("head_version_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.CheckConstraint("branch_type IN ('MAIN', 'NARRATIVE_BRANCH')", name="ck_canon_branches_branch_type"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_branch_id"],
            ["canon_branches.branch_id"],
            name="fk_canon_branches_parent_branch_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("branch_id"),
    )
    op.create_index(op.f("ix_canon_branches_user_id"), "canon_branches", ["user_id"], unique=False)
    op.create_index("ix_canon_branches_project_name", "canon_branches", ["project_name"], unique=False)
    op.create_index("ix_canon_branches_parent_version_id", "canon_branches", ["parent_version_id"], unique=False)
    op.create_index("ix_canon_branches_head_version_id", "canon_branches", ["head_version_id"], unique=False)
    op.create_index(
        "uq_canon_branches_one_main_per_scope",
        "canon_branches",
        ["user_id", "project_name"],
        unique=True,
        sqlite_where=sa.text("branch_type = 'MAIN'"),
        postgresql_where=sa.text("branch_type = 'MAIN'"),
    )

    op.create_table(
        "canon_deltas",
        sa.Column("canon_delta_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("target_branch_id", sa.String(length=255), nullable=False),
        sa.Column("base_canon_version_id", sa.String(length=255), nullable=True),
        sa.Column("operations_json", sa.JSON(), nullable=False),
        sa.Column("source_change_set_refs_json", sa.JSON(), nullable=False),
        sa.Column("author_decision_refs_json", sa.JSON(), nullable=False),
        sa.Column("validation_report_refs_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=255), nullable=False),
        sa.Column("payload_hash_algorithm", sa.String(length=64), nullable=False),
        sa.Column("payload_hash_version", sa.String(length=64), nullable=False),
        sa.Column("content_schema_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("approval_ref", sa.String(length=255), nullable=False),
        sa.Column("approved_by", sa.String(length=255), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approval_status", sa.String(length=32), nullable=False),
        sa.Column("committed_version_id", sa.String(length=255), nullable=False),
        sa.CheckConstraint("approval_status IN ('APPROVED')", name="ck_canon_deltas_approval_status"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["target_branch_id"],
            ["canon_branches.branch_id"],
            name="fk_canon_deltas_target_branch_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("canon_delta_id"),
        sa.UniqueConstraint("approval_ref", name="uq_canon_deltas_approval_ref"),
    )
    op.create_index(op.f("ix_canon_deltas_user_id"), "canon_deltas", ["user_id"], unique=False)
    op.create_index("ix_canon_deltas_project_name", "canon_deltas", ["project_name"], unique=False)
    op.create_index("ix_canon_deltas_target_branch_id", "canon_deltas", ["target_branch_id"], unique=False)
    op.create_index(
        "ix_canon_deltas_base_canon_version_id",
        "canon_deltas",
        ["base_canon_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_canon_deltas_committed_version_id",
        "canon_deltas",
        ["committed_version_id"],
        unique=False,
    )

    op.create_table(
        "canon_versions",
        sa.Column("canon_version_id", sa.String(length=255), nullable=False),
        sa.Column("branch_id", sa.String(length=255), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.String(length=255), nullable=True),
        sa.Column("committed_delta_id", sa.String(length=255), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_by", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=255), nullable=False),
        sa.Column("content_hash_algorithm", sa.String(length=64), nullable=False),
        sa.Column("content_hash_version", sa.String(length=64), nullable=False),
        sa.Column("content_schema_version", sa.String(length=64), nullable=False),
        sa.CheckConstraint("version_number >= 1", name="ck_canon_versions_version_number_positive"),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["canon_branches.branch_id"],
            name="fk_canon_versions_branch_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"],
            ["canon_versions.canon_version_id"],
            name="fk_canon_versions_parent_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["committed_delta_id"],
            ["canon_deltas.canon_delta_id"],
            name="fk_canon_versions_committed_delta_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("canon_version_id"),
        sa.UniqueConstraint("branch_id", "version_number", name="uq_canon_versions_branch_version_number"),
    )
    op.create_index("ix_canon_versions_branch_id", "canon_versions", ["branch_id"], unique=False)
    op.create_index("ix_canon_versions_parent_version_id", "canon_versions", ["parent_version_id"], unique=False)
    op.create_index(
        "ix_canon_versions_committed_delta_id",
        "canon_versions",
        ["committed_delta_id"],
        unique=False,
    )

    op.create_table(
        "canon_resolved_projections",
        sa.Column("canon_version_id", sa.String(length=255), nullable=False),
        sa.Column("resolved_view_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=255), nullable=False),
        sa.Column("content_hash_algorithm", sa.String(length=64), nullable=False),
        sa.Column("content_hash_version", sa.String(length=64), nullable=False),
        sa.Column("content_schema_version", sa.String(length=64), nullable=False),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["canon_version_id"],
            ["canon_versions.canon_version_id"],
            name="fk_canon_resolved_projections_version_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("canon_version_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("canon_resolved_projections")
    op.drop_index("ix_canon_versions_committed_delta_id", table_name="canon_versions")
    op.drop_index("ix_canon_versions_parent_version_id", table_name="canon_versions")
    op.drop_index("ix_canon_versions_branch_id", table_name="canon_versions")
    op.drop_table("canon_versions")
    op.drop_index("ix_canon_deltas_committed_version_id", table_name="canon_deltas")
    op.drop_index("ix_canon_deltas_base_canon_version_id", table_name="canon_deltas")
    op.drop_index("ix_canon_deltas_target_branch_id", table_name="canon_deltas")
    op.drop_index("ix_canon_deltas_project_name", table_name="canon_deltas")
    op.drop_index(op.f("ix_canon_deltas_user_id"), table_name="canon_deltas")
    op.drop_table("canon_deltas")
    op.drop_index("uq_canon_branches_one_main_per_scope", table_name="canon_branches")
    op.drop_index("ix_canon_branches_head_version_id", table_name="canon_branches")
    op.drop_index("ix_canon_branches_parent_version_id", table_name="canon_branches")
    op.drop_index("ix_canon_branches_project_name", table_name="canon_branches")
    op.drop_index(op.f("ix_canon_branches_user_id"), table_name="canon_branches")
    op.drop_table("canon_branches")
