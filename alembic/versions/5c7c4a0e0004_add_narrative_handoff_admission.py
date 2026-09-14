"""add narrative handoff admission

Revision ID: 5c7c4a0e0004
Revises: 5c7c4a0e0003
Create Date: 2026-09-14 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c7c4a0e0004"
down_revision: str | Sequence[str] | None = "5c7c4a0e0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "narrative_handoff_admissions",
        sa.Column("admission_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column("scene_contract_id", sa.String(length=255), nullable=False),
        sa.Column("canon_branch_id", sa.String(length=255), nullable=False),
        sa.Column("compilation_attempt_id", sa.String(length=255), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("compilation_result_id", sa.String(length=255), nullable=False),
        sa.Column("canon_delta_id", sa.String(length=255), nullable=False),
        sa.Column("canon_delta_payload_hash", sa.String(length=255), nullable=False),
        sa.Column("canon_commit_approval_ref", sa.String(length=255), nullable=False),
        sa.Column("canon_commit_approval_json", sa.JSON(), nullable=False),
        sa.Column("canon_commit_approval_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("canon_commit_approval_fingerprint_algorithm", sa.String(length=64), nullable=False),
        sa.Column("canon_commit_approval_fingerprint_version", sa.String(length=64), nullable=False),
        sa.Column("revision_acceptance_decision_id", sa.String(length=255), nullable=False),
        sa.Column("review_decision_ids_json", sa.JSON(), nullable=False),
        sa.Column("conflict_resolution_decision_ids_json", sa.JSON(), nullable=False),
        sa.Column("base_canon_version_id", sa.String(length=255), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canonical_identity_hash", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint("generation >= 0", name="ck_narrative_handoff_admissions_generation"),
        sa.CheckConstraint(
            "canon_commit_approval_fingerprint_algorithm IN ('sha256')",
            name="ck_narrative_handoff_admissions_fingerprint_algorithm",
        ),
        sa.CheckConstraint(
            "canon_commit_approval_fingerprint_version IN ('r2-m5c-canon-approval-binding-v1')",
            name="ck_narrative_handoff_admissions_fingerprint_version",
        ),
        sa.ForeignKeyConstraint(
            ["compilation_attempt_id", "generation"],
            [
                "narrative_compilation_attempts.attempt_id",
                "narrative_compilation_attempts.generation",
            ],
            name="fk_narrative_handoff_admissions_attempt_generation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "compilation_attempt_id"],
            [
                "narrative_compilation_attempts.user_id",
                "narrative_compilation_attempts.project_name",
                "narrative_compilation_attempts.attempt_id",
            ],
            name="fk_narrative_handoff_admissions_attempt_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "compilation_result_id"],
            [
                "narrative_compilation_results.user_id",
                "narrative_compilation_results.project_name",
                "narrative_compilation_results.result_id",
            ],
            name="fk_narrative_handoff_admissions_result_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "revision_acceptance_decision_id"],
            [
                "revision_acceptance_decisions.user_id",
                "revision_acceptance_decisions.project_name",
                "revision_acceptance_decisions.decision_id",
            ],
            name="fk_narrative_handoff_admissions_revision_acceptance",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("admission_id"),
        sa.UniqueConstraint("user_id", "project_name", "admission_id", name="uq_narrative_handoff_admissions_scope"),
    )
    with op.batch_alter_table("narrative_handoff_admissions", schema=None) as batch_op:
        batch_op.create_index("ix_narrative_handoff_admissions_project_name", ["project_name"], unique=False)
        batch_op.create_index(
            "ix_narrative_handoff_admissions_compilation_result", ["compilation_result_id"], unique=False
        )
        batch_op.create_index(
            "ix_narrative_handoff_admissions_revision_acceptance", ["revision_acceptance_decision_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_narrative_handoff_admissions_user_id"), ["user_id"], unique=False)

    op.create_table(
        "narrative_handoff_admission_observed_heads",
        sa.Column("admission_id", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("head_family", sa.String(length=32), nullable=False),
        sa.Column("logical_key_json", sa.JSON(), nullable=False),
        sa.Column("effective_decision_id", sa.String(length=255), nullable=True),
        sa.Column("effective_generation", sa.Integer(), nullable=False),
        sa.Column("decision_generation", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_narrative_handoff_admission_observed_heads_position"),
        sa.CheckConstraint(
            "head_family IN ('REVISION_ACCEPTANCE','CHANGE_SET_REVIEW','CONFLICT_RESOLUTION')",
            name="ck_narrative_handoff_admission_observed_heads_family",
        ),
        sa.CheckConstraint(
            "(effective_decision_id IS NULL AND effective_generation = 0) "
            "OR (effective_decision_id IS NOT NULL AND effective_generation > 0)",
            name="ck_narrative_handoff_admission_observed_heads_effective_zero",
        ),
        sa.CheckConstraint(
            "decision_generation >= 0", name="ck_narrative_handoff_admission_observed_heads_decision_gen"
        ),
        sa.CheckConstraint(
            "effective_generation <= decision_generation",
            name="ck_narrative_handoff_admission_observed_heads_not_ahead",
        ),
        sa.ForeignKeyConstraint(
            ["admission_id"],
            ["narrative_handoff_admissions.admission_id"],
            name="fk_narrative_handoff_admission_observed_heads_admission",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["effective_decision_id"],
            ["narrative_decision_identities.decision_id"],
            name="fk_narrative_handoff_admission_observed_heads_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("admission_id", "position", name="pk_narrative_handoff_admission_observed_heads"),
    )
    with op.batch_alter_table("narrative_handoff_admission_observed_heads", schema=None) as batch_op:
        batch_op.create_index(
            "ix_narrative_handoff_admission_observed_heads_identity", ["effective_decision_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_narrative_handoff_admission_observed_heads_user_id"), ["user_id"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("narrative_handoff_admission_observed_heads", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_narrative_handoff_admission_observed_heads_user_id"))
        batch_op.drop_index("ix_narrative_handoff_admission_observed_heads_identity")

    op.drop_table("narrative_handoff_admission_observed_heads")
    with op.batch_alter_table("narrative_handoff_admissions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_narrative_handoff_admissions_user_id"))
        batch_op.drop_index("ix_narrative_handoff_admissions_revision_acceptance")
        batch_op.drop_index("ix_narrative_handoff_admissions_compilation_result")
        batch_op.drop_index("ix_narrative_handoff_admissions_project_name")

    op.drop_table("narrative_handoff_admissions")
