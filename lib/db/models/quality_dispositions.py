"""Scoped disposition custody: append-only authorizations, dispositions, receipts and outbox, and a CAS head."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base
from lib.db.models.quality_probes import json_ceiling


class DispositionAuthorizationModel(Base):
    __tablename__ = "m10_disposition_authorizations"
    __table_args__ = (
        *json_ceiling("m10_disposition_authorizations", "lease_json"),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "authorization_id", name="pk_m10_disposition_authorizations"
        ),
        sa.CheckConstraint("grant_sequence >= 1", name="ck_m10_disposition_authorizations_grant"),
        sa.CheckConstraint("admit_not_after > issued_at", name="ck_m10_disposition_authorizations_window"),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    authorization_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    command_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    request_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    subject_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    grant_sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    admit_not_after: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    lease_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)


class QualityDispositionModel(Base):
    __tablename__ = "m10_quality_dispositions"
    __table_args__ = (
        *json_ceiling("m10_quality_dispositions", "disposition_json"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "disposition_id", name="pk_m10_quality_dispositions"),
        sa.UniqueConstraint("user_id", "project_name", "actor_id", "command_id", name="uq_m10_dispositions_command"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "authorization_id"],
            [
                "m10_disposition_authorizations.user_id",
                "m10_disposition_authorizations.project_name",
                "m10_disposition_authorizations.authorization_id",
            ],
            name="fk_m10_dispositions_authorization",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("decision IN ('PASS', 'REWORK', 'WAIVE')", name="ck_m10_dispositions_decision"),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    disposition_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    command_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    authorization_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    subject_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    profile_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    quality_run_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    decision: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    disposition_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    disposition_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class DispositionCommandModel(Base):
    __tablename__ = "m10_disposition_commands"
    __table_args__ = (
        *json_ceiling("m10_disposition_commands", "receipt_json"),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "actor_id", "command_id", name="pk_m10_disposition_commands"
        ),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    command_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    request_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    result_ref: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    result_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    receipt_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    committed_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class DispositionOutboxModel(Base):
    __tablename__ = "m10_disposition_outbox"
    __table_args__ = (
        *json_ceiling("m10_disposition_outbox", "event_json"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "disposition_id", name="pk_m10_disposition_outbox"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "disposition_id"],
            [
                "m10_quality_dispositions.user_id",
                "m10_quality_dispositions.project_name",
                "m10_quality_dispositions.disposition_id",
            ],
            name="fk_m10_disposition_outbox_disposition",
            ondelete="RESTRICT",
        ),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    disposition_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    event_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    admitted_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class DispositionHeadModel(Base):
    __tablename__ = "m10_disposition_heads"
    __table_args__ = (
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "subject_digest", "profile_id", name="pk_m10_disposition_heads"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "current_disposition_id"],
            [
                "m10_quality_dispositions.user_id",
                "m10_quality_dispositions.project_name",
                "m10_quality_dispositions.disposition_id",
            ],
            name="fk_m10_disposition_heads_current",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("version >= 1", name="ck_m10_disposition_heads_version"),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    subject_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    profile_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    current_disposition_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    current_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)


__all__ = [
    "DispositionAuthorizationModel",
    "DispositionCommandModel",
    "DispositionHeadModel",
    "DispositionOutboxModel",
    "QualityDispositionModel",
]
