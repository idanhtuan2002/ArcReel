"""Integration tests for atomic C04 budget reservations."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.budget_reservation import BudgetScopeModel

NOW = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)


async def _create_scope(
    factory: async_sessionmaker[AsyncSession],
    *,
    limit: Decimal = Decimal("10"),
) -> None:
    from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository

    async with factory() as session:
        await BudgetReservationRepository(session).create_scope(
            budget_scope_ref="scope-1",
            currency="USD",
            authorized_limit=limit,
            now=NOW,
        )


async def test_reserve_holds_available_budget(session_factory: async_sessionmaker[AsyncSession]) -> None:
    from lib.budget_reservation import BudgetReservationState
    from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository

    await _create_scope(session_factory)
    async with session_factory() as session:
        result = await BudgetReservationRepository(session).reserve(
            budget_scope_ref="scope-1",
            reservation_ref="reservation-1",
            execution_decision_ref="decision-1",
            requested_amount=Decimal("4"),
            expires_at=None,
            provenance_json={"attempt_ref": "attempt-1"},
            now=NOW,
        )

    assert result.reservation.state is BudgetReservationState.ACTIVE
    assert result.reservation.reserved_amount == Decimal("4")
    assert result.scope.reserved_total == Decimal("4")
    assert result.scope.committed_total == Decimal("0")


async def test_concurrent_reserve_allows_exactly_one_writer(
    concurrent_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from lib.budget_reservation import BudgetDeniedError
    from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository

    factory = concurrent_session_factory
    await _create_scope(factory)
    start = asyncio.Event()

    async def _attempt(suffix: str) -> str:
        await start.wait()
        async with factory() as session:
            try:
                await BudgetReservationRepository(session).reserve(
                    budget_scope_ref="scope-1",
                    reservation_ref=f"reservation-{suffix}",
                    execution_decision_ref=f"decision-{suffix}",
                    requested_amount=Decimal("7"),
                    expires_at=None,
                    provenance_json={},
                    now=NOW,
                )
            except BudgetDeniedError:
                return "denied"
        return "reserved"

    first = asyncio.create_task(_attempt("a"))
    second = asyncio.create_task(_attempt("b"))
    start.set()
    assert sorted(await asyncio.gather(first, second)) == ["denied", "reserved"]

    async with factory() as session:
        scope = await BudgetReservationRepository(session).get_scope("scope-1")
    assert scope is not None
    assert scope.reserved_total == Decimal("7")


async def test_committed_spend_reduces_available_budget(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from lib.budget_reservation import BudgetDeniedError
    from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository

    await _create_scope(session_factory)
    async with session_factory() as session:
        await session.execute(
            update(BudgetScopeModel)
            .where(BudgetScopeModel.budget_scope_ref == "scope-1")
            .values(committed_total=Decimal("8"))
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(BudgetDeniedError):
            await BudgetReservationRepository(session).reserve(
                budget_scope_ref="scope-1",
                reservation_ref="reservation-1",
                execution_decision_ref="decision-1",
                requested_amount=Decimal("3"),
                expires_at=None,
                provenance_json={},
                now=NOW,
            )


async def test_duplicate_execution_decision_fails_explicitly(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from lib.budget_reservation import BudgetReservationIntegrityError
    from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository

    await _create_scope(session_factory)
    async with session_factory() as session:
        repo = BudgetReservationRepository(session)
        await repo.reserve(
            budget_scope_ref="scope-1",
            reservation_ref="reservation-1",
            execution_decision_ref="decision-1",
            requested_amount=Decimal("2"),
            expires_at=None,
            provenance_json={},
            now=NOW,
        )

    async with session_factory() as session:
        with pytest.raises(BudgetReservationIntegrityError):
            await BudgetReservationRepository(session).reserve(
                budget_scope_ref="scope-1",
                reservation_ref="reservation-2",
                execution_decision_ref="decision-1",
                requested_amount=Decimal("2"),
                expires_at=None,
                provenance_json={},
                now=NOW,
            )


async def test_repository_rejects_naive_datetimes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository

    async with session_factory() as session:
        with pytest.raises(ValueError, match="timezone-aware"):
            await BudgetReservationRepository(session).create_scope(
                budget_scope_ref="scope-1",
                currency="USD",
                authorized_limit=Decimal("10"),
                now=datetime(2026, 9, 7, 9, 0),
            )

    await _create_scope(session_factory)
    async with session_factory() as session:
        with pytest.raises(ValueError, match="timezone-aware"):
            await BudgetReservationRepository(session).reserve(
                budget_scope_ref="scope-1",
                reservation_ref="reservation-1",
                execution_decision_ref="decision-1",
                requested_amount=Decimal("1"),
                expires_at=datetime(2026, 9, 8, 9, 0),
                provenance_json={},
                now=NOW,
            )
