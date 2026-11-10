"""Append-only autopilot delegation versions (ADR-0124); the highest version of a project is its current one."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base


class AutopilotDelegationModel(Base):
    __tablename__ = "auto_autopilot_delegations"
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    delegation_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    delegation_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_auto_autopilot_version"),
        CheckConstraint("state IN ('ENABLED', 'DISABLED')", name="ck_auto_autopilot_state"),
        CheckConstraint("kind IN ('story', 'film')", name="ck_auto_autopilot_kind"),
        Index("ix_auto_autopilot_state", "state", "user_id", "project_name"),
    )


__all__ = ["AutopilotDelegationModel"]
