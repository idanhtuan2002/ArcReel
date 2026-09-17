"""add narrative lifecycle evidence

Revision ID: 5c7c4a0e0001
Revises: 5b7c4a0e0001
Create Date: 2026-09-10 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c7c4a0e0001"
down_revision: str | Sequence[str] | None = "5b7c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OUTCOMES = "('SUCCEEDED','ABSTAINED','CONFLICT','FAILED','OUTCOME_UNKNOWN')"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "narrative_draft_candidates",
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column("scene_contract_id", sa.String(length=255), nullable=False),
        sa.Column("canon_branch_id", sa.String(length=255), nullable=False),
        sa.Column("base_canon_version_id", sa.String(length=255), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("scene_contract_version", sa.Integer(), nullable=False),
        sa.Column("context_pack_id", sa.String(length=255), nullable=False),
        sa.Column("normalized_content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=255), nullable=False),
        sa.Column("writer_kind", sa.String(length=255), nullable=False),
        sa.Column("writer_version", sa.String(length=255), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("semantic_fingerprint", sa.String(length=255), nullable=False),
        sa.CheckConstraint("plan_version >= 1", name="ck_narrative_draft_candidates_plan_version"),
        sa.CheckConstraint("scene_contract_version >= 1", name="ck_narrative_draft_candidates_scene_version"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("candidate_id"),
        sa.UniqueConstraint("user_id", "project_name", "candidate_id", name="uq_narrative_draft_candidates_scope"),
    )
    op.create_index(
        op.f("ix_narrative_draft_candidates_user_id"), "narrative_draft_candidates", ["user_id"], unique=False
    )
    op.create_index(
        "ix_narrative_draft_candidates_project_name", "narrative_draft_candidates", ["project_name"], unique=False
    )

    op.create_table(
        "narrative_revisions",
        sa.Column("revision_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column("scene_contract_id", sa.String(length=255), nullable=False),
        sa.Column("canon_branch_id", sa.String(length=255), nullable=False),
        sa.Column("base_candidate_id", sa.String(length=255), nullable=False),
        sa.Column("predecessor_revision_id", sa.String(length=255), nullable=True),
        sa.Column("base_canon_version_id", sa.String(length=255), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("scene_contract_version", sa.Integer(), nullable=False),
        sa.Column("context_pack_id", sa.String(length=255), nullable=False),
        sa.Column("normalized_content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=255), nullable=False),
        sa.Column("review_refs_json", sa.JSON(), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("semantic_fingerprint", sa.String(length=255), nullable=False),
        sa.CheckConstraint("plan_version >= 1", name="ck_narrative_revisions_plan_version"),
        sa.CheckConstraint("scene_contract_version >= 1", name="ck_narrative_revisions_scene_version"),
        sa.CheckConstraint(
            "predecessor_revision_id IS NULL OR predecessor_revision_id <> revision_id",
            name="ck_narrative_revisions_predecessor_not_self",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "base_candidate_id"],
            [
                "narrative_draft_candidates.user_id",
                "narrative_draft_candidates.project_name",
                "narrative_draft_candidates.candidate_id",
            ],
            name="fk_narrative_revisions_base_candidate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "predecessor_revision_id"],
            [
                "narrative_revisions.user_id",
                "narrative_revisions.project_name",
                "narrative_revisions.revision_id",
            ],
            name="fk_narrative_revisions_predecessor",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("revision_id"),
        sa.UniqueConstraint("user_id", "project_name", "revision_id", name="uq_narrative_revisions_scope"),
        sa.UniqueConstraint(
            "revision_id",
            "base_canon_version_id",
            "plan_version",
            "scene_contract_version",
            "context_pack_id",
            name="uq_narrative_revisions_full_basis",
        ),
        sa.UniqueConstraint("revision_id", "base_canon_version_id", name="uq_narrative_revisions_canon_basis"),
    )
    op.create_index(op.f("ix_narrative_revisions_user_id"), "narrative_revisions", ["user_id"], unique=False)
    op.create_index("ix_narrative_revisions_project_name", "narrative_revisions", ["project_name"], unique=False)

    op.create_table(
        "narrative_extraction_attempts",
        sa.Column("attempt_id", sa.String(length=255), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column("scene_contract_id", sa.String(length=255), nullable=False),
        sa.Column("canon_branch_id", sa.String(length=255), nullable=False),
        sa.Column("revision_id", sa.String(length=255), nullable=False),
        sa.Column("revision_acceptance_decision_id", sa.String(length=255), nullable=False),
        sa.Column("observed_revision_effective_generation", sa.Integer(), nullable=False),
        sa.Column("base_canon_version_id", sa.String(length=255), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("scene_contract_version", sa.Integer(), nullable=False),
        sa.Column("context_pack_id", sa.String(length=255), nullable=False),
        sa.Column("extractor_kind", sa.String(length=255), nullable=False),
        sa.Column("extractor_version", sa.String(length=255), nullable=False),
        sa.Column("policy_ref", sa.String(length=255), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("admitted_by", sa.String(length=255), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=255), nullable=False),
        sa.CheckConstraint("generation >= 0", name="ck_narrative_extraction_attempts_generation"),
        sa.CheckConstraint(
            "observed_revision_effective_generation >= 0",
            name="ck_narrative_extraction_attempts_observed_generation",
        ),
        sa.CheckConstraint("plan_version >= 1", name="ck_narrative_extraction_attempts_plan_version"),
        sa.CheckConstraint("scene_contract_version >= 1", name="ck_narrative_extraction_attempts_scene_version"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "revision_id"],
            [
                "narrative_revisions.user_id",
                "narrative_revisions.project_name",
                "narrative_revisions.revision_id",
            ],
            name="fk_narrative_extraction_attempts_revision",
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
            name="fk_narrative_extraction_attempts_revision_basis",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint("attempt_id", "generation", name="uq_narrative_extraction_attempts_generation"),
        sa.UniqueConstraint("user_id", "project_name", "attempt_id", name="uq_narrative_extraction_attempts_scope"),
    )
    op.create_index(
        op.f("ix_narrative_extraction_attempts_user_id"), "narrative_extraction_attempts", ["user_id"], unique=False
    )
    op.create_index(
        "ix_narrative_extraction_attempts_project_name",
        "narrative_extraction_attempts",
        ["project_name"],
        unique=False,
    )

    op.create_table(
        "narrative_extraction_results",
        sa.Column("result_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("attempt_id", sa.String(length=255), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("diagnostics_json", sa.JSON(), nullable=False),
        sa.Column("provider_receipt_json", sa.JSON(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("output_fingerprint", sa.String(length=255), nullable=False),
        sa.CheckConstraint("generation >= 0", name="ck_narrative_extraction_results_generation"),
        sa.CheckConstraint(f"outcome IN {_OUTCOMES}", name="ck_narrative_extraction_results_outcome"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["attempt_id", "generation"],
            [
                "narrative_extraction_attempts.attempt_id",
                "narrative_extraction_attempts.generation",
            ],
            name="fk_narrative_extraction_results_attempt_generation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "attempt_id"],
            [
                "narrative_extraction_attempts.user_id",
                "narrative_extraction_attempts.project_name",
                "narrative_extraction_attempts.attempt_id",
            ],
            name="fk_narrative_extraction_results_attempt_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("result_id"),
        sa.UniqueConstraint("attempt_id", "generation", name="uq_narrative_extraction_results_generation"),
        sa.UniqueConstraint("user_id", "project_name", "result_id", name="uq_narrative_extraction_results_scope"),
    )
    op.create_index(
        op.f("ix_narrative_extraction_results_user_id"), "narrative_extraction_results", ["user_id"], unique=False
    )
    op.create_index(
        "ix_narrative_extraction_results_project_name",
        "narrative_extraction_results",
        ["project_name"],
        unique=False,
    )

    op.create_table(
        "narrative_change_sets",
        sa.Column("change_set_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("change_set_lineage_id", sa.String(length=255), nullable=False),
        sa.Column("source_revision_id", sa.String(length=255), nullable=False),
        sa.Column("extraction_attempt_id", sa.String(length=255), nullable=False),
        sa.Column("extraction_generation", sa.Integer(), nullable=False),
        sa.Column("base_canon_version_id", sa.String(length=255), nullable=False),
        sa.Column("source_spans_json", sa.JSON(), nullable=False),
        sa.Column("semantic_effect_keys_json", sa.JSON(), nullable=False),
        sa.Column("changes_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("extractor_version", sa.String(length=255), nullable=False),
        sa.Column("policy_ref", sa.String(length=255), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("output_fingerprint", sa.String(length=255), nullable=False),
        sa.CheckConstraint("extraction_generation >= 0", name="ck_narrative_change_sets_generation"),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_narrative_change_sets_confidence"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "source_revision_id"],
            [
                "narrative_revisions.user_id",
                "narrative_revisions.project_name",
                "narrative_revisions.revision_id",
            ],
            name="fk_narrative_change_sets_source_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id", "base_canon_version_id"],
            ["narrative_revisions.revision_id", "narrative_revisions.base_canon_version_id"],
            name="fk_narrative_change_sets_revision_basis",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_attempt_id", "extraction_generation"],
            [
                "narrative_extraction_attempts.attempt_id",
                "narrative_extraction_attempts.generation",
            ],
            name="fk_narrative_change_sets_attempt_generation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("change_set_id"),
        sa.UniqueConstraint("user_id", "project_name", "change_set_id", name="uq_narrative_change_sets_scope"),
    )
    op.create_index(op.f("ix_narrative_change_sets_user_id"), "narrative_change_sets", ["user_id"], unique=False)
    op.create_index("ix_narrative_change_sets_project_name", "narrative_change_sets", ["project_name"], unique=False)
    op.create_index(
        "ix_narrative_change_sets_lineage", "narrative_change_sets", ["change_set_lineage_id"], unique=False
    )

    op.create_table(
        "narrative_extraction_result_change_sets",
        sa.Column("result_id", sa.String(length=255), nullable=False),
        sa.Column("change_set_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_narrative_extraction_result_change_sets_position"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "result_id"],
            [
                "narrative_extraction_results.user_id",
                "narrative_extraction_results.project_name",
                "narrative_extraction_results.result_id",
            ],
            name="fk_narrative_extraction_result_change_sets_result",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "change_set_id"],
            [
                "narrative_change_sets.user_id",
                "narrative_change_sets.project_name",
                "narrative_change_sets.change_set_id",
            ],
            name="fk_narrative_extraction_result_change_sets_change_set",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("result_id", "change_set_id"),
        sa.UniqueConstraint("result_id", "position", name="uq_narrative_extraction_result_change_sets_position"),
    )
    op.create_index(
        op.f("ix_narrative_extraction_result_change_sets_user_id"),
        "narrative_extraction_result_change_sets",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_narrative_extraction_result_change_sets_change_set",
        "narrative_extraction_result_change_sets",
        ["change_set_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_narrative_extraction_result_change_sets_change_set",
        table_name="narrative_extraction_result_change_sets",
    )
    op.drop_index(
        op.f("ix_narrative_extraction_result_change_sets_user_id"),
        table_name="narrative_extraction_result_change_sets",
    )
    op.drop_table("narrative_extraction_result_change_sets")

    op.drop_index("ix_narrative_change_sets_lineage", table_name="narrative_change_sets")
    op.drop_index("ix_narrative_change_sets_project_name", table_name="narrative_change_sets")
    op.drop_index(op.f("ix_narrative_change_sets_user_id"), table_name="narrative_change_sets")
    op.drop_table("narrative_change_sets")

    op.drop_index("ix_narrative_extraction_results_project_name", table_name="narrative_extraction_results")
    op.drop_index(op.f("ix_narrative_extraction_results_user_id"), table_name="narrative_extraction_results")
    op.drop_table("narrative_extraction_results")

    op.drop_index("ix_narrative_extraction_attempts_project_name", table_name="narrative_extraction_attempts")
    op.drop_index(op.f("ix_narrative_extraction_attempts_user_id"), table_name="narrative_extraction_attempts")
    op.drop_table("narrative_extraction_attempts")

    op.drop_index("ix_narrative_revisions_project_name", table_name="narrative_revisions")
    op.drop_index(op.f("ix_narrative_revisions_user_id"), table_name="narrative_revisions")
    op.drop_table("narrative_revisions")

    op.drop_index("ix_narrative_draft_candidates_project_name", table_name="narrative_draft_candidates")
    op.drop_index(op.f("ix_narrative_draft_candidates_user_id"), table_name="narrative_draft_candidates")
    op.drop_table("narrative_draft_candidates")
