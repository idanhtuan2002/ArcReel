"""Host-owned, command-bound authorization leases; M9-A owns their schema lifecycle."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, PrimaryKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base


class HostCustodianLeaseModel(Base):
    __tablename__ = "host_custodian_leases"
    __table_args__ = (
        PrimaryKeyConstraint("authorization_id", name="pk_host_custodian_leases"),
        UniqueConstraint(
            "user_id", "project_name", "actor_id", "operation", "command_id", name="uq_host_custodian_leases_command"
        ),
        CheckConstraint("admit_not_after > issued_at", name="ck_host_custodian_leases_window"),
        Index("ix_host_custodian_leases_scope", "user_id", "project_name", "actor_id"),
    )

    authorization_id: Mapped[str] = mapped_column(String(36))
    user_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("users.id", ondelete="RESTRICT", name="fk_host_custodian_leases_user"), nullable=False
    )
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    command_id: Mapped[str] = mapped_column(String(36), nullable=False)
    subject_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    policy_id: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(255), nullable=False)
    grant_event_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    admit_not_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
