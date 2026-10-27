"""Scoped publication evidence; only profile heads are mutable through repository CAS."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base


class QualityProfileHeadModel(Base):
    __tablename__ = "m10_quality_profile_heads"
    __table_args__ = (
        sa.PrimaryKeyConstraint("user_id", "project_name", "profile_id", name="pk_m10_quality_profile_heads"),
        sa.CheckConstraint(
            "(current_revision IS NULL AND current_digest IS NULL) OR (current_revision IS NOT NULL AND current_revision >= 1 AND current_digest IS NOT NULL)",
            name="ck_m10_profile_heads_current_pair",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "profile_id", "current_revision"],
            [
                "m10_quality_profile_revisions.user_id",
                "m10_quality_profile_revisions.project_name",
                "m10_quality_profile_revisions.profile_id",
                "m10_quality_profile_revisions.revision",
            ],
            name="fk_m10_profile_heads_current",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    profile_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    current_revision: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    current_digest: Mapped[str | None] = mapped_column(sa.String(71), nullable=True)


class ProfilePublicationAuthorizationModel(Base):
    __tablename__ = "m10_profile_publication_authorizations"
    __table_args__ = (
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "authorization_id", name="pk_m10_publication_authorizations"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "actor_id", "grant_sequence"],
            [
                "r2_showrunner_grant_events.user_id",
                "r2_showrunner_grant_events.project_name",
                "r2_showrunner_grant_events.principal",
                "r2_showrunner_grant_events.sequence",
            ],
            name="fk_m10_publication_authorizations_grant",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("action = 'PROFILE_PUBLICATION'", name="ck_m10_publication_authorizations_action"),
        sa.CheckConstraint("grant_sequence >= 1", name="ck_m10_publication_authorizations_grant_sequence"),
        sa.CheckConstraint("admit_not_after > issued_at", name="ck_m10_publication_authorizations_window"),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    authorization_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    action: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    command_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    request_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    subject_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    policy_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    policy_version: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    evidence_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    grant_sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    admit_not_after: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    lease_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)


class QualityProfileRevisionModel(Base):
    __tablename__ = "m10_quality_profile_revisions"
    __table_args__ = (
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "profile_id", "revision", name="pk_m10_quality_profile_revisions"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "profile_id"],
            [
                "m10_quality_profile_heads.user_id",
                "m10_quality_profile_heads.project_name",
                "m10_quality_profile_heads.profile_id",
            ],
            name="fk_m10_profile_revisions_head",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "profile_id", "parent_revision"],
            [
                "m10_quality_profile_revisions.user_id",
                "m10_quality_profile_revisions.project_name",
                "m10_quality_profile_revisions.profile_id",
                "m10_quality_profile_revisions.revision",
            ],
            name="fk_m10_profile_revisions_parent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "authorization_id"],
            [
                "m10_profile_publication_authorizations.user_id",
                "m10_profile_publication_authorizations.project_name",
                "m10_profile_publication_authorizations.authorization_id",
            ],
            name="fk_m10_profile_revisions_authorization",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_m10_profile_revisions_revision"),
        sa.CheckConstraint(
            "(revision = 1 AND parent_revision IS NULL) OR (revision > 1 AND parent_revision IS NOT NULL AND parent_revision = revision - 1)",
            name="ck_m10_profile_revisions_parent",
        ),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    profile_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    revision: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    parent_revision: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    authorization_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    cohort_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    product_surface: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    policy_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    profile_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    created_by: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    admitted_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    body_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)


class QualityCommandModel(Base):
    __tablename__ = "m10_quality_commands"
    __table_args__ = (
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "actor_id", "operation", "command_id", name="pk_m10_quality_commands"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "result_profile_id", "result_revision"],
            [
                "m10_quality_profile_revisions.user_id",
                "m10_quality_profile_revisions.project_name",
                "m10_quality_profile_revisions.profile_id",
                "m10_quality_profile_revisions.revision",
            ],
            name="fk_m10_quality_commands_revision",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("operation = 'PUBLISH_PROFILE'", name="ck_m10_quality_commands_operation"),
        sa.CheckConstraint("result_revision >= 1", name="ck_m10_quality_commands_revision"),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    operation: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    command_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    request_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    result_profile_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    result_revision: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    result_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    receipt_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    committed_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class QualityOutboxModel(Base):
    __tablename__ = "m10_quality_outbox"
    __table_args__ = (
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "actor_id", "operation", "command_id", name="pk_m10_quality_outbox"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "actor_id", "operation", "command_id"],
            [
                "m10_quality_commands.user_id",
                "m10_quality_commands.project_name",
                "m10_quality_commands.actor_id",
                "m10_quality_commands.operation",
                "m10_quality_commands.command_id",
            ],
            name="fk_m10_quality_outbox_command",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("operation = 'PUBLISH_PROFILE'", name="ck_m10_quality_outbox_operation"),
        sa.CheckConstraint("revision >= 1", name="ck_m10_quality_outbox_revision"),
        sa.CheckConstraint(
            "(revision = 1 AND previous_revision IS NULL) OR (revision > 1 AND previous_revision IS NOT NULL AND previous_revision = revision - 1)",
            name="ck_m10_quality_outbox_previous",
        ),
        sa.CheckConstraint(
            "supersession_effect IN ('HISTORICAL_ONLY', 'REEVALUATE_CURRENT')",
            name="ck_m10_quality_outbox_supersession",
        ),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    operation: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    command_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    profile_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    revision: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    profile_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    previous_revision: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    cohort_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    product_surface: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    supersession_effect: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    admitted_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    event_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)


__all__ = [
    "ProfilePublicationAuthorizationModel",
    "QualityCommandModel",
    "QualityOutboxModel",
    "QualityProfileHeadModel",
    "QualityProfileRevisionModel",
]
