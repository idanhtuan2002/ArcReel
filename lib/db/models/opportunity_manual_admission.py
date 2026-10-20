"""Opaque manual custody anchors; original bytes and seals live in erasable objects."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
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

from lib.db.base import Base


class M9ManualAdmissionModel(Base):
    __tablename__ = "m9_manual_admissions"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "attempt_id"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "attempt_id"],
            [
                "m9_acquisition_attempts.user_id",
                "m9_acquisition_attempts.project_name",
                "m9_acquisition_attempts.attempt_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("version >= 1"),
        CheckConstraint("phase IN ('RESERVED','READY','CLEANUP_PENDING','ERASED')"),
        CheckConstraint("phase <> 'READY' OR admitted_at IS NOT NULL"),
        CheckConstraint(
            "(erasure_fenced_at IS NULL AND erasure_version IS NULL) OR (erasure_fenced_at IS NOT NULL AND erasure_version IS NOT NULL AND erasure_version >= 1)"
        ),
    )

    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.id", ondelete="RESTRICT"))
    project_name: Mapped[str] = mapped_column(String(255))
    attempt_id: Mapped[str] = mapped_column(String(255))
    phase: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer)
    admitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    erasure_fenced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    erasure_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    metadata_digest: Mapped[str] = mapped_column(String(71))


class M9ManualPublicationIntentModel(Base):
    __tablename__ = "m9_manual_publication_intents"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "publication_key"),
        UniqueConstraint("user_id", "project_name", "attempt_id"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "attempt_id"],
            [
                "m9_acquisition_attempts.user_id",
                "m9_acquisition_attempts.project_name",
                "m9_acquisition_attempts.attempt_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("version >= 1"),
        CheckConstraint("phase IN ('RESERVED','READY','CLEANUP_PENDING','ERASED')"),
    )

    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.id", ondelete="RESTRICT"))
    project_name: Mapped[str] = mapped_column(String(255))
    publication_key: Mapped[str] = mapped_column(String(255))
    attempt_id: Mapped[str] = mapped_column(String(255))
    phase: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer)
    body_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    metadata_digest: Mapped[str] = mapped_column(String(71))


class M9ManualUploadLeaseModel(Base):
    __tablename__ = "m9_manual_upload_leases"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "claim_ref", "upload_version", "attempt_id"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "attempt_id"],
            [
                "m9_acquisition_attempts.user_id",
                "m9_acquisition_attempts.project_name",
                "m9_acquisition_attempts.attempt_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("version >= 1 AND upload_version >= 1"),
        CheckConstraint("state IN ('ACTIVE','CLOSING','SPENT')"),
    )

    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.id", ondelete="RESTRICT"))
    project_name: Mapped[str] = mapped_column(String(255))
    claim_ref: Mapped[str] = mapped_column(String(255))
    upload_version: Mapped[int] = mapped_column(Integer)
    attempt_id: Mapped[str] = mapped_column(String(255))
    source_kind: Mapped[str] = mapped_column(String(64))
    source_contract_version: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer)
    closure_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    metadata_digest: Mapped[str] = mapped_column(String(71))


class M9ManualReadLeaseModel(Base):
    __tablename__ = "m9_manual_read_leases"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "lease_id"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "attempt_id"],
            [
                "m9_acquisition_attempts.user_id",
                "m9_acquisition_attempts.project_name",
                "m9_acquisition_attempts.attempt_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("attempt_version >= 1 AND envelope_version >= 1"),
        CheckConstraint("expires_at > issued_at"),
        CheckConstraint("released_at IS NULL OR released_at >= issued_at"),
    )

    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.id", ondelete="RESTRICT"))
    project_name: Mapped[str] = mapped_column(String(255))
    lease_id: Mapped[str] = mapped_column(String(255))
    attempt_id: Mapped[str] = mapped_column(String(255))
    attempt_version: Mapped[int] = mapped_column(Integer)
    envelope_version: Mapped[int] = mapped_column(Integer)
    operational: Mapped[bool] = mapped_column(Boolean)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    body_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    metadata_digest: Mapped[str] = mapped_column(String(71))


class M9ManualClosureIntentModel(Base):
    __tablename__ = "m9_manual_closure_intents"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "closure_id"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "attempt_id"],
            [
                "m9_acquisition_attempts.user_id",
                "m9_acquisition_attempts.project_name",
                "m9_acquisition_attempts.attempt_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("version >= 1 AND attempt_version >= 1 AND envelope_version >= 1"),
        CheckConstraint("phase IN ('CLEANUP_PENDING','ERASED')"),
    )

    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.id", ondelete="RESTRICT"))
    project_name: Mapped[str] = mapped_column(String(255))
    closure_id: Mapped[str] = mapped_column(String(255))
    attempt_id: Mapped[str] = mapped_column(String(255))
    attempt_version: Mapped[int] = mapped_column(Integer)
    envelope_version: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer)
    fenced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    body_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    metadata_digest: Mapped[str] = mapped_column(String(71))
