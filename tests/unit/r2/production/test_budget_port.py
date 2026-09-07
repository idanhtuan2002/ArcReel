"""Unit tests for the R2 budget authorization adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from lib.budget_reservation import BudgetReservationSnapshot, BudgetReservationState
from r2.production.budget_port import ArcReelBudgetAuthorizationAdapter

FIXED_NOW = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)

_SNAPSHOT = BudgetReservationSnapshot(
    reservation_ref="reservation-1",
    budget_scope_ref="scope-1",
    execution_decision_ref="decision-1",
    reserved_amount=Decimal("4"),
    currency="USD",
    state=BudgetReservationState.ACTIVE,
    created_at=FIXED_NOW,
    expires_at=None,
    claimed_at=None,
    released_at=None,
    reconciled_at=None,
    cost_record_ref=None,
    version=0,
)


class _FakeHostBudgetService:
    def __init__(self) -> None:
        self.reserve_calls: list[dict[str, Any]] = []
        self.release_calls: list[dict[str, Any]] = []

    async def reserve_for_execution(self, **kwargs: Any) -> BudgetReservationSnapshot:
        self.reserve_calls.append(kwargs)
        return _SNAPSHOT

    async def release_pre_submit(self, **kwargs: Any) -> BudgetReservationSnapshot:
        self.release_calls.append(kwargs)
        return _SNAPSHOT


async def test_reserve_delegates_once_with_exact_values() -> None:
    service = _FakeHostBudgetService()
    adapter = ArcReelBudgetAuthorizationAdapter(service, clock=lambda: FIXED_NOW)
    provenance = {"attempt_ref": "attempt-1"}

    result = await adapter.reserve(
        budget_scope_ref="scope-1",
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
        amount=Decimal("4.50"),
        currency="USD",
        expires_at=None,
        provenance=provenance,
    )

    assert result is _SNAPSHOT
    assert service.release_calls == []
    assert service.reserve_calls == [
        {
            "budget_scope_ref": "scope-1",
            "reservation_ref": "reservation-1",
            "execution_decision_ref": "decision-1",
            "amount": Decimal("4.50"),
            "currency": "USD",
            "expires_at": None,
            "provenance": provenance,
            "now": FIXED_NOW,
        }
    ]
    assert isinstance(service.reserve_calls[0]["amount"], Decimal)


async def test_release_pre_submit_delegates_once() -> None:
    service = _FakeHostBudgetService()
    adapter = ArcReelBudgetAuthorizationAdapter(service, clock=lambda: FIXED_NOW)

    result = await adapter.release_pre_submit(
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
    )

    assert result is _SNAPSHOT
    assert service.reserve_calls == []
    assert service.release_calls == [
        {
            "reservation_ref": "reservation-1",
            "execution_decision_ref": "decision-1",
            "now": FIXED_NOW,
        }
    ]


async def test_adapter_uses_injected_clock_per_call() -> None:
    stamps = [
        datetime(2026, 9, 7, 9, 0, tzinfo=UTC),
        datetime(2026, 9, 7, 9, 5, tzinfo=UTC),
    ]
    service = _FakeHostBudgetService()
    adapter = ArcReelBudgetAuthorizationAdapter(service, clock=lambda: stamps.pop(0))

    await adapter.reserve(
        budget_scope_ref="scope-1",
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
        amount=Decimal("1"),
        currency="USD",
        expires_at=None,
        provenance={},
    )
    await adapter.release_pre_submit(
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
    )

    assert service.reserve_calls[0]["now"] == datetime(2026, 9, 7, 9, 0, tzinfo=UTC)
    assert service.release_calls[0]["now"] == datetime(2026, 9, 7, 9, 5, tzinfo=UTC)


async def test_adapter_forwards_no_routing_parameters() -> None:
    service = _FakeHostBudgetService()
    adapter = ArcReelBudgetAuthorizationAdapter(service, clock=lambda: FIXED_NOW)

    await adapter.reserve(
        budget_scope_ref="scope-1",
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
        amount=Decimal("1"),
        currency="USD",
        expires_at=None,
        provenance={},
    )

    forwarded = set(service.reserve_calls[0])
    assert forwarded == {
        "budget_scope_ref",
        "reservation_ref",
        "execution_decision_ref",
        "amount",
        "currency",
        "expires_at",
        "provenance",
        "now",
    }
