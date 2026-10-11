"""Scoped heads, immutable decisions and command receipts for reviewed spatial pairs."""

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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import DEFAULT_USER_ID, Base


class SpatialPairHeadModel(Base):
    __tablename__ = "m8_spatial_pair_heads"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "pair_id", name="pk_m8_spatial_pair_heads"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "pair_id", "current_version"],
            [
                "m8_spatial_pair_decisions.user_id",
                "m8_spatial_pair_decisions.project_name",
                "m8_spatial_pair_decisions.pair_id",
                "m8_spatial_pair_decisions.pair_version",
            ],
            name="fk_m8_spatial_pair_heads_current",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(current_version IS NULL AND current_decision_digest IS NULL) OR "
            "(current_version IS NOT NULL AND current_version >= 1 AND current_decision_digest IS NOT NULL)",
            name="ck_m8_spatial_pair_heads_current_pair",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="RESTRICT"), server_default=DEFAULT_USER_ID
    )
    project_name: Mapped[str] = mapped_column(String(255))
    pair_id: Mapped[str] = mapped_column(String(255))
    current_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_decision_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)


class SpatialPairDecisionModel(Base):
    __tablename__ = "m8_spatial_pair_decisions"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "pair_id", "pair_version", name="pk_m8_spatial_pair_decisions"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "pair_id"],
            ["m8_spatial_pair_heads.user_id", "m8_spatial_pair_heads.project_name", "m8_spatial_pair_heads.pair_id"],
            name="fk_m8_spatial_pair_decisions_head",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
            ["user_id", "project_name", "master_receipt_id"],
            [
                "m8_spatial_frame_receipts.user_id",
                "m8_spatial_frame_receipts.project_name",
                "m8_spatial_frame_receipts.receipt_id",
            ],
            name="fk_m8_spatial_pair_decisions_master_receipt",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "reverse_receipt_id"],
            [
                "m8_spatial_frame_receipts.user_id",
                "m8_spatial_frame_receipts.project_name",
                "m8_spatial_frame_receipts.receipt_id",
            ],
            name="fk_m8_spatial_pair_decisions_reverse_receipt",
            ondelete="RESTRICT",
        ),
        CheckConstraint("pair_version >= 1", name="ck_m8_spatial_pair_decisions_version"),
        CheckConstraint("binding_version >= 1", name="ck_m8_spatial_pair_decisions_binding_version"),
        CheckConstraint("target_type = 'SHOT' AND scene_type = 'SCENE'", name="ck_m8_spatial_pair_decisions_types"),
        CheckConstraint("master_receipt_id <> reverse_receipt_id", name="ck_m8_spatial_pair_decisions_distinct_frames"),
        CheckConstraint("decision IN ('APPROVE','REJECT')", name="ck_m8_spatial_pair_decisions_action"),
    )

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="RESTRICT"), server_default=DEFAULT_USER_ID
    )
    project_name: Mapped[str] = mapped_column(String(255))
    pair_id: Mapped[str] = mapped_column(String(255))
    pair_version: Mapped[int] = mapped_column(Integer)
    decision_body_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    decision_digest: Mapped[str] = mapped_column(String(71))
    command_digest: Mapped[str] = mapped_column(String(71))
    authorization_digest: Mapped[str] = mapped_column(String(71))
    binding_id: Mapped[str] = mapped_column(String(255))
    binding_version: Mapped[int] = mapped_column(Integer)
    binding_envelope_digest: Mapped[str] = mapped_column(String(71))
    binding_core_digest: Mapped[str] = mapped_column(String(71))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(255))
    target_registry_version: Mapped[int] = mapped_column(Integer)
    target_version_digest: Mapped[str] = mapped_column(String(71))
    scene_type: Mapped[str] = mapped_column(String(32))
    scene_id: Mapped[str] = mapped_column(String(255))
    scene_registry_version: Mapped[int] = mapped_column(Integer)
    scene_version_digest: Mapped[str] = mapped_column(String(71))
    master_receipt_id: Mapped[str] = mapped_column(String(255))
    reverse_receipt_id: Mapped[str] = mapped_column(String(255))
    decision: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SpatialPairCommandModel(Base):
    __tablename__ = "m8_spatial_pair_commands"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "principal", "command_id", name="pk_m8_spatial_pair_commands"),
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


class SpatialPairV2CustodyModel(Base):
    __tablename__ = "m8_spatial_pair_v2_custody"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id", "project_name", "pair_id", "pair_version", name="pk_m8_spatial_pair_v2_custody"
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "pair_id", "pair_version"],
            [
                "m8_spatial_pair_decisions.user_id",
                "m8_spatial_pair_decisions.project_name",
                "m8_spatial_pair_decisions.pair_id",
                "m8_spatial_pair_decisions.pair_version",
            ],
            name="fk_m8_spatial_pair_v2_custody_decision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "review_session_id"],
            [
                "m8_spatial_review_sessions.user_id",
                "m8_spatial_review_sessions.project_name",
                "m8_spatial_review_sessions.session_id",
            ],
            name="fk_m8_spatial_pair_v2_custody_session",
            ondelete="RESTRICT",
        ),
        CheckConstraint("pair_version >= 1", name="ck_m8_spatial_pair_v2_custody_version"),
        UniqueConstraint("user_id", "project_name", "review_session_id", name="uq_m8_spatial_pair_v2_custody_session"),
    )

    user_id: Mapped[str] = mapped_column(String)
    project_name: Mapped[str] = mapped_column(String(255))
    pair_id: Mapped[str] = mapped_column(String(255))
    pair_version: Mapped[int] = mapped_column(Integer)
    review_session_id: Mapped[str] = mapped_column(String(32))
    review_evidence_digest: Mapped[str] = mapped_column(String(71))
    decision_digest: Mapped[str] = mapped_column(String(71))


__all__ = ["SpatialPairCommandModel", "SpatialPairDecisionModel", "SpatialPairHeadModel", "SpatialPairV2CustodyModel"]
