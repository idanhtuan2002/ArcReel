"""add gate a-d receipt tables

Revision ID: d80b64c4edcf
Revises: 7b7c4a0e0001
Create Date: 2026-09-22 10:31:01.813338

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d80b64c4edcf"
down_revision: str | Sequence[str] | None = "7b7c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "gate_greenlight_decisions",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("decision_id", sa.String(length=255), nullable=False),
        sa.Column("source_digest", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("authorization_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_gate_greenlight_decisions_sequence"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "decision_id", name="pk_gate_greenlight_decisions"),
        sa.UniqueConstraint("user_id", "project_name", "sequence", name="uq_gate_greenlight_decisions_sequence"),
    )

    op.create_table(
        "gate_publish_approval_decisions",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("decision_id", sa.String(length=255), nullable=False),
        sa.Column("deliverable_digest", sa.String(length=255), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("visibility", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("authorization_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_gate_publish_approval_decisions_sequence"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "decision_id", name="pk_gate_publish_approval_decisions"),
        sa.UniqueConstraint("user_id", "project_name", "sequence", name="uq_gate_publish_approval_decisions_sequence"),
    )

    op.create_table(
        "gate_final_cut_receipts",
        sa.Column("final_cut_receipt_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("artifact_key", sa.String(length=255), nullable=False),
        sa.Column("selected_candidate_id", sa.String(length=255), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("approval_record", sa.String(length=255), nullable=False),
        sa.Column("selected_by", sa.String(length=255), nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_gate_final_cut_receipts_sequence"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("final_cut_receipt_id", name="pk_gate_final_cut_receipts"),
        sa.UniqueConstraint(
            "user_id",
            "project_name",
            "artifact_key",
            "sequence",
            name="uq_gate_final_cut_receipts_scope_sequence",
        ),
    )
    with op.batch_alter_table("gate_final_cut_receipts", schema=None) as batch_op:
        batch_op.create_index(
            "ix_gate_final_cut_receipts_scope", ["user_id", "project_name", "artifact_key"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("gate_final_cut_receipts", schema=None) as batch_op:
        batch_op.drop_index("ix_gate_final_cut_receipts_scope")
    op.drop_table("gate_final_cut_receipts")

    op.drop_table("gate_publish_approval_decisions")

    op.drop_table("gate_greenlight_decisions")
