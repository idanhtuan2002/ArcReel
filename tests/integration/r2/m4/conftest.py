"""D09 pipeline harness — wires the real M4 services around fixture inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from lib.budget_reservation import BudgetDeniedError, BudgetReservationSnapshot, BudgetReservationState
from r2.contracts import (
    AdmissionOutcome,
    CapabilityResolution,
    DirectorKind,
    DirectorResult,
    DirectorSuccess,
    ExecutionDecision,
    GenerationAdmission,
    MethodDecision,
    ProductionReadiness,
    PromptPlan,
    Provenance,
    ProvenanceActor,
    ProviderRequest,
    ReadinessState,
    RoutingDecision,
)
from r2.production_intelligence.admission import GenerationAdmissionService
from r2.production_intelligence.capability_registry import (
    CapabilityMatcher,
    CapabilityRegistry,
    CapabilityRequirementBuilder,
    default_freshness_policy,
)
from r2.production_intelligence.director import (
    DirectorExecutionService,
    DirectorRoutingPolicy,
)
from r2.production_intelligence.execution import ExecutionDecisionService
from r2.production_intelligence.fixture_loader import M4ShotCase, load_m4_golden_12
from r2.production_intelligence.identity import VisualIdentityResolver
from r2.production_intelligence.method_router import MethodRouter, MethodRoutingContext
from r2.production_intelligence.prompting import DefaultPromptCompiler, PromptPlanner
from r2.production_intelligence.readiness import ProductionReadinessEvaluator
from scripts.r2.m4_test_doubles import DirectorDoubleMode, FixtureDirectorAdapter

_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
_SNAPSHOT = "golden-12-binding-snapshot@1"


class _FakeBudgetPort:
    def __init__(self, *, deny: bool = False) -> None:
        self.reserve_calls = 0
        self._deny = deny

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
            state=BudgetReservationState.ACTIVE,
            created_at=_NOW,
            expires_at=expires_at,
            claimed_at=None,
            released_at=None,
            reconciled_at=None,
            cost_record_ref=None,
            version=1,
        )

    async def release_pre_submit(self, *, reservation_ref, execution_decision_ref):  # pragma: no cover
        raise AssertionError("pipeline must not release")


@dataclass
class M4PipelineResult:
    case: M4ShotCase
    routing: RoutingDecision
    director_result: DirectorResult
    readiness: ProductionReadiness | None = None
    method_decision: MethodDecision | None = None
    capability_resolution: CapabilityResolution | None = None
    prompt_plan: PromptPlan | None = None
    admission: GenerationAdmission | None = None
    execution_decision: ExecutionDecision | None = None
    provider_request: ProviderRequest | None = None
    method_error: BaseException | None = None

    @property
    def admitted(self) -> bool:
        return self.admission is not None and self.admission.outcome is AdmissionOutcome.ADMITTED


async def run_pipeline(
    case: M4ShotCase,
    *,
    director_mode: DirectorDoubleMode = DirectorDoubleMode.SUCCEED,
    drop_required_binding: bool = False,
    feature_support_override: dict[str, Any] | None = None,
    stale_observation: bool = False,
    budget_denied: bool = False,
) -> M4PipelineResult:
    routing = DirectorRoutingPolicy(clock=lambda: _NOW).decide(
        input_profile_ref=f"profile:{case.shot.id}",
        content_basis=case.content_basis,
        human_override=DirectorKind.ARCREEL_NATIVE if case.director is DirectorKind.ARCREEL_NATIVE else None,
        override_actor="human-showrunner" if case.director is DirectorKind.ARCREEL_NATIVE else None,
        override_reason="fixture routes sequence C natively" if case.director is DirectorKind.ARCREEL_NATIVE else None,
        override_allows_fallback=False,
        decision_id=f"RD:{case.shot.id}",
    )
    adapter = FixtureDirectorAdapter(
        director_kind=routing.selected_director,
        scenes=[case.scene],
        shots=[case.shot],
        mode=director_mode,
    )
    native = FixtureDirectorAdapter(director_kind=DirectorKind.ARCREEL_NATIVE, scenes=[case.scene], shots=[case.shot])
    director_result = DirectorExecutionService(clock=lambda: _NOW).execute(
        routing=routing,
        adapters={routing.selected_director: adapter, DirectorKind.ARCREEL_NATIVE: native},
        artifact=case.shot,
    )
    result = M4PipelineResult(case=case, routing=routing, director_result=director_result)
    if not isinstance(director_result, DirectorSuccess):
        return result

    resolved_identity = VisualIdentityResolver().resolve(target_ref=case.shot.id, profiles=list(case.identity_profiles))
    bindings = () if drop_required_binding else case.bindings
    readiness = ProductionReadinessEvaluator().evaluate(
        shot=case.shot,
        bindings=list(bindings),
        resolved_identity=resolved_identity,
        observed_target_version=f"{case.shot.id}@1",
        binding_snapshot_ref=_SNAPSHOT,
    )
    result.readiness = readiness
    if readiness.state is not ReadinessState.READY:
        return result

    try:
        method_decision = MethodRouter().decide(
            MethodRoutingContext(
                target_ref=case.shot.id,
                allowed_methods=case.allowed_methods,
                readiness=readiness,
                identity=resolved_identity,
                source_authenticity_required=False,
                reusable_asset_current=case.reusable_asset_current,
                deterministic_equivalent_available=case.deterministic_equivalent_available,
                policy_version="m4-method-router-v1",
            )
        )
    except Exception as exc:
        result.method_error = exc
        return result
    result.method_decision = method_decision

    requirements = CapabilityRequirementBuilder().build(
        method_decision=method_decision, identity=resolved_identity, shot=case.shot
    )
    observation = case.observation
    if stale_observation:
        observation = observation.model_copy(update={"observed_at": _NOW.replace(hour=11, minute=0)})
    descriptor = case.descriptor
    if feature_support_override:
        from r2.contracts import CapabilityFeatureSupport

        overrides = [CapabilityFeatureSupport(feature_key=k, support=v) for k, v in feature_support_override.items()]
        observation = observation.model_copy(update={"feature_support": overrides})
        descriptor = descriptor.model_copy(update={"typed_features": []})

    registry = CapabilityRegistry(descriptors=[descriptor], observations=[observation], registry_version="reg-12-v1")
    capability_resolution = CapabilityMatcher().resolve(
        requirements=requirements,
        registry=registry,
        freshness_policy=default_freshness_policy(created_at=_NOW),
        now=_NOW,
    )
    result.capability_resolution = capability_resolution

    prompt_plan = PromptPlanner().build(shot=case.shot, method_decision=method_decision, identity=resolved_identity)
    result.prompt_plan = prompt_plan

    port = _FakeBudgetPort(deny=budget_denied)
    admission = await GenerationAdmissionService(budget_port=port).evaluate(
        readiness=readiness,
        method_decision=method_decision,
        capability_resolution=capability_resolution,
        prompt_plan=prompt_plan,
        budget_scope_ref=f"scope:{case.shot.id}" if case.paid else None,
        budget_amount=Decimal("3.00") if case.paid else None,
        budget_currency="USD" if case.paid else None,
        approval_ref=f"APPROVAL:{case.shot.id}" if case.requires_approval else None,
        now=_NOW,
        requires_approval=case.requires_approval,
    )
    result.admission = admission
    if admission.outcome is not AdmissionOutcome.ADMITTED:
        return result

    selected = capability_resolution.eligible_candidates[0]
    execution_decision = ExecutionDecisionService().create(
        admission=admission,
        capability_resolution=capability_resolution,
        prompt_plan=prompt_plan,
        selected_capability_id=selected,
        descriptor=descriptor,
    )
    result.execution_decision = execution_decision
    result.provider_request = DefaultPromptCompiler().compile(plan=prompt_plan, decision=execution_decision)
    return result


@pytest.fixture
def golden_12():
    return load_m4_golden_12()


@pytest.fixture
def pipeline():
    return run_pipeline


# --------------------------------------------------------------------------- #
# Host-integration doubles
# --------------------------------------------------------------------------- #


class _FakeReservationService:
    def __init__(self, *, claim_error: BaseException | None = None) -> None:
        self.claim_calls = 0
        self.release_calls = 0
        self._claim_error = claim_error

    async def claim_for_submission(self, *, reservation_ref, execution_decision_ref, now):
        self.claim_calls += 1
        if self._claim_error is not None:
            raise self._claim_error
        return _reservation_snapshot(reservation_ref, execution_decision_ref, BudgetReservationState.CLAIMED)

    async def release_pre_submit(self, *, reservation_ref, execution_decision_ref, now):  # pragma: no cover
        self.release_calls += 1
        return _reservation_snapshot(reservation_ref, execution_decision_ref, BudgetReservationState.RELEASED)


class _FakeSubmitter:
    def __init__(self, *, outcome: object | None = None, error: BaseException | None = None) -> None:
        from r2.production_intelligence.host_integration import HostSubmitOutcome

        self.calls = 0
        self._outcome = outcome or HostSubmitOutcome(
            succeeded=True, provider_execution_ref="job:1", output_asset_ref="asset:1"
        )
        self._error = error

    async def __call__(self, request):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._outcome


def _reservation_snapshot(reservation_ref: str, execution_decision_ref: str, state: BudgetReservationState):
    return BudgetReservationSnapshot(
        reservation_ref=reservation_ref,
        budget_scope_ref="scope:1",
        execution_decision_ref=execution_decision_ref,
        reserved_amount=Decimal("3.00"),
        currency="USD",
        state=state,
        created_at=_NOW,
        expires_at=None,
        claimed_at=_NOW if state is BudgetReservationState.CLAIMED else None,
        released_at=None,
        reconciled_at=None,
        cost_record_ref=None,
        version=1,
    )


def _make_decision(*, provider: str = "cloud", reservation: str | None = "RSV:1"):
    from r2.contracts import ExecutionDecision, ExecutionIdentityStability, ExecutionType

    return ExecutionDecision(
        id=f"ED:SH01:{provider}",
        target_ref="SH01",
        method_decision_ref="MD:SH01",
        prompt_plan_ref="PP:SH01",
        capability_resolution_ref="req-hash",
        adapter_id=f"adapter:{provider}",
        provider_id=provider,
        model_or_tool_id=f"cap:{provider}",
        execution_type=ExecutionType.API if reservation else ExecutionType.LOCAL,
        capability_descriptor_version="cat-v1",
        observation_snapshot_ref="obs-1",
        execution_identity_stability=ExecutionIdentityStability.IMMUTABLE_REVISION,
        request_semantics_hash="r" * 16,
        selection_policy_version="sel-v1",
        budget_reservation_ref=reservation,
        provenance=Provenance(created_by=ProvenanceActor.SYSTEM, created_at=_NOW),
    )


def _make_request(*, provider: str = "cloud"):
    return ProviderRequest(
        id="REQ-1",
        method_decision_ref="MD:SH01",
        prompt_plan_ref="PP:SH01",
        provider=provider,
        model=f"cap:{provider}",
        endpoint="generate/api",
        payload={"instruction": "do the thing"},
        adapter_version="cat-v1",
    )


class _HostKit:
    NOW = _NOW
    ReservationService = _FakeReservationService
    Submitter = _FakeSubmitter
    make_decision = staticmethod(_make_decision)
    make_request = staticmethod(_make_request)


@pytest.fixture
def hostkit():
    return _HostKit
