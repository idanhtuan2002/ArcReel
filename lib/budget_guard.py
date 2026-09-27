"""Budget before submit for paid calls in a release deployment (ADR-0091).

In ``PRODUCTION_CANDIDATE`` release mode, every paid call bracketed by the usage
ledger reserves and claims an operator-authorized budget before the provider
request, and reconciles the reservation against the call's settled cost
afterwards. ``DEV`` does nothing here.

- One budget scope per currency, named ``<prefix>:<currency>``. The prefix comes
  from ``ARCREEL_BUDGET_SCOPE`` (default ``release``). The operator creates scopes
  with ``scripts/r2/budget_scope.py``; a missing scope refuses the call.
- The reservation amount is the pre-submit estimate from the same pricing
  strategies settlement uses (``estimate_only``), floored at
  :data:`MIN_RESERVATION`. A call whose cost cannot be estimated before the
  request (token-priced text) still needs that much headroom, so an exhausted
  scope refuses it; its actual cost is committed at reconciliation.
- The reservation and execution references are ``api_call:<id>``, so a resumed
  call reconciles against the same reservation after a restart.

Reconciliation failures never fail a call whose provider cost is already spent;
they are logged and leave the reservation claimed for operator review.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from lib.budget_reservation import BudgetDeniedError, BudgetReservationState
from lib.cost_calculator import cost_calculator
from lib.db.models.api_call import ApiCall
from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository
from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from lib.pricing.strategies import PricingParams
from r2.host_hardening.paid_routes import current_release_mode
from r2.host_hardening.provider_capabilities import ReleaseMode

logger = logging.getLogger(__name__)

BUDGET_SCOPE_ENV = "ARCREEL_BUDGET_SCOPE"
DEFAULT_BUDGET_SCOPE_PREFIX = "release"
MIN_RESERVATION = Decimal("0.01")
#: An unclaimed hold (a crash or claim failure between reserve and claim) expires after this window;
#: a claimed hold never expires and is released only by reconciliation.
CLAIM_WINDOW = timedelta(minutes=10)
_MONEY_QUANTUM = Decimal("0.000001")


class BudgetScopeMissingError(RuntimeError):
    """No operator-created budget scope exists for the call's currency."""

    code = "budget_scope_missing"

    def __init__(self, scope_ref: str) -> None:
        self.params: dict[str, str] = {"scope": scope_ref}
        super().__init__(f"{self.code}: {scope_ref}")


class BudgetExceededError(RuntimeError):
    """The call's reservation does not fit in the scope's remaining authorization."""

    code = "budget_exceeded"

    def __init__(self, scope_ref: str, requested: Decimal, detail: str) -> None:
        self.params: dict[str, str] = {"scope": scope_ref, "requested": str(requested)}
        super().__init__(f"{self.code}: {scope_ref} requested={requested} ({detail})")


def budget_scope_ref(currency: str) -> str:
    prefix = (os.environ.get(BUDGET_SCOPE_ENV) or "").strip() or DEFAULT_BUDGET_SCOPE_PREFIX
    return f"{prefix}:{currency}"


def call_reference(call_id: int) -> str:
    return f"api_call:{call_id}"


async def _estimate(session, provider: str, params: PricingParams) -> tuple[Decimal, str]:
    """Pre-submit estimate through the pricing path settlement uses, custom declared prices included."""
    price = await CustomProviderRepository(session).resolve_price(provider, params.model or "")
    amount, currency = cost_calculator.calculate_cost(
        provider,
        params,
        custom_price_input=price.price_input,
        custom_price_output=price.price_output,
        custom_currency=price.currency,
        estimate_only=True,
    )
    estimate = Decimal(str(amount)).quantize(_MONEY_QUANTUM)
    return max(estimate, MIN_RESERVATION), currency


async def reserve_for_call(session_factory, *, call_id: int, provider: str, params: PricingParams) -> str | None:
    """Reserve and claim budget for ``call_id`` before its provider request; ``None`` in DEV."""
    if current_release_mode() is ReleaseMode.DEV:
        return None
    ref = call_reference(call_id)
    now = datetime.now(UTC)
    async with session_factory() as session:
        amount, currency = await _estimate(session, provider, params)
        scope_ref = budget_scope_ref(currency)
        scope_exists = await BudgetReservationRepository(session).get_scope(scope_ref) is not None
    if not scope_exists:
        raise BudgetScopeMissingError(scope_ref)
    # 预算写入要求一个没有先行读取的新事务：估价与查范围在上一个会话里完成。
    async with session_factory() as session:
        try:
            await BudgetReservationRepository(session).reserve(
                budget_scope_ref=scope_ref,
                reservation_ref=ref,
                execution_decision_ref=ref,
                requested_amount=amount,
                expires_at=now + CLAIM_WINDOW,
                provenance_json={"provider": provider, "call_type": params.call_type, "model": params.model},
                now=now,
                currency=currency,
            )
        except BudgetDeniedError as exc:
            raise BudgetExceededError(scope_ref, amount, str(exc)) from exc
    async with session_factory() as session:
        await BudgetReservationRepository(session).claim_or_revalidate(
            reservation_ref=ref, execution_decision_ref=ref, now=now
        )
    return ref


async def reconcile_call(session_factory, *, call_id: int) -> None:
    """Commit ``call_id``'s settled cost against its claimed reservation, if it has one."""
    ref = call_reference(call_id)
    try:
        async with session_factory() as session:
            repo = BudgetReservationRepository(session)
            reservation = await repo.get_reservation(ref)
            if (
                reservation is None
                or reservation.state != BudgetReservationState.CLAIMED
                or reservation.reconciled_at is not None
            ):
                return
            row = (
                await session.execute(select(ApiCall.cost_amount, ApiCall.currency).where(ApiCall.id == call_id))
            ).one_or_none()
        if row is None or row.cost_amount is None:
            return
        actual = Decimal(str(row.cost_amount))
        # 失败 / 过期行按 0 结算，币种列只是缺省值：零金额没有币种，按预留币种核销，否则每次失败都会
        # 因「币种不符」把占用永久留在范围里。非零金额币种不符是真实的数据不一致，留待人工核查。
        evidence_currency = reservation.currency if actual == 0 else (row.currency or reservation.currency)
        async with session_factory() as session:
            await BudgetReservationRepository(session).reconcile(
                reservation_ref=ref,
                execution_decision_ref=ref,
                cost_record_ref=ref,
                actual_cost=actual,
                evidence_currency=evidence_currency,
                now=datetime.now(UTC),
            )
    except Exception:
        logger.exception("budget reconciliation failed for %s; reservation left claimed for review", ref)


__all__ = [
    "BUDGET_SCOPE_ENV",
    "CLAIM_WINDOW",
    "DEFAULT_BUDGET_SCOPE_PREFIX",
    "MIN_RESERVATION",
    "BudgetExceededError",
    "BudgetScopeMissingError",
    "budget_scope_ref",
    "call_reference",
    "reconcile_call",
    "reserve_for_call",
]
