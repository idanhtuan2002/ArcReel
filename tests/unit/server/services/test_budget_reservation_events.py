"""Unit tests for the C04 budget authorization event projection."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from server.services.budget_reservation_events import (
    BudgetAuthorizationEvent,
    BudgetEventContext,
    BudgetEventName,
    LoggingBudgetEventSink,
    NullBudgetEventSink,
    RecordingBudgetEventSink,
)

NOW = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)


def _event(name: BudgetEventName) -> BudgetAuthorizationEvent:
    return BudgetAuthorizationEvent(
        name=name,
        occurred_at=NOW,
        budget_scope_ref="scope-1",
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
        attempt_ref="attempt-1",
        cost_record_ref="api_call:7",
        trace_id="trace-1",
        span_id="span-1",
        reason_code=None,
    )


def test_event_vocabulary_is_fixed() -> None:
    assert {member.value for member in BudgetEventName} == {
        "budget.scope.created",
        "budget.reservation.active",
        "budget.reservation.claimed",
        "budget.reservation.released",
        "budget.reservation.expired",
        "budget.reservation.reconciled",
        "budget.reservation.denied",
    }


def test_context_defaults_are_none() -> None:
    context = BudgetEventContext()
    assert context.attempt_ref is None
    assert context.trace_id is None
    assert context.span_id is None


def test_recording_sink_captures_events_in_order() -> None:
    sink = RecordingBudgetEventSink()
    sink.emit(_event(BudgetEventName.SCOPE_CREATED))
    sink.emit(_event(BudgetEventName.RESERVATION_ACTIVE))
    assert [event.name for event in sink.events] == [
        BudgetEventName.SCOPE_CREATED,
        BudgetEventName.RESERVATION_ACTIVE,
    ]


def test_null_sink_discards_without_error() -> None:
    result = NullBudgetEventSink().emit(_event(BudgetEventName.RESERVATION_ACTIVE))
    assert result is None


def test_logging_sink_emits_structured_record(caplog) -> None:
    sink = LoggingBudgetEventSink(logging.getLogger("test.budget.events"))
    with caplog.at_level(logging.INFO, logger="test.budget.events"):
        sink.emit(_event(BudgetEventName.RESERVATION_RECONCILED))
    record = next(r for r in caplog.records if getattr(r, "budget_event_name", None))
    assert record.budget_event_name == "budget.reservation.reconciled"
    assert record.budget_scope_ref == "scope-1"
    assert record.budget_cost_record_ref == "api_call:7"
    assert record.budget_trace_id == "trace-1"
