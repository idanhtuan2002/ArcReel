"""D08 Gate 2 — Generation Admission.

Evaluates one prospective execution attempt. Only ``ADMITTED`` may lead to an
``ExecutionDecision``. Hard-budget admission goes through the C04 Host budget
port (an atomic reserve); M4 keeps no shadow balance or second cost ledger.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
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
    synchronously, immediately before ADMITTED."""

    ok: bool
    reason_codes: tuple[str, ...] = ()


# Given the selected capability id, re-prove its hard-dynamic predicates now.
HardDynamicRevalidator = Callable[[str], Awaitable[HardDynamicRevalidation]]


@dataclass(frozen=True)
class _AdmissionInputs:
    """The provider-neutral inputs every ``GenerationAdmission`` for one attempt
    is built from; identical across the outcome branches."""

    now: datetime
    readiness: ProductionReadiness
    method_decision: MethodDecision
    capability_resolution: CapabilityResolution
    prompt_plan: PromptPlan

    @property
    def target(self) -> str:
        return self.prompt_plan.target_ref

    def outcome(
        self,
        outcome: AdmissionOutcome,
        reason_codes: Sequence[str],
        *,
        budget_reservation_ref: str | None = None,
        approval_ref: str | None = None,
    ) -> GenerationAdmission:
        return GenerationAdmission(
            id=f"GA:{self.target}:{self.now.strftime('%Y%m%dT%H%M%S%f')}",
            target_ref=self.target,
            outcome=outcome,
            method_decision_ref=self.method_decision.id,
            capability_resolution_ref=self.capability_resolution.requirement_set_ref,
            prompt_plan_ref=self.prompt_plan.id,
            readiness_ref=self.readiness.id,
            budget_reservation_ref=budget_reservation_ref,
            approval_ref=approval_ref,
            reason_codes=list(reason_codes),
            evaluated_at=self.now,
            provenance=Provenance(created_by=ProvenanceActor.SYSTEM, created_at=self.now),
        )


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
        ctx = _AdmissionInputs(
            now=now,
            readiness=readiness,
            method_decision=method_decision,
            capability_resolution=capability_resolution,
            prompt_plan=prompt_plan,
        )

        if readiness.state is not ReadinessState.READY:
            return ctx.outcome(
                AdmissionOutcome.DENIED_NOT_READY,
                ["READINESS_BLOCKED", readiness.blocked_reason or "NOT_READY"],
            )
        if not readiness_is_current:
            return ctx.outcome(AdmissionOutcome.DENIED_NOT_READY, ["STALE_READINESS"])

        if not capability_resolution.eligible_candidates:
            if capability_resolution.unknown_candidates:
                return ctx.outcome(AdmissionOutcome.DENIED_UNAVAILABLE, ["CAPABILITY_UNKNOWN"])
            return ctx.outcome(AdmissionOutcome.DENIED_NO_CAPABILITY, ["NO_HARD_CAPABILITY"])

        if requires_approval and approval_ref is None:
            return ctx.outcome(AdmissionOutcome.APPROVAL_REQUIRED, ["APPROVAL_MISSING"], approval_ref=approval_ref)

        if not policy_ok:
            return ctx.outcome(AdmissionOutcome.DENIED_POLICY, ["POLICY_DENIED"])

        # Synchronously re-prove the top-ranked eligible candidate's hard-dynamic
        # predicates before any reservation, so a stale/broken candidate cannot be
        # admitted and cannot leave a dangling reservation behind.
        selected_candidate = capability_resolution.eligible_candidates[0]
        revalidation = await revalidate(selected_candidate)
        if not revalidation.ok:
            return ctx.outcome(
                AdmissionOutcome.DENIED_UNAVAILABLE,
                ["HARD_DYNAMIC_REVALIDATION_FAILED", *revalidation.reason_codes],
                approval_ref=approval_ref,
            )

        budget_reservation_ref: str | None = None
        if budget_scope_ref is not None:
            reservation_ref = f"RSV:{ctx.target}:{now.strftime('%Y%m%dT%H%M%S%f')}"
            try:
                snapshot = await self._budget_port.reserve(
                    budget_scope_ref=budget_scope_ref,
                    reservation_ref=reservation_ref,
                    execution_decision_ref=f"ED-PENDING:{ctx.target}",
                    amount=budget_amount if budget_amount is not None else Decimal("0"),
                    currency=budget_currency or "",
                    expires_at=None,
                    provenance={"stage": "admission", "target_ref": ctx.target},
                )
            except BudgetDeniedError:
                return ctx.outcome(AdmissionOutcome.DENIED_BUDGET, ["HOST_RESERVE_DENIED"], approval_ref=approval_ref)
            if snapshot.state is not BudgetReservationState.ACTIVE:
                return ctx.outcome(
                    AdmissionOutcome.DENIED_BUDGET,
                    [f"RESERVATION_{snapshot.state.value}"],
                    approval_ref=approval_ref,
                )
            budget_reservation_ref = reservation_ref

        return ctx.outcome(
            AdmissionOutcome.ADMITTED,
            ["ALL_CHECKS_PASS"],
            budget_reservation_ref=budget_reservation_ref,
            approval_ref=approval_ref,
        )
