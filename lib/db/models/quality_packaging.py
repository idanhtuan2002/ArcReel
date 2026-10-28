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


__all__ = ["PackagingObservationModel"]
