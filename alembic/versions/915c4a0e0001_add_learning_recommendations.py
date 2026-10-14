"""Add scoped append-only M8-D recommendations, their evidence and Human decisions.

Revision ID: 915c4a0e0001
Revises: 914c4a0e0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "915c4a0e0001"
down_revision: str | Sequence[str] | None = "914c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TERMINAL = sa.text("terminal")
_RECOMMENDATION = [
    "m8_learning_recommendations.user_id",
    "m8_learning_recommendations.project_name",
    "m8_learning_recommendations.recommendation_id",
]


def upgrade() -> None:
    op.create_table(
        "m8_learning_recommendations",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("recommendation_id", sa.String(length=255), nullable=False),
        sa.Column("recommendation_json", sa.JSON(), nullable=False),
        sa.Column("recommendation_digest", sa.String(length=71), nullable=False),
        sa.Column("proposal_key", sa.String(length=71), nullable=False),
        sa.Column("rule", sa.String(length=64), nullable=False),
        sa.Column("evidence_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("command_digest", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "recommendation_id", name="pk_m8_learning_recommendations"),
        sa.UniqueConstraint("user_id", "project_name", "command_id", name="uq_m8_learning_recommendations_command"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_m8_learning_recommendations_proposal",
        "m8_learning_recommendations",
        ["user_id", "project_name", "proposal_key"],
    )
    op.create_table(
        "m8_learning_recommendation_evidence",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("recommendation_id", sa.String(length=255), nullable=False),
        sa.Column("observation_id", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id",
            "project_name",
            "recommendation_id",
            "observation_id",
            name="pk_m8_learning_recommendation_evidence",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "recommendation_id"],
            _RECOMMENDATION,
            name="fk_m8_learning_recommendation_evidence_recommendation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "observation_id"],
            [
                "m8_learning_observations.user_id",
                "m8_learning_observations.project_name",
                "m8_learning_observations.observation_id",
            ],
            name="fk_m8_learning_recommendation_evidence_observation",
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "m8_learning_recommendation_decisions",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("decision_id", sa.String(length=255), nullable=False),
        sa.Column("recommendation_id", sa.String(length=255), nullable=False),
        sa.Column("disposition", sa.String(length=32), nullable=False),
        sa.Column("terminal", sa.Boolean(), nullable=False),
        sa.Column("governed_proposal_ref", sa.String(length=255), nullable=True),
        sa.Column("decision_json", sa.JSON(), nullable=False),
        sa.Column("decision_digest", sa.String(length=71), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("command_digest", sa.String(length=71), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "decision_id", name="pk_m8_learning_recommendation_decisions"
        ),
        sa.UniqueConstraint(
            "user_id", "project_name", "command_id", name="uq_m8_learning_recommendation_decisions_command"
        ),
        sa.CheckConstraint(
            "disposition IN ('ACCEPT', 'REJECT', 'DEFER', 'REQUEST_EXPERIMENT')",
            name="ck_m8_learning_decision_disposition",
        ),
        sa.CheckConstraint("terminal = (disposition IN ('ACCEPT', 'REJECT'))", name="ck_m8_learning_decision_terminal"),
        sa.CheckConstraint(
            "(disposition = 'ACCEPT') = (governed_proposal_ref IS NOT NULL)", name="ck_m8_learning_decision_proposal"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "recommendation_id"],
            _RECOMMENDATION,
            name="fk_m8_learning_recommendation_decisions_recommendation",
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "m8_learning_evaluations",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("request_digest", sa.String(length=71), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("recommendation_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "command_id", name="pk_m8_learning_evaluations"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "uq_m8_learning_recommendation_decisions_terminal",
        "m8_learning_recommendation_decisions",
        ["user_id", "project_name", "recommendation_id"],
        unique=True,
        postgresql_where=_TERMINAL,
        sqlite_where=_TERMINAL,
    )


def downgrade() -> None:
    op.drop_table("m8_learning_evaluations")
    op.drop_index("uq_m8_learning_recommendation_decisions_terminal", table_name="m8_learning_recommendation_decisions")
    op.drop_table("m8_learning_recommendation_decisions")
    op.drop_table("m8_learning_recommendation_evidence")
    op.drop_index("ix_m8_learning_recommendations_proposal", table_name="m8_learning_recommendations")
    op.drop_table("m8_learning_recommendations")
