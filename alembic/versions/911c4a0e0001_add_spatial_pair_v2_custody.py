"""Add scoped V2 pair decision and review session custody.

Revision ID: 911c4a0e0001
Revises: 901c4a0e0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "911c4a0e0001"
down_revision: str | Sequence[str] | None = "901c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "m8_spatial_pair_v2_custody",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("pair_id", sa.String(255), nullable=False),
        sa.Column("pair_version", sa.Integer(), nullable=False),
        sa.Column("review_session_id", sa.String(32), nullable=False),
        sa.Column("review_evidence_digest", sa.String(71), nullable=False),
        sa.Column("decision_digest", sa.String(71), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "pair_id", "pair_version", name="pk_m8_spatial_pair_v2_custody"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "pair_id", "pair_version"],
            [
                "m8_spatial_pair_decisions.user_id",
                "m8_spatial_pair_decisions.project_name",
                "m8_spatial_pair_decisions.pair_id",
                "m8_spatial_pair_decisions.pair_version",
            ],
            name="fk_m8_spatial_pair_v2_custody_decision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "review_session_id"],
            [
                "m8_spatial_review_sessions.user_id",
                "m8_spatial_review_sessions.project_name",
                "m8_spatial_review_sessions.session_id",
            ],
            name="fk_m8_spatial_pair_v2_custody_session",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("pair_version >= 1", name="ck_m8_spatial_pair_v2_custody_version"),
        sa.UniqueConstraint(
            "user_id", "project_name", "review_session_id", name="uq_m8_spatial_pair_v2_custody_session"
        ),
    )


def downgrade() -> None:
    op.drop_table("m8_spatial_pair_v2_custody")
