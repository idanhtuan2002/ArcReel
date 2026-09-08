"""Append-only NarrativePlan (Authorial Intent) ORM models.

``narrative_plan_versions`` rows are immutable authority; the mutable
``narrative_plans.head_version`` is a logical pointer only (no physical FK) to avoid
a create-time table cycle and preserve the SQLite migration path. Every other
plan-to-plan relationship uses ``RESTRICT`` so history can never be deleted.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base, UserOwnedMixin

_ID = String(255)
_SELECTOR = String(64)


class NarrativePlanModel(UserOwnedMixin, Base):
    __tablename__ = "narrative_plans"
    __table_args__ = (
        CheckConstraint("head_version IS NULL OR head_version >= 1", name="ck_narrative_plans_head_version_positive"),
        Index("ix_narrative_plans_project_name", "project_name"),
    )

    plan_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    head_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)


class NarrativePlanVersionModel(UserOwnedMixin, Base):
    __tablename__ = "narrative_plan_versions"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_narrative_plan_versions_version_positive"),
        UniqueConstraint("plan_id", "version", name="uq_narrative_plan_versions_plan_version"),
        UniqueConstraint("plan_revision_id", name="uq_narrative_plan_versions_plan_revision_id"),
        UniqueConstraint("approval_ref", name="uq_narrative_plan_versions_approval_ref"),
        CheckConstraint("approval_status IN ('APPROVED')", name="ck_narrative_plan_versions_approval_status"),
        ForeignKeyConstraint(
            ["plan_id", "parent_version"],
            ["narrative_plan_versions.plan_id", "narrative_plan_versions.version"],
            name="fk_narrative_plan_versions_parent",
            ondelete="RESTRICT",
        ),
        Index("ix_narrative_plan_versions_project_name", "project_name"),
        Index("ix_narrative_plan_versions_plan_id", "plan_id"),
    )

    plan_id: Mapped[str] = mapped_column(ForeignKey("narrative_plans.plan_id", ondelete="RESTRICT"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_revision_id: Mapped[str] = mapped_column(_ID, nullable=False)
    parent_version: Mapped[int | None] = mapped_column(Integer)
    canon_branch_id: Mapped[str] = mapped_column(_ID, nullable=False)
    canon_version_id: Mapped[str] = mapped_column(_ID, nullable=False)
    schema_version: Mapped[str] = mapped_column(_SELECTOR, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(_ID, nullable=False)
    content_hash_algorithm: Mapped[str] = mapped_column(_SELECTOR, nullable=False)
    content_hash_version: Mapped[str] = mapped_column(_SELECTOR, nullable=False)
    approval_ref: Mapped[str] = mapped_column(_ID, nullable=False)
    approved_by: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    committed_by: Mapped[str] = mapped_column(String(255), nullable=False)
