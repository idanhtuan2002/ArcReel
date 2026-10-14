"""Add scoped append-only M8-D learning observations with a linear correction chain.

Revision ID: 914c4a0e0001
Revises: 913c4a0e0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "914c4a0e0001"
down_revision: str | Sequence[str] | None = "913c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORIGINAL = sa.text("correction_of IS NULL")


def upgrade() -> None:
    op.create_table(
        "m8_learning_observations",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("observation_id", sa.String(length=255), nullable=False),
        sa.Column("source_family", sa.String(length=255), nullable=False),
        sa.Column("source_record_id", sa.String(length=255), nullable=False),
        sa.Column("metric_name", sa.String(length=255), nullable=False),
        sa.Column("metric_definition_version", sa.String(length=255), nullable=False),
        sa.Column("window_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_timezone_name", sa.String(length=64), nullable=False),
        sa.Column("window_aggregation", sa.String(length=64), nullable=False),
        sa.Column("has_value", sa.Boolean(), nullable=False),
        sa.Column("missing_reason", sa.String(length=32), nullable=True),
        sa.Column("correction_of", sa.String(length=255), nullable=True),
        sa.Column("observation_json", sa.JSON(), nullable=False),
        sa.Column("observation_digest", sa.String(length=71), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("command_digest", sa.String(length=71), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "observation_id", name="pk_m8_learning_observations"),
        sa.UniqueConstraint("user_id", "project_name", "command_id", name="uq_m8_learning_observations_command"),
        sa.UniqueConstraint("user_id", "project_name", "correction_of", name="uq_m8_learning_observations_successor"),
        sa.CheckConstraint("correction_of IS NULL OR correction_of <> observation_id", name="ck_m8_learning_not_self"),
        sa.CheckConstraint("window_starts_at < window_ends_at", name="ck_m8_learning_window"),
        sa.CheckConstraint(
            "(has_value AND missing_reason IS NULL) OR (NOT has_value AND missing_reason IN "
            "('MISSING', 'PRIVATE', 'DELETED', 'NOT_YET_AVAILABLE'))",
            name="ck_m8_learning_value_or_reason",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "correction_of"],
            [
                "m8_learning_observations.user_id",
                "m8_learning_observations.project_name",
                "m8_learning_observations.observation_id",
            ],
            name="fk_m8_learning_observations_predecessor",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "uq_m8_learning_observations_original",
        "m8_learning_observations",
        [
            "user_id",
            "project_name",
            "source_family",
            "source_record_id",
            "metric_name",
            "metric_definition_version",
            "window_starts_at",
            "window_ends_at",
            "window_timezone_name",
            "window_aggregation",
        ],
        unique=True,
        postgresql_where=_ORIGINAL,
        sqlite_where=_ORIGINAL,
    )
    op.create_index(
        "ix_m8_learning_observations_ingested", "m8_learning_observations", ["user_id", "project_name", "ingested_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_m8_learning_observations_ingested", table_name="m8_learning_observations")
    op.drop_index("uq_m8_learning_observations_original", table_name="m8_learning_observations")
    op.drop_table("m8_learning_observations")
