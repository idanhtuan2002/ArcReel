"""Scoped Governance grant heads and immutable signed-event history."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base


class ShowrunnerGrantHeadModel(Base):
    __tablename__ = "r2_showrunner_grant_heads"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "principal", name="pk_r2_showrunner_grant_heads"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "principal", "current_sequence"],
            [
                "r2_showrunner_grant_events.user_id",
                "r2_showrunner_grant_events.project_name",
                "r2_showrunner_grant_events.principal",
                "r2_showrunner_grant_events.sequence",
            ],
            name="fk_r2_showrunner_grant_heads_current",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(current_sequence IS NULL AND current_event_digest IS NULL) OR "
            "(current_sequence >= 1 AND current_event_digest IS NOT NULL)",
            name="ck_r2_showrunner_grant_heads_current_pair",
        ),
    )

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="RESTRICT"))
    project_name: Mapped[str] = mapped_column(String(255))
    principal: Mapped[str] = mapped_column(String(255))
    current_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_event_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)


class ShowrunnerGrantEventModel(Base):
    __tablename__ = "r2_showrunner_grant_events"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "principal", "sequence", name="pk_r2_showrunner_grant_events"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "principal"],
            [
                "r2_showrunner_grant_heads.user_id",
                "r2_showrunner_grant_heads.project_name",
                "r2_showrunner_grant_heads.principal",
            ],
            name="fk_r2_showrunner_grant_events_head",
            ondelete="RESTRICT",
        ),
        CheckConstraint("sequence >= 1", name="ck_r2_showrunner_grant_events_sequence"),
        CheckConstraint("event_type IN ('ISSUE','REVOKE')", name="ck_r2_showrunner_grant_events_type"),
    )

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="RESTRICT"))
    project_name: Mapped[str] = mapped_column(String(255))
    principal: Mapped[str] = mapped_column(String(255))
    sequence: Mapped[int] = mapped_column(Integer)
    raw_event: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    event_digest: Mapped[str] = mapped_column(String(71))
    event_type: Mapped[str] = mapped_column(String(16))
    issued_at: Mapped[str] = mapped_column(String(20))
    signer_key_id: Mapped[str] = mapped_column(String(255))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


__all__ = ["ShowrunnerGrantEventModel", "ShowrunnerGrantHeadModel"]
