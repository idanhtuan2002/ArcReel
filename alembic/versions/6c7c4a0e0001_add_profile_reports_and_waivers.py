"""add profile reports and waivers

Revision ID: 6c7c4a0e0001
Revises: 6b7c4a0e0001
Create Date: 2026-09-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6c7c4a0e0001"
down_revision: str | Sequence[str] | None = "6b7c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "adaptation_profile_sidecars",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("sidecar_id", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("content_hash", sa.String(length=255), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('WESTERN_DRAMA_ANALYSIS','SHUANGWEN_ANALYSIS')", name="ck_adaptation_profile_sidecars_kind"
        ),
        sa.CheckConstraint("version >= 1", name="ck_adaptation_profile_sidecars_version"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("sidecar_id", "version", name="pk_adaptation_profile_sidecars"),
        sa.UniqueConstraint(
            "user_id", "project_name", "sidecar_id", "version", name="uq_adaptation_profile_sidecars_scope"
        ),
    )
    with op.batch_alter_table("adaptation_profile_sidecars", schema=None) as batch_op:
        batch_op.create_index("ix_adaptation_profile_sidecars_project_name", ["project_name"], unique=False)

    op.create_table(
        "adaptation_evaluation_reports",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("report_digest", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("artifact_hash", sa.String(length=255), nullable=False),
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column("profile_version", sa.String(length=64), nullable=False),
        sa.Column("policy_pack_digest", sa.String(length=255), nullable=False),
        sa.Column("evaluator_version", sa.String(length=64), nullable=False),
        sa.Column("sidecar_ref_id", sa.String(length=255), nullable=False),
        sa.Column("sidecar_ref_version", sa.Integer(), nullable=False),
        sa.Column("sidecar_ref_hash", sa.String(length=255), nullable=False),
        sa.Column("sidecar_digest", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "report_digest", name="pk_adaptation_evaluation_reports"),
    )
    with op.batch_alter_table("adaptation_evaluation_reports", schema=None) as batch_op:
        batch_op.create_index("ix_adaptation_evaluation_reports_project_name", ["project_name"], unique=False)
        batch_op.create_index(
            "ix_adaptation_evaluation_reports_artifact",
            ["user_id", "project_name", "artifact_hash", "profile_id"],
            unique=False,
        )

    op.create_table(
        "adaptation_evaluation_findings",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("report_digest", sa.String(length=255), nullable=False),
        sa.Column("finding_id", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.String(length=255), nullable=False),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column("disposition", sa.String(length=32), nullable=False),
        sa.Column("applicability", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("target_path", sa.String(length=2000), nullable=False),
        sa.Column("source_span", sa.String(length=2000), nullable=False),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("message_params_json", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "disposition IN ('INTEGRITY_BLOCK','PROFILE_BLOCK','ADVISORY','NOT_APPLICABLE')",
            name="ck_adaptation_evaluation_findings_disposition",
        ),
        sa.CheckConstraint("position >= 0", name="ck_adaptation_evaluation_findings_position"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "report_digest"],
            [
                "adaptation_evaluation_reports.user_id",
                "adaptation_evaluation_reports.project_name",
                "adaptation_evaluation_reports.report_digest",
            ],
            name="fk_adaptation_evaluation_findings_report",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "report_digest", "finding_id", name="pk_adaptation_evaluation_findings"
        ),
        sa.UniqueConstraint(
            "user_id",
            "project_name",
            "report_digest",
            "position",
            name="uq_adaptation_evaluation_findings_position",
        ),
    )
    with op.batch_alter_table("adaptation_evaluation_findings", schema=None) as batch_op:
        batch_op.create_index("ix_adaptation_evaluation_findings_project_name", ["project_name"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("adaptation_evaluation_findings", schema=None) as batch_op:
        batch_op.drop_index("ix_adaptation_evaluation_findings_project_name")
    op.drop_table("adaptation_evaluation_findings")

    with op.batch_alter_table("adaptation_evaluation_reports", schema=None) as batch_op:
        batch_op.drop_index("ix_adaptation_evaluation_reports_artifact")
        batch_op.drop_index("ix_adaptation_evaluation_reports_project_name")
    op.drop_table("adaptation_evaluation_reports")

    with op.batch_alter_table("adaptation_profile_sidecars", schema=None) as batch_op:
        batch_op.drop_index("ix_adaptation_profile_sidecars_project_name")
    op.drop_table("adaptation_profile_sidecars")
