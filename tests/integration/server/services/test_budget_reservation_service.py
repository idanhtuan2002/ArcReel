"""Integration tests for the Host budget reservation service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.budget_reservation import (
    BudgetDeniedError,
    BudgetReservationIntegrityError,
    BudgetReservationState,
)
from lib.db.models.api_call import ApiCall
from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository
from server.services.budget_reservation_events import (
    BudgetEventContext,
    BudgetEventName,
    RecordingBudgetEventSink,
)
from server.services.budget_reservation_service import BudgetReservationService

NOW = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)


async def _insert_api_call(
    factory: async_sessionmaker[AsyncSession],
    *,
    cost: Decimal,
    currency: str = "USD",
    status: str = "success",
) -> str:
    async with factory() as session:
        row = ApiCall(
            project_name="proj",
            call_type="video",
            model="test-model",
            status=status,
            started_at=NOW,
            cost_amount=float(cost),
            currency=currency,
        )
        session.add(row)
        await session.commit()
        return f"api_call:{row.id}"


async def _prepare_claimed(
    factory: async_sessionmaker[AsyncSession],
    *,
    limit: Decimal,
    amount: Decimal,
) -> BudgetReservationService:
    async with factory() as session:
        await BudgetReservationRepository(session).create_scope(
            budget_scope_ref="scope-1",
            currency="USD",
            authorized_limit=limit,
            now=NOW,
        )
    service = BudgetReservationService(factory)
    await service.reserve_for_execution(
        budget_scope_ref="scope-1",
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
        amount=amount,
        expires_at=None,
        provenance={"attempt_ref": "attempt-1"},
        now=NOW,
    )
    await service.claim_for_submission(
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
        now=NOW + timedelta(seconds=1),
    )
    return service


async def test_reconcile_lower_actual_frees_hold_and_commits_actual(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await _prepare_claimed(session_factory, limit=Decimal("10"), amount=Decimal("4"))
    cost_ref = await _insert_api_call(session_factory, cost=Decimal("3"))

    reconciled = await service.reconcile(
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
        cost_record_ref=cost_ref,
        now=NOW + timedelta(seconds=2),
    )

    assert reconciled.state is BudgetReservationState.CLAIMED
    assert reconciled.reconciled_at == NOW + timedelta(seconds=2)
    assert reconciled.cost_record_ref == cost_ref

    async with session_factory() as session:
        scope = await BudgetReservationRepository(session).get_scope("scope-1")
    assert scope is not None
    assert scope.reserved_total == Decimal("0")
    assert scope.committed_total == Decimal("3")


async def test_reconcile_higher_actual_commits_actual_and_blocks_later_reserve(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await _prepare_claimed(session_factory, limit=Decimal("5"), amount=Decimal("4"))
    cost_ref = await _insert_api_call(session_factory, cost=Decimal("6"))

    await service.reconcile(
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
        cost_record_ref=cost_ref,
        now=NOW + timedelta(seconds=2),
    )

    async with session_factory() as session:
        scope = await BudgetReservationRepository(session).get_scope("scope-1")
    assert scope is not None
    assert scope.committed_total == Decimal("6")
    assert scope.reserved_total == Decimal("0")

    with pytest.raises(BudgetDeniedError):
        await service.reserve_for_execution(
            budget_scope_ref="scope-1",
            reservation_ref="reservation-2",
            execution_decision_ref="decision-2",
            amount=Decimal("1"),
            expires_at=None,
            provenance={},
            now=NOW + timedelta(seconds=3),
        )


async def test_reconcile_fails_closed_when_cost_record_missing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await _prepare_claimed(session_factory, limit=Decimal("10"), amount=Decimal("4"))

    with pytest.raises(BudgetReservationIntegrityError):
        await service.reconcile(
            reservation_ref="reservation-1",
            execution_decision_ref="decision-1",
            cost_record_ref="api_call:999999",
            now=NOW + timedelta(seconds=2),
        )

    async with session_factory() as session:
        scope = await BudgetReservationRepository(session).get_scope("scope-1")
    assert scope is not None
    assert scope.reserved_total == Decimal("4")
    assert scope.committed_total == Decimal("0")


async def test_reconcile_fails_closed_on_currency_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await _prepare_claimed(session_factory, limit=Decimal("10"), amount=Decimal("4"))
    cost_ref = await _insert_api_call(session_factory, cost=Decimal("3"), currency="EUR")

    with pytest.raises(BudgetReservationIntegrityError):
        await service.reconcile(
            reservation_ref="reservation-1",
            execution_decision_ref="decision-1",
            cost_record_ref=cost_ref,
            now=NOW + timedelta(seconds=2),
        )

    async with session_factory() as session:
        scope = await BudgetReservationRepository(session).get_scope("scope-1")
    assert scope is not None
    assert scope.reserved_total == Decimal("4")
    assert scope.committed_total == Decimal("0")


async def test_reconcile_fails_closed_on_wrong_execution_decision(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await _prepare_claimed(session_factory, limit=Decimal("10"), amount=Decimal("4"))
    cost_ref = await _insert_api_call(session_factory, cost=Decimal("3"))

    with pytest.raises(BudgetReservationIntegrityError):
        await service.reconcile(
            reservation_ref="reservation-1",
            execution_decision_ref="decision-other",
            cost_record_ref=cost_ref,
            now=NOW + timedelta(seconds=2),
        )

    async with session_factory() as session:
        scope = await BudgetReservationRepository(session).get_scope("scope-1")
    assert scope is not None
    assert scope.reserved_total == Decimal("4")
    assert scope.committed_total == Decimal("0")


async def test_reconcile_twice_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await _prepare_claimed(session_factory, limit=Decimal("10"), amount=Decimal("4"))
    cost_ref = await _insert_api_call(session_factory, cost=Decimal("3"))

    first = await service.reconcile(
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
        cost_record_ref=cost_ref,
        now=NOW + timedelta(seconds=2),
    )
    second = await service.reconcile(
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
        cost_record_ref=cost_ref,
        now=NOW + timedelta(seconds=5),
    )

    assert second == first

    async with session_factory() as session:
        scope = await BudgetReservationRepository(session).get_scope("scope-1")
    assert scope is not None
    assert scope.committed_total == Decimal("3")
    assert scope.reserved_total == Decimal("0")


async def test_reconcile_rejects_second_cost_record(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await _prepare_claimed(session_factory, limit=Decimal("10"), amount=Decimal("4"))
    first_ref = await _insert_api_call(session_factory, cost=Decimal("3"))
    other_ref = await _insert_api_call(session_factory, cost=Decimal("2"))

    await service.reconcile(
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
        cost_record_ref=first_ref,
        now=NOW + timedelta(seconds=2),
    )

    with pytest.raises(BudgetReservationIntegrityError):
        await service.reconcile(
            reservation_ref="reservation-1",
            execution_decision_ref="decision-1",
            cost_record_ref=other_ref,
            now=NOW + timedelta(seconds=3),
        )


async def test_each_operation_emits_exactly_one_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    sink = RecordingBudgetEventSink()
    service = BudgetReservationService(session_factory, event_sink=sink)

    await service.create_scope(
        budget_scope_ref="scope-1",
        currency="USD",
        authorized_limit=Decimal("10"),
        now=NOW,
    )
    await service.reserve_for_execution(
        budget_scope_ref="scope-1",
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
        amount=Decimal("4"),
        expires_at=None,
        provenance={},
        now=NOW,
    )
    await service.claim_for_submission(
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
        now=NOW + timedelta(seconds=1),
    )
    cost_ref = await _insert_api_call(session_factory, cost=Decimal("3"))
    await service.reconcile(
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
        cost_record_ref=cost_ref,
        now=NOW + timedelta(seconds=2),
    )

    assert [event.name for event in sink.events] == [
        BudgetEventName.SCOPE_CREATED,
        BudgetEventName.RESERVATION_ACTIVE,
        BudgetEventName.RESERVATION_CLAIMED,
        BudgetEventName.RESERVATION_RECONCILED,
    ]


async def test_release_and_expire_emit_their_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    sink = RecordingBudgetEventSink()
    service = BudgetReservationService(session_factory, event_sink=sink)
    await service.create_scope(
        budget_scope_ref="scope-1",
        currency="USD",
        authorized_limit=Decimal("10"),
        now=NOW,
    )
    await service.reserve_for_execution(
        budget_scope_ref="scope-1",
        reservation_ref="reservation-release",
        execution_decision_ref="decision-release",
        amount=Decimal("2"),
        expires_at=None,
        provenance={},
        now=NOW,
    )
    await service.reserve_for_execution(
        budget_scope_ref="scope-1",
        reservation_ref="reservation-expire",
        execution_decision_ref="decision-expire",
        amount=Decimal("2"),
        expires_at=NOW + timedelta(seconds=1),
        provenance={},
        now=NOW,
    )
    sink.events.clear()

    await service.release_pre_submit(
        reservation_ref="reservation-release",
        execution_decision_ref="decision-release",
        now=NOW + timedelta(seconds=1),
    )
    expired = await service.expire_due(
        budget_scope_ref="scope-1",
        now=NOW + timedelta(seconds=2),
    )

    assert [event.name for event in sink.events] == [
        BudgetEventName.RESERVATION_RELEASED,
        BudgetEventName.RESERVATION_EXPIRED,
    ]
    assert [event.reservation_ref for event in sink.events] == [
        "reservation-release",
        "reservation-expire",
    ]
    assert [snapshot.reservation_ref for snapshot in expired] == ["reservation-expire"]


async def test_denied_reserve_emits_single_denied_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    sink = RecordingBudgetEventSink()
    service = BudgetReservationService(session_factory, event_sink=sink)
    await service.create_scope(
        budget_scope_ref="scope-1",
        currency="USD",
        authorized_limit=Decimal("1"),
        now=NOW,
    )
    sink.events.clear()

    with pytest.raises(BudgetDeniedError):
        await service.reserve_for_execution(
            budget_scope_ref="scope-1",
            reservation_ref="reservation-1",
            execution_decision_ref="decision-1",
            amount=Decimal("5"),
            expires_at=None,
            provenance={},
            now=NOW,
        )

    assert len(sink.events) == 1
    denied = sink.events[0]
    assert denied.name is BudgetEventName.RESERVATION_DENIED
    assert denied.reservation_ref == "reservation-1"
    assert denied.execution_decision_ref == "decision-1"
    assert denied.reason_code is not None


async def test_event_context_propagates_correlation_ids(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    sink = RecordingBudgetEventSink()
    context = BudgetEventContext(attempt_ref="attempt-9", trace_id="trace-9", span_id="span-9")
    service = BudgetReservationService(session_factory, event_sink=sink, event_context=context)
    await service.create_scope(
        budget_scope_ref="scope-1",
        currency="USD",
        authorized_limit=Decimal("10"),
        now=NOW,
    )
    await service.reserve_for_execution(
        budget_scope_ref="scope-1",
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
        amount=Decimal("4"),
        expires_at=None,
        provenance={},
        now=NOW,
    )

    for event in sink.events:
        assert event.attempt_ref == "attempt-9"
        assert event.trace_id == "trace-9"
        assert event.span_id == "span-9"
    active = sink.events[-1]
    assert active.budget_scope_ref == "scope-1"
    assert active.reservation_ref == "reservation-1"
    assert active.execution_decision_ref == "decision-1"
