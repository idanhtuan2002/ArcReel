"""add M8 exploration authority (plan 2026-09-13 M8-A, execution contract amendments)

Six append-only M8 evidence tables: candidate heads and revisions, command receipts, promotion
previews, authorizations and receipts. No cascade deletion from any evidence table; downgrade
removes only these six tables, in reverse dependency order.

Revision ID: 8a8c4a0e0001
Revises: c9e1f4a2b701
Create Date: 2026-09-29 13:08:21.823998

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8a8c4a0e0001"
down_revision: str | Sequence[str] | None = "c9e1f4a2b701"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES_IN_DEPENDENCY_ORDER = (
    "m8_candidate_heads",
    "m8_command_receipts",
    "m8_candidate_revisions",
    "m8_promotion_previews",
    "m8_promotion_authorizations",
    "m8_promotion_receipts",
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "m8_candidate_heads",
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("head_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint("current_revision >= 1", name="ck_m8_candidate_heads_current_revision"),
        sa.CheckConstraint("head_version >= 1", name="ck_m8_candidate_heads_head_version"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("candidate_id", name="pk_m8_candidate_heads"),
        sa.UniqueConstraint("user_id", "project_name", "candidate_id", name="uq_m8_candidate_heads_scope"),
    )
    with op.batch_alter_table("m8_candidate_heads", schema=None) as batch_op:
        batch_op.create_index("ix_m8_candidate_heads_scope", ["user_id", "project_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_m8_candidate_heads_user_id"), ["user_id"], unique=False)

    op.create_table(
        "m8_command_receipts",
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("actor_scope", sa.String(length=255), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("command_digest", sa.String(length=71), nullable=False),
        sa.Column("result_kind", sa.String(length=32), nullable=False),
        sa.Column("result_ref", sa.String(length=255), nullable=False),
        sa.Column("result_digest", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint(
            "operation IN ('APPEND_REVISION', 'PREVIEW', 'PROMOTE')", name="ck_m8_command_receipts_operation"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "actor_scope", "operation", "command_id", name="pk_m8_command_receipts"
        ),
    )
    with op.batch_alter_table("m8_command_receipts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_m8_command_receipts_user_id"), ["user_id"], unique=False)

    op.create_table(
        "m8_candidate_revisions",
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("parent_revision", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_digest", sa.String(length=71), nullable=False),
        sa.Column("lineage_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint("kind IN ('CANVAS', 'SPATIAL', 'FORMAT')", name="ck_m8_candidate_revisions_kind"),
        sa.CheckConstraint(
            "parent_revision IS NULL OR parent_revision = revision - 1", name="ck_m8_candidate_revisions_parent"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_m8_candidate_revisions_revision"),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["m8_candidate_heads.candidate_id"], name="fk_m8_candidate_revisions_candidate"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("candidate_id", "revision", name="pk_m8_candidate_revisions"),
        sa.UniqueConstraint(
            "user_id", "project_name", "candidate_id", "revision", name="uq_m8_candidate_revisions_scope"
        ),
    )
    with op.batch_alter_table("m8_candidate_revisions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_m8_candidate_revisions_user_id"), ["user_id"], unique=False)

    op.create_table(
        "m8_promotion_previews",
        sa.Column("preview_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("preview_command_id", sa.String(length=255), nullable=False),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("candidate_revision", sa.Integer(), nullable=False),
        sa.Column("candidate_payload_digest", sa.String(length=71), nullable=False),
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        sa.Column("target_ref", sa.String(length=255), nullable=False),
        sa.Column("expected_target_version", sa.Integer(), nullable=False),
        sa.Column("expected_master_id", sa.String(length=255), nullable=True),
        sa.Column("expected_master_digest", sa.String(length=71), nullable=True),
        sa.Column("impact_json", sa.JSON(), nullable=False),
        sa.Column("impact_digest", sa.String(length=71), nullable=False),
        sa.Column("preview_digest", sa.String(length=71), nullable=False),
        sa.Column("authorization_scope", sa.String(length=255), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint(
            "(target_kind = 'ARTIFACT_SLOT' AND expected_master_id IS NOT NULL AND expected_master_digest IS NOT NULL) OR (target_kind = 'PRODUCTION_BINDING' AND expected_master_id IS NULL AND expected_master_digest IS NULL)",
            name="ck_m8_promotion_previews_master_coupling",
        ),
        sa.CheckConstraint("expected_target_version >= 0", name="ck_m8_promotion_previews_target_version"),
        sa.CheckConstraint("ttl_seconds > 0 AND ttl_seconds <= 3600", name="ck_m8_promotion_previews_ttl"),
        sa.ForeignKeyConstraint(
            ["candidate_id", "candidate_revision"],
            ["m8_candidate_revisions.candidate_id", "m8_candidate_revisions.revision"],
            name="fk_m8_promotion_previews_revision",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("preview_id", name="pk_m8_promotion_previews"),
        sa.UniqueConstraint("user_id", "project_name", "preview_command_id", name="uq_m8_promotion_previews_command"),
    )
    with op.batch_alter_table("m8_promotion_previews", schema=None) as batch_op:
        batch_op.create_index("ix_m8_promotion_previews_expiry", ["expires_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_m8_promotion_previews_user_id"), ["user_id"], unique=False)

    op.create_table(
        "m8_promotion_authorizations",
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("preview_id", sa.String(length=255), nullable=False),
        sa.Column("preview_digest", sa.String(length=71), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("actor_scope", sa.String(length=255), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorization_digest", sa.String(length=71), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint("decision = 'APPROVE'", name="ck_m8_promotion_authorizations_decision"),
        sa.ForeignKeyConstraint(
            ["preview_id"], ["m8_promotion_previews.preview_id"], name="fk_m8_promotion_authorizations_preview"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "command_id", name="pk_m8_promotion_authorizations"),
        sa.UniqueConstraint(
            "user_id", "project_name", "authorization_digest", name="uq_m8_promotion_authorizations_digest"
        ),
    )
    with op.batch_alter_table("m8_promotion_authorizations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_m8_promotion_authorizations_user_id"), ["user_id"], unique=False)

    op.create_table(
        "m8_promotion_receipts",
        sa.Column("receipt_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("preview_id", sa.String(length=255), nullable=False),
        sa.Column("preview_digest", sa.String(length=71), nullable=False),
        sa.Column("authorization_digest", sa.String(length=71), nullable=False),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("candidate_revision", sa.Integer(), nullable=False),
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        sa.Column("target_ref", sa.String(length=255), nullable=False),
        sa.Column("expected_target_version", sa.Integer(), nullable=False),
        sa.Column("result_artifact_ref", sa.String(length=255), nullable=False),
        sa.Column("result_master_id", sa.String(length=255), nullable=True),
        sa.Column("result_digest", sa.String(length=71), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.CheckConstraint(
            "(target_kind = 'ARTIFACT_SLOT' AND result_master_id IS NOT NULL) OR (target_kind = 'PRODUCTION_BINDING' AND result_master_id IS NULL)",
            name="ck_m8_promotion_receipts_master_coupling",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id", "candidate_revision"],
            ["m8_candidate_revisions.candidate_id", "m8_candidate_revisions.revision"],
            name="fk_m8_promotion_receipts_revision",
        ),
        sa.ForeignKeyConstraint(
            ["preview_id"], ["m8_promotion_previews.preview_id"], name="fk_m8_promotion_receipts_preview"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "command_id"],
            [
                "m8_promotion_authorizations.user_id",
                "m8_promotion_authorizations.project_name",
                "m8_promotion_authorizations.command_id",
            ],
            name="fk_m8_promotion_receipts_authorization",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("receipt_id", name="pk_m8_promotion_receipts"),
        sa.UniqueConstraint("user_id", "project_name", "command_id", name="uq_m8_promotion_receipts_command"),
    )
    with op.batch_alter_table("m8_promotion_receipts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_m8_promotion_receipts_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    for table in reversed(_TABLES_IN_DEPENDENCY_ORDER):
        op.drop_table(table)
