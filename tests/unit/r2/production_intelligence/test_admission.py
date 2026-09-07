"""D08 — Gate 2 Generation Admission outcome matrix."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from lib.budget_reservation import BudgetDeniedError, BudgetReservationSnapshot, BudgetReservationState
from r2.contracts import (
    AdmissionOutcome,
    CapabilityResolution,
    MethodDecision,
    ProductionMethod,
    ProductionReadiness,
)
from r2.production_intelligence.admission import GenerationAdmissionService
from r2.production_intelligence.execution import ExecutionDecisionService, ExecutionNotAdmitted

_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


class _FakeBudgetPort:
    def __init__(self, *, deny: bool = False, state: BudgetReservationState = BudgetReservationState.ACTIVE) -> None:
        self.reserve_calls = 0
        self._deny = deny
        self._state = state

    async def reserve(
        self, *, budget_scope_ref, reservation_ref, execution_decision_ref, amount, currency, expires_at, provenance
    ):
        self.reserve_calls += 1
        if self._deny:
            raise BudgetDeniedError("over budget")
        return BudgetReservationSnapshot(
            reservation_ref=reservation_ref,
            budget_scope_ref=budget_scope_ref,
            execution_decision_ref=execution_decision_ref,
            reserved_amount=amount,
            currency=currency,
            state=self._state,
            created_at=_NOW,
            expires_at=expires_at,
            claimed_at=None,
            released_at=None,
            reconciled_at=None,
            cost_record_ref=None,
            version=1,
        )

    async def release_pre_submit(self, *, reservation_ref, execution_decision_ref):  # pragma: no cover
        raise AssertionError("admission must not release")


def _readiness(*, ready: bool = True) -> ProductionReadiness:
    payload = {"id": "READY:SH01", "target_id": "SH01", "requirements": []}
    if not ready:
        payload["blocked_reason"] = "MISSING_REQUIRED_BINDING"
    return ProductionReadiness.model_validate(payload)


def _method() -> MethodDecision:
    return MethodDecision(
        id="MD:SH01",
        target_ref="SH01",
        method=ProductionMethod.GENERATED_IMAGE,
        rationale="r",
        cost_class="MEDIUM",
        quality_tier=0,
    )


def _resolution(*, eligible=("cap:a",), unknown=()) -> CapabilityResolution:
    return CapabilityResolution(
        requirement_set_ref="req-hash",
        registry_version="reg-v1",
        observation_snapshot_ref="obs-1",
        matcher_policy_version="match-v1",
        eligible_candidates=list(eligible),
        unknown_candidates=list(unknown),
    )


def _plan_stub():
    from r2.contracts import PromptPlan

    return PromptPlan(
        id="PP:SH01",
        schema_version="1",
        version=1,
        target_ref="SH01",
        semantic_instruction="do the thing",
        compiler_version="c1",
        method_decision_ref="MD:SH01",
    )


async def _evaluate(port, **over):
    kwargs = {
        "readiness": _readiness(),
        "method_decision": _method(),
        "capability_resolution": _resolution(),
        "prompt_plan": _plan_stub(),
        "budget_scope_ref": None,
        "budget_amount": None,
        "budget_currency": None,
        "approval_ref": None,
        "now": _NOW,
    }
    kwargs.update(over)
    return await GenerationAdmissionService(budget_port=port).evaluate(**kwargs)


async def test_all_checks_pass_is_admitted() -> None:
    port = _FakeBudgetPort()
    admission = await _evaluate(port)
    assert admission.outcome is AdmissionOutcome.ADMITTED


async def test_not_ready_is_denied_not_ready_and_yields_no_execution_decision() -> None:
    port = _FakeBudgetPort()
    admission = await _evaluate(port, readiness=_readiness(ready=False))
    assert admission.outcome is AdmissionOutcome.DENIED_NOT_READY
    assert port.reserve_calls == 0
    with pytest.raises(ExecutionNotAdmitted):
        ExecutionDecisionService().create(
            admission=admission,
            capability_resolution=_resolution(),
            prompt_plan=_plan_stub(),
            selected_capability_id="cap:a",
            descriptor=None,
        )


async def test_stale_readiness_is_denied_not_ready() -> None:
    port = _FakeBudgetPort()
    admission = await _evaluate(port, readiness_is_current=False)
    assert admission.outcome is AdmissionOutcome.DENIED_NOT_READY
    assert "STALE_READINESS" in admission.reason_codes


async def test_no_eligible_and_no_unknown_is_denied_no_capability() -> None:
    port = _FakeBudgetPort()
    admission = await _evaluate(port, capability_resolution=_resolution(eligible=(), unknown=()))
    assert admission.outcome is AdmissionOutcome.DENIED_NO_CAPABILITY
    assert port.reserve_calls == 0


async def test_no_eligible_but_unknown_is_denied_unavailable() -> None:
    port = _FakeBudgetPort()
    admission = await _evaluate(port, capability_resolution=_resolution(eligible=(), unknown=("cap:x",)))
    assert admission.outcome is AdmissionOutcome.DENIED_UNAVAILABLE
    assert port.reserve_calls == 0


async def test_missing_approval_is_approval_required() -> None:
    port = _FakeBudgetPort()
    admission = await _evaluate(port, requires_approval=True, approval_ref=None)
    assert admission.outcome is AdmissionOutcome.APPROVAL_REQUIRED
    assert port.reserve_calls == 0


async def test_policy_denied_is_denied_policy() -> None:
    port = _FakeBudgetPort()
    admission = await _evaluate(port, policy_ok=False)
    assert admission.outcome is AdmissionOutcome.DENIED_POLICY
    assert port.reserve_calls == 0


async def test_host_reserve_denied_is_denied_budget() -> None:
    port = _FakeBudgetPort(deny=True)
    admission = await _evaluate(port, budget_scope_ref="scope:1", budget_amount=Decimal("2.50"), budget_currency="USD")
    assert admission.outcome is AdmissionOutcome.DENIED_BUDGET
    assert port.reserve_calls == 1
    assert admission.budget_reservation_ref is None


async def test_non_active_reservation_is_denied_budget() -> None:
    port = _FakeBudgetPort(state=BudgetReservationState.EXPIRED)
    admission = await _evaluate(port, budget_scope_ref="scope:1", budget_amount=Decimal("2.50"), budget_currency="USD")
    assert admission.outcome is AdmissionOutcome.DENIED_BUDGET


async def test_hard_budget_admitted_carries_reservation_ref() -> None:
    port = _FakeBudgetPort()
    admission = await _evaluate(port, budget_scope_ref="scope:1", budget_amount=Decimal("2.50"), budget_currency="USD")
    assert admission.outcome is AdmissionOutcome.ADMITTED
    assert admission.budget_reservation_ref is not None
    assert port.reserve_calls == 1
