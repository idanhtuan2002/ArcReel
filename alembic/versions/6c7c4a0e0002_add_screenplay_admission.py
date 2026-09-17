"""add screenplay admission

Revision ID: 6c7c4a0e0002
Revises: 6c7c4a0e0001
Create Date: 2026-09-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6c7c4a0e0002"
down_revision: str | Sequence[str] | None = "6c7c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "adaptation_screenplay_admissions",
        sa.Column("screenplay_id", sa.String(length=255), nullable=False),
        sa.Column("screenplay_version", sa.Integer(), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("screenplay_content_hash", sa.String(length=255), nullable=False),
        sa.Column("admission_decision_id", sa.String(length=255), nullable=False),
        sa.Column("admission_decision_digest", sa.String(length=255), nullable=False),
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column("profile_version", sa.String(length=64), nullable=False),
        sa.Column("policy_pack_digest", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["admission_decision_id", "user_id", "project_name"],
            ["adaptation_decisions.decision_id", "adaptation_decisions.user_id", "adaptation_decisions.project_name"],
            name="fk_adaptation_screenplay_admissions_decision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "screenplay_id", "screenplay_version"],
            [
                "adaptation_screenplays.user_id",
                "adaptation_screenplays.project_name",
                "adaptation_screenplays.screenplay_id",
                "adaptation_screenplays.version",
            ],
            name="fk_adaptation_screenplay_admissions_screenplay",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("screenplay_id", "screenplay_version", name="pk_adaptation_screenplay_admissions"),
        sa.UniqueConstraint(
            "user_id",
            "project_name",
            "screenplay_id",
            "screenplay_version",
            name="uq_adaptation_screenplay_admissions_scope",
        ),
    )
    with op.batch_alter_table("adaptation_screenplay_admissions", schema=None) as batch_op:
        batch_op.create_index("ix_adaptation_screenplay_admissions_project_name", ["project_name"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("adaptation_screenplay_admissions", schema=None) as batch_op:
        batch_op.drop_index("ix_adaptation_screenplay_admissions_project_name")
    op.drop_table("adaptation_screenplay_admissions")
