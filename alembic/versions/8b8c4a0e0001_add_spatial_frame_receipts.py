"""Add scoped immutable source-frame derivation receipts.

Revision ID: 8b8c4a0e0001
Revises: 8a8c4a0e0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8b8c4a0e0001"
down_revision: str | Sequence[str] | None = "8a8c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "m8_spatial_frame_receipts",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("receipt_id", sa.String(length=255), nullable=False),
        sa.Column("frame_candidate_id", sa.String(length=255), nullable=False),
        sa.Column("parent_artifact_key", sa.String(length=255), nullable=False),
        sa.Column("parent_master_version", sa.Integer(), nullable=False),
        sa.Column("parent_candidate_id", sa.String(length=255), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("command_digest", sa.String(length=71), nullable=False),
        sa.Column("frame_byte_size", sa.Integer(), nullable=False),
        sa.Column("frame_probe_digest", sa.String(length=71), nullable=False),
        sa.Column("receipt_body_json", sa.JSON(), nullable=False),
        sa.Column("receipt_digest", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "receipt_id", name="pk_m8_spatial_frame_receipts"),
        sa.UniqueConstraint("user_id", "project_name", "command_id", name="uq_m8_spatial_frame_receipts_command"),
        sa.CheckConstraint("receipt_id = frame_candidate_id", name="ck_m8_spatial_frame_receipts_id_match"),
        sa.CheckConstraint("parent_master_version >= 1", name="ck_m8_spatial_frame_receipts_parent_version"),
        sa.CheckConstraint("frame_byte_size > 0", name="ck_m8_spatial_frame_receipts_byte_size"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "frame_candidate_id"],
            ["candidate_objects.user_id", "candidate_objects.project_name", "candidate_objects.candidate_id"],
            name="fk_m8_spatial_frame_receipts_candidate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "parent_artifact_key", "parent_master_version"],
            [
                "master_head_versions.user_id",
                "master_head_versions.project_name",
                "master_head_versions.artifact_key",
                "master_head_versions.master_version",
            ],
            name="fk_m8_spatial_frame_receipts_parent",
            ondelete="RESTRICT",
        ),
    )


def downgrade() -> None:
    op.drop_table("m8_spatial_frame_receipts")
