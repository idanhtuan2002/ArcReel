"""add narrative compilation

Revision ID: 5c7c4a0e0003
Revises: 5c7c4a0e0002
Create Date: 2026-09-13 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c7c4a0e0003"
down_revision: str | Sequence[str] | None = "5c7c4a0e0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "narrative_compilation_attempts",
        sa.Column("attempt_id", sa.String(length=255), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column("scene_contract_id", sa.String(length=255), nullable=False),
        sa.Column("canon_branch_id", sa.String(length=255), nullable=False),
        sa.Column("revision_id", sa.String(length=255), nullable=False),
        sa.Column("revision_acceptance_decision_id", sa.String(length=255), nullable=False),
        sa.Column("base_canon_version_id", sa.String(length=255), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("scene_contract_version", sa.Integer(), nullable=False),
        sa.Column("context_pack_id", sa.String(length=255), nullable=False),
        sa.Column("creative_policy_ref", sa.String(length=255), nullable=False),
        sa.Column("creative_policy_version", sa.String(length=64), nullable=False),
        sa.Column("compiler_version", sa.String(length=255), nullable=False),
        sa.Column("requested_canon_delta_id", sa.String(length=255), nullable=False),
        sa.Column("delta_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delta_created_by", sa.String(length=255), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("admitted_by", sa.String(length=255), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint("generation >= 0", name="ck_narrative_compilation_attempts_generation"),
        sa.CheckConstraint("plan_version >= 1", name="ck_narrative_compilation_attempts_plan_version"),
        sa.CheckConstraint("scene_contract_version >= 1", name="ck_narrative_compilation_attempts_scene_version"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "revision_id"],
            [
                "narrative_revisions.user_id",
                "narrative_revisions.project_name",
                "narrative_revisions.revision_id",
            ],
            name="fk_narrative_compilation_attempts_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "base_canon_version_id", "plan_version", "scene_contract_version", "context_pack_id"],
            [
                "narrative_revisions.revision_id",
                "narrative_revisions.base_canon_version_id",
                "narrative_revisions.plan_version",
                "narrative_revisions.scene_contract_version",
                "narrative_revisions.context_pack_id",
            ],
            name="fk_narrative_compilation_attempts_revision_basis",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "revision_acceptance_decision_id"],
            [
                "revision_acceptance_decisions.user_id",
                "revision_acceptance_decisions.project_name",
                "revision_acceptance_decisions.decision_id",
            ],
            name="fk_narrative_compilation_attempts_revision_acceptance",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint("attempt_id", "generation", name="uq_narrative_compilation_attempts_generation"),
        sa.UniqueConstraint("user_id", "project_name", "attempt_id", name="uq_narrative_compilation_attempts_scope"),
    )
    with op.batch_alter_table("narrative_compilation_attempts", schema=None) as batch_op:
        batch_op.create_index("ix_narrative_compilation_attempts_project_name", ["project_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_narrative_compilation_attempts_user_id"), ["user_id"], unique=False)

    op.create_table(
        "narrative_compilation_selected_change_sets",
        sa.Column("attempt_id", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("change_set_id", sa.String(length=255), nullable=False),
        sa.Column("review_decision_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_narrative_compilation_selected_change_sets_position"),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["narrative_compilation_attempts.attempt_id"],
            name="fk_narrative_compilation_selected_change_sets_attempt",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "change_set_id"],
            [
                "narrative_change_sets.user_id",
                "narrative_change_sets.project_name",
                "narrative_change_sets.change_set_id",
            ],
            name="fk_narrative_compilation_selected_change_sets_change_set",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["review_decision_id"],
            ["change_set_review_decisions.decision_id"],
            name="fk_narrative_compilation_selected_change_sets_review",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("attempt_id", "position", name="pk_narrative_compilation_selected_change_sets"),
    )
    with op.batch_alter_table("narrative_compilation_selected_change_sets", schema=None) as batch_op:
        batch_op.create_index(
            "ix_narrative_compilation_selected_change_sets_change_set", ["change_set_id"], unique=False
        )
        batch_op.create_index(
            "ix_narrative_compilation_selected_change_sets_review", ["review_decision_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_narrative_compilation_selected_change_sets_user_id"), ["user_id"], unique=False
        )

    op.create_table(
        "narrative_compilation_conflict_resolutions",
        sa.Column("attempt_id", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("conflict_resolution_decision_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_narrative_compilation_conflict_resolutions_position"),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["narrative_compilation_attempts.attempt_id"],
            name="fk_narrative_compilation_conflict_resolutions_attempt",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conflict_resolution_decision_id"],
            ["conflict_resolution_decisions.decision_id"],
            name="fk_narrative_compilation_conflict_resolutions_decision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("attempt_id", "position", name="pk_narrative_compilation_conflict_resolutions"),
    )
    with op.batch_alter_table("narrative_compilation_conflict_resolutions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_narrative_compilation_conflict_resolutions_decision",
            ["conflict_resolution_decision_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_narrative_compilation_conflict_resolutions_user_id"), ["user_id"], unique=False
        )

    op.create_table(
        "narrative_compilation_observed_heads",
        sa.Column("attempt_id", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("decision_id", sa.String(length=255), nullable=False),
        sa.Column("effective_generation", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_narrative_compilation_observed_heads_position"),
        sa.CheckConstraint("effective_generation >= 1", name="ck_narrative_compilation_observed_heads_generation"),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["narrative_compilation_attempts.attempt_id"],
            name="fk_narrative_compilation_observed_heads_attempt",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["narrative_decision_identities.decision_id"],
            name="fk_narrative_compilation_observed_heads_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("attempt_id", "position", name="pk_narrative_compilation_observed_heads"),
    )
    with op.batch_alter_table("narrative_compilation_observed_heads", schema=None) as batch_op:
        batch_op.create_index("ix_narrative_compilation_observed_heads_decision", ["decision_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_narrative_compilation_observed_heads_user_id"), ["user_id"], unique=False)

    op.create_table(
        "narrative_compilation_results",
        sa.Column("result_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("attempt_id", sa.String(length=255), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("canon_delta_id", sa.String(length=255), nullable=True),
        sa.Column("canon_delta_payload_hash", sa.String(length=255), nullable=True),
        sa.Column("diagnostics_json", sa.JSON(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("output_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint("generation >= 0", name="ck_narrative_compilation_results_generation"),
        sa.CheckConstraint(
            "outcome IN ('SUCCEEDED','NO_CANON_MUTATION','ABSTAINED','CONFLICT','FAILED')",
            name="ck_narrative_compilation_results_outcome",
        ),
        sa.CheckConstraint(
            "(outcome = 'SUCCEEDED' AND canon_delta_id IS NOT NULL AND canon_delta_payload_hash IS NOT NULL) "
            "OR (outcome != 'SUCCEEDED' AND canon_delta_id IS NULL AND canon_delta_payload_hash IS NULL)",
            name="ck_narrative_compilation_results_delta_matches_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "generation"],
            [
                "narrative_compilation_attempts.attempt_id",
                "narrative_compilation_attempts.generation",
            ],
            name="fk_narrative_compilation_results_attempt_generation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "attempt_id"],
            [
                "narrative_compilation_attempts.user_id",
                "narrative_compilation_attempts.project_name",
                "narrative_compilation_attempts.attempt_id",
            ],
            name="fk_narrative_compilation_results_attempt_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("result_id"),
        sa.UniqueConstraint("attempt_id", "generation", name="uq_narrative_compilation_results_generation"),
        sa.UniqueConstraint("user_id", "project_name", "result_id", name="uq_narrative_compilation_results_scope"),
    )
    with op.batch_alter_table("narrative_compilation_results", schema=None) as batch_op:
        batch_op.create_index("ix_narrative_compilation_results_project_name", ["project_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_narrative_compilation_results_user_id"), ["user_id"], unique=False)

    op.create_table(
        "narrative_compiled_canon_deltas",
        sa.Column("compilation_result_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("compilation_attempt_id", sa.String(length=255), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("canon_delta_json", sa.JSON(), nullable=False),
        sa.Column("canon_delta_payload_hash", sa.String(length=255), nullable=False),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint("generation >= 0", name="ck_narrative_compiled_canon_deltas_generation"),
        sa.ForeignKeyConstraint(
            ["compilation_result_id"],
            ["narrative_compilation_results.result_id"],
            name="fk_narrative_compiled_canon_deltas_result",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["compilation_attempt_id", "generation"],
            [
                "narrative_compilation_attempts.attempt_id",
                "narrative_compilation_attempts.generation",
            ],
            name="fk_narrative_compiled_canon_deltas_attempt_generation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "compilation_result_id"],
            [
                "narrative_compilation_results.user_id",
                "narrative_compilation_results.project_name",
                "narrative_compilation_results.result_id",
            ],
            name="fk_narrative_compiled_canon_deltas_result_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("compilation_result_id"),
    )
    with op.batch_alter_table("narrative_compiled_canon_deltas", schema=None) as batch_op:
        batch_op.create_index("ix_narrative_compiled_canon_deltas_project_name", ["project_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_narrative_compiled_canon_deltas_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("narrative_compiled_canon_deltas", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_narrative_compiled_canon_deltas_user_id"))
        batch_op.drop_index("ix_narrative_compiled_canon_deltas_project_name")

    op.drop_table("narrative_compiled_canon_deltas")
    with op.batch_alter_table("narrative_compilation_results", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_narrative_compilation_results_user_id"))
        batch_op.drop_index("ix_narrative_compilation_results_project_name")

    op.drop_table("narrative_compilation_results")
    with op.batch_alter_table("narrative_compilation_observed_heads", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_narrative_compilation_observed_heads_user_id"))
        batch_op.drop_index("ix_narrative_compilation_observed_heads_decision")

    op.drop_table("narrative_compilation_observed_heads")
    with op.batch_alter_table("narrative_compilation_conflict_resolutions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_narrative_compilation_conflict_resolutions_user_id"))
        batch_op.drop_index("ix_narrative_compilation_conflict_resolutions_decision")

    op.drop_table("narrative_compilation_conflict_resolutions")
    with op.batch_alter_table("narrative_compilation_selected_change_sets", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_narrative_compilation_selected_change_sets_user_id"))
        batch_op.drop_index("ix_narrative_compilation_selected_change_sets_review")
        batch_op.drop_index("ix_narrative_compilation_selected_change_sets_change_set")

    op.drop_table("narrative_compilation_selected_change_sets")
    with op.batch_alter_table("narrative_compilation_attempts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_narrative_compilation_attempts_user_id"))
        batch_op.drop_index("ix_narrative_compilation_attempts_project_name")

    op.drop_table("narrative_compilation_attempts")
