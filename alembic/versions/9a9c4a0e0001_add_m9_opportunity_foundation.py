"""Append-only M9 profiles, CAS heads, command receipts, events and host lease replay."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9a9c4a0e0001"
down_revision: str | Sequence[str] | None = "918c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _owner(table: str) -> sa.Column:
    return sa.Column(
        "user_id",
        sa.String(255),
        sa.ForeignKey("users.id", ondelete="RESTRICT", name=f"fk_{table}_user"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "m9_cohort_profiles",
        _owner("m9_cohort_profiles"),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("parent_revision", sa.Integer(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_digest", sa.String(71), nullable=False),
        sa.Column("profile_digest", sa.String(71), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("custodian_authorization_id", sa.String(36), nullable=False),
        sa.Column("custodian_policy_id", sa.String(255), nullable=False),
        sa.Column("custodian_policy_version", sa.String(255), nullable=False),
        sa.Column("custodian_evidence_digest", sa.String(71), nullable=False),
        sa.Column("custodian_admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "profile_id", "revision", name="pk_m9_cohort_profiles"),
        sa.UniqueConstraint("user_id", "project_name", "profile_digest", name="uq_m9_cohort_profiles_digest"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "profile_id", "parent_revision"],
            [
                "m9_cohort_profiles.user_id",
                "m9_cohort_profiles.project_name",
                "m9_cohort_profiles.profile_id",
                "m9_cohort_profiles.revision",
            ],
            name="fk_m9_cohort_profiles_parent",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_m9_cohort_profiles_revision"),
        sa.CheckConstraint(
            "(revision = 1 AND parent_revision IS NULL) OR (revision > 1 AND parent_revision IS NOT NULL AND parent_revision = revision - 1)",
            name="ck_m9_cohort_profiles_parent",
        ),
    )
    op.create_index("ix_m9_cohort_profiles_scope", "m9_cohort_profiles", ["user_id", "project_name", "profile_id"])
    op.create_table(
        "m9_cohort_profile_heads",
        _owner("m9_cohort_profile_heads"),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("head_version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "profile_id", name="pk_m9_cohort_profile_heads"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "profile_id", "current_revision"],
            [
                "m9_cohort_profiles.user_id",
                "m9_cohort_profiles.project_name",
                "m9_cohort_profiles.profile_id",
                "m9_cohort_profiles.revision",
            ],
            name="fk_m9_cohort_profile_heads_profile",
        ),
        sa.CheckConstraint("current_revision >= 1", name="ck_m9_cohort_profile_heads_revision"),
        sa.CheckConstraint("head_version >= 1", name="ck_m9_cohort_profile_heads_version"),
    )
    op.create_table(
        "m9_command_receipts",
        _owner("m9_command_receipts"),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("command_id", sa.String(36), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("result_kind", sa.String(64), nullable=False),
        sa.Column("result_ref", sa.String(255), nullable=False),
        sa.Column("result_digest", sa.String(71), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "actor_id", "operation", "command_id", name="pk_m9_command_receipts"
        ),
        sa.UniqueConstraint("user_id", "actor_id", "operation", "command_id", name="uq_m9_command_receipts_key"),
    )
    op.create_index(
        "ix_m9_command_receipts_result", "m9_command_receipts", ["user_id", "project_name", "result_kind", "result_ref"]
    )
    op.create_table(
        "m9_events",
        sa.Column("event_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        _owner("m9_events"),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("event_kind", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(36), nullable=False),
        sa.Column("aggregate_revision", sa.Integer(), nullable=False),
        sa.Column("payload_digest", sa.String(71), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id", name="pk_m9_events"),
        sa.CheckConstraint("aggregate_revision >= 1", name="ck_m9_events_revision"),
    )
    op.create_index("ix_m9_events_scope", "m9_events", ["user_id", "project_name", "event_id"])
    op.create_table(
        "host_custodian_leases",
        sa.Column("authorization_id", sa.String(36), nullable=False),
        _owner("host_custodian_leases"),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("command_id", sa.String(36), nullable=False),
        sa.Column("subject_digest", sa.String(71), nullable=False),
        sa.Column("policy_id", sa.String(255), nullable=False),
        sa.Column("policy_version", sa.String(255), nullable=False),
        sa.Column("grant_event_digest", sa.String(71), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("admit_not_after", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("authorization_id", name="pk_host_custodian_leases"),
        sa.UniqueConstraint(
            "user_id", "project_name", "actor_id", "operation", "command_id", name="uq_host_custodian_leases_command"
        ),
        sa.CheckConstraint("admit_not_after > issued_at", name="ck_host_custodian_leases_window"),
    )
    op.create_index("ix_host_custodian_leases_scope", "host_custodian_leases", ["user_id", "project_name", "actor_id"])


def downgrade() -> None:
    op.drop_table("host_custodian_leases")
    op.drop_table("m9_events")
    op.drop_table("m9_command_receipts")
    op.drop_table("m9_cohort_profile_heads")
    op.drop_table("m9_cohort_profiles")
