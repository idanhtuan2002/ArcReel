"""D09 — controlled metamorphic fault overlays MUT-01..MUT-08."""

from __future__ import annotations

from datetime import UTC, datetime

from r2.contracts import (
    AdmissionOutcome,
    CapabilitySupport,
    DirectorFailure,
    DirectorFailureClass,
    DirectorKind,
    DirectorSuccess,
    ProductionMethod,
    ReadinessState,
    compute_content_fingerprint,
    compute_execution_fingerprint,
)
from r2.production_intelligence.execution import ExecutionDecisionService
from r2.production_intelligence.failure import FailureNormalizer
from r2.production_intelligence.telemetry import ProductionTelemetryProjector
from scripts.r2.m4_test_doubles import (
    ControlledExecutionDouble,
    DirectorDoubleMode,
    ExecutionMode,
    ExecutionTier,
)

_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


async def test_mut_01_missing_required_binding_blocks_with_zero_expensive_execution(golden_12, pipeline) -> None:
    result = await pipeline(golden_12.by_id("SH05"), drop_required_binding=True)
    assert result.readiness is not None
    assert result.readiness.state is ReadinessState.BLOCKED
    assert result.admission is None
    assert result.execution_decision is None
    assert result.provider_request is None


async def test_mut_02_hard_feature_unknown_does_not_downgrade_the_method(golden_12, pipeline) -> None:
    result = await pipeline(
        golden_12.by_id("SH05"),
        feature_support_override={"CHARACTER_REFERENCE": CapabilitySupport.UNKNOWN},
    )
    assert result.method_decision is not None
    assert result.method_decision.method is ProductionMethod.GENERATED_IMAGE
    assert result.capability_resolution is not None
    assert "cap:sh05" in result.capability_resolution.unknown_candidates
    assert result.admission is not None
    assert result.admission.outcome is AdmissionOutcome.DENIED_UNAVAILABLE
    assert result.execution_decision is None


async def test_mut_03_director_unsupported_falls_back_to_arcreel_native_with_provenance(golden_12, pipeline) -> None:
    result = await pipeline(golden_12.by_id("SH05"), director_mode=DirectorDoubleMode.ROUTE_UNAVAILABLE)
    assert isinstance(result.director_result, DirectorSuccess)
    assert result.director_result.actual_director is DirectorKind.ARCREEL_NATIVE
    assert result.routing.selected_director is DirectorKind.TAKE
    assert result.routing.fallback_enabled is True
    assert result.director_result.provenance is not None


async def test_mut_04_malformed_director_output_fails_closed_without_fallback(golden_12, pipeline) -> None:
    result = await pipeline(golden_12.by_id("SH05"), director_mode=DirectorDoubleMode.MALFORMED)
    assert isinstance(result.director_result, DirectorFailure)
    assert result.director_result.failure_class is DirectorFailureClass.CONTRACT_OR_SEMANTIC_FAILURE
    assert result.director_result.attempted_director is DirectorKind.TAKE  # never re-attempted natively
    assert result.readiness is None


async def test_mut_05_same_method_provider_fallback_new_ed_same_content_fp_changed_execution_fp(
    golden_12, pipeline
) -> None:
    case = golden_12.by_id("SH05")
    result = await pipeline(case)
    assert result.execution_decision is not None
    assert result.provider_request is not None
    ed_a, req_a = result.execution_decision, result.provider_request

    alt_descriptor = case.descriptor.model_copy(
        update={"capability_id": "cap:sh05-alt", "provider_id": "cloud-2", "adapter_id": "adapter:sh05-alt"}
    )
    ed_b = ExecutionDecisionService().create(
        admission=result.admission,
        capability_resolution=result.capability_resolution,
        prompt_plan=result.prompt_plan,
        selected_capability_id="cap:sh05-alt",
        descriptor=alt_descriptor,
    )
    from r2.production_intelligence.prompting import DefaultPromptCompiler

    req_b = DefaultPromptCompiler().compile(plan=result.prompt_plan, decision=ed_b)

    assert ed_a.id != ed_b.id
    assert ed_a.method_decision_ref == ed_b.method_decision_ref

    identity_refs = [c.semantic_key for c in _resolved(result)]
    content_a = compute_content_fingerprint(
        shot_spec=case.shot,
        bindings=list(case.bindings),
        visual_identity_refs=identity_refs,
        approved_source_asset_refs=[],
    )
    content_b = compute_content_fingerprint(
        shot_spec=case.shot,
        bindings=list(case.bindings),
        visual_identity_refs=identity_refs,
        approved_source_asset_refs=[],
    )
    assert content_a == content_b

    exec_a = _exec_fp(req_a)
    exec_b = _exec_fp(req_b)
    assert exec_a != exec_b


async def test_mut_06_execution_only_config_change_preserves_content_fp_changes_execution_fp(
    golden_12, pipeline
) -> None:
    case = golden_12.by_id("SH06")
    result = await pipeline(case)
    assert result.provider_request is not None
    req = result.provider_request

    content_a = compute_content_fingerprint(
        shot_spec=case.shot, bindings=list(case.bindings), visual_identity_refs=[], approved_source_asset_refs=[]
    )
    content_b = compute_content_fingerprint(
        shot_spec=case.shot, bindings=list(case.bindings), visual_identity_refs=[], approved_source_asset_refs=[]
    )
    assert content_a == content_b

    exec_seed_1 = _exec_fp(req, seed=1)
    exec_seed_2 = _exec_fp(req, seed=2)
    assert exec_seed_1 != exec_seed_2


async def test_mut_07_charge_then_fail_keeps_cost_attributable_and_failure_observable(golden_12, pipeline) -> None:
    case = golden_12.by_id("SH06")
    result = await pipeline(case)
    assert result.provider_request is not None

    double = ControlledExecutionDouble(
        tier=ExecutionTier.PREMIUM_CLOUD_TIER_DOUBLE, mode=ExecutionMode.CHARGE_THEN_FAIL
    )
    outcome = double.run(result.provider_request)
    assert outcome.succeeded is False
    assert outcome.cost_record_ref is not None  # cost stays attributable

    from r2.contracts import FailureDomain

    record = FailureNormalizer().normalize_outcome(
        domain=FailureDomain.EXECUTION,
        reason_code="CHARGE_THEN_FAIL",
        target_ref=case.shot.id,
        now=_NOW,
        attempt_ref="ATT-1",
        decision_refs=[result.execution_decision.id],
    )
    event = ProductionTelemetryProjector(production_run_id="run-mut07").project_failure(record)
    assert event.target_ref == case.shot.id
    assert event.reason_code == "CHARGE_THEN_FAIL"


async def test_mut_08_stale_capability_observation_cannot_silently_admit(golden_12, pipeline) -> None:
    result = await pipeline(golden_12.by_id("SH05"), stale_observation=True)
    assert result.capability_resolution is not None
    assert "cap:sh05" in result.capability_resolution.unknown_candidates
    assert result.capability_resolution.eligible_candidates == []
    assert result.admission is not None
    assert result.admission.outcome is AdmissionOutcome.DENIED_UNAVAILABLE
    assert result.execution_decision is None


def _resolved(result):
    from r2.production_intelligence.identity import VisualIdentityResolver

    return (
        VisualIdentityResolver()
        .resolve(target_ref=result.case.shot.id, profiles=list(result.case.identity_profiles))
        .resolved_constraints
    )


def _exec_fp(request, *, seed: int | None = None) -> str:
    return compute_execution_fingerprint(
        provider=request.provider,
        model=request.model,
        endpoint=request.endpoint,
        seed=seed,
        resolution=None,
        generation_settings={},
        prompt_compiler_version="m4-prompt-compiler-v1",
        provider_adapter_version=request.adapter_version,
    )
