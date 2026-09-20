"""add atomic master promotion

Revision ID: 7b7c4a0e0001
Revises: 7a7c4a0e0001
Create Date: 2026-09-20 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7b7c4a0e0001"
down_revision: str | Sequence[str] | None = "7a7c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BACKUP_SET_STATES = "('PREPARING','COMPLETE','VERIFIED','REJECTED')"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "candidate_objects",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("artifact_key", sa.String(length=255), nullable=False),
        sa.Column("object_ref", sa.String(length=1024), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_digest", sa.String(length=255), nullable=False),
        sa.Column("media_probe_digest", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("byte_size >= 0", name="ck_candidate_objects_byte_size"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("candidate_id", name="pk_candidate_objects"),
        sa.UniqueConstraint("user_id", "project_name", "candidate_id", name="uq_candidate_objects_scope"),
    )
    with op.batch_alter_table("candidate_objects", schema=None) as batch_op:
        batch_op.create_index("ix_candidate_objects_project_name", ["project_name"], unique=False)
        batch_op.create_index(
            "ix_candidate_objects_artifact_key", ["user_id", "project_name", "artifact_key"], unique=False
        )

    op.create_table(
        "master_authorities",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("artifact_key", sa.String(length=255), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("current_version >= 0", name="ck_master_authorities_current_version"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "artifact_key", name="pk_master_authorities"),
    )

    op.create_table(
        "master_head_versions",
        sa.Column("master_head_version_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("artifact_key", sa.String(length=255), nullable=False),
        sa.Column("master_version", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("object_ref", sa.String(length=1024), nullable=False),
        sa.Column("content_digest", sa.String(length=255), nullable=False),
        sa.Column("approval_record", sa.String(length=255), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("master_version >= 1", name="ck_master_head_versions_master_version"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidate_objects.candidate_id"],
            name="fk_master_head_versions_candidate",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("master_head_version_id", name="pk_master_head_versions"),
        sa.UniqueConstraint(
            "user_id", "project_name", "artifact_key", "master_version", name="uq_master_head_versions_scope_version"
        ),
    )
    with op.batch_alter_table("master_head_versions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_master_head_versions_scope", ["user_id", "project_name", "artifact_key"], unique=False
        )
        batch_op.create_index("ix_master_head_versions_candidate_id", ["candidate_id"], unique=False)

    op.create_table(
        "promotion_receipts",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("artifact_key", sa.String(length=255), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("command_digest", sa.String(length=255), nullable=False),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.Column("master_version", sa.Integer(), nullable=False),
        sa.Column("approval_record", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidate_objects.candidate_id"],
            name="fk_promotion_receipts_candidate",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id", "project_name", "artifact_key", "command_id", name="pk_promotion_receipts"),
    )
    with op.batch_alter_table("promotion_receipts", schema=None) as batch_op:
        batch_op.create_index("ix_promotion_receipts_candidate_id", ["candidate_id"], unique=False)
        batch_op.create_index("ix_promotion_receipts_project_name", ["project_name"], unique=False)

    op.create_table(
        "backup_sets",
        sa.Column("user_id", sa.String(), server_default="default", nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("backup_set_id", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"state IN {_BACKUP_SET_STATES}", name="ck_backup_sets_state"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("backup_set_id", name="pk_backup_sets"),
        sa.UniqueConstraint("user_id", "project_name", "backup_set_id", name="uq_backup_sets_scope"),
    )
    with op.batch_alter_table("backup_sets", schema=None) as batch_op:
        batch_op.create_index("ix_backup_sets_project_name", ["project_name"], unique=False)

    op.create_table(
        "backup_set_media_refs",
        sa.Column("backup_set_id", sa.String(length=255), nullable=False),
        sa.Column("candidate_id", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["backup_set_id"],
            ["backup_sets.backup_set_id"],
            name="fk_backup_set_media_refs_backup_set",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidate_objects.candidate_id"],
            name="fk_backup_set_media_refs_candidate",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("backup_set_id", "candidate_id", name="pk_backup_set_media_refs"),
    )
    with op.batch_alter_table("backup_set_media_refs", schema=None) as batch_op:
        batch_op.create_index("ix_backup_set_media_refs_candidate_id", ["candidate_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("backup_set_media_refs", schema=None) as batch_op:
        batch_op.drop_index("ix_backup_set_media_refs_candidate_id")
    op.drop_table("backup_set_media_refs")

    with op.batch_alter_table("backup_sets", schema=None) as batch_op:
        batch_op.drop_index("ix_backup_sets_project_name")
    op.drop_table("backup_sets")

    with op.batch_alter_table("promotion_receipts", schema=None) as batch_op:
        batch_op.drop_index("ix_promotion_receipts_project_name")
        batch_op.drop_index("ix_promotion_receipts_candidate_id")
    op.drop_table("promotion_receipts")

    with op.batch_alter_table("master_head_versions", schema=None) as batch_op:
        batch_op.drop_index("ix_master_head_versions_candidate_id")
        batch_op.drop_index("ix_master_head_versions_scope")
    op.drop_table("master_head_versions")

    op.drop_table("master_authorities")

    with op.batch_alter_table("candidate_objects", schema=None) as batch_op:
        batch_op.drop_index("ix_candidate_objects_artifact_key")
        batch_op.drop_index("ix_candidate_objects_project_name")
    op.drop_table("candidate_objects")
