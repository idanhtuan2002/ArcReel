"""Persist write-ahead owner attempts without command identity, and passing step outcomes."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b7a310300003"
down_revision = "b7a310300002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auto_owner_attempts",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("sub_key", sa.String(length=255), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt >= 0", name="ck_auto_attempt_index"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "run_id"],
            ["auto_production_runs.user_id", "auto_production_runs.project_name", "auto_production_runs.run_id"],
            name="fk_auto_attempt_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id", "project_name", "run_id", "command_id", "sub_key", "attempt"),
    )

    if op.get_bind().dialect.name == "postgresql":
        ceiling = sa.CheckConstraint("octet_length(outcome_json) <= 1048576", name="ck_auto_outcome_json_bytes_pg")
    else:
        ceiling = sa.CheckConstraint(
            "length(CAST(outcome_json AS BLOB)) <= 1048576", name="ck_auto_outcome_json_bytes_sqlite"
        )
    op.create_table(
        "auto_step_outcomes",
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("input_digest", sa.String(length=71), nullable=False),
        sa.Column("outcome_digest", sa.String(length=71), nullable=False),
        sa.Column("outcome_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "run_id", "command_id"],
            [
                "auto_production_steps.user_id",
                "auto_production_steps.project_name",
                "auto_production_steps.run_id",
                "auto_production_steps.command_id",
            ],
            name="fk_auto_outcome_step",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("command_id"),
        ceiling,
    )
    op.create_index("ix_auto_step_outcomes_stage", "auto_step_outcomes", ["user_id", "project_name", "run_id", "stage"])


def downgrade() -> None:
    op.drop_index("ix_auto_step_outcomes_stage", table_name="auto_step_outcomes")
    op.drop_table("auto_step_outcomes")
    op.drop_table("auto_owner_attempts")
