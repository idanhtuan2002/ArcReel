"""Non-authoritative projection of C04 budget authorization transitions.

This module emits structured events after a budget transaction has already
committed. It owns no budget state, no cost ledger, no queue, and no persistence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

logger = logging.getLogger(__name__)


class BudgetEventName(StrEnum):
    SCOPE_CREATED = "budget.scope.created"
    RESERVATION_ACTIVE = "budget.reservation.active"
    RESERVATION_CLAIMED = "budget.reservation.claimed"
    RESERVATION_RELEASED = "budget.reservation.released"
    RESERVATION_EXPIRED = "budget.reservation.expired"
    RESERVATION_RECONCILED = "budget.reservation.reconciled"
    RESERVATION_DENIED = "budget.reservation.denied"


@dataclass(frozen=True)
class BudgetEventContext:
    attempt_ref: str | None = None
    trace_id: str | None = None
    span_id: str | None = None


@dataclass(frozen=True)
class BudgetAuthorizationEvent:
    name: BudgetEventName
    occurred_at: datetime
    budget_scope_ref: str
    reservation_ref: str | None
    execution_decision_ref: str | None
    attempt_ref: str | None
    cost_record_ref: str | None
    trace_id: str | None
    span_id: str | None
    reason_code: str | None = None


class BudgetEventSink(Protocol):
    def emit(self, event: BudgetAuthorizationEvent) -> None: ...


class NullBudgetEventSink:
    """Default sink: discards every event."""

    def emit(self, event: BudgetAuthorizationEvent) -> None:
        del event


class LoggingBudgetEventSink:
    """Structured-logging projection. Persists nothing authoritative."""

    def __init__(self, target: logging.Logger | None = None) -> None:
        self._logger = target or logger

    def emit(self, event: BudgetAuthorizationEvent) -> None:
        self._logger.info(
            "budget authorization event %s",
            event.name.value,
            extra={
                "budget_event_name": event.name.value,
                "budget_event_occurred_at": event.occurred_at.isoformat(),
                "budget_scope_ref": event.budget_scope_ref,
                "budget_reservation_ref": event.reservation_ref,
                "budget_execution_decision_ref": event.execution_decision_ref,
                "budget_attempt_ref": event.attempt_ref,
                "budget_cost_record_ref": event.cost_record_ref,
                "budget_trace_id": event.trace_id,
                "budget_span_id": event.span_id,
                "budget_reason_code": event.reason_code,
            },
        )


class RecordingBudgetEventSink:
    """In-memory sink for tests and local inspection."""

    def __init__(self) -> None:
        self.events: list[BudgetAuthorizationEvent] = []

    def emit(self, event: BudgetAuthorizationEvent) -> None:
        self.events.append(event)
