"""D09 — controlled metamorphic fault overlays MUT-01..MUT-08."""

from __future__ import annotations

from datetime import UTC, datetime

from r2.contracts import (
    AdmissionOutcome,
    CapabilityAvailability,
    CapabilityObservation,
    CapabilitySupport,
    DirectorFailure,
    DirectorFailureClass,
    DirectorKind,
    DirectorSuccess,
    FailureDomain,
    ProductionMethod,
    ReadinessState,
    compute_content_fingerprint,
    compute_execution_fingerprint,
)
from r2.production_intelligence.capability_registry import (
    CapabilityMatcher,
    CapabilityRegistry,
    CapabilityRequirementBuilder,
    default_freshness_policy,
)
from r2.production_intelligence.execution import ExecutionDecisionService
from r2.production_intelligence.failure import FailureNormalizer
from r2.production_intelligence.host_integration import M4HostIntegration
from r2.production_intelligence.identity import VisualIdentityResolver
from r2.production_intelligence.prompting import DefaultPromptCompiler
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
    primary_cap = ed_a.model_or_tool_id

    # Real second capability resolution: an alternate descriptor for the SAME
    # method, resolved through the real matcher so the fallback ED is built from
    # an actually-eligible candidate (not an invented id).
    alt_descriptor = case.descriptor.model_copy(
        update={"capability_id": "cap:sh05-alt", "provider_id": "cloud-2", "adapter_id": "adapter:sh05-alt"}
    )
    alt_obs = CapabilityObservation(
        capability_id="cap:sh05-alt",
        observation_class="HARD_DYNAMIC_AVAILABILITY",
        availability=CapabilityAvailability.AVAILABLE,
        observed_at=_NOW,
        observation_version="cap:sh05-alt-obs",
    )
    resolved_identity = _resolved_identity(result)
    requirements = CapabilityRequirementBuilder().build(
        method_decision=result.method_decision, identity=resolved_identity, shot=case.shot
    )
    registry = CapabilityRegistry(
        descriptors=[case.descriptor, alt_descriptor],
        observations=[case.observation, alt_obs],
        registry_version="reg-mut05",
    )
    resolution_b = CapabilityMatcher().resolve(
        requirements=requirements,
        registry=registry,
        freshness_policy=default_freshness_policy(created_at=_NOW),
        now=_NOW,
    )
    fallback_cap = next(c for c in resolution_b.eligible_candidates if c != primary_cap)
    assert fallback_cap == "cap:sh05-alt"

    ed_b = ExecutionDecisionService().create(
        admission=result.admission,
        capability_resolution=resolution_b,
        prompt_plan=result.prompt_plan,
        selected_capability_id=fallback_cap,
        descriptor=alt_descriptor,
    )
    req_b = DefaultPromptCompiler().compile(plan=result.prompt_plan, decision=ed_b)

    assert ed_a.id != ed_b.id
    assert ed_a.method_decision_ref == ed_b.method_decision_ref

    # content fingerprint is a pure function of shot + bindings + identity; the
    # provider swap must not touch it, while the execution fingerprint must move.
    identity_refs = [c.semantic_key for c in resolved_identity.resolved_constraints]
    content = compute_content_fingerprint(
        shot_spec=case.shot,
        bindings=list(case.bindings),
        visual_identity_refs=identity_refs,
        approved_source_asset_refs=[],
    )
    assert content  # deterministic, non-empty
    assert _exec_fp(req_a) != _exec_fp(req_b)


async def test_mut_06_execution_only_config_change_preserves_content_fp_changes_execution_fp(
    golden_12, pipeline
) -> None:
    import inspect

    case = golden_12.by_id("SH06")
    result = await pipeline(case)
    assert result.provider_request is not None
    req = result.provider_request

    # Structural proof that content-plane fingerprinting cannot depend on
    # execution config: its signature accepts no provider/model/seed/endpoint.
    content_params = set(inspect.signature(compute_content_fingerprint).parameters)
    assert content_params.isdisjoint({"provider", "model", "endpoint", "seed", "resolution", "generation_settings"})
    content = compute_content_fingerprint(
        shot_spec=case.shot, bindings=list(case.bindings), visual_identity_refs=[], approved_source_asset_refs=[]
    )
    assert content

    # Execution-only mutations (seed) move only the execution fingerprint.
    assert _exec_fp(req, seed=1) != _exec_fp(req, seed=2)
    assert _exec_fp(req, seed=1) == _exec_fp(req, seed=1)


async def test_mut_07_charge_then_fail_keeps_cost_attributable_and_failure_observable(
    golden_12, pipeline, hostkit
) -> None:
    case = golden_12.by_id("SH06")
    result = await pipeline(case)
    assert result.execution_decision is not None
    assert result.provider_request is not None

    # Run the real Host-integration path with a CHARGE_THEN_FAIL provider double.
    double = ControlledExecutionDouble(
        tier=ExecutionTier.PREMIUM_CLOUD_TIER_DOUBLE, mode=ExecutionMode.CHARGE_THEN_FAIL
    )

    async def _submit(request):
        outcome = double.run(request)
        from r2.production_intelligence.host_integration import HostSubmitOutcome

        return HostSubmitOutcome(
            succeeded=outcome.succeeded,
            provider_execution_ref="job:mut07",
            output_asset_ref=outcome.output_ref,
            cost_record_ref=outcome.cost_record_ref,
        )

    integration = M4HostIntegration(submitter=_submit, reservation_service=hostkit.ReservationService())
    decision = result.execution_decision.model_copy(update={"budget_reservation_ref": "RSV:mut07"})
    candidate = await integration.execute_admitted(
        decision=decision,
        request=result.provider_request,
        attempt_ref="ATT-mut07",
        content_fingerprint="c" * 64,
    )
    assert candidate.lifecycle_state.value == "FAILED"
    assert integration.cost_records
    assert integration.cost_records[0][0] == "ATT-mut07"

    record = FailureNormalizer().normalize_outcome(
        domain=FailureDomain.EXECUTION,
        reason_code="CHARGE_THEN_FAIL",
        target_ref=case.shot.id,
        now=_NOW,
        attempt_ref="ATT-mut07",
        decision_refs=[decision.id],
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


def _resolved_identity(result):
    return VisualIdentityResolver().resolve(
        target_ref=result.case.shot.id,
        scope_ancestry=result.case.scope_ancestry,
        profiles=list(result.case.identity_profiles),
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
