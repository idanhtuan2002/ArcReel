"""Durable production orchestration, scoped intents and run-cap accounting."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base


def _ceiling(column: str) -> tuple[CheckConstraint, CheckConstraint]:
    return (
        CheckConstraint(f"octet_length({column}) <= 1048576", name=f"ck_auto_{column}_bytes_pg").ddl_if(
            dialect="postgresql"
        ),
        CheckConstraint(f"length(CAST({column} AS BLOB)) <= 1048576", name=f"ck_auto_{column}_bytes_sqlite").ddl_if(
            dialect="sqlite"
        ),
    )


class ProductionPolicyModel(Base):
    __tablename__ = "auto_production_policies"
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    policy_digest: Mapped[str] = mapped_column(String(71), primary_key=True)
    policy_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (*_ceiling("policy_json"),)


class ProductionRunModel(Base):
    __tablename__ = "auto_production_runs"
    run_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    input_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    start_command_id: Mapped[str] = mapped_column(String(255), nullable=False)
    start_command_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    start_command_json: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fencing_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("user_id", "project_name", "run_id", name="uq_auto_run_scope"),
        UniqueConstraint("user_id", "project_name", "start_command_id", name="uq_auto_start_command"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "run_id", "policy_digest"],
            [
                "auto_production_policies.user_id",
                "auto_production_policies.project_name",
                "auto_production_policies.run_id",
                "auto_production_policies.policy_digest",
            ],
            name="fk_auto_run_policy",
            ondelete="RESTRICT",
        ),
        CheckConstraint("version >= 1 AND generation >= 1 AND fencing_epoch >= 0", name="ck_auto_run_versions"),
        CheckConstraint("(lease_owner IS NULL) = (lease_until IS NULL)", name="ck_auto_run_lease_pair"),
        Index("idx_auto_run_due", "status", "due_at"),
        Index(
            "uq_auto_active_project",
            "user_id",
            "project_name",
            unique=True,
            postgresql_where=text("status NOT IN ('SUCCEEDED','FAILED','FAILED_QUALITY','CANCELLED')"),
            sqlite_where=text("status NOT IN ('SUCCEEDED','FAILED','FAILED_QUALITY','CANCELLED')"),
        ),
        *_ceiling("snapshot_json"),
        *_ceiling("start_command_json"),
    )


class ProductionStepModel(Base):
    __tablename__ = "auto_production_steps"
    command_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    unit_key: Mapped[str] = mapped_column(String(255), nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    repair_index: Mapped[int] = mapped_column(Integer, nullable=False)
    input_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    policy_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    intent_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    intent_json: Mapped[str] = mapped_column(Text, nullable=False)
    receipt_json: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "project_name", "run_id"],
            ["auto_production_runs.user_id", "auto_production_runs.project_name", "auto_production_runs.run_id"],
            name="fk_auto_step_run",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("user_id", "project_name", "run_id", "command_id", name="uq_auto_step_scope"),
        UniqueConstraint(
            "user_id",
            "project_name",
            "run_id",
            "stage",
            "unit_key",
            "generation",
            "repair_index",
            "input_digest",
            "policy_digest",
            name="uq_auto_step_identity",
        ),
        CheckConstraint("generation >= 1 AND repair_index >= 0", name="ck_auto_step_versions"),
        *_ceiling("intent_json"),
        *_ceiling("receipt_json"),
    )


class ProductionBudgetModel(Base):
    __tablename__ = "auto_production_allocations"
    reservation_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    command_id: Mapped[str] = mapped_column(String(255), nullable=False)
    reservation_json: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    held_cost: Mapped[int] = mapped_column(BigInteger, nullable=False)
    held_calls: Mapped[int] = mapped_column(BigInteger, nullable=False)
    held_tasks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    held_runtime: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settled_usage_digest: Mapped[str | None] = mapped_column(String(71))
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "project_name", "run_id", "command_id"],
            [
                "auto_production_steps.user_id",
                "auto_production_steps.project_name",
                "auto_production_steps.run_id",
                "auto_production_steps.command_id",
            ],
            name="fk_auto_allocation_step",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("user_id", "project_name", "run_id", "reservation_id", name="uq_auto_allocation_scope"),
        UniqueConstraint("command_id", name="uq_auto_allocation_command"),
        CheckConstraint("state IN ('RESERVED','UNKNOWN','SETTLED')", name="ck_auto_allocation_state"),
        CheckConstraint(
            "held_cost >= 0 AND held_calls >= 0 AND held_tasks >= 0 AND held_runtime >= 0",
            name="ck_auto_allocation_totals",
        ),
        *_ceiling("reservation_json"),
    )


class ProductionUsageModel(Base):
    __tablename__ = "auto_production_usage_refs"
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), primary_key=True)
    receipt_ref: Mapped[str] = mapped_column(String(255), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    reservation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    usage_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    usage_json: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "project_name", "run_id", "reservation_id"],
            [
                "auto_production_allocations.user_id",
                "auto_production_allocations.project_name",
                "auto_production_allocations.run_id",
                "auto_production_allocations.reservation_id",
            ],
            name="fk_auto_usage_allocation",
            ondelete="RESTRICT",
        ),
        *_ceiling("usage_json"),
    )


class ProductionOwnerAttemptModel(Base):
    """One write-ahead attempt of a step's owner action that has no command identity of its own."""

    __tablename__ = "auto_owner_attempts"
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    command_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    sub_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    attempt: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "project_name", "run_id"],
            ["auto_production_runs.user_id", "auto_production_runs.project_name", "auto_production_runs.run_id"],
            name="fk_auto_attempt_run",
            ondelete="RESTRICT",
        ),
        CheckConstraint("attempt >= 0", name="ck_auto_attempt_index"),
    )


class ProductionStepOutcomeModel(Base):
    """The passing outcome of one step command, with the owner evidence later stages read."""

    __tablename__ = "auto_step_outcomes"
    command_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    input_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    outcome_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    outcome_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "project_name", "run_id", "command_id"],
            [
                "auto_production_steps.user_id",
                "auto_production_steps.project_name",
                "auto_production_steps.run_id",
                "auto_production_steps.command_id",
            ],
            name="fk_auto_outcome_step",
            ondelete="RESTRICT",
        ),
        Index("ix_auto_step_outcomes_stage", "user_id", "project_name", "run_id", "stage"),
        *_ceiling("outcome_json"),
    )
