"""Add scoped LOCATION binding heads, versions and command receipts.

Revision ID: 8d8c4a0e0001
Revises: 8c9c4a0e0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8d8c4a0e0001"
down_revision: str | Sequence[str] | None = "8c9c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _user_id() -> sa.Column[str]:
    return sa.Column(
        "user_id", sa.String(), sa.ForeignKey("users.id", ondelete="RESTRICT"), server_default="default", nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "production_binding_heads",
        _user_id(),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("binding_id", sa.String(length=255), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=True),
        sa.Column("current_envelope_digest", sa.String(length=71), nullable=True),
        sa.PrimaryKeyConstraint("user_id", "project_name", "binding_id", name="pk_production_binding_heads"),
        sa.CheckConstraint(
            "(current_version IS NULL AND current_envelope_digest IS NULL) OR "
            "(current_version IS NOT NULL AND current_version >= 1 AND current_envelope_digest IS NOT NULL)",
            name="ck_production_binding_heads_current_pair",
        ),
    )
    op.create_table(
        "production_binding_versions",
        _user_id(),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("binding_id", sa.String(length=255), nullable=False),
        sa.Column("binding_version", sa.Integer(), nullable=False),
        sa.Column("binding_body_json", sa.JSON(), nullable=False),
        sa.Column("binding_body_digest", sa.String(length=71), nullable=False),
        sa.Column("envelope_json", sa.JSON(), nullable=False),
        sa.Column("envelope_digest", sa.String(length=71), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("target_registry_version", sa.Integer(), nullable=False),
        sa.Column("target_version_digest", sa.String(length=71), nullable=False),
        sa.Column("scene_type", sa.String(length=32), nullable=False),
        sa.Column("scene_id", sa.String(length=255), nullable=False),
        sa.Column("scene_registry_version", sa.Integer(), nullable=False),
        sa.Column("scene_version_digest", sa.String(length=71), nullable=False),
        sa.Column("receipt_a_id", sa.String(length=255), nullable=False),
        sa.Column("receipt_b_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "binding_id", "binding_version", name="pk_production_binding_versions"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "binding_id"],
            [
                "production_binding_heads.user_id",
                "production_binding_heads.project_name",
                "production_binding_heads.binding_id",
            ],
            name="fk_production_binding_versions_head",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "target_type", "target_id", "target_registry_version"],
            [
                "production_target_versions.user_id",
                "production_target_versions.project_name",
                "production_target_versions.target_type",
                "production_target_versions.target_id",
                "production_target_versions.registry_version",
            ],
            name="fk_production_binding_versions_target",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "scene_type", "scene_id", "scene_registry_version"],
            [
                "production_target_versions.user_id",
                "production_target_versions.project_name",
                "production_target_versions.target_type",
                "production_target_versions.target_id",
                "production_target_versions.registry_version",
            ],
            name="fk_production_binding_versions_scene",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "receipt_a_id"],
            [
                "m8_spatial_frame_receipts.user_id",
                "m8_spatial_frame_receipts.project_name",
                "m8_spatial_frame_receipts.receipt_id",
            ],
            name="fk_production_binding_versions_receipt_a",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "receipt_b_id"],
            [
                "m8_spatial_frame_receipts.user_id",
                "m8_spatial_frame_receipts.project_name",
                "m8_spatial_frame_receipts.receipt_id",
            ],
            name="fk_production_binding_versions_receipt_b",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("binding_version >= 1", name="ck_production_binding_versions_number"),
        sa.CheckConstraint(
            "target_type = 'SHOT' AND scene_type = 'SCENE'", name="ck_production_binding_versions_types"
        ),
        sa.CheckConstraint("receipt_a_id < receipt_b_id", name="ck_production_binding_versions_receipt_order"),
    )
    with op.batch_alter_table("production_binding_heads") as batch_op:
        batch_op.create_foreign_key(
            "fk_production_binding_heads_current",
            "production_binding_versions",
            ["user_id", "project_name", "binding_id", "current_version"],
            ["user_id", "project_name", "binding_id", "binding_version"],
            ondelete="RESTRICT",
        )
    op.create_table(
        "production_binding_commands",
        _user_id(),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("principal", sa.String(length=255), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("command_digest", sa.String(length=71), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("result_digest", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "principal", "command_id", name="pk_production_binding_commands"
        ),
    )


def downgrade() -> None:
    op.drop_table("production_binding_commands")
    with op.batch_alter_table("production_binding_heads") as batch_op:
        batch_op.drop_constraint("fk_production_binding_heads_current", type_="foreignkey")
    op.drop_table("production_binding_versions")
    op.drop_table("production_binding_heads")
