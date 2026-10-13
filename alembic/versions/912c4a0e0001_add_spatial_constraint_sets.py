"""Add scoped immutable spatial constraint sets.

Revision ID: 912c4a0e0001
Revises: 911c4a0e0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "912c4a0e0001"
down_revision: str | Sequence[str] | None = "911c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RECEIPT = ["m8_spatial_frame_receipts.user_id", "m8_spatial_frame_receipts.project_name"]


def upgrade() -> None:
    op.create_table(
        "m8_spatial_constraint_sets",
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("set_id", sa.String(255), nullable=False),
        sa.Column("set_digest", sa.String(71), nullable=False),
        sa.Column("binding_id", sa.String(255), nullable=False),
        sa.Column("master_receipt_id", sa.String(255), nullable=False),
        sa.Column("reverse_receipt_id", sa.String(255), nullable=False),
        sa.Column("body_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "set_id", name="pk_m8_spatial_constraint_sets"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "binding_id"],
            [
                "production_binding_heads.user_id",
                "production_binding_heads.project_name",
                "production_binding_heads.binding_id",
            ],
            name="fk_m8_spatial_constraint_sets_binding",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "master_receipt_id"],
            [*_RECEIPT, "m8_spatial_frame_receipts.receipt_id"],
            name="fk_m8_spatial_constraint_sets_master",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "reverse_receipt_id"],
            [*_RECEIPT, "m8_spatial_frame_receipts.receipt_id"],
            name="fk_m8_spatial_constraint_sets_reverse",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("master_receipt_id <> reverse_receipt_id", name="ck_m8_spatial_constraint_sets_two_views"),
        sa.CheckConstraint("substr(set_id, 5) = substr(set_digest, 8)", name="ck_m8_spatial_constraint_sets_id_digest"),
    )


def downgrade() -> None:
    op.drop_table("m8_spatial_constraint_sets")
