"""Add scoped M8-E format profiles, overlay sets, projection plans and append-only reports.

Revision ID: 916c4a0e0001
Revises: 915c4a0e0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "916c4a0e0001"
down_revision: str | Sequence[str] | None = "915c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLAN = ["m8_format_plans.user_id", "m8_format_plans.project_name", "m8_format_plans.plan_id"]


def _scope() -> list[sa.Column]:
    return [
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
    ]


def _owner() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT")


def upgrade() -> None:
    op.create_table(
        "m8_format_profiles",
        *_scope(),
        sa.Column("profile_ref", sa.String(length=255), nullable=False),
        sa.Column("profile_json", sa.JSON(), nullable=False),
        sa.Column("profile_digest", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "profile_ref", name="pk_m8_format_profiles"),
        _owner(),
    )
    op.create_table(
        "m8_overlay_constraint_sets",
        *_scope(),
        sa.Column("constraint_ref", sa.String(length=255), nullable=False),
        sa.Column("overlay_json", sa.JSON(), nullable=False),
        sa.Column("overlay_digest", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "constraint_ref", name="pk_m8_overlay_constraint_sets"),
        _owner(),
    )
    op.create_table(
        "m8_format_plans",
        *_scope(),
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column("plan_digest", sa.String(length=71), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("profile_ref", sa.String(length=255), nullable=False),
        sa.Column("constraint_ref", sa.String(length=255), nullable=False),
        sa.Column("source_master_id", sa.String(length=255), nullable=False),
        sa.Column("source_master_digest", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "plan_id", name="pk_m8_format_plans"),
        sa.UniqueConstraint("user_id", "project_name", "plan_digest", name="uq_m8_format_plans_digest"),
        _owner(),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "profile_ref"],
            ["m8_format_profiles.user_id", "m8_format_profiles.project_name", "m8_format_profiles.profile_ref"],
            name="fk_m8_format_plans_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "constraint_ref"],
            [
                "m8_overlay_constraint_sets.user_id",
                "m8_overlay_constraint_sets.project_name",
                "m8_overlay_constraint_sets.constraint_ref",
            ],
            name="fk_m8_format_plans_overlay",
            ondelete="RESTRICT",
        ),
    )
    for table, extra in (
        ("m8_format_technical_reports", []),
        (
            "m8_format_semantic_reports",
            [
                sa.Column("reviewer_count", sa.Integer(), nullable=False),
                sa.Column("deviation", sa.String(length=255), nullable=True),
            ],
        ),
    ):
        op.create_table(
            table,
            *_scope(),
            sa.Column("report_id", sa.String(length=255), nullable=False),
            sa.Column("plan_id", sa.String(length=255), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("artifact_digest", sa.String(length=71), nullable=False),
            sa.Column("report_json", sa.JSON(), nullable=False),
            sa.Column("report_digest", sa.String(length=71), nullable=False),
            *extra,
            sa.Column("passed", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("user_id", "project_name", "report_id", name=f"pk_{table}"),
            sa.UniqueConstraint("user_id", "project_name", "plan_id", "sequence", name=f"uq_{table}_sequence"),
            _owner(),
            sa.ForeignKeyConstraint(
                ["user_id", "project_name", "plan_id"], _PLAN, name=f"fk_{table}_plan", ondelete="RESTRICT"
            ),
        )

    op.create_table(
        "m8_format_renders",
        *_scope(),
        sa.Column("execution_id", sa.String(length=255), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column("source_digest", sa.String(length=71), nullable=False),
        sa.Column("argv_json", sa.JSON(), nullable=False),
        sa.Column("ffmpeg_version", sa.String(length=255), nullable=False),
        sa.Column("artifact_digest", sa.String(length=71), nullable=False),
        sa.Column("artifact_ref", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "execution_id", name="pk_m8_format_renders"),
        sa.UniqueConstraint("user_id", "project_name", "command_id", name="uq_m8_format_renders_command"),
        _owner(),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "plan_id"], _PLAN, name="fk_m8_format_renders_plan", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            ["execution_attempts.user_id", "execution_attempts.project_name", "execution_attempts.execution_id"],
            name="fk_m8_format_renders_attempt",
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "m8_format_review_packets",
        *_scope(),
        sa.Column("packet_id", sa.String(length=255), nullable=False),
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column("execution_id", sa.String(length=255), nullable=False),
        sa.Column("artifact_digest", sa.String(length=71), nullable=False),
        sa.Column("artifact_ref", sa.String(length=255), nullable=False),
        sa.Column("source_digest", sa.String(length=71), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=False),
        sa.Column("projection_label", sa.String(length=1), nullable=False),
        sa.Column("reviewer_id", sa.String(length=255), nullable=False),
        sa.Column("review_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("user_id", "project_name", "packet_id", name="pk_m8_format_review_packets"),
        sa.CheckConstraint("projection_label IN ('A', 'B')", name="ck_m8_format_review_packets_label"),
        _owner(),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "plan_id"], _PLAN, name="fk_m8_format_review_packets_plan", ondelete="RESTRICT"
        ),
    )


def downgrade() -> None:
    op.drop_table("m8_format_review_packets")
    op.drop_table("m8_format_renders")
    op.drop_table("m8_format_semantic_reports")
    op.drop_table("m8_format_technical_reports")
    op.drop_table("m8_format_plans")
    op.drop_table("m8_overlay_constraint_sets")
    op.drop_table("m8_format_profiles")
