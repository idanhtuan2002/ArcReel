"""M8-E format projection evidence: exact profiles and overlay sets, plans, and append-only
technical and semantic reports (plan 2026-10-14 M8-E E1).

Every row is scoped by ``(user_id, project_name)`` and never updated or deleted. A plan references
the exact profile and overlay rows by ref; a report references its plan.
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
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
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
        UniqueConstraint(
            "user_id", "project_name", "plan_id", "sequence", name="uq_m8_format_technical_reports_sequence"
        ),
    )

    report_id: Mapped[str] = mapped_column(_ID)
    plan_id: Mapped[str] = mapped_column(_ID, nullable=False)
    sequence: Mapped[int] = mapped_column(nullable=False)
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
        UniqueConstraint(
            "user_id", "project_name", "plan_id", "sequence", name="uq_m8_format_semantic_reports_sequence"
        ),
    )

    report_id: Mapped[str] = mapped_column(_ID)
    plan_id: Mapped[str] = mapped_column(_ID, nullable=False)
    sequence: Mapped[int] = mapped_column(nullable=False)
    artifact_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    report_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    reviewer_count: Mapped[int] = mapped_column(nullable=False)
    deviation: Mapped[str | None] = mapped_column(_ID, nullable=True)
    passed: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FormatRenderModel(_Scoped, Base):
    """The evidence of one succeeded M7 render execution of a plan.

    The execution itself (planning, submit, failure, unknown outcomes, recovery) is an M7
    ``execution_attempts`` row; this row binds that execution to its plan, command, exact source,
    argv, FFmpeg build and content-addressed output. It is written once, when the attempt succeeds.
    """

    __tablename__ = "m8_format_renders"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "execution_id", name="pk_m8_format_renders"),
        UniqueConstraint("user_id", "project_name", "command_id", name="uq_m8_format_renders_command"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "plan_id"], _PLAN, name="fk_m8_format_renders_plan", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            ["execution_attempts.user_id", "execution_attempts.project_name", "execution_attempts.execution_id"],
            name="fk_m8_format_renders_attempt",
            ondelete="RESTRICT",
        ),
    )

    execution_id: Mapped[str] = mapped_column(_ID)
    command_id: Mapped[str] = mapped_column(_ID, nullable=False)
    plan_id: Mapped[str] = mapped_column(_ID, nullable=False)
    source_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    argv_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    ffmpeg_version: Mapped[str] = mapped_column(_ID, nullable=False)
    artifact_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    artifact_ref: Mapped[str] = mapped_column(_ID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FormatReviewPacketModel(_Scoped, Base):
    """One blind review assignment: two clips labelled A and B in a server-drawn order.

    ``projection_label`` says which label is the projection; it is never sent to the reviewer.
    A packet takes at most one review, from the reviewer it was opened for.
    """

    __tablename__ = "m8_format_review_packets"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "packet_id", name="pk_m8_format_review_packets"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "plan_id"], _PLAN, name="fk_m8_format_review_packets_plan", ondelete="RESTRICT"
        ),
        CheckConstraint("projection_label IN ('A', 'B')", name="ck_m8_format_review_packets_label"),
    )

    packet_id: Mapped[str] = mapped_column(_ID)
    plan_id: Mapped[str] = mapped_column(_ID, nullable=False)
    execution_id: Mapped[str] = mapped_column(_ID, nullable=False)
    artifact_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    artifact_ref: Mapped[str] = mapped_column(_ID, nullable=False)
    source_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    source_ref: Mapped[str] = mapped_column(_ID, nullable=False)
    projection_label: Mapped[str] = mapped_column(String(1), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(_ID, nullable=False)
    review_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "FormatPlanModel",
    "FormatProfileModel",
    "FormatRenderModel",
    "FormatReviewPacketModel",
    "FormatSemanticReportModel",
    "FormatTechnicalReportModel",
    "OverlayConstraintSetModel",
]
