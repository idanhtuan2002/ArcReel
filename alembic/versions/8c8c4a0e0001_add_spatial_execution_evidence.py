"""Add scoped immutable spatial execution evidence.

Revision ID: 8c8c4a0e0001
Revises: 8b8c4a0e0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8c8c4a0e0001"
down_revision: str | Sequence[str] | None = "8b8c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FRAME_RECEIPT = ["m8_spatial_frame_receipts.user_id", "m8_spatial_frame_receipts.project_name"]


def upgrade() -> None:
    op.create_table(
        "m8_spatial_execution_evidence",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("execution_id", sa.String(length=255), nullable=False),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("master_frame_receipt_id", sa.String(length=255), nullable=False),
        sa.Column("reverse_frame_receipt_id", sa.String(length=255), nullable=False),
        sa.Column("evidence_body_json", sa.JSON(), nullable=False),
        sa.Column("evidence_digest", sa.String(length=71), nullable=False),
        sa.Column("raw_response", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "execution_id", name="pk_m8_spatial_execution_evidence"),
        sa.UniqueConstraint(
            "user_id", "project_name", "candidate_id", "revision", name="uq_m8_spatial_execution_evidence_revision"
        ),
        sa.UniqueConstraint("user_id", "project_name", "command_id", name="uq_m8_spatial_execution_evidence_command"),
        sa.CheckConstraint(
            "master_frame_receipt_id <> reverse_frame_receipt_id", name="ck_m8_spatial_execution_evidence_two_views"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            ["execution_attempts.user_id", "execution_attempts.project_name", "execution_attempts.execution_id"],
            name="fk_m8_spatial_execution_evidence_attempt",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "candidate_id", "revision"],
            [
                "m8_candidate_revisions.user_id",
                "m8_candidate_revisions.project_name",
                "m8_candidate_revisions.candidate_id",
                "m8_candidate_revisions.revision",
            ],
            name="fk_m8_spatial_execution_evidence_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "master_frame_receipt_id"],
            [*_FRAME_RECEIPT, "m8_spatial_frame_receipts.receipt_id"],
            name="fk_m8_spatial_execution_evidence_master",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "reverse_frame_receipt_id"],
            [*_FRAME_RECEIPT, "m8_spatial_frame_receipts.receipt_id"],
            name="fk_m8_spatial_execution_evidence_reverse",
            ondelete="RESTRICT",
        ),
    )


def downgrade() -> None:
    op.drop_table("m8_spatial_execution_evidence")
