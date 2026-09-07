"""Integration tests for atomic C04 budget reservations."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
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


async def _reserve(
    factory: async_sessionmaker[AsyncSession],
    *,
    suffix: str = "1",
    amount: Decimal = Decimal("4"),
    expires_at: datetime | None = None,
) -> None:
    from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository

    async with factory() as session:
        await BudgetReservationRepository(session).reserve(
            budget_scope_ref="scope-1",
            reservation_ref=f"reservation-{suffix}",
            execution_decision_ref=f"decision-{suffix}",
            requested_amount=amount,
            expires_at=expires_at,
            provenance_json={"attempt_ref": f"attempt-{suffix}"},
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


async def test_claim_keeps_the_budget_hold(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from lib.budget_reservation import BudgetReservationState
    from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository

    await _create_scope(session_factory)
    await _reserve(session_factory)
    async with session_factory() as session:
        repo = BudgetReservationRepository(session)
        claimed = await repo.claim_or_revalidate(
            reservation_ref="reservation-1",
            execution_decision_ref="decision-1",
            now=NOW + timedelta(seconds=1),
        )
        scope = await repo.get_scope("scope-1")

    assert claimed.state is BudgetReservationState.CLAIMED
    assert claimed.claimed_at == NOW + timedelta(seconds=1)
    assert scope is not None
    assert scope.reserved_total == Decimal("4")


async def test_release_returns_an_active_hold(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from lib.budget_reservation import BudgetReservationState
    from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository

    await _create_scope(session_factory)
    await _reserve(session_factory)
    async with session_factory() as session:
        repo = BudgetReservationRepository(session)
        released = await repo.release(
            reservation_ref="reservation-1",
            execution_decision_ref="decision-1",
            now=NOW + timedelta(seconds=1),
        )
        scope = await repo.get_scope("scope-1")

    assert released.state is BudgetReservationState.RELEASED
    assert scope is not None
    assert scope.reserved_total == Decimal("0")


async def test_expire_returns_only_reached_active_holds(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from lib.budget_reservation import BudgetReservationState
    from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository

    await _create_scope(session_factory)
    await _reserve(session_factory, suffix="due", expires_at=NOW + timedelta(seconds=1))
    await _reserve(session_factory, suffix="later", amount=Decimal("2"), expires_at=NOW + timedelta(hours=1))
    async with session_factory() as session:
        repo = BudgetReservationRepository(session)
        expired = await repo.expire_active(
            budget_scope_ref="scope-1",
            now=NOW + timedelta(seconds=1),
        )
        scope = await repo.get_scope("scope-1")

    assert [item.reservation_ref for item in expired] == ["reservation-due"]
    assert expired[0].state is BudgetReservationState.EXPIRED
    assert scope is not None
    assert scope.reserved_total == Decimal("2")


async def test_claim_rejects_wrong_execution_decision(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from lib.budget_reservation import BudgetReservationIntegrityError
    from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository

    await _create_scope(session_factory)
    await _reserve(session_factory)
    async with session_factory() as session:
        with pytest.raises(BudgetReservationIntegrityError, match="execution decision"):
            await BudgetReservationRepository(session).claim_or_revalidate(
                reservation_ref="reservation-1",
                execution_decision_ref="decision-other",
                now=NOW + timedelta(seconds=1),
            )


async def test_terminal_and_claimed_reservations_cannot_transition_again(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from lib.budget_reservation import InvalidBudgetTransitionError
    from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository

    await _create_scope(session_factory)
    await _reserve(session_factory, suffix="claimed")
    await _reserve(session_factory, suffix="released")
    await _reserve(
        session_factory,
        suffix="expired",
        amount=Decimal("1"),
        expires_at=NOW + timedelta(seconds=1),
    )
    async with session_factory() as session:
        repo = BudgetReservationRepository(session)
        await repo.claim_or_revalidate(
            reservation_ref="reservation-claimed",
            execution_decision_ref="decision-claimed",
            now=NOW + timedelta(seconds=1),
        )
    async with session_factory() as session:
        await BudgetReservationRepository(session).release(
            reservation_ref="reservation-released",
            execution_decision_ref="decision-released",
            now=NOW + timedelta(seconds=1),
        )
    async with session_factory() as session:
        await BudgetReservationRepository(session).expire_active(
            budget_scope_ref="scope-1",
            now=NOW + timedelta(seconds=1),
        )

    for suffix in ("claimed", "released", "expired"):
        async with session_factory() as session:
            with pytest.raises(InvalidBudgetTransitionError):
                await BudgetReservationRepository(session).claim_or_revalidate(
                    reservation_ref=f"reservation-{suffix}",
                    execution_decision_ref=f"decision-{suffix}",
                    now=NOW + timedelta(seconds=2),
                )

    async with session_factory() as session:
        with pytest.raises(InvalidBudgetTransitionError):
            await BudgetReservationRepository(session).release(
                reservation_ref="reservation-claimed",
                execution_decision_ref="decision-claimed",
                now=NOW + timedelta(seconds=2),
            )


async def test_reopen_preserves_reservation_state_and_counters(
    concurrent_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from lib.budget_reservation import BudgetReservationState
    from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository

    factory = concurrent_session_factory
    await _create_scope(factory)
    await _reserve(factory)
    async with factory() as first_session:
        claimed = await BudgetReservationRepository(first_session).claim_or_revalidate(
            reservation_ref="reservation-1",
            execution_decision_ref="decision-1",
            now=NOW + timedelta(seconds=1),
        )
        assert claimed.state is BudgetReservationState.CLAIMED

    async with factory() as reopened_session:
        repo = BudgetReservationRepository(reopened_session)
        reloaded = await repo.get_reservation("reservation-1")
        scope = await repo.get_scope("scope-1")

    assert reloaded is not None
    assert reloaded.state is BudgetReservationState.CLAIMED
    assert reloaded.claimed_at == NOW + timedelta(seconds=1)
    assert scope is not None
    assert scope.reserved_total == Decimal("4")
