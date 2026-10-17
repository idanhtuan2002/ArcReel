"""Add the nine scoped M9 acquisition and observation metadata tables."""

import sqlalchemy as sa

from alembic import op

revision = "9b9c4a0e0001"
down_revision = "9a9c4a0e0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "m9_consumed_capability_grants",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("grant_id", sa.String(length=255), nullable=False),
        sa.Column("grant_version", sa.Integer(), nullable=False),
        sa.Column("grant_digest", sa.String(length=71), nullable=False),
        sa.Column("body_json", sa.JSON(), nullable=False),
        sa.CheckConstraint("grant_version >= 1"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "grant_id", "grant_version"),
        sa.UniqueConstraint("user_id", "project_name", "grant_digest"),
    )
    op.create_table(
        "m9_capability_evaluations",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("evaluation_id", sa.String(length=255), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("grant_id", sa.String(length=255), nullable=False),
        sa.Column("grant_version", sa.Integer(), nullable=False),
        sa.Column("evaluation_digest", sa.String(length=71), nullable=False),
        sa.Column("body_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "grant_id", "grant_version"],
            [
                "m9_consumed_capability_grants.user_id",
                "m9_consumed_capability_grants.project_name",
                "m9_consumed_capability_grants.grant_id",
                "m9_consumed_capability_grants.grant_version",
            ],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "evaluation_id"),
        sa.UniqueConstraint("user_id", "project_name", "evaluation_id", "grant_id", "grant_version"),
    )
    op.create_table(
        "m9_source_queries",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("query_id", sa.String(length=255), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("parent_revision", sa.Integer(), nullable=True),
        sa.Column("cohort_profile_id", sa.String(length=255), nullable=False),
        sa.Column("cohort_profile_revision", sa.Integer(), nullable=False),
        sa.Column("capability_grant_id", sa.String(length=255), nullable=False),
        sa.Column("capability_grant_version", sa.Integer(), nullable=False),
        sa.Column("capability_evaluation_id", sa.String(length=255), nullable=False),
        sa.Column("query_digest", sa.String(length=71), nullable=False),
        sa.Column("body_json", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "(revision = 1 AND parent_revision IS NULL) OR (revision > 1 AND parent_revision IS NOT NULL AND parent_revision = revision - 1)",
            name="ck_m9_source_queries_parent",
        ),
        sa.CheckConstraint("revision >= 1"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "capability_evaluation_id", "capability_grant_id", "capability_grant_version"],
            [
                "m9_capability_evaluations.user_id",
                "m9_capability_evaluations.project_name",
                "m9_capability_evaluations.evaluation_id",
                "m9_capability_evaluations.grant_id",
                "m9_capability_evaluations.grant_version",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "cohort_profile_id", "cohort_profile_revision"],
            [
                "m9_cohort_profiles.user_id",
                "m9_cohort_profiles.project_name",
                "m9_cohort_profiles.profile_id",
                "m9_cohort_profiles.revision",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "query_id", "parent_revision"],
            [
                "m9_source_queries.user_id",
                "m9_source_queries.project_name",
                "m9_source_queries.query_id",
                "m9_source_queries.revision",
            ],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "query_id", "revision"),
    )
    op.create_table(
        "m9_acquisition_attempts",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("attempt_id", sa.String(length=255), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("operation", sa.String(length=255), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("request_digest", sa.String(length=71), nullable=False),
        sa.Column("query_id", sa.String(length=255), nullable=False),
        sa.Column("query_revision", sa.Integer(), nullable=False),
        sa.Column("attempt_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=255), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body_json", sa.JSON(), nullable=False),
        sa.CheckConstraint("operation = 'acquire'"),
        sa.CheckConstraint("state IN ('PLANNED','RUNNING','SUCCEEDED','FAILED','OUTCOME_UNKNOWN','NEEDS_OPERATOR')"),
        sa.CheckConstraint("attempt_version >= 1"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "query_id", "query_revision"],
            [
                "m9_source_queries.user_id",
                "m9_source_queries.project_name",
                "m9_source_queries.query_id",
                "m9_source_queries.revision",
            ],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "attempt_id"),
        sa.UniqueConstraint("user_id", "actor_id", "operation", "command_id"),
        sa.UniqueConstraint("user_id", "project_name", "attempt_id", "query_id", "query_revision"),
    )
    op.create_table(
        "m9_source_query_heads",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("query_id", sa.String(length=255), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("head_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("current_revision >= 1 AND head_version >= 1"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "query_id", "current_revision"],
            [
                "m9_source_queries.user_id",
                "m9_source_queries.project_name",
                "m9_source_queries.query_id",
                "m9_source_queries.revision",
            ],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "query_id"),
    )
    op.create_table(
        "m9_snapshot_pages",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("attempt_id", sa.String(length=255), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("body_json", sa.JSON(), nullable=False),
        sa.Column("checkpoint_json", sa.JSON(), nullable=False),
        sa.CheckConstraint("ordinal >= 1 AND ordinal <= 20"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "attempt_id"],
            [
                "m9_acquisition_attempts.user_id",
                "m9_acquisition_attempts.project_name",
                "m9_acquisition_attempts.attempt_id",
            ],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "attempt_id", "ordinal"),
    )
    op.create_table(
        "m9_source_snapshots",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("snapshot_id", sa.String(length=255), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("parent_revision", sa.Integer(), nullable=True),
        sa.Column("attempt_id", sa.String(length=255), nullable=False),
        sa.Column("query_id", sa.String(length=255), nullable=False),
        sa.Column("query_revision", sa.Integer(), nullable=False),
        sa.Column("snapshot_digest", sa.String(length=71), nullable=False),
        sa.Column("body_json", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "(revision = 1 AND parent_revision IS NULL) OR (revision > 1 AND parent_revision IS NOT NULL AND parent_revision = revision - 1)",
            name="ck_m9_source_snapshots_parent",
        ),
        sa.CheckConstraint("revision >= 1"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "attempt_id", "query_id", "query_revision"],
            [
                "m9_acquisition_attempts.user_id",
                "m9_acquisition_attempts.project_name",
                "m9_acquisition_attempts.attempt_id",
                "m9_acquisition_attempts.query_id",
                "m9_acquisition_attempts.query_revision",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "snapshot_id", "parent_revision"],
            [
                "m9_source_snapshots.user_id",
                "m9_source_snapshots.project_name",
                "m9_source_snapshots.snapshot_id",
                "m9_source_snapshots.revision",
            ],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "snapshot_id", "revision"),
        sa.UniqueConstraint("user_id", "project_name", "attempt_id"),
        sa.UniqueConstraint("user_id", "project_name", "snapshot_id", "snapshot_digest"),
    )
    op.create_table(
        "m9_source_observations",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("observation_id", sa.String(length=255), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("parent_revision", sa.Integer(), nullable=True),
        sa.Column("snapshot_id", sa.String(length=255), nullable=False),
        sa.Column("snapshot_digest", sa.String(length=71), nullable=False),
        sa.Column("source_identity_ref", sa.String(length=255), nullable=False),
        sa.Column("observation_digest", sa.String(length=71), nullable=False),
        sa.Column("body_json", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "(revision = 1 AND parent_revision IS NULL) OR (revision > 1 AND parent_revision IS NOT NULL AND parent_revision = revision - 1)",
            name="ck_m9_source_observations_parent",
        ),
        sa.CheckConstraint("revision >= 1"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "observation_id", "parent_revision"],
            [
                "m9_source_observations.user_id",
                "m9_source_observations.project_name",
                "m9_source_observations.observation_id",
                "m9_source_observations.revision",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "snapshot_id", "snapshot_digest"],
            [
                "m9_source_snapshots.user_id",
                "m9_source_snapshots.project_name",
                "m9_source_snapshots.snapshot_id",
                "m9_source_snapshots.snapshot_digest",
            ],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "observation_id", "revision"),
    )
    op.create_table(
        "m9_observation_heads",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("observation_id", sa.String(length=255), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("head_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("current_revision >= 1 AND head_version >= 1"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "observation_id", "current_revision"],
            [
                "m9_source_observations.user_id",
                "m9_source_observations.project_name",
                "m9_source_observations.observation_id",
                "m9_source_observations.revision",
            ],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "observation_id"),
    )


def downgrade() -> None:
    op.drop_table("m9_observation_heads")
    op.drop_table("m9_source_observations")
    op.drop_table("m9_source_snapshots")
    op.drop_table("m9_snapshot_pages")
    op.drop_table("m9_source_query_heads")
    op.drop_table("m9_acquisition_attempts")
    op.drop_table("m9_source_queries")
    op.drop_table("m9_capability_evaluations")
    op.drop_table("m9_consumed_capability_grants")
