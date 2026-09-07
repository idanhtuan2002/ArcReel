"""Durable Host budget authorization models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base, utc_now

MONEY_PRECISION = 20
MONEY_SCALE = 6


class BudgetScopeModel(Base):
    __tablename__ = "budget_scopes"
    __table_args__ = (
        CheckConstraint("authorized_limit >= 0", name="ck_budget_scopes_authorized_limit_nonnegative"),
        CheckConstraint("reserved_total >= 0", name="ck_budget_scopes_reserved_total_nonnegative"),
        CheckConstraint("committed_total >= 0", name="ck_budget_scopes_committed_total_nonnegative"),
        CheckConstraint("version >= 0", name="ck_budget_scopes_version_nonnegative"),
    )

    budget_scope_ref: Mapped[str] = mapped_column(String(255), primary_key=True)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    authorized_limit: Mapped[Decimal] = mapped_column(Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=False)
    reserved_total: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), default=Decimal("0"), server_default="0", nullable=False
    )
    committed_total: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), default=Decimal("0"), server_default="0", nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class BudgetReservationModel(Base):
    __tablename__ = "budget_reservations"
    __table_args__ = (
        CheckConstraint("reserved_amount > 0", name="ck_budget_reservations_reserved_amount_positive"),
        CheckConstraint(
            "state IN ('ACTIVE', 'CLAIMED', 'RELEASED', 'EXPIRED')",
            name="ck_budget_reservations_state",
        ),
        CheckConstraint("version >= 0", name="ck_budget_reservations_version_nonnegative"),
        UniqueConstraint("execution_decision_ref", name="uq_budget_reservations_execution_decision_ref"),
        Index("ix_budget_reservations_budget_scope_ref", "budget_scope_ref"),
        Index("ix_budget_reservations_execution_decision_ref", "execution_decision_ref"),
        Index("ix_budget_reservations_cost_record_ref", "cost_record_ref"),
    )

    reservation_ref: Mapped[str] = mapped_column(String(255), primary_key=True)
    budget_scope_ref: Mapped[str] = mapped_column(
        String(255), ForeignKey("budget_scopes.budget_scope_ref"), nullable=False
    )
    execution_decision_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    reserved_amount: Mapped[Decimal] = mapped_column(Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cost_record_ref: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
