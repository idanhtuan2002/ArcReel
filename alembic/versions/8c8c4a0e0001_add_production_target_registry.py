"""Add scoped Take-derived target heads, versions and command receipts.

Revision ID: 8c8c4a0e0001
Revises: 8b8c4a0e0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8c8c4a0e0001"
down_revision: str | Sequence[str] | None = "8b8c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TARGET_KIND = "target_type IN ('SCENE', 'SHOT')"
_SCENE_DEPENDENCY = (
    "(target_type = 'SCENE' AND scene_target_type IS NULL AND scene_target_id IS NULL "
    "AND scene_registry_version IS NULL AND scene_version_digest IS NULL) OR "
    "(target_type = 'SHOT' AND scene_target_type = 'SCENE' AND scene_target_id IS NOT NULL "
    "AND scene_registry_version IS NOT NULL AND scene_registry_version >= 1 AND scene_version_digest IS NOT NULL)"
)


def upgrade() -> None:
    op.create_table(
        "production_target_heads",
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            server_default="default",
            nullable=False,
        ),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=True),
        sa.Column("current_version_digest", sa.String(length=71), nullable=True),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "target_type", "target_id", name="pk_production_target_heads"
        ),
        sa.CheckConstraint(_TARGET_KIND, name="ck_production_target_heads_type"),
        sa.CheckConstraint(
            "(current_version IS NULL AND current_version_digest IS NULL) OR "
            "(current_version >= 1 AND current_version_digest IS NOT NULL)",
            name="ck_production_target_heads_current_pair",
        ),
    )
    op.create_table(
        "production_target_versions",
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            server_default="default",
            nullable=False,
        ),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("registry_version", sa.Integer(), nullable=False),
        sa.Column("target_body_json", sa.JSON(), nullable=False),
        sa.Column("target_body_digest", sa.String(length=71), nullable=False),
        sa.Column("admitted_screenplay_ref_json", sa.JSON(), nullable=False),
        sa.Column("take_derivation_version", sa.String(length=255), nullable=False),
        sa.Column("version_digest", sa.String(length=71), nullable=False),
        sa.Column("scene_target_type", sa.String(length=32), nullable=True),
        sa.Column("scene_target_id", sa.String(length=255), nullable=True),
        sa.Column("scene_registry_version", sa.Integer(), nullable=True),
        sa.Column("scene_version_digest", sa.String(length=71), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id",
            "project_name",
            "target_type",
            "target_id",
            "registry_version",
            name="pk_production_target_versions",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "target_type", "target_id"],
            [
                "production_target_heads.user_id",
                "production_target_heads.project_name",
                "production_target_heads.target_type",
                "production_target_heads.target_id",
            ],
            name="fk_production_target_versions_head",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "scene_target_type", "scene_target_id", "scene_registry_version"],
            [
                "production_target_versions.user_id",
                "production_target_versions.project_name",
                "production_target_versions.target_type",
                "production_target_versions.target_id",
                "production_target_versions.registry_version",
            ],
            name="fk_production_target_versions_scene",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(_TARGET_KIND, name="ck_production_target_versions_type"),
        sa.CheckConstraint("registry_version >= 1", name="ck_production_target_versions_number"),
        sa.CheckConstraint(_SCENE_DEPENDENCY, name="ck_production_target_versions_scene_dependency"),
    )
    with op.batch_alter_table("production_target_heads") as batch_op:
        batch_op.create_foreign_key(
            "fk_production_target_heads_current",
            "production_target_versions",
            ["user_id", "project_name", "target_type", "target_id", "current_version"],
            ["user_id", "project_name", "target_type", "target_id", "registry_version"],
            ondelete="RESTRICT",
        )
    op.create_table(
        "production_target_commands",
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            server_default="default",
            nullable=False,
        ),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("principal", sa.String(length=255), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("command_digest", sa.String(length=71), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("result_digest", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "principal", "command_id", name="pk_production_target_commands"
        ),
    )


def downgrade() -> None:
    op.drop_table("production_target_commands")
    with op.batch_alter_table("production_target_heads") as batch_op:
        batch_op.drop_constraint("fk_production_target_heads_current", type_="foreignkey")
    op.drop_table("production_target_versions")
    op.drop_table("production_target_heads")
