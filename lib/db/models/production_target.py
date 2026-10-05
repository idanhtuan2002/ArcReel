"""Scoped immutable Take-derived target versions and current-head receipts."""

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

_TARGET_KIND = "target_type IN ('SCENE', 'SHOT')"
_SCENE_DEPENDENCY = (
    "(target_type = 'SCENE' AND scene_target_type IS NULL AND scene_target_id IS NULL "
    "AND scene_registry_version IS NULL AND scene_version_digest IS NULL) OR "
    "(target_type = 'SHOT' AND scene_target_type = 'SCENE' AND scene_target_id IS NOT NULL "
    "AND scene_registry_version IS NOT NULL AND scene_registry_version >= 1 AND scene_version_digest IS NOT NULL)"
)


class ProductionTargetHeadModel(Base):
    __tablename__ = "production_target_heads"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "target_type", "target_id", name="pk_production_target_heads"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "target_type", "target_id", "current_version"],
            [
                "production_target_versions.user_id",
                "production_target_versions.project_name",
                "production_target_versions.target_type",
                "production_target_versions.target_id",
                "production_target_versions.registry_version",
            ],
            name="fk_production_target_heads_current",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_TARGET_KIND, name="ck_production_target_heads_type"),
        CheckConstraint(
            "(current_version IS NULL AND current_version_digest IS NULL) OR "
            "(current_version >= 1 AND current_version_digest IS NOT NULL)",
            name="ck_production_target_heads_current_pair",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="RESTRICT"), server_default=DEFAULT_USER_ID
    )
    project_name: Mapped[str] = mapped_column(String(255))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(255))
    current_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_version_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)


class ProductionTargetVersionModel(Base):
    __tablename__ = "production_target_versions"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id",
            "project_name",
            "target_type",
            "target_id",
            "registry_version",
            name="pk_production_target_versions",
        ),
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
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
        CheckConstraint(_TARGET_KIND, name="ck_production_target_versions_type"),
        CheckConstraint("registry_version >= 1", name="ck_production_target_versions_number"),
        CheckConstraint(_SCENE_DEPENDENCY, name="ck_production_target_versions_scene_dependency"),
    )

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="RESTRICT"), server_default=DEFAULT_USER_ID
    )
    project_name: Mapped[str] = mapped_column(String(255))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(255))
    registry_version: Mapped[int] = mapped_column(Integer)
    target_body_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    target_body_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    admitted_screenplay_ref_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    take_derivation_version: Mapped[str] = mapped_column(String(255), nullable=False)
    version_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    scene_target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scene_target_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scene_registry_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scene_version_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProductionTargetCommandModel(Base):
    __tablename__ = "production_target_commands"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id", "project_name", "principal", "command_id", name="pk_production_target_commands"
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="RESTRICT"), server_default=DEFAULT_USER_ID
    )
    project_name: Mapped[str] = mapped_column(String(255))
    principal: Mapped[str] = mapped_column(String(255))
    command_id: Mapped[str] = mapped_column(String(255))
    command_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
