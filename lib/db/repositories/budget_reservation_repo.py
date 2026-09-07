"""Atomic persistence for Host budget authorization state."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from lib.budget_reservation import (
    BudgetDeniedError,
    BudgetReservationIntegrityError,
    BudgetReservationSnapshot,
    BudgetReservationState,
    BudgetScopeSnapshot,
    InvalidBudgetTransitionError,
    ReserveBudgetResult,
    require_nonnegative_money,
    require_positive_money,
)
from lib.db.models.budget_reservation import BudgetReservationModel, BudgetScopeModel
from lib.db.repositories.base import BaseRepository


def _require_aware(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _stored_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _money(value: Decimal) -> Decimal:
    return Decimal(str(value))


def _scope_snapshot(row: BudgetScopeModel) -> BudgetScopeSnapshot:
    return BudgetScopeSnapshot(
        budget_scope_ref=row.budget_scope_ref,
        currency=row.currency,
        authorized_limit=_money(row.authorized_limit),
        reserved_total=_money(row.reserved_total),
        committed_total=_money(row.committed_total),
        version=row.version,
    )


def _reservation_snapshot(row: BudgetReservationModel) -> BudgetReservationSnapshot:
    created_at = _stored_aware(row.created_at)
    assert created_at is not None
    return BudgetReservationSnapshot(
        reservation_ref=row.reservation_ref,
        budget_scope_ref=row.budget_scope_ref,
        execution_decision_ref=row.execution_decision_ref,
        reserved_amount=_money(row.reserved_amount),
        currency=row.currency,
        state=BudgetReservationState(row.state),
        created_at=created_at,
        expires_at=_stored_aware(row.expires_at),
        claimed_at=_stored_aware(row.claimed_at),
        released_at=_stored_aware(row.released_at),
        reconciled_at=_stored_aware(row.reconciled_at),
        cost_record_ref=row.cost_record_ref,
        version=row.version,
    )


class BudgetReservationRepository(BaseRepository):
    async def _begin_serialized_write(self) -> None:
        if self.session.in_transaction():
            raise BudgetReservationIntegrityError("budget write requires a fresh session transaction")
        if self.session.get_bind().dialect.name == "sqlite":
            await self.session.execute(text("BEGIN IMMEDIATE"))

    async def _locked_scope(self, budget_scope_ref: str) -> BudgetScopeModel:
        result = await self.session.execute(
            select(BudgetScopeModel).where(BudgetScopeModel.budget_scope_ref == budget_scope_ref).with_for_update()
        )
        scope = result.scalar_one_or_none()
        if scope is None:
            raise BudgetReservationIntegrityError(f"unknown budget scope: {budget_scope_ref}")
        return scope

    async def _expire_eligible_locked(
        self,
        *,
        scope: BudgetScopeModel,
        now: datetime,
    ) -> tuple[BudgetReservationModel, ...]:
        result = await self.session.execute(
            select(BudgetReservationModel)
            .where(
                BudgetReservationModel.budget_scope_ref == scope.budget_scope_ref,
                BudgetReservationModel.state == BudgetReservationState.ACTIVE.value,
                BudgetReservationModel.expires_at.is_not(None),
                BudgetReservationModel.expires_at <= now,
            )
            .with_for_update()
        )
        expired = tuple(result.scalars())
        for reservation in expired:
            reservation.state = BudgetReservationState.EXPIRED.value
            reservation.released_at = now
            reservation.version += 1
            scope.reserved_total -= reservation.reserved_amount
            scope.version += 1
            scope.updated_at = now
        return expired

    async def _reservation_scope_ref(self, reservation_ref: str) -> str:
        result = await self.session.execute(
            select(BudgetReservationModel.budget_scope_ref).where(
                BudgetReservationModel.reservation_ref == reservation_ref
            )
        )
        budget_scope_ref = result.scalar_one_or_none()
        if budget_scope_ref is None:
            raise BudgetReservationIntegrityError(f"unknown budget reservation: {reservation_ref}")
        return budget_scope_ref

    async def _locked_reservation(self, reservation_ref: str) -> BudgetReservationModel:
        result = await self.session.execute(
            select(BudgetReservationModel)
            .where(BudgetReservationModel.reservation_ref == reservation_ref)
            .with_for_update()
        )
        reservation = result.scalar_one_or_none()
        if reservation is None:
            raise BudgetReservationIntegrityError(f"unknown budget reservation: {reservation_ref}")
        return reservation

    @staticmethod
    def _require_execution_decision(
        reservation: BudgetReservationModel,
        execution_decision_ref: str,
    ) -> None:
        if reservation.execution_decision_ref != execution_decision_ref:
            raise BudgetReservationIntegrityError("reservation does not belong to this execution decision")

    async def create_scope(
        self,
        *,
        budget_scope_ref: str,
        currency: str,
        authorized_limit: Decimal,
        now: datetime,
    ) -> BudgetScopeSnapshot:
        authorized_limit = require_nonnegative_money(authorized_limit, field_name="authorized_limit")
        now = _require_aware(now, field_name="now")
        if not budget_scope_ref or not currency:
            raise BudgetReservationIntegrityError("budget scope reference and currency are required")

        row = BudgetScopeModel(
            budget_scope_ref=budget_scope_ref,
            currency=currency,
            authorized_limit=authorized_limit,
            reserved_total=Decimal("0"),
            committed_total=Decimal("0"),
            version=0,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise BudgetReservationIntegrityError(f"budget scope already exists: {budget_scope_ref}") from exc
        return _scope_snapshot(row)

    async def reserve(
        self,
        *,
        budget_scope_ref: str,
        reservation_ref: str,
        execution_decision_ref: str,
        requested_amount: Decimal,
        expires_at: datetime | None,
        provenance_json: dict[str, object],
        now: datetime,
    ) -> ReserveBudgetResult:
        requested_amount = require_positive_money(requested_amount, field_name="requested_amount")
        now = _require_aware(now, field_name="now")
        if expires_at is not None:
            expires_at = _require_aware(expires_at, field_name="expires_at")
        if not reservation_ref or not execution_decision_ref:
            raise BudgetReservationIntegrityError("reservation and execution decision references are required")

        try:
            await self._begin_serialized_write()
            scope = await self._locked_scope(budget_scope_ref)
            await self._expire_eligible_locked(scope=scope, now=now)
            available = scope.authorized_limit - scope.committed_total - scope.reserved_total
            if requested_amount > available:
                raise BudgetDeniedError(
                    f"requested {requested_amount} {scope.currency}; available {available} {scope.currency}"
                )

            reservation = BudgetReservationModel(
                reservation_ref=reservation_ref,
                budget_scope_ref=scope.budget_scope_ref,
                execution_decision_ref=execution_decision_ref,
                reserved_amount=requested_amount,
                currency=scope.currency,
                state=BudgetReservationState.ACTIVE.value,
                created_at=now,
                expires_at=expires_at,
                claimed_at=None,
                released_at=None,
                reconciled_at=None,
                cost_record_ref=None,
                version=0,
                provenance_json=dict(provenance_json),
            )
            self.session.add(reservation)
            scope.reserved_total += requested_amount
            scope.version += 1
            scope.updated_at = now
            await self.session.flush()
            result = ReserveBudgetResult(
                scope=_scope_snapshot(scope),
                reservation=_reservation_snapshot(reservation),
            )
            await self.session.commit()
            return result
        except BudgetDeniedError:
            await self.session.rollback()
            raise
        except BudgetReservationIntegrityError:
            await self.session.rollback()
            raise
        except IntegrityError as exc:
            await self.session.rollback()
            raise BudgetReservationIntegrityError("reservation identity is not unique") from exc

    async def get_scope(self, budget_scope_ref: str) -> BudgetScopeSnapshot | None:
        result = await self.session.execute(
            select(BudgetScopeModel).where(BudgetScopeModel.budget_scope_ref == budget_scope_ref)
        )
        row = result.scalar_one_or_none()
        return _scope_snapshot(row) if row is not None else None

    async def get_reservation(self, reservation_ref: str) -> BudgetReservationSnapshot | None:
        result = await self.session.execute(
            select(BudgetReservationModel).where(BudgetReservationModel.reservation_ref == reservation_ref)
        )
        row = result.scalar_one_or_none()
        return _reservation_snapshot(row) if row is not None else None

    async def claim_or_revalidate(
        self,
        *,
        reservation_ref: str,
        execution_decision_ref: str,
        now: datetime,
    ) -> BudgetReservationSnapshot:
        now = _require_aware(now, field_name="now")
        try:
            await self._begin_serialized_write()
            budget_scope_ref = await self._reservation_scope_ref(reservation_ref)
            scope = await self._locked_scope(budget_scope_ref)
            reservation = await self._locked_reservation(reservation_ref)
            self._require_execution_decision(reservation, execution_decision_ref)

            expires_at = _stored_aware(reservation.expires_at)
            if (
                reservation.state == BudgetReservationState.ACTIVE.value
                and expires_at is not None
                and expires_at <= now
            ):
                reservation.state = BudgetReservationState.EXPIRED.value
                reservation.released_at = now
                reservation.version += 1
                scope.reserved_total -= reservation.reserved_amount
                scope.version += 1
                scope.updated_at = now
                await self.session.commit()
                raise InvalidBudgetTransitionError("expired reservation cannot be claimed")

            if reservation.state != BudgetReservationState.ACTIVE.value:
                raise InvalidBudgetTransitionError(f"cannot claim reservation in state {reservation.state}")
            if reservation.currency != scope.currency:
                raise BudgetReservationIntegrityError("reservation currency does not match its budget scope")
            if scope.reserved_total < reservation.reserved_amount:
                raise BudgetReservationIntegrityError("reservation is not represented in the scope hold total")

            reservation.state = BudgetReservationState.CLAIMED.value
            reservation.claimed_at = now
            reservation.version += 1
            scope.version += 1
            scope.updated_at = now
            await self.session.flush()
            snapshot = _reservation_snapshot(reservation)
            await self.session.commit()
            return snapshot
        except InvalidBudgetTransitionError:
            if self.session.in_transaction():
                await self.session.rollback()
            raise
        except BudgetReservationIntegrityError:
            await self.session.rollback()
            raise

    async def release(
        self,
        *,
        reservation_ref: str,
        execution_decision_ref: str,
        now: datetime,
    ) -> BudgetReservationSnapshot:
        now = _require_aware(now, field_name="now")
        try:
            await self._begin_serialized_write()
            budget_scope_ref = await self._reservation_scope_ref(reservation_ref)
            scope = await self._locked_scope(budget_scope_ref)
            reservation = await self._locked_reservation(reservation_ref)
            self._require_execution_decision(reservation, execution_decision_ref)
            if reservation.state != BudgetReservationState.ACTIVE.value:
                raise InvalidBudgetTransitionError(f"cannot release reservation in state {reservation.state}")
            if reservation.currency != scope.currency:
                raise BudgetReservationIntegrityError("reservation currency does not match its budget scope")
            if scope.reserved_total < reservation.reserved_amount:
                raise BudgetReservationIntegrityError("reservation is not represented in the scope hold total")

            reservation.state = BudgetReservationState.RELEASED.value
            reservation.released_at = now
            reservation.version += 1
            scope.reserved_total -= reservation.reserved_amount
            scope.version += 1
            scope.updated_at = now
            await self.session.flush()
            snapshot = _reservation_snapshot(reservation)
            await self.session.commit()
            return snapshot
        except (BudgetReservationIntegrityError, InvalidBudgetTransitionError):
            await self.session.rollback()
            raise

    async def expire_active(
        self,
        *,
        budget_scope_ref: str,
        now: datetime,
    ) -> tuple[BudgetReservationSnapshot, ...]:
        now = _require_aware(now, field_name="now")
        try:
            await self._begin_serialized_write()
            scope = await self._locked_scope(budget_scope_ref)
            expired = await self._expire_eligible_locked(scope=scope, now=now)
            await self.session.flush()
            snapshots = tuple(_reservation_snapshot(item) for item in expired)
            await self.session.commit()
            return snapshots
        except BudgetReservationIntegrityError:
            await self.session.rollback()
            raise
