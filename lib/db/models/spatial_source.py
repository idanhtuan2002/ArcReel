"""Immutable, scoped custody receipt for a frame derived from a promoted video master."""

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


class SpatialFrameReceiptModel(Base):
    __tablename__ = "m8_spatial_frame_receipts"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "receipt_id", name="pk_m8_spatial_frame_receipts"),
        UniqueConstraint("user_id", "project_name", "command_id", name="uq_m8_spatial_frame_receipts_command"),
        CheckConstraint("receipt_id = frame_candidate_id", name="ck_m8_spatial_frame_receipts_id_match"),
        CheckConstraint("parent_master_version >= 1", name="ck_m8_spatial_frame_receipts_parent_version"),
        CheckConstraint("frame_byte_size > 0", name="ck_m8_spatial_frame_receipts_byte_size"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "frame_candidate_id"],
            ["candidate_objects.user_id", "candidate_objects.project_name", "candidate_objects.candidate_id"],
            name="fk_m8_spatial_frame_receipts_candidate",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "parent_artifact_key", "parent_master_version"],
            [
                "master_head_versions.user_id",
                "master_head_versions.project_name",
                "master_head_versions.artifact_key",
                "master_head_versions.master_version",
            ],
            name="fk_m8_spatial_frame_receipts_parent",
            ondelete="RESTRICT",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="RESTRICT"), server_default=DEFAULT_USER_ID
    )
    project_name: Mapped[str] = mapped_column(String(255))
    receipt_id: Mapped[str] = mapped_column(String(255))
    frame_candidate_id: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_artifact_key: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_master_version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_candidate_id: Mapped[str] = mapped_column(String(255), nullable=False)
    command_id: Mapped[str] = mapped_column(String(255), nullable=False)
    command_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    frame_byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_probe_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    receipt_body_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    receipt_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
