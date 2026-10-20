"""Scoped M9 acquisition metadata; sensitive values stay behind erasable host refs."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base


class M9ConsumedCapabilityGrantModel(Base):
    __tablename__ = "m9_consumed_capability_grants"
    __table_args__ = (
        PrimaryKeyConstraint(*["user_id", "project_name", "grant_id", "grant_version"]),
        CheckConstraint("grant_version >= 1"),
        UniqueConstraint("user_id", "project_name", "grant_digest"),
    )

    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.id", ondelete="RESTRICT"))

    project_name: Mapped[str] = mapped_column(String(255))

    grant_id: Mapped[str] = mapped_column(String(255))

    grant_version: Mapped[int] = mapped_column(Integer)

    grant_digest: Mapped[str] = mapped_column(String(71))

    body_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class M9CapabilityEvaluationModel(Base):
    __tablename__ = "m9_capability_evaluations"
    __table_args__ = (
        PrimaryKeyConstraint(*["user_id", "project_name", "evaluation_id"]),
        ForeignKeyConstraint(
            ["user_id", "project_name", "grant_id", "grant_version"],
            [
                "m9_consumed_capability_grants.user_id",
                "m9_consumed_capability_grants.project_name",
                "m9_consumed_capability_grants.grant_id",
                "m9_consumed_capability_grants.grant_version",
            ],
        ),
        UniqueConstraint("user_id", "project_name", "evaluation_id", "grant_id", "grant_version"),
    )

    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.id", ondelete="RESTRICT"))

    project_name: Mapped[str] = mapped_column(String(255))

    evaluation_id: Mapped[str] = mapped_column(String(255))

    actor_id: Mapped[str] = mapped_column(String(255))

    grant_id: Mapped[str] = mapped_column(String(255))

    grant_version: Mapped[int] = mapped_column(Integer)

    evaluation_digest: Mapped[str] = mapped_column(String(71))

    body_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class M9SourceQueryModel(Base):
    __tablename__ = "m9_source_queries"
    __table_args__ = (
        PrimaryKeyConstraint(*["user_id", "project_name", "query_id", "revision"]),
        ForeignKeyConstraint(
            ["user_id", "project_name", "query_id", "parent_revision"],
            [
                "m9_source_queries.user_id",
                "m9_source_queries.project_name",
                "m9_source_queries.query_id",
                "m9_source_queries.revision",
            ],
        ),
        CheckConstraint(
            "(revision = 1 AND parent_revision IS NULL) OR (revision > 1 AND parent_revision IS NOT NULL AND parent_revision = revision - 1)",
            name="ck_m9_source_queries_parent",
        ),
        CheckConstraint("revision >= 1"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "cohort_profile_id", "cohort_profile_revision"],
            [
                "m9_cohort_profiles.user_id",
                "m9_cohort_profiles.project_name",
                "m9_cohort_profiles.profile_id",
                "m9_cohort_profiles.revision",
            ],
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "capability_evaluation_id", "capability_grant_id", "capability_grant_version"],
            [
                "m9_capability_evaluations.user_id",
                "m9_capability_evaluations.project_name",
                "m9_capability_evaluations.evaluation_id",
                "m9_capability_evaluations.grant_id",
                "m9_capability_evaluations.grant_version",
            ],
        ),
    )

    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.id", ondelete="RESTRICT"))

    project_name: Mapped[str] = mapped_column(String(255))

    query_id: Mapped[str] = mapped_column(String(255))

    revision: Mapped[int] = mapped_column(Integer)

    parent_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)

    cohort_profile_id: Mapped[str] = mapped_column(String(255))

    cohort_profile_revision: Mapped[int] = mapped_column(Integer)

    capability_grant_id: Mapped[str] = mapped_column(String(255))

    capability_grant_version: Mapped[int] = mapped_column(Integer)

    capability_evaluation_id: Mapped[str] = mapped_column(String(255))

    query_digest: Mapped[str] = mapped_column(String(71))

    body_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class M9SourceQueryHeadModel(Base):
    __tablename__ = "m9_source_query_heads"
    __table_args__ = (
        PrimaryKeyConstraint(*["user_id", "project_name", "query_id"]),
        ForeignKeyConstraint(
            ["user_id", "project_name", "query_id", "current_revision"],
            [
                "m9_source_queries.user_id",
                "m9_source_queries.project_name",
                "m9_source_queries.query_id",
                "m9_source_queries.revision",
            ],
        ),
        CheckConstraint("current_revision >= 1 AND head_version >= 1"),
    )

    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.id", ondelete="RESTRICT"))

    project_name: Mapped[str] = mapped_column(String(255))

    query_id: Mapped[str] = mapped_column(String(255))

    current_revision: Mapped[int] = mapped_column(Integer)

    head_version: Mapped[int] = mapped_column(Integer)


class M9AcquisitionAttemptModel(Base):
    __tablename__ = "m9_acquisition_attempts"
    __table_args__ = (
        PrimaryKeyConstraint(*["user_id", "project_name", "attempt_id"]),
        ForeignKeyConstraint(
            ["user_id", "project_name", "query_id", "query_revision"],
            [
                "m9_source_queries.user_id",
                "m9_source_queries.project_name",
                "m9_source_queries.query_id",
                "m9_source_queries.revision",
            ],
        ),
        UniqueConstraint("user_id", "actor_id", "operation", "command_id"),
        UniqueConstraint("user_id", "project_name", "attempt_id", "query_id", "query_revision"),
        CheckConstraint("attempt_version >= 1"),
        CheckConstraint("operation = 'acquire'"),
        CheckConstraint("protocol_version IN ('m9.acquisition.v1','m9.acquisition.v2')", name="ck_m9_attempt_protocol"),
        CheckConstraint(
            "(protocol_version = 'm9.acquisition.v1' AND state IN ('PLANNED','RUNNING','SUCCEEDED','FAILED','OUTCOME_UNKNOWN','NEEDS_OPERATOR')) OR "
            "(protocol_version = 'm9.acquisition.v2' AND state IN ('PLANNED','RUNNING','SUCCEEDED','FAILED','OUTCOME_UNKNOWN','NEEDS_OPERATOR','EXPIRED_UNRECOVERABLE'))",
            name="ck_m9_attempt_state_protocol",
        ),
    )

    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.id", ondelete="RESTRICT"))

    project_name: Mapped[str] = mapped_column(String(255))

    attempt_id: Mapped[str] = mapped_column(String(255))

    actor_id: Mapped[str] = mapped_column(String(255))

    operation: Mapped[str] = mapped_column(String(255))

    command_id: Mapped[str] = mapped_column(String(255))

    request_digest: Mapped[str] = mapped_column(String(71))

    query_id: Mapped[str] = mapped_column(String(255))

    query_revision: Mapped[int] = mapped_column(Integer)

    attempt_version: Mapped[int] = mapped_column(Integer)

    protocol_version: Mapped[str] = mapped_column(
        String(32), default="m9.acquisition.v1", server_default="m9.acquisition.v1"
    )

    state: Mapped[str] = mapped_column(String(255))

    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    body_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class M9SnapshotPageModel(Base):
    __tablename__ = "m9_snapshot_pages"
    __table_args__ = (
        PrimaryKeyConstraint(*["user_id", "project_name", "attempt_id", "ordinal"]),
        ForeignKeyConstraint(
            ["user_id", "project_name", "attempt_id"],
            [
                "m9_acquisition_attempts.user_id",
                "m9_acquisition_attempts.project_name",
                "m9_acquisition_attempts.attempt_id",
            ],
        ),
        CheckConstraint("ordinal >= 1 AND ordinal <= 20"),
    )

    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.id", ondelete="RESTRICT"))

    project_name: Mapped[str] = mapped_column(String(255))

    attempt_id: Mapped[str] = mapped_column(String(255))

    ordinal: Mapped[int] = mapped_column(Integer)

    body_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    checkpoint_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class M9SourceSnapshotModel(Base):
    __tablename__ = "m9_source_snapshots"
    __table_args__ = (
        PrimaryKeyConstraint(*["user_id", "project_name", "snapshot_id", "revision"]),
        ForeignKeyConstraint(
            ["user_id", "project_name", "snapshot_id", "parent_revision"],
            [
                "m9_source_snapshots.user_id",
                "m9_source_snapshots.project_name",
                "m9_source_snapshots.snapshot_id",
                "m9_source_snapshots.revision",
            ],
        ),
        CheckConstraint(
            "(revision = 1 AND parent_revision IS NULL) OR (revision > 1 AND parent_revision IS NOT NULL AND parent_revision = revision - 1)",
            name="ck_m9_source_snapshots_parent",
        ),
        CheckConstraint("revision >= 1"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "attempt_id", "query_id", "query_revision"],
            [
                "m9_acquisition_attempts.user_id",
                "m9_acquisition_attempts.project_name",
                "m9_acquisition_attempts.attempt_id",
                "m9_acquisition_attempts.query_id",
                "m9_acquisition_attempts.query_revision",
            ],
        ),
        UniqueConstraint("user_id", "project_name", "attempt_id"),
        UniqueConstraint("user_id", "project_name", "snapshot_id", "snapshot_digest"),
    )

    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.id", ondelete="RESTRICT"))

    project_name: Mapped[str] = mapped_column(String(255))

    snapshot_id: Mapped[str] = mapped_column(String(255))

    revision: Mapped[int] = mapped_column(Integer)

    parent_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)

    attempt_id: Mapped[str] = mapped_column(String(255))

    query_id: Mapped[str] = mapped_column(String(255))

    query_revision: Mapped[int] = mapped_column(Integer)

    snapshot_digest: Mapped[str] = mapped_column(String(71))

    body_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class M9SourceObservationModel(Base):
    __tablename__ = "m9_source_observations"
    __table_args__ = (
        PrimaryKeyConstraint(*["user_id", "project_name", "observation_id", "revision"]),
        ForeignKeyConstraint(
            ["user_id", "project_name", "observation_id", "parent_revision"],
            [
                "m9_source_observations.user_id",
                "m9_source_observations.project_name",
                "m9_source_observations.observation_id",
                "m9_source_observations.revision",
            ],
        ),
        CheckConstraint(
            "(revision = 1 AND parent_revision IS NULL) OR (revision > 1 AND parent_revision IS NOT NULL AND parent_revision = revision - 1)",
            name="ck_m9_source_observations_parent",
        ),
        CheckConstraint("revision >= 1"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "snapshot_id", "snapshot_digest"],
            [
                "m9_source_snapshots.user_id",
                "m9_source_snapshots.project_name",
                "m9_source_snapshots.snapshot_id",
                "m9_source_snapshots.snapshot_digest",
            ],
        ),
    )

    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.id", ondelete="RESTRICT"))

    project_name: Mapped[str] = mapped_column(String(255))

    observation_id: Mapped[str] = mapped_column(String(255))

    revision: Mapped[int] = mapped_column(Integer)

    parent_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)

    snapshot_id: Mapped[str] = mapped_column(String(255))

    snapshot_digest: Mapped[str] = mapped_column(String(71))

    source_identity_ref: Mapped[str] = mapped_column(String(255))

    observation_digest: Mapped[str] = mapped_column(String(71))

    body_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class M9ObservationHeadModel(Base):
    __tablename__ = "m9_observation_heads"
    __table_args__ = (
        PrimaryKeyConstraint(*["user_id", "project_name", "observation_id"]),
        ForeignKeyConstraint(
            ["user_id", "project_name", "observation_id", "current_revision"],
            [
                "m9_source_observations.user_id",
                "m9_source_observations.project_name",
                "m9_source_observations.observation_id",
                "m9_source_observations.revision",
            ],
        ),
        CheckConstraint("current_revision >= 1 AND head_version >= 1"),
    )

    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.id", ondelete="RESTRICT"))

    project_name: Mapped[str] = mapped_column(String(255))

    observation_id: Mapped[str] = mapped_column(String(255))

    current_revision: Mapped[int] = mapped_column(Integer)

    head_version: Mapped[int] = mapped_column(Integer)
