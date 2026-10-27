"""Append-only scoped probe custody: invocation, staged execution result and finalized observation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base


class QualityProbeInvocationModel(Base):
    __tablename__ = "m10_quality_probe_invocations"
    __table_args__ = (
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


__all__ = ["QualityProbeInvocationModel", "QualityProbeObservationModel", "QualityProbeResultModel"]
