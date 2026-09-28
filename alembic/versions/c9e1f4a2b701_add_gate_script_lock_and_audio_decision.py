"""add gate script lock decisions and final cut audio decision (ADR-0092)

Revision ID: c9e1f4a2b701
Revises: b8d4f0e2a300
Create Date: 2026-09-28 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9e1f4a2b701"
down_revision: str | Sequence[str] | None = "b8d4f0e2a300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "gate_script_lock_decisions",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("decision_id", sa.String(length=255), nullable=False),
        sa.Column("source_digest", sa.String(length=255), nullable=False),
        sa.Column("script_digest", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("authorization_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_gate_script_lock_decisions_sequence"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "decision_id", name="pk_gate_script_lock_decisions"),
        sa.UniqueConstraint("user_id", "project_name", "sequence", name="uq_gate_script_lock_decisions_sequence"),
    )
    with op.batch_alter_table("gate_final_cut_receipts") as batch:
        batch.add_column(sa.Column("audio_decision", sa.String(length=16), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("gate_final_cut_receipts") as batch:
        batch.drop_column("audio_decision")
    op.drop_table("gate_script_lock_decisions")
