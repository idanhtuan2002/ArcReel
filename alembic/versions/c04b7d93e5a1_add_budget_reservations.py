"""add budget reservations

Revision ID: c04b7d93e5a1
Revises: 9f3c7a52d1b4
Create Date: 2026-09-07 16:12:47.740228

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c04b7d93e5a1"
down_revision: str | Sequence[str] | None = "9f3c7a52d1b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "budget_scopes",
        sa.Column("budget_scope_ref", sa.String(length=255), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("authorized_limit", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("reserved_total", sa.Numeric(precision=20, scale=6), server_default="0", nullable=False),
        sa.Column("committed_total", sa.Numeric(precision=20, scale=6), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("authorized_limit >= 0", name="ck_budget_scopes_authorized_limit_nonnegative"),
        sa.CheckConstraint("reserved_total >= 0", name="ck_budget_scopes_reserved_total_nonnegative"),
        sa.CheckConstraint("committed_total >= 0", name="ck_budget_scopes_committed_total_nonnegative"),
        sa.CheckConstraint("version >= 0", name="ck_budget_scopes_version_nonnegative"),
        sa.PrimaryKeyConstraint("budget_scope_ref"),
    )
    op.create_table(
        "budget_reservations",
        sa.Column("reservation_ref", sa.String(length=255), nullable=False),
        sa.Column("budget_scope_ref", sa.String(length=255), nullable=False),
        sa.Column("execution_decision_ref", sa.String(length=255), nullable=False),
        sa.Column("reserved_amount", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cost_record_ref", sa.String(length=255), nullable=True),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.CheckConstraint("reserved_amount > 0", name="ck_budget_reservations_reserved_amount_positive"),
        sa.CheckConstraint(
            "state IN ('ACTIVE', 'CLAIMED', 'RELEASED', 'EXPIRED')",
            name="ck_budget_reservations_state",
        ),
        sa.CheckConstraint("version >= 0", name="ck_budget_reservations_version_nonnegative"),
        sa.ForeignKeyConstraint(
            ["budget_scope_ref"],
            ["budget_scopes.budget_scope_ref"],
            name="fk_budget_reservations_scope_ref",
        ),
        sa.PrimaryKeyConstraint("reservation_ref"),
        sa.UniqueConstraint("execution_decision_ref", name="uq_budget_reservations_execution_decision_ref"),
    )
    with op.batch_alter_table("budget_reservations", schema=None) as batch_op:
        batch_op.create_index("ix_budget_reservations_budget_scope_ref", ["budget_scope_ref"], unique=False)
        batch_op.create_index("ix_budget_reservations_execution_decision_ref", ["execution_decision_ref"], unique=False)
        batch_op.create_index("ix_budget_reservations_cost_record_ref", ["cost_record_ref"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("budget_reservations", schema=None) as batch_op:
        batch_op.drop_index("ix_budget_reservations_cost_record_ref")
        batch_op.drop_index("ix_budget_reservations_execution_decision_ref")
        batch_op.drop_index("ix_budget_reservations_budget_scope_ref")
    op.drop_table("budget_reservations")
    op.drop_table("budget_scopes")
