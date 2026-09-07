"""Typed values for Host-owned budget authorization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class BudgetReservationState(StrEnum):
    ACTIVE = "ACTIVE"
    CLAIMED = "CLAIMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class BudgetScopeSnapshot:
    budget_scope_ref: str
    currency: str
    authorized_limit: Decimal
    reserved_total: Decimal
    committed_total: Decimal
    version: int


@dataclass(frozen=True)
class BudgetReservationSnapshot:
    reservation_ref: str
    budget_scope_ref: str
    execution_decision_ref: str
    reserved_amount: Decimal
    currency: str
    state: BudgetReservationState
    created_at: datetime
    expires_at: datetime | None
    claimed_at: datetime | None
    released_at: datetime | None
    reconciled_at: datetime | None
    cost_record_ref: str | None
    version: int


@dataclass(frozen=True)
class ReserveBudgetResult:
    scope: BudgetScopeSnapshot
    reservation: BudgetReservationSnapshot


class BudgetDeniedError(RuntimeError):
    """The requested hold exceeds the scope's currently available budget."""


class BudgetReservationIntegrityError(RuntimeError):
    """Persisted budget state or a caller-supplied identity is inconsistent."""


class InvalidBudgetTransitionError(RuntimeError):
    """A reservation state transition is not allowed."""


def _require_decimal(value: object, *, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return value


def require_nonnegative_money(value: object, *, field_name: str) -> Decimal:
    value = _require_decimal(value, field_name=field_name)
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def require_positive_money(value: object, *, field_name: str) -> Decimal:
    value = _require_decimal(value, field_name=field_name)
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value
