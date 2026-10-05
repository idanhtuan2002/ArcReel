"""Scoped immutable LOCATION binding versions and command receipts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import DEFAULT_USER_ID, Base


class ProductionBindingHeadModel(Base):
    __tablename__ = "production_binding_heads"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "binding_id", name="pk_production_binding_heads"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "binding_id", "current_version"],
            [
                "production_binding_versions.user_id",
                "production_binding_versions.project_name",
                "production_binding_versions.binding_id",
                "production_binding_versions.binding_version",
            ],
            name="fk_production_binding_heads_current",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(current_version IS NULL AND current_envelope_digest IS NULL) OR "
            "(current_version IS NOT NULL AND current_version >= 1 AND current_envelope_digest IS NOT NULL)",
            name="ck_production_binding_heads_current_pair",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="RESTRICT"), server_default=DEFAULT_USER_ID
    )
    project_name: Mapped[str] = mapped_column(String(255))
    binding_id: Mapped[str] = mapped_column(String(255))
    current_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_envelope_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)


class ProductionBindingVersionModel(Base):
    __tablename__ = "production_binding_versions"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id", "project_name", "binding_id", "binding_version", name="pk_production_binding_versions"
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "binding_id"],
            [
                "production_binding_heads.user_id",
                "production_binding_heads.project_name",
                "production_binding_heads.binding_id",
            ],
            name="fk_production_binding_versions_head",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
            ["user_id", "project_name", "receipt_a_id"],
            [
                "m8_spatial_frame_receipts.user_id",
                "m8_spatial_frame_receipts.project_name",
                "m8_spatial_frame_receipts.receipt_id",
            ],
            name="fk_production_binding_versions_receipt_a",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "receipt_b_id"],
            [
                "m8_spatial_frame_receipts.user_id",
                "m8_spatial_frame_receipts.project_name",
                "m8_spatial_frame_receipts.receipt_id",
            ],
            name="fk_production_binding_versions_receipt_b",
            ondelete="RESTRICT",
        ),
        CheckConstraint("binding_version >= 1", name="ck_production_binding_versions_number"),
        CheckConstraint("target_type = 'SHOT' AND scene_type = 'SCENE'", name="ck_production_binding_versions_types"),
        CheckConstraint("receipt_a_id < receipt_b_id", name="ck_production_binding_versions_receipt_order"),
    )

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="RESTRICT"), server_default=DEFAULT_USER_ID
    )
    project_name: Mapped[str] = mapped_column(String(255))
    binding_id: Mapped[str] = mapped_column(String(255))
    binding_version: Mapped[int] = mapped_column(Integer)
    binding_body_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    binding_body_digest: Mapped[str] = mapped_column(String(71))
    envelope_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    envelope_digest: Mapped[str] = mapped_column(String(71))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(255))
    target_registry_version: Mapped[int] = mapped_column(Integer)
    target_version_digest: Mapped[str] = mapped_column(String(71))
    scene_type: Mapped[str] = mapped_column(String(32))
    scene_id: Mapped[str] = mapped_column(String(255))
    scene_registry_version: Mapped[int] = mapped_column(Integer)
    scene_version_digest: Mapped[str] = mapped_column(String(71))
    receipt_a_id: Mapped[str] = mapped_column(String(255))
    receipt_b_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProductionBindingCommandModel(Base):
    __tablename__ = "production_binding_commands"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id", "project_name", "principal", "command_id", name="pk_production_binding_commands"
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="RESTRICT"), server_default=DEFAULT_USER_ID
    )
    project_name: Mapped[str] = mapped_column(String(255))
    principal: Mapped[str] = mapped_column(String(255))
    command_id: Mapped[str] = mapped_column(String(255))
    command_digest: Mapped[str] = mapped_column(String(71))
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_digest: Mapped[str] = mapped_column(String(71))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
