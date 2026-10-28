"""Append-only M10-B package-scoped evidence: one packaging observation per check command."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base
from lib.db.models.quality_probes import json_ceiling


class PackagingObservationModel(Base):
    __tablename__ = "m10_packaging_observations"
    __table_args__ = (
        *json_ceiling("m10_packaging_observations", "observation_json"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "observation_id", name="pk_m10_packaging_observations"),
        sa.UniqueConstraint(
            "user_id", "project_name", "actor_id", "command_id", name="uq_m10_packaging_observations_command"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "candidate_id", "candidate_revision"],
            [
                "m8_candidate_revisions.user_id",
                "m8_candidate_revisions.project_name",
                "m8_candidate_revisions.candidate_id",
                "m8_candidate_revisions.revision",
            ],
            name="fk_m10_packaging_observations_revision",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("status IN ('PASS', 'FAIL')", name="ck_m10_packaging_observations_status"),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    observation_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    command_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    request_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    candidate_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    candidate_revision: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    candidate_payload_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    quality_run_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    constraint_snapshot_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    observation_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    observation_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


_SLOT = ("source_artifact_key", "cohort_id", "product_surface")


class PackagePreviewModel(Base):
    __tablename__ = "m10_package_previews"
    __table_args__ = (
        *json_ceiling("m10_package_previews", "preview_json"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "preview_id", name="pk_m10_package_previews"),
        sa.UniqueConstraint(
            "user_id", "project_name", "actor_id", "command_id", name="uq_m10_package_previews_command"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "packaging_observation_id"],
            [
                "m10_packaging_observations.user_id",
                "m10_packaging_observations.project_name",
                "m10_packaging_observations.observation_id",
            ],
            name="fk_m10_package_previews_observation",
            ondelete="RESTRICT",
        ),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    preview_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    command_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    request_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    source_artifact_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    cohort_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    product_surface: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    packaging_observation_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    preview_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    preview_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class PackageSelectionAuthorizationModel(Base):
    __tablename__ = "m10_package_selection_authorizations"
    __table_args__ = (
        *json_ceiling("m10_package_selection_authorizations", "lease_json"),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "authorization_id", name="pk_m10_package_selection_authorizations"
        ),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    authorization_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    lease_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    grant_sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class PackageSelectionModel(Base):
    __tablename__ = "m10_package_selections"
    __table_args__ = (
        *json_ceiling("m10_package_selections", "selection_json"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "selection_id", name="pk_m10_package_selections"),
        sa.UniqueConstraint(
            "user_id", "project_name", "actor_id", "command_id", name="uq_m10_package_selections_command"
        ),
        sa.UniqueConstraint("user_id", "project_name", "authorization_id", name="uq_m10_package_selections_lease"),
        sa.UniqueConstraint("user_id", "project_name", *_SLOT, "head_version", name="uq_m10_package_selections_slot"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "preview_id"],
            ["m10_package_previews.user_id", "m10_package_previews.project_name", "m10_package_previews.preview_id"],
            name="fk_m10_package_selections_preview",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "authorization_id"],
            [
                "m10_package_selection_authorizations.user_id",
                "m10_package_selection_authorizations.project_name",
                "m10_package_selection_authorizations.authorization_id",
            ],
            name="fk_m10_package_selections_lease",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("head_version >= 1", name="ck_m10_package_selections_version"),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    selection_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    command_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    request_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    preview_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    authorization_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    source_artifact_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    cohort_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    product_surface: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    head_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    selection_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    selection_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    selected_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class PackagingHeadModel(Base):
    """The only mutable M10-B row: which selection currently fills one `PACKAGING_SLOT`."""

    __tablename__ = "m10_packaging_heads"
    __table_args__ = (
        sa.PrimaryKeyConstraint("user_id", "project_name", *_SLOT, name="pk_m10_packaging_heads"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "current_selection_id"],
            [
                "m10_package_selections.user_id",
                "m10_package_selections.project_name",
                "m10_package_selections.selection_id",
            ],
            name="fk_m10_packaging_heads_selection",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("head_version >= 1", name="ck_m10_packaging_heads_version"),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    source_artifact_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    cohort_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    product_surface: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    current_selection_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    head_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class ExportInvocationModel(Base):
    """One prepared export: the M7 execution it is bound to and the manifest it must materialize."""

    __tablename__ = "m10_export_invocations"
    __table_args__ = (
        *json_ceiling("m10_export_invocations", "manifest_json"),
        *json_ceiling("m10_export_invocations", "request_json"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "execution_id", name="pk_m10_export_invocations"),
        sa.UniqueConstraint(
            "user_id", "project_name", "actor_id", "command_id", name="uq_m10_export_invocations_command"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "selection_id"],
            [
                "m10_package_selections.user_id",
                "m10_package_selections.project_name",
                "m10_package_selections.selection_id",
            ],
            name="fk_m10_export_invocations_selection",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            ["execution_attempts.user_id", "execution_attempts.project_name", "execution_attempts.execution_id"],
            name="fk_m10_export_invocations_attempt",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    execution_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    command_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    request_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    selection_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    task_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    manifest_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    identity_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    prepared_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class ExportReceiptModel(Base):
    __tablename__ = "m10_export_receipts"
    __table_args__ = (
        *json_ceiling("m10_export_receipts", "receipt_json"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "receipt_id", name="pk_m10_export_receipts"),
        sa.UniqueConstraint("user_id", "project_name", "execution_id", name="uq_m10_export_receipts_execution"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            [
                "m10_export_invocations.user_id",
                "m10_export_invocations.project_name",
                "m10_export_invocations.execution_id",
            ],
            name="fk_m10_export_receipts_invocation",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("archive_byte_size > 0", name="ck_m10_export_receipts_size"),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    receipt_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    execution_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    archive_ref: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    archive_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    archive_byte_size: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    receipt_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    receipt_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    exported_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


__all__ = [
    "ExportInvocationModel",
    "ExportReceiptModel",
    "PackagePreviewModel",
    "PackageSelectionAuthorizationModel",
    "PackageSelectionModel",
    "PackagingHeadModel",
    "PackagingObservationModel",
]
