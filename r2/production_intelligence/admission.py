"""D08 Gate 2 — Generation Admission.

Evaluates one prospective execution attempt. Only ``ADMITTED`` may lead to an
``ExecutionDecision``. Hard-budget admission goes through the C04 Host budget
port (an atomic reserve); M4 keeps no shadow balance or second cost ledger.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from lib.budget_reservation import BudgetDeniedError, BudgetReservationState
from r2.contracts import (
    AdmissionOutcome,
    CapabilityResolution,
    GenerationAdmission,
    MethodDecision,
    ProductionReadiness,
    PromptPlan,
    Provenance,
    ProvenanceActor,
    ReadinessState,
)
from r2.production.budget_port import BudgetAuthorizationPort

ADMISSION_POLICY_VERSION = "m4-generation-admission-v1"


@dataclass(frozen=True)
class HardDynamicRevalidation:
    """The result of re-proving the selected candidate's hard-dynamic predicates
    synchronously, immediately before ADMITTED (C03 §754-779)."""

    ok: bool
    reason_codes: tuple[str, ...] = ()


# Given the selected capability id, re-prove its hard-dynamic predicates now.
HardDynamicRevalidator = Callable[[str], Awaitable[HardDynamicRevalidation]]


class GenerationAdmissionService:
    def __init__(self, *, budget_port: BudgetAuthorizationPort) -> None:
        self._budget_port = budget_port

    async def evaluate(
        self,
        *,
        readiness: ProductionReadiness,
        method_decision: MethodDecision,
        capability_resolution: CapabilityResolution,
        prompt_plan: PromptPlan,
        budget_scope_ref: str | None,
        budget_amount: Decimal | None,
        budget_currency: str | None,
        approval_ref: str | None,
        now: datetime,
        revalidate: HardDynamicRevalidator,
        readiness_is_current: bool = True,
        requires_approval: bool = False,
        policy_ok: bool = True,
    ) -> GenerationAdmission:
        target = prompt_plan.target_ref

        if readiness.state is not ReadinessState.READY:
            return self._deny(
                target,
                AdmissionOutcome.DENIED_NOT_READY,
                now,
                prompt_plan,
                method_decision,
                readiness,
                capability_resolution,
                ["READINESS_BLOCKED", readiness.blocked_reason or "NOT_READY"],
            )
        if not readiness_is_current:
            return self._deny(
                target,
                AdmissionOutcome.DENIED_NOT_READY,
                now,
                prompt_plan,
                method_decision,
                readiness,
                capability_resolution,
                ["STALE_READINESS"],
            )

        if not capability_resolution.eligible_candidates:
            outcome = (
                AdmissionOutcome.DENIED_UNAVAILABLE
                if capability_resolution.unknown_candidates
                else AdmissionOutcome.DENIED_NO_CAPABILITY
            )
            reason = "CAPABILITY_UNKNOWN" if capability_resolution.unknown_candidates else "NO_HARD_CAPABILITY"
            return self._deny(
                target, outcome, now, prompt_plan, method_decision, readiness, capability_resolution, [reason]
            )

        if requires_approval and approval_ref is None:
            return self._deny(
                target,
                AdmissionOutcome.APPROVAL_REQUIRED,
                now,
                prompt_plan,
                method_decision,
                readiness,
                capability_resolution,
                ["APPROVAL_MISSING"],
                approval_ref=approval_ref,
            )

        if not policy_ok:
            return self._deny(
                target,
                AdmissionOutcome.DENIED_POLICY,
                now,
                prompt_plan,
                method_decision,
                readiness,
                capability_resolution,
                ["POLICY_DENIED"],
            )

        # Synchronously re-prove the selected (top-ranked) candidate's hard-dynamic
        # predicates before any reservation, so a stale/broken candidate cannot be
        # admitted and cannot leave a dangling reservation behind.
        selected_candidate = capability_resolution.eligible_candidates[0]
        revalidation = await revalidate(selected_candidate)
        if not revalidation.ok:
            return self._deny(
                target,
                AdmissionOutcome.DENIED_UNAVAILABLE,
                now,
                prompt_plan,
                method_decision,
                readiness,
                capability_resolution,
                ["HARD_DYNAMIC_REVALIDATION_FAILED", *revalidation.reason_codes],
                approval_ref=approval_ref,
            )

        budget_reservation_ref: str | None = None
        if budget_scope_ref is not None:
            reservation_ref = f"RSV:{target}:{now.strftime('%Y%m%dT%H%M%S%f')}"
            try:
                snapshot = await self._budget_port.reserve(
                    budget_scope_ref=budget_scope_ref,
                    reservation_ref=reservation_ref,
                    execution_decision_ref=f"ED-PENDING:{target}",
                    amount=budget_amount if budget_amount is not None else Decimal("0"),
                    currency=budget_currency or "",
                    expires_at=None,
                    provenance={"stage": "admission", "target_ref": target},
                )
            except BudgetDeniedError:
                return self._deny(
                    target,
                    AdmissionOutcome.DENIED_BUDGET,
                    now,
                    prompt_plan,
                    method_decision,
                    readiness,
                    capability_resolution,
                    ["HOST_RESERVE_DENIED"],
                    approval_ref=approval_ref,
                )
            if snapshot.state is not BudgetReservationState.ACTIVE:
                return self._deny(
                    target,
                    AdmissionOutcome.DENIED_BUDGET,
                    now,
                    prompt_plan,
                    method_decision,
                    readiness,
                    capability_resolution,
                    [f"RESERVATION_{snapshot.state.value}"],
                    approval_ref=approval_ref,
                )
            budget_reservation_ref = reservation_ref

        return GenerationAdmission(
            id=f"GA:{target}:{now.strftime('%Y%m%dT%H%M%S%f')}",
            target_ref=target,
            outcome=AdmissionOutcome.ADMITTED,
            method_decision_ref=method_decision.id,
            capability_resolution_ref=capability_resolution.requirement_set_ref,
            prompt_plan_ref=prompt_plan.id,
            readiness_ref=readiness.id,
            budget_reservation_ref=budget_reservation_ref,
            approval_ref=approval_ref,
            reason_codes=["ALL_CHECKS_PASS"],
            evaluated_at=now,
            provenance=Provenance(created_by=ProvenanceActor.SYSTEM, created_at=now),
        )

    @staticmethod
    def _deny(
        target: str,
        outcome: AdmissionOutcome,
        now: datetime,
        prompt_plan: PromptPlan,
        method_decision: MethodDecision,
        readiness: ProductionReadiness,
        capability_resolution: CapabilityResolution,
        reason_codes: list[str],
        *,
        approval_ref: str | None = None,
    ) -> GenerationAdmission:
        return GenerationAdmission(
            id=f"GA:{target}:{now.strftime('%Y%m%dT%H%M%S%f')}",
            target_ref=target,
            outcome=outcome,
            method_decision_ref=method_decision.id,
            capability_resolution_ref=capability_resolution.requirement_set_ref,
            prompt_plan_ref=prompt_plan.id,
            readiness_ref=readiness.id,
            budget_reservation_ref=None,
            approval_ref=approval_ref,
            reason_codes=reason_codes,
            evaluated_at=now,
            provenance=Provenance(created_by=ProvenanceActor.SYSTEM, created_at=now),
        )
