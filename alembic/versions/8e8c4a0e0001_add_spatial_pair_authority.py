"""Add scoped spatial pair decision heads and immutable history.

Revision ID: 8e8c4a0e0001
Revises: 8d8c4a0e0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8e8c4a0e0001"
down_revision: str | Sequence[str] | None = "8d8c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _user_id() -> sa.Column[str]:
    return sa.Column(
        "user_id", sa.String(), sa.ForeignKey("users.id", ondelete="RESTRICT"), server_default="default", nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "m8_spatial_pair_heads",
        _user_id(),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("pair_id", sa.String(length=255), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=True),
        sa.Column("current_decision_digest", sa.String(length=71), nullable=True),
        sa.PrimaryKeyConstraint("user_id", "project_name", "pair_id", name="pk_m8_spatial_pair_heads"),
        sa.CheckConstraint(
            "(current_version IS NULL AND current_decision_digest IS NULL) OR "
            "(current_version IS NOT NULL AND current_version >= 1 AND current_decision_digest IS NOT NULL)",
            name="ck_m8_spatial_pair_heads_current_pair",
        ),
    )
    op.create_table(
        "m8_spatial_pair_decisions",
        _user_id(),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("pair_id", sa.String(length=255), nullable=False),
        sa.Column("pair_version", sa.Integer(), nullable=False),
        sa.Column("decision_body_json", sa.JSON(), nullable=False),
        sa.Column("decision_digest", sa.String(length=71), nullable=False),
        sa.Column("command_digest", sa.String(length=71), nullable=False),
        sa.Column("authorization_digest", sa.String(length=71), nullable=False),
        sa.Column("binding_id", sa.String(length=255), nullable=False),
        sa.Column("binding_version", sa.Integer(), nullable=False),
        sa.Column("binding_envelope_digest", sa.String(length=71), nullable=False),
        sa.Column("binding_core_digest", sa.String(length=71), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("target_registry_version", sa.Integer(), nullable=False),
        sa.Column("target_version_digest", sa.String(length=71), nullable=False),
        sa.Column("scene_type", sa.String(length=32), nullable=False),
        sa.Column("scene_id", sa.String(length=255), nullable=False),
        sa.Column("scene_registry_version", sa.Integer(), nullable=False),
        sa.Column("scene_version_digest", sa.String(length=71), nullable=False),
        sa.Column("master_receipt_id", sa.String(length=255), nullable=False),
        sa.Column("reverse_receipt_id", sa.String(length=255), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "pair_id", "pair_version", name="pk_m8_spatial_pair_decisions"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "pair_id"],
            ["m8_spatial_pair_heads.user_id", "m8_spatial_pair_heads.project_name", "m8_spatial_pair_heads.pair_id"],
            name="fk_m8_spatial_pair_decisions_head",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "binding_id", "binding_version"],
            [
                "production_binding_versions.user_id",
                "production_binding_versions.project_name",
                "production_binding_versions.binding_id",
                "production_binding_versions.binding_version",
            ],
            name="fk_m8_spatial_pair_decisions_binding",
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
            name="fk_m8_spatial_pair_decisions_target",
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
            name="fk_m8_spatial_pair_decisions_scene",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "master_receipt_id"],
            [
                "m8_spatial_frame_receipts.user_id",
                "m8_spatial_frame_receipts.project_name",
                "m8_spatial_frame_receipts.receipt_id",
            ],
            name="fk_m8_spatial_pair_decisions_master_receipt",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "reverse_receipt_id"],
            [
                "m8_spatial_frame_receipts.user_id",
                "m8_spatial_frame_receipts.project_name",
                "m8_spatial_frame_receipts.receipt_id",
            ],
            name="fk_m8_spatial_pair_decisions_reverse_receipt",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("pair_version >= 1", name="ck_m8_spatial_pair_decisions_version"),
        sa.CheckConstraint("binding_version >= 1", name="ck_m8_spatial_pair_decisions_binding_version"),
        sa.CheckConstraint("target_type = 'SHOT' AND scene_type = 'SCENE'", name="ck_m8_spatial_pair_decisions_types"),
        sa.CheckConstraint(
            "master_receipt_id <> reverse_receipt_id", name="ck_m8_spatial_pair_decisions_distinct_frames"
        ),
        sa.CheckConstraint("decision IN ('APPROVE','REJECT')", name="ck_m8_spatial_pair_decisions_action"),
    )
    with op.batch_alter_table("m8_spatial_pair_heads") as batch_op:
        batch_op.create_foreign_key(
            "fk_m8_spatial_pair_heads_current",
            "m8_spatial_pair_decisions",
            ["user_id", "project_name", "pair_id", "current_version"],
            ["user_id", "project_name", "pair_id", "pair_version"],
            ondelete="RESTRICT",
        )
    op.create_table(
        "m8_spatial_pair_commands",
        _user_id(),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("principal", sa.String(length=255), nullable=False),
        sa.Column("command_id", sa.String(length=255), nullable=False),
        sa.Column("command_digest", sa.String(length=71), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("result_digest", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "principal", "command_id", name="pk_m8_spatial_pair_commands"
        ),
    )


def downgrade() -> None:
    op.drop_table("m8_spatial_pair_commands")
    with op.batch_alter_table("m8_spatial_pair_heads") as batch_op:
        batch_op.drop_constraint("fk_m8_spatial_pair_heads_current", type_="foreignkey")
    op.drop_table("m8_spatial_pair_decisions")
    op.drop_table("m8_spatial_pair_heads")
