"""Scoped session, delivery and acknowledgment custody for spatial frame review."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base


class SpatialReviewSessionModel(Base):
    __tablename__ = "m8_spatial_review_sessions"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "session_id", name="pk_m8_spatial_review_sessions"),
        CheckConstraint("created_at < expires_at", name="ck_m8_spatial_review_sessions_window"),
    )

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="RESTRICT"))
    project_name: Mapped[str] = mapped_column(String(255))
    session_id: Mapped[str] = mapped_column(String(32))
    principal: Mapped[str] = mapped_column(String(255))
    snapshot_body_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    snapshot_digest: Mapped[str] = mapped_column(String(71))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_command_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)


class SpatialReviewDeliveryModel(Base):
    __tablename__ = "m8_spatial_review_deliveries"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id", "project_name", "session_id", "attempt_id", name="pk_m8_spatial_review_deliveries"
        ),
        UniqueConstraint(
            "user_id",
            "project_name",
            "session_id",
            "attempt_id",
            "role",
            "png_digest",
            name="uq_m8_spatial_review_deliveries_role_digest",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "session_id"],
            [
                "m8_spatial_review_sessions.user_id",
                "m8_spatial_review_sessions.project_name",
                "m8_spatial_review_sessions.session_id",
            ],
            name="fk_m8_spatial_review_deliveries_session",
            ondelete="RESTRICT",
        ),
        CheckConstraint("role IN ('MASTER','REVERSE')", name="ck_m8_spatial_review_deliveries_role"),
    )

    user_id: Mapped[str] = mapped_column(String)
    project_name: Mapped[str] = mapped_column(String(255))
    session_id: Mapped[str] = mapped_column(String(32))
    attempt_id: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    png_digest: Mapped[str] = mapped_column(String(71))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SpatialReviewAcknowledgmentModel(Base):
    __tablename__ = "m8_spatial_review_acknowledgments"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id", "project_name", "session_id", "role", name="pk_m8_spatial_review_acknowledgments"
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "session_id", "attempt_id", "role", "png_digest"],
            [
                "m8_spatial_review_deliveries.user_id",
                "m8_spatial_review_deliveries.project_name",
                "m8_spatial_review_deliveries.session_id",
                "m8_spatial_review_deliveries.attempt_id",
                "m8_spatial_review_deliveries.role",
                "m8_spatial_review_deliveries.png_digest",
            ],
            name="fk_m8_spatial_review_acknowledgments_delivery",
            ondelete="RESTRICT",
        ),
        CheckConstraint("role IN ('MASTER','REVERSE')", name="ck_m8_spatial_review_acknowledgments_role"),
        CheckConstraint("decoded", name="ck_m8_spatial_review_acknowledgments_decoded"),
    )

    user_id: Mapped[str] = mapped_column(String)
    project_name: Mapped[str] = mapped_column(String(255))
    session_id: Mapped[str] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(16))
    attempt_id: Mapped[str] = mapped_column(String(255))
    principal: Mapped[str] = mapped_column(String(255))
    png_digest: Mapped[str] = mapped_column(String(71))
    decoded: Mapped[bool] = mapped_column(Boolean)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


__all__ = ["SpatialReviewAcknowledgmentModel", "SpatialReviewDeliveryModel", "SpatialReviewSessionModel"]
