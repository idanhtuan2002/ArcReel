"""M8-D learning observations: append-only, scoped, one original per identity and a linear
correction chain (plan 2026-10-14 D1).

A row is never updated or deleted. The identity columns copy the observation's source family and
record, metric name and definition version, and exact window. A partial unique index admits one
original per identity; a unique ``correction_of`` admits one direct correction per record, so two
racing corrections of the same tip have one winner. Every successful ingest command, including one
that replays an existing observation, reserves its scoped ``command_id`` in
``m8_learning_observation_commands``.
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
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import DEFAULT_USER_ID, Base

_ID = String(255)
_DIGEST = String(71)
_SHORT = String(64)
_ORIGINAL = text("correction_of IS NULL")


class LearningObservationModel(Base):
    __tablename__ = "m8_learning_observations"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "observation_id", name="pk_m8_learning_observations"),
        UniqueConstraint("user_id", "project_name", "correction_of", name="uq_m8_learning_observations_successor"),
        CheckConstraint("correction_of IS NULL OR correction_of <> observation_id", name="ck_m8_learning_not_self"),
        CheckConstraint("window_starts_at < window_ends_at", name="ck_m8_learning_window"),
        CheckConstraint(
            "(has_value AND missing_reason IS NULL) OR (NOT has_value AND missing_reason IN "
            "('MISSING', 'PRIVATE', 'DELETED', 'NOT_YET_AVAILABLE'))",
            name="ck_m8_learning_value_or_reason",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "correction_of"],
            [
                "m8_learning_observations.user_id",
                "m8_learning_observations.project_name",
                "m8_learning_observations.observation_id",
            ],
            name="fk_m8_learning_observations_predecessor",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_m8_learning_observations_original",
            "user_id",
            "project_name",
            "source_family",
            "source_record_id",
            "metric_name",
            "metric_definition_version",
            "window_starts_at",
            "window_ends_at",
            "window_timezone_name",
            "window_aggregation",
            unique=True,
            postgresql_where=_ORIGINAL,
            sqlite_where=_ORIGINAL,
        ),
        Index("ix_m8_learning_observations_ingested", "user_id", "project_name", "ingested_at"),
    )

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, server_default=DEFAULT_USER_ID
    )
    project_name: Mapped[str] = mapped_column(_ID)
    observation_id: Mapped[str] = mapped_column(_ID)
    source_family: Mapped[str] = mapped_column(_ID, nullable=False)
    source_record_id: Mapped[str] = mapped_column(_ID, nullable=False)
    metric_name: Mapped[str] = mapped_column(_ID, nullable=False)
    metric_definition_version: Mapped[str] = mapped_column(_ID, nullable=False)
    window_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_timezone_name: Mapped[str] = mapped_column(_SHORT, nullable=False)
    window_aggregation: Mapped[str] = mapped_column(_SHORT, nullable=False)
    has_value: Mapped[bool] = mapped_column(nullable=False)
    missing_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    correction_of: Mapped[str | None] = mapped_column(_ID, nullable=True)
    observation_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    observation_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LearningObservationCommandModel(Base):
    __tablename__ = "m8_learning_observation_commands"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "command_id", name="pk_m8_learning_observation_commands"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "observation_id"],
            [
                "m8_learning_observations.user_id",
                "m8_learning_observations.project_name",
                "m8_learning_observations.observation_id",
            ],
            name="fk_m8_learning_observation_commands_result",
            ondelete="RESTRICT",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, server_default=DEFAULT_USER_ID
    )
    project_name: Mapped[str] = mapped_column(_ID)
    command_id: Mapped[str] = mapped_column(_ID)
    command_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    observation_id: Mapped[str] = mapped_column(_ID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["LearningObservationCommandModel", "LearningObservationModel"]
