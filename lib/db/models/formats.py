"""M8-E format projection evidence: exact profiles and overlay sets, plans, and append-only
technical and semantic reports (plan 2026-10-14 M8-E E1).

Every row is scoped by ``(user_id, project_name)`` and never updated or deleted. A plan references
the exact profile and overlay rows by ref; a report references its plan.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, ForeignKeyConstraint, PrimaryKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import DEFAULT_USER_ID, Base

_ID = String(255)
_DIGEST = String(71)


class _Scoped:
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, server_default=DEFAULT_USER_ID
    )
    project_name: Mapped[str] = mapped_column(_ID)


class FormatProfileModel(_Scoped, Base):
    __tablename__ = "m8_format_profiles"
    __table_args__ = (PrimaryKeyConstraint("user_id", "project_name", "profile_ref", name="pk_m8_format_profiles"),)

    profile_ref: Mapped[str] = mapped_column(_ID)
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    profile_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OverlayConstraintSetModel(_Scoped, Base):
    __tablename__ = "m8_overlay_constraint_sets"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "constraint_ref", name="pk_m8_overlay_constraint_sets"),
    )

    constraint_ref: Mapped[str] = mapped_column(_ID)
    overlay_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    overlay_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FormatPlanModel(_Scoped, Base):
    __tablename__ = "m8_format_plans"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "plan_id", name="pk_m8_format_plans"),
        UniqueConstraint("user_id", "project_name", "plan_digest", name="uq_m8_format_plans_digest"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "profile_ref"],
            ["m8_format_profiles.user_id", "m8_format_profiles.project_name", "m8_format_profiles.profile_ref"],
            name="fk_m8_format_plans_profile",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "constraint_ref"],
            [
                "m8_overlay_constraint_sets.user_id",
                "m8_overlay_constraint_sets.project_name",
                "m8_overlay_constraint_sets.constraint_ref",
            ],
            name="fk_m8_format_plans_overlay",
            ondelete="RESTRICT",
        ),
    )

    plan_id: Mapped[str] = mapped_column(_ID)
    plan_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    profile_ref: Mapped[str] = mapped_column(_ID, nullable=False)
    constraint_ref: Mapped[str] = mapped_column(_ID, nullable=False)
    source_master_id: Mapped[str] = mapped_column(_ID, nullable=False)
    source_master_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


_PLAN = ["m8_format_plans.user_id", "m8_format_plans.project_name", "m8_format_plans.plan_id"]


class FormatTechnicalReportModel(_Scoped, Base):
    __tablename__ = "m8_format_technical_reports"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "report_id", name="pk_m8_format_technical_reports"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "plan_id"],
            _PLAN,
            name="fk_m8_format_technical_reports_plan",
            ondelete="RESTRICT",
        ),
    )

    report_id: Mapped[str] = mapped_column(_ID)
    plan_id: Mapped[str] = mapped_column(_ID, nullable=False)
    artifact_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    report_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    passed: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FormatSemanticReportModel(_Scoped, Base):
    __tablename__ = "m8_format_semantic_reports"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "report_id", name="pk_m8_format_semantic_reports"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "plan_id"],
            _PLAN,
            name="fk_m8_format_semantic_reports_plan",
            ondelete="RESTRICT",
        ),
    )

    report_id: Mapped[str] = mapped_column(_ID)
    plan_id: Mapped[str] = mapped_column(_ID, nullable=False)
    artifact_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    report_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    reviewer_count: Mapped[int] = mapped_column(nullable=False)
    deviation: Mapped[str | None] = mapped_column(_ID, nullable=True)
    passed: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "FormatPlanModel",
    "FormatProfileModel",
    "FormatSemanticReportModel",
    "FormatTechnicalReportModel",
    "OverlayConstraintSetModel",
]
