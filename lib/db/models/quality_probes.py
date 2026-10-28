"""Append-only scoped probe custody: invocation, staged execution result and finalized observation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base


def json_ceiling(table: str, column: str) -> tuple[sa.CheckConstraint, sa.CheckConstraint]:
    """The migration-owned 1 MiB JSON ceiling, expressed per dialect so ORM-created schemas match."""
    name = f"ck_{table}_{column}_bytes"
    return (
        sa.CheckConstraint(f"octet_length(CAST({column} AS text)) <= 1048576", name=name).ddl_if(dialect="postgresql"),
        sa.CheckConstraint(f"length(CAST({column} AS BLOB)) <= 1048576", name=name).ddl_if(dialect="sqlite"),
    )


class QualityProbeInvocationModel(Base):
    __tablename__ = "m10_quality_probe_invocations"
    __table_args__ = (
        *json_ceiling("m10_quality_probe_invocations", "request_json"),
        *json_ceiling("m10_quality_probe_invocations", "route_json"),
        *json_ceiling("m10_quality_probe_invocations", "provider_request_json"),
        *json_ceiling("m10_quality_probe_invocations", "input_digests_json"),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "actor_id", "execution_ref", name="pk_m10_quality_probe_invocations"
        ),
        sa.UniqueConstraint("user_id", "project_name", "execution_id", name="uq_m10_probe_invocations_execution"),
        sa.UniqueConstraint("user_id", "project_name", "observation_id", name="uq_m10_probe_invocations_observation"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            ["execution_attempts.user_id", "execution_attempts.project_name", "execution_attempts.execution_id"],
            name="fk_m10_probe_invocations_attempt",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    execution_ref: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    request_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    execution_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    task_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    observation_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    route_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    provider_request_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    config_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    catalog_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    tool_identity_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    input_digests_json: Mapped[list[str]] = mapped_column(sa.JSON, nullable=False)
    prepared_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class QualityProbeResultModel(Base):
    __tablename__ = "m10_quality_probe_results"
    __table_args__ = (
        *json_ceiling("m10_quality_probe_results", "result_json"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "execution_id", name="pk_m10_quality_probe_results"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            [
                "m10_quality_probe_invocations.user_id",
                "m10_quality_probe_invocations.project_name",
                "m10_quality_probe_invocations.execution_id",
            ],
            name="fk_m10_probe_results_invocation",
            ondelete="RESTRICT",
        ),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    execution_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    result_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    measurement_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    staged_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class QualityProbeObservationModel(Base):
    __tablename__ = "m10_quality_probe_observations"
    __table_args__ = (
        *json_ceiling("m10_quality_probe_observations", "observation_json"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "observation_id", name="pk_m10_quality_probe_observations"),
        sa.UniqueConstraint(
            "user_id", "project_name", "actor_id", "execution_ref", name="uq_m10_probe_observations_invocation"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "actor_id", "execution_ref"],
            [
                "m10_quality_probe_invocations.user_id",
                "m10_quality_probe_invocations.project_name",
                "m10_quality_probe_invocations.actor_id",
                "m10_quality_probe_invocations.execution_ref",
            ],
            name="fk_m10_probe_observations_invocation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "observation_id"],
            [
                "m10_quality_probe_invocations.user_id",
                "m10_quality_probe_invocations.project_name",
                "m10_quality_probe_invocations.observation_id",
            ],
            name="fk_m10_probe_observations_reserved_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            [
                "m10_quality_probe_results.user_id",
                "m10_quality_probe_results.project_name",
                "m10_quality_probe_results.execution_id",
            ],
            name="fk_m10_probe_observations_result",
            ondelete="RESTRICT",
        ),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    observation_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    execution_ref: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    execution_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    observation_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    observation_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    finalized_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


__all__ = [
    "QualityProbeInvocationModel",
    "QualityProbeObservationModel",
    "QualityProbeResultModel",
    "json_ceiling",
]


PROBE_FAILURE_CODES = ("M10_PROBE_FAILED", "M10_REFERENCE_INVALID", "M10_OPERATIONAL_ENVELOPE_EXCEEDED")


class QualityProbeFailureModel(Base):
    """A known probe failure recorded with its M7 FAILED_BEFORE_ACCEPTANCE attempt; resources only when reported."""

    __tablename__ = "m10_quality_probe_failures"
    __table_args__ = (
        *json_ceiling("m10_quality_probe_failures", "resources_json"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "execution_id", name="pk_m10_quality_probe_failures"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "execution_id"],
            [
                "m10_quality_probe_invocations.user_id",
                "m10_quality_probe_invocations.project_name",
                "m10_quality_probe_invocations.execution_id",
            ],
            name="fk_m10_probe_failures_invocation",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "error_code IN ('M10_PROBE_FAILED', 'M10_REFERENCE_INVALID', 'M10_OPERATIONAL_ENVELOPE_EXCEEDED')",
            name="ck_m10_quality_probe_failures_code",
        ),
        sa.CheckConstraint(
            "(resources_json IS NULL) = (resources_digest IS NULL)", name="ck_m10_quality_probe_failures_resources"
        ),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    execution_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    error_code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    resources_json: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON(none_as_null=True), nullable=True)
    resources_digest: Mapped[str | None] = mapped_column(sa.String(71), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
