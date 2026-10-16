"""M9 profile evidence is append-only; the scoped head is its sole mutable projection."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base
from lib.db.models.host_custodian import HostCustodianLeaseModel as HostCustodianLeaseModel


class M9CohortProfileModel(Base):
    __tablename__ = "m9_cohort_profiles"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "profile_id", "revision", name="pk_m9_cohort_profiles"),
        UniqueConstraint("user_id", "project_name", "profile_digest", name="uq_m9_cohort_profiles_digest"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "profile_id", "parent_revision"],
            [
                "m9_cohort_profiles.user_id",
                "m9_cohort_profiles.project_name",
                "m9_cohort_profiles.profile_id",
                "m9_cohort_profiles.revision",
            ],
            name="fk_m9_cohort_profiles_parent",
        ),
        CheckConstraint("revision >= 1", name="ck_m9_cohort_profiles_revision"),
        CheckConstraint(
            "(revision = 1 AND parent_revision IS NULL) OR (revision > 1 AND parent_revision IS NOT NULL AND parent_revision = revision - 1)",
            name="ck_m9_cohort_profiles_parent",
        ),
        Index("ix_m9_cohort_profiles_scope", "user_id", "project_name", "profile_id"),
    )

    user_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("users.id", ondelete="RESTRICT", name="fk_m9_cohort_profiles_user")
    )
    project_name: Mapped[str] = mapped_column(String(255))
    profile_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    parent_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    profile_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    custodian_authorization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    custodian_policy_id: Mapped[str] = mapped_column(String(255), nullable=False)
    custodian_policy_version: Mapped[str] = mapped_column(String(255), nullable=False)
    custodian_evidence_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    custodian_admitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class M9ProfileHeadModel(Base):
    __tablename__ = "m9_cohort_profile_heads"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "profile_id", name="pk_m9_cohort_profile_heads"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "profile_id", "current_revision"],
            [
                "m9_cohort_profiles.user_id",
                "m9_cohort_profiles.project_name",
                "m9_cohort_profiles.profile_id",
                "m9_cohort_profiles.revision",
            ],
            name="fk_m9_cohort_profile_heads_profile",
        ),
        CheckConstraint("current_revision >= 1", name="ck_m9_cohort_profile_heads_revision"),
        CheckConstraint("head_version >= 1", name="ck_m9_cohort_profile_heads_version"),
    )

    user_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("users.id", ondelete="RESTRICT", name="fk_m9_cohort_profile_heads_user")
    )
    project_name: Mapped[str] = mapped_column(String(255))
    profile_id: Mapped[str] = mapped_column(String(36))
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    head_version: Mapped[int] = mapped_column(Integer, nullable=False)


class M9CommandReceiptModel(Base):
    __tablename__ = "m9_command_receipts"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id", "project_name", "actor_id", "operation", "command_id", name="pk_m9_command_receipts"
        ),
        UniqueConstraint("user_id", "actor_id", "operation", "command_id", name="uq_m9_command_receipts_key"),
        Index("ix_m9_command_receipts_result", "user_id", "project_name", "result_kind", "result_ref"),
    )

    user_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("users.id", ondelete="RESTRICT", name="fk_m9_command_receipts_user")
    )
    project_name: Mapped[str] = mapped_column(String(255))
    actor_id: Mapped[str] = mapped_column(String(255))
    operation: Mapped[str] = mapped_column(String(64))
    command_id: Mapped[str] = mapped_column(String(36))
    request_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    result_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    result_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    result_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class M9EventModel(Base):
    __tablename__ = "m9_events"
    __table_args__ = (
        PrimaryKeyConstraint("event_id", name="pk_m9_events"),
        CheckConstraint("aggregate_revision >= 1", name="ck_m9_events_revision"),
        Index("ix_m9_events_scope", "user_id", "project_name", "event_id"),
    )

    event_id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("users.id", ondelete="RESTRICT", name="fk_m9_events_user"), nullable=False
    )
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    event_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    aggregate_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
