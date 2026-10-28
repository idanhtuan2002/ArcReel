"""Scoped run-closure custody: append-only Human observations, sealed runs, command receipts and a CAS run head."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base
from lib.db.models.quality_probes import json_ceiling


class QualityHumanObservationModel(Base):
    __tablename__ = "m10_quality_human_observations"
    __table_args__ = (
        *json_ceiling("m10_quality_human_observations", "observation_json"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "observation_id", name="pk_m10_quality_human_observations"),
        sa.UniqueConstraint(
            "user_id", "project_name", "actor_id", "command_id", name="uq_m10_human_observations_command"
        ),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    observation_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    command_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    request_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    grant_event_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    profile_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    profile_revision: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    profile_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    observation_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    observation_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class QualityRunModel(Base):
    __tablename__ = "m10_quality_runs"
    __table_args__ = (
        *json_ceiling("m10_quality_runs", "run_json"),
        sa.PrimaryKeyConstraint("user_id", "project_name", "run_id", name="pk_m10_quality_runs"),
        sa.UniqueConstraint("user_id", "project_name", "actor_id", "command_id", name="uq_m10_quality_runs_command"),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    command_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    request_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    subject_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    profile_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    profile_revision: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    run_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    run_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    sealed_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class QualityRunCommandModel(Base):
    __tablename__ = "m10_quality_run_commands"
    __table_args__ = (
        *json_ceiling("m10_quality_run_commands", "receipt_json"),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "actor_id", "operation", "command_id", name="pk_m10_quality_run_commands"
        ),
        sa.CheckConstraint(
            "operation IN ('RECORD_HUMAN_OBSERVATION', 'COMPLETE_RUN')", name="ck_m10_quality_run_commands_operation"
        ),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    operation: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    command_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    request_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    result_ref: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    result_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    receipt_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    committed_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class QualityRunHeadModel(Base):
    __tablename__ = "m10_quality_run_heads"
    __table_args__ = (
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "subject_digest", "profile_id", name="pk_m10_quality_run_heads"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "current_run_id"],
            ["m10_quality_runs.user_id", "m10_quality_runs.project_name", "m10_quality_runs.run_id"],
            name="fk_m10_run_heads_current",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_m10_quality_run_heads_sequence"),
    )

    user_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    subject_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    profile_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    current_run_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    current_run_digest: Mapped[str] = mapped_column(sa.String(71), nullable=False)
    sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)


__all__ = ["QualityHumanObservationModel", "QualityRunCommandModel", "QualityRunHeadModel", "QualityRunModel"]
