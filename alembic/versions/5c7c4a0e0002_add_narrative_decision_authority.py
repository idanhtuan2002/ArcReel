"""add narrative decision authority

Revision ID: 5c7c4a0e0002
Revises: 5c7c4a0e0001
Create Date: 2026-09-11 21:52:24.392153

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c7c4a0e0002"
down_revision: str | Sequence[str] | None = "5c7c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "narrative_decision_identities",
        sa.Column("decision_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("decision_family", sa.String(length=32), nullable=False),
        sa.Column("canonical_identity_hash", sa.String(length=255), nullable=False),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint(
            "decision_family IN ('REVISION_ACCEPTANCE','CHANGE_SET_REVIEW','CONFLICT_RESOLUTION')",
            name="ck_narrative_decision_identities_family",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("decision_id"),
        sa.UniqueConstraint("decision_id", "decision_family", name="uq_narrative_decision_identities_family"),
    )
    with op.batch_alter_table("narrative_decision_identities", schema=None) as batch_op:
        batch_op.create_index("ix_narrative_decision_identities_project_name", ["project_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_narrative_decision_identities_user_id"), ["user_id"], unique=False)

    op.create_table(
        "revision_acceptance_decisions",
        sa.Column("decision_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("decision_family", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column("scene_contract_id", sa.String(length=255), nullable=False),
        sa.Column("canon_branch_id", sa.String(length=255), nullable=False),
        sa.Column("selected_revision_id", sa.String(length=255), nullable=False),
        sa.Column("expected_latest_decision_id", sa.String(length=255), nullable=True),
        sa.Column("expected_effective_decision_id", sa.String(length=255), nullable=True),
        sa.Column("base_canon_version_id", sa.String(length=255), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("scene_contract_version", sa.Integer(), nullable=False),
        sa.Column("context_pack_id", sa.String(length=255), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("decision_generation", sa.Integer(), nullable=False),
        sa.Column("authorization_ref", sa.String(length=255), nullable=False),
        sa.Column("authorization_actor_id", sa.String(length=255), nullable=False),
        sa.Column("authorization_authority_role", sa.String(length=32), nullable=False),
        sa.Column("authorization_stable_subject_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("authorization_decision_command_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("authorization_authenticated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorization_authenticated_via", sa.String(length=255), nullable=False),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint("action IN ('ACCEPT','REJECT','SUPERSEDE')", name="ck_revision_acceptance_decisions_action"),
        sa.CheckConstraint("decision_family = 'REVISION_ACCEPTANCE'", name="ck_revision_acceptance_decisions_family"),
        sa.CheckConstraint("decision_generation >= 1", name="ck_revision_acceptance_decisions_generation"),
        sa.CheckConstraint("plan_version >= 1", name="ck_revision_acceptance_decisions_plan_version"),
        sa.CheckConstraint("scene_contract_version >= 1", name="ck_revision_acceptance_decisions_scene_version"),
        sa.ForeignKeyConstraint(
            ["decision_id", "decision_family"],
            ["narrative_decision_identities.decision_id", "narrative_decision_identities.decision_family"],
            name="fk_revision_acceptance_decisions_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "expected_effective_decision_id",
                "user_id",
                "project_name",
                "plan_id",
                "scene_contract_id",
                "canon_branch_id",
            ],
            [
                "revision_acceptance_decisions.decision_id",
                "revision_acceptance_decisions.user_id",
                "revision_acceptance_decisions.project_name",
                "revision_acceptance_decisions.plan_id",
                "revision_acceptance_decisions.scene_contract_id",
                "revision_acceptance_decisions.canon_branch_id",
            ],
            name="fk_revision_acceptance_decisions_expected_effective",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "expected_latest_decision_id",
                "user_id",
                "project_name",
                "plan_id",
                "scene_contract_id",
                "canon_branch_id",
            ],
            [
                "revision_acceptance_decisions.decision_id",
                "revision_acceptance_decisions.user_id",
                "revision_acceptance_decisions.project_name",
                "revision_acceptance_decisions.plan_id",
                "revision_acceptance_decisions.scene_contract_id",
                "revision_acceptance_decisions.canon_branch_id",
            ],
            name="fk_revision_acceptance_decisions_expected_latest",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("decision_id"),
        sa.UniqueConstraint("decision_id", "decision_family", name="uq_revision_acceptance_decisions_family"),
        sa.UniqueConstraint(
            "decision_id",
            "user_id",
            "project_name",
            "plan_id",
            "scene_contract_id",
            "canon_branch_id",
            name="uq_revision_acceptance_decisions_subject",
        ),
        sa.UniqueConstraint("user_id", "project_name", "decision_id", name="uq_revision_acceptance_decisions_scope"),
    )
    with op.batch_alter_table("revision_acceptance_decisions", schema=None) as batch_op:
        batch_op.create_index("ix_revision_acceptance_decisions_project_name", ["project_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_revision_acceptance_decisions_user_id"), ["user_id"], unique=False)

    op.create_table(
        "change_set_review_decisions",
        sa.Column("decision_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("decision_family", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column("scene_contract_id", sa.String(length=255), nullable=False),
        sa.Column("canon_branch_id", sa.String(length=255), nullable=False),
        sa.Column("revision_acceptance_decision_id", sa.String(length=255), nullable=False),
        sa.Column("change_set_lineage_id", sa.String(length=255), nullable=False),
        sa.Column("selected_change_set_id", sa.String(length=255), nullable=False),
        sa.Column("expected_latest_decision_id", sa.String(length=255), nullable=True),
        sa.Column("expected_effective_decision_id", sa.String(length=255), nullable=True),
        sa.Column("base_canon_version_id", sa.String(length=255), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("scene_contract_version", sa.Integer(), nullable=False),
        sa.Column("context_pack_id", sa.String(length=255), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("decision_generation", sa.Integer(), nullable=False),
        sa.Column("authorization_ref", sa.String(length=255), nullable=False),
        sa.Column("authorization_actor_id", sa.String(length=255), nullable=False),
        sa.Column("authorization_authority_role", sa.String(length=32), nullable=False),
        sa.Column("authorization_stable_subject_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("authorization_decision_command_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("authorization_authenticated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorization_authenticated_via", sa.String(length=255), nullable=False),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint("action IN ('ACCEPT','REJECT','SUPERSEDE')", name="ck_change_set_review_decisions_action"),
        sa.CheckConstraint("decision_family = 'CHANGE_SET_REVIEW'", name="ck_change_set_review_decisions_family"),
        sa.CheckConstraint("decision_generation >= 1", name="ck_change_set_review_decisions_generation"),
        sa.CheckConstraint("plan_version >= 1", name="ck_change_set_review_decisions_plan_version"),
        sa.CheckConstraint("scene_contract_version >= 1", name="ck_change_set_review_decisions_scene_version"),
        sa.ForeignKeyConstraint(
            ["decision_id", "decision_family"],
            ["narrative_decision_identities.decision_id", "narrative_decision_identities.decision_family"],
            name="fk_change_set_review_decisions_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["expected_effective_decision_id", "revision_acceptance_decision_id", "change_set_lineage_id"],
            [
                "change_set_review_decisions.decision_id",
                "change_set_review_decisions.revision_acceptance_decision_id",
                "change_set_review_decisions.change_set_lineage_id",
            ],
            name="fk_change_set_review_decisions_expected_effective",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["expected_latest_decision_id", "revision_acceptance_decision_id", "change_set_lineage_id"],
            [
                "change_set_review_decisions.decision_id",
                "change_set_review_decisions.revision_acceptance_decision_id",
                "change_set_review_decisions.change_set_lineage_id",
            ],
            name="fk_change_set_review_decisions_expected_latest",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "revision_acceptance_decision_id"],
            [
                "revision_acceptance_decisions.user_id",
                "revision_acceptance_decisions.project_name",
                "revision_acceptance_decisions.decision_id",
            ],
            name="fk_change_set_review_decisions_revision_acceptance",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("decision_id"),
        sa.UniqueConstraint("decision_id", "decision_family", name="uq_change_set_review_decisions_family"),
        sa.UniqueConstraint(
            "decision_id",
            "revision_acceptance_decision_id",
            "change_set_lineage_id",
            name="uq_change_set_review_decisions_subject",
        ),
        sa.UniqueConstraint("user_id", "project_name", "decision_id", name="uq_change_set_review_decisions_scope"),
    )
    with op.batch_alter_table("change_set_review_decisions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_change_set_review_decisions_lineage",
            ["revision_acceptance_decision_id", "change_set_lineage_id"],
            unique=False,
        )
        batch_op.create_index("ix_change_set_review_decisions_project_name", ["project_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_change_set_review_decisions_user_id"), ["user_id"], unique=False)

    op.create_table(
        "conflict_resolution_lineages",
        sa.Column("revision_acceptance_decision_id", sa.String(length=255), nullable=False),
        sa.Column("conflict_resolution_lineage_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("conflict_subject_json", sa.JSON(), nullable=False),
        sa.Column("conflict_subject_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "revision_acceptance_decision_id"],
            [
                "revision_acceptance_decisions.user_id",
                "revision_acceptance_decisions.project_name",
                "revision_acceptance_decisions.decision_id",
            ],
            name="fk_conflict_resolution_lineages_revision_acceptance",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "revision_acceptance_decision_id", "conflict_resolution_lineage_id", name="pk_conflict_resolution_lineages"
        ),
        sa.UniqueConstraint(
            "revision_acceptance_decision_id",
            "conflict_subject_fingerprint",
            name="uq_conflict_resolution_lineages_subject",
        ),
    )
    with op.batch_alter_table("conflict_resolution_lineages", schema=None) as batch_op:
        batch_op.create_index("ix_conflict_resolution_lineages_project_name", ["project_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_conflict_resolution_lineages_user_id"), ["user_id"], unique=False)

    op.create_table(
        "revision_acceptance_heads",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column("scene_contract_id", sa.String(length=255), nullable=False),
        sa.Column("canon_branch_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("latest_decision_id", sa.String(length=255), nullable=True),
        sa.Column("decision_generation", sa.Integer(), nullable=False),
        sa.Column("effective_decision_id", sa.String(length=255), nullable=True),
        sa.Column("effective_generation", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "(effective_decision_id IS NULL AND effective_generation = 0) OR (effective_decision_id IS NOT NULL AND effective_generation > 0)",
            name="ck_revision_acceptance_heads_effective_zero_generation",
        ),
        sa.CheckConstraint(
            "(latest_decision_id IS NULL AND decision_generation = 0) OR (latest_decision_id IS NOT NULL AND decision_generation > 0)",
            name="ck_revision_acceptance_heads_latest_zero_generation",
        ),
        sa.CheckConstraint(
            "effective_generation <= decision_generation", name="ck_revision_acceptance_heads_effective_not_ahead"
        ),
        sa.ForeignKeyConstraint(
            ["effective_decision_id", "user_id", "project_name", "plan_id", "scene_contract_id", "canon_branch_id"],
            [
                "revision_acceptance_decisions.decision_id",
                "revision_acceptance_decisions.user_id",
                "revision_acceptance_decisions.project_name",
                "revision_acceptance_decisions.plan_id",
                "revision_acceptance_decisions.scene_contract_id",
                "revision_acceptance_decisions.canon_branch_id",
            ],
            name="fk_revision_acceptance_heads_effective",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["latest_decision_id", "user_id", "project_name", "plan_id", "scene_contract_id", "canon_branch_id"],
            [
                "revision_acceptance_decisions.decision_id",
                "revision_acceptance_decisions.user_id",
                "revision_acceptance_decisions.project_name",
                "revision_acceptance_decisions.plan_id",
                "revision_acceptance_decisions.scene_contract_id",
                "revision_acceptance_decisions.canon_branch_id",
            ],
            name="fk_revision_acceptance_heads_latest",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "user_id",
            "project_name",
            "plan_id",
            "scene_contract_id",
            "canon_branch_id",
            name="pk_revision_acceptance_heads",
        ),
    )
    with op.batch_alter_table("revision_acceptance_heads", schema=None) as batch_op:
        batch_op.create_index("ix_revision_acceptance_heads_project_name", ["project_name"], unique=False)

    op.create_table(
        "change_set_review_heads",
        sa.Column("revision_acceptance_decision_id", sa.String(length=255), nullable=False),
        sa.Column("change_set_lineage_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("latest_decision_id", sa.String(length=255), nullable=True),
        sa.Column("decision_generation", sa.Integer(), nullable=False),
        sa.Column("effective_decision_id", sa.String(length=255), nullable=True),
        sa.Column("effective_generation", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint(
            "(effective_decision_id IS NULL AND effective_generation = 0) OR (effective_decision_id IS NOT NULL AND effective_generation > 0)",
            name="ck_change_set_review_heads_effective_zero_generation",
        ),
        sa.CheckConstraint(
            "(latest_decision_id IS NULL AND decision_generation = 0) OR (latest_decision_id IS NOT NULL AND decision_generation > 0)",
            name="ck_change_set_review_heads_latest_zero_generation",
        ),
        sa.CheckConstraint(
            "effective_generation <= decision_generation", name="ck_change_set_review_heads_effective_not_ahead"
        ),
        sa.ForeignKeyConstraint(
            ["effective_decision_id", "revision_acceptance_decision_id", "change_set_lineage_id"],
            [
                "change_set_review_decisions.decision_id",
                "change_set_review_decisions.revision_acceptance_decision_id",
                "change_set_review_decisions.change_set_lineage_id",
            ],
            name="fk_change_set_review_heads_effective",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["latest_decision_id", "revision_acceptance_decision_id", "change_set_lineage_id"],
            [
                "change_set_review_decisions.decision_id",
                "change_set_review_decisions.revision_acceptance_decision_id",
                "change_set_review_decisions.change_set_lineage_id",
            ],
            name="fk_change_set_review_heads_latest",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "revision_acceptance_decision_id"],
            [
                "revision_acceptance_decisions.user_id",
                "revision_acceptance_decisions.project_name",
                "revision_acceptance_decisions.decision_id",
            ],
            name="fk_change_set_review_heads_revision_acceptance",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "revision_acceptance_decision_id", "change_set_lineage_id", name="pk_change_set_review_heads"
        ),
    )
    with op.batch_alter_table("change_set_review_heads", schema=None) as batch_op:
        batch_op.create_index("ix_change_set_review_heads_project_name", ["project_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_change_set_review_heads_user_id"), ["user_id"], unique=False)

    op.create_table(
        "conflict_resolution_decisions",
        sa.Column("decision_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("decision_family", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column("scene_contract_id", sa.String(length=255), nullable=False),
        sa.Column("canon_branch_id", sa.String(length=255), nullable=False),
        sa.Column("revision_acceptance_decision_id", sa.String(length=255), nullable=False),
        sa.Column("conflict_resolution_lineage_id", sa.String(length=255), nullable=False),
        sa.Column("chosen_resolution", sa.Text(), nullable=False),
        sa.Column("expected_latest_decision_id", sa.String(length=255), nullable=True),
        sa.Column("expected_effective_decision_id", sa.String(length=255), nullable=True),
        sa.Column("base_canon_version_id", sa.String(length=255), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("scene_contract_version", sa.Integer(), nullable=False),
        sa.Column("context_pack_id", sa.String(length=255), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("decision_generation", sa.Integer(), nullable=False),
        sa.Column("authorization_ref", sa.String(length=255), nullable=False),
        sa.Column("authorization_actor_id", sa.String(length=255), nullable=False),
        sa.Column("authorization_authority_role", sa.String(length=32), nullable=False),
        sa.Column("authorization_stable_subject_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("authorization_decision_command_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("authorization_authenticated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorization_authenticated_via", sa.String(length=255), nullable=False),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint(
            "action IN ('RESOLVE','REJECT','SUPERSEDE')", name="ck_conflict_resolution_decisions_action"
        ),
        sa.CheckConstraint("decision_family = 'CONFLICT_RESOLUTION'", name="ck_conflict_resolution_decisions_family"),
        sa.CheckConstraint("decision_generation >= 1", name="ck_conflict_resolution_decisions_generation"),
        sa.CheckConstraint("plan_version >= 1", name="ck_conflict_resolution_decisions_plan_version"),
        sa.CheckConstraint("scene_contract_version >= 1", name="ck_conflict_resolution_decisions_scene_version"),
        sa.ForeignKeyConstraint(
            ["decision_id", "decision_family"],
            ["narrative_decision_identities.decision_id", "narrative_decision_identities.decision_family"],
            name="fk_conflict_resolution_decisions_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["expected_effective_decision_id", "revision_acceptance_decision_id", "conflict_resolution_lineage_id"],
            [
                "conflict_resolution_decisions.decision_id",
                "conflict_resolution_decisions.revision_acceptance_decision_id",
                "conflict_resolution_decisions.conflict_resolution_lineage_id",
            ],
            name="fk_conflict_resolution_decisions_expected_effective",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["expected_latest_decision_id", "revision_acceptance_decision_id", "conflict_resolution_lineage_id"],
            [
                "conflict_resolution_decisions.decision_id",
                "conflict_resolution_decisions.revision_acceptance_decision_id",
                "conflict_resolution_decisions.conflict_resolution_lineage_id",
            ],
            name="fk_conflict_resolution_decisions_expected_latest",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revision_acceptance_decision_id", "conflict_resolution_lineage_id"],
            [
                "conflict_resolution_lineages.revision_acceptance_decision_id",
                "conflict_resolution_lineages.conflict_resolution_lineage_id",
            ],
            name="fk_conflict_resolution_decisions_lineage",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("decision_id"),
        sa.UniqueConstraint("decision_id", "decision_family", name="uq_conflict_resolution_decisions_family"),
        sa.UniqueConstraint(
            "decision_id",
            "revision_acceptance_decision_id",
            "conflict_resolution_lineage_id",
            name="uq_conflict_resolution_decisions_subject",
        ),
        sa.UniqueConstraint("user_id", "project_name", "decision_id", name="uq_conflict_resolution_decisions_scope"),
    )
    with op.batch_alter_table("conflict_resolution_decisions", schema=None) as batch_op:
        batch_op.create_index("ix_conflict_resolution_decisions_project_name", ["project_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_conflict_resolution_decisions_user_id"), ["user_id"], unique=False)

    op.create_table(
        "conflict_resolution_decision_competitors",
        sa.Column("decision_id", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("change_set_id", sa.String(length=255), nullable=False),
        sa.Column("review_decision_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_conflict_resolution_decision_competitors_position"),
        sa.ForeignKeyConstraint(
            ["review_decision_id"],
            ["change_set_review_decisions.decision_id"],
            name="fk_conflict_resolution_decision_competitors_review",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "change_set_id"],
            [
                "narrative_change_sets.user_id",
                "narrative_change_sets.project_name",
                "narrative_change_sets.change_set_id",
            ],
            name="fk_conflict_resolution_decision_competitors_change_set",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "decision_id"],
            [
                "conflict_resolution_decisions.user_id",
                "conflict_resolution_decisions.project_name",
                "conflict_resolution_decisions.decision_id",
            ],
            name="fk_conflict_resolution_decision_competitors_decision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("decision_id", "position", name="pk_conflict_resolution_decision_competitors"),
    )
    with op.batch_alter_table("conflict_resolution_decision_competitors", schema=None) as batch_op:
        batch_op.create_index("ix_conflict_resolution_decision_competitors_change_set", ["change_set_id"], unique=False)
        batch_op.create_index(
            "ix_conflict_resolution_decision_competitors_review", ["review_decision_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_conflict_resolution_decision_competitors_user_id"), ["user_id"], unique=False
        )

    op.create_table(
        "conflict_resolution_heads",
        sa.Column("revision_acceptance_decision_id", sa.String(length=255), nullable=False),
        sa.Column("conflict_resolution_lineage_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("latest_decision_id", sa.String(length=255), nullable=True),
        sa.Column("decision_generation", sa.Integer(), nullable=False),
        sa.Column("effective_decision_id", sa.String(length=255), nullable=True),
        sa.Column("effective_generation", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint(
            "(effective_decision_id IS NULL AND effective_generation = 0) OR (effective_decision_id IS NOT NULL AND effective_generation > 0)",
            name="ck_conflict_resolution_heads_effective_zero_generation",
        ),
        sa.CheckConstraint(
            "(latest_decision_id IS NULL AND decision_generation = 0) OR (latest_decision_id IS NOT NULL AND decision_generation > 0)",
            name="ck_conflict_resolution_heads_latest_zero_generation",
        ),
        sa.CheckConstraint(
            "effective_generation <= decision_generation", name="ck_conflict_resolution_heads_effective_not_ahead"
        ),
        sa.ForeignKeyConstraint(
            ["effective_decision_id", "revision_acceptance_decision_id", "conflict_resolution_lineage_id"],
            [
                "conflict_resolution_decisions.decision_id",
                "conflict_resolution_decisions.revision_acceptance_decision_id",
                "conflict_resolution_decisions.conflict_resolution_lineage_id",
            ],
            name="fk_conflict_resolution_heads_effective",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["latest_decision_id", "revision_acceptance_decision_id", "conflict_resolution_lineage_id"],
            [
                "conflict_resolution_decisions.decision_id",
                "conflict_resolution_decisions.revision_acceptance_decision_id",
                "conflict_resolution_decisions.conflict_resolution_lineage_id",
            ],
            name="fk_conflict_resolution_heads_latest",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revision_acceptance_decision_id", "conflict_resolution_lineage_id"],
            [
                "conflict_resolution_lineages.revision_acceptance_decision_id",
                "conflict_resolution_lineages.conflict_resolution_lineage_id",
            ],
            name="fk_conflict_resolution_heads_lineage",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "revision_acceptance_decision_id", "conflict_resolution_lineage_id", name="pk_conflict_resolution_heads"
        ),
    )
    with op.batch_alter_table("conflict_resolution_heads", schema=None) as batch_op:
        batch_op.create_index("ix_conflict_resolution_heads_project_name", ["project_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_conflict_resolution_heads_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("conflict_resolution_heads", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_conflict_resolution_heads_user_id"))
        batch_op.drop_index("ix_conflict_resolution_heads_project_name")

    op.drop_table("conflict_resolution_heads")
    with op.batch_alter_table("conflict_resolution_decision_competitors", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_conflict_resolution_decision_competitors_user_id"))
        batch_op.drop_index("ix_conflict_resolution_decision_competitors_review")
        batch_op.drop_index("ix_conflict_resolution_decision_competitors_change_set")

    op.drop_table("conflict_resolution_decision_competitors")
    with op.batch_alter_table("conflict_resolution_decisions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_conflict_resolution_decisions_user_id"))
        batch_op.drop_index("ix_conflict_resolution_decisions_project_name")

    op.drop_table("conflict_resolution_decisions")
    with op.batch_alter_table("change_set_review_heads", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_change_set_review_heads_user_id"))
        batch_op.drop_index("ix_change_set_review_heads_project_name")

    op.drop_table("change_set_review_heads")
    with op.batch_alter_table("revision_acceptance_heads", schema=None) as batch_op:
        batch_op.drop_index("ix_revision_acceptance_heads_project_name")

    op.drop_table("revision_acceptance_heads")
    with op.batch_alter_table("conflict_resolution_lineages", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_conflict_resolution_lineages_user_id"))
        batch_op.drop_index("ix_conflict_resolution_lineages_project_name")

    op.drop_table("conflict_resolution_lineages")
    with op.batch_alter_table("change_set_review_decisions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_change_set_review_decisions_user_id"))
        batch_op.drop_index("ix_change_set_review_decisions_project_name")
        batch_op.drop_index("ix_change_set_review_decisions_lineage")

    op.drop_table("change_set_review_decisions")
    with op.batch_alter_table("revision_acceptance_decisions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_revision_acceptance_decisions_user_id"))
        batch_op.drop_index("ix_revision_acceptance_decisions_project_name")

    op.drop_table("revision_acceptance_decisions")
    with op.batch_alter_table("narrative_decision_identities", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_narrative_decision_identities_user_id"))
        batch_op.drop_index("ix_narrative_decision_identities_project_name")

    op.drop_table("narrative_decision_identities")
