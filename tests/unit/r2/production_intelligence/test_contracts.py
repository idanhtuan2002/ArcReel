"""L0 contract tests for the M4 production-intelligence kernel extensions.

Covers provider-neutrality of stable semantic contracts, the discriminated
DirectorResult boundary, and additive round-trip compatibility for the extended
M1 contracts.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from r2.contracts import (
    AdmissionOutcome,
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityFreshnessPolicy,
    CapabilityFreshnessRule,
    CapabilityObservation,
    CapabilityRequirements,
    CapabilityResolution,
    CapabilitySupport,
    ContentBasis,
    ContentBasisType,
    CreativeApprovalStatus,
    DirectorFailure,
    DirectorFailureClass,
    DirectorKind,
    DirectorResult,
    DirectorSuccess,
    ExecutionDecision,
    ExecutionIdentityStability,
    ExecutionType,
    FailureRecord,
    GenerationAdmission,
    IdentityConstraint,
    IdentityScopeType,
    IdentityStrength,
    MethodDecision,
    ObservationExpiryBehavior,
    ProductionEvent,
    ProductionMethod,
    ProductionReadiness,
    PromptPlan,
    Provenance,
    ProvenanceActor,
    ProviderRequest,
    ReadinessRequirement,
    ReadinessState,
    ResolvedIdentityConstraint,
    ResolvedIdentityStatus,
    ResolvedVisualIdentity,
    RetryDisposition,
    RoutingDecision,
    SceneSpec,
    ShotSpec,
    VisualIdentityProfile,
)
from r2.contracts.enums import FailureClassification, FailureDomain

# Provider/runtime identity must never appear on a stable semantic contract.
FORBIDDEN_PROVIDER_FIELDS = {
    "endpoint",
    "payload",
    "provider_job_id",
    "submitted_base_url",
    "api_key",
    "provider",
    "model",
}

PROVIDER_NEUTRAL_MODELS = (
    SceneSpec,
    ShotSpec,
    MethodDecision,
    PromptPlan,
    VisualIdentityProfile,
    ResolvedVisualIdentity,
)


def _basis() -> ContentBasis:
    return ContentBasis(
        basis_type=ContentBasisType.FACTUAL,
        basis_version="v1",
        refs=["research:RP-1"],
    )


def _provenance() -> Provenance:
    return Provenance(
        created_by=ProvenanceActor.SYSTEM,
        created_at=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
    )


def _shot(**overrides: object) -> ShotSpec:
    data: dict[str, object] = {
        "id": "SH01",
        "schema_version": "1",
        "version": 1,
        "scene_id": "SC01",
        "content_basis": _basis(),
        "purpose": "Visualize SH01",
        "target_duration": 8.0,
        "framing": "graphic",
        "camera": "static",
        "audio_intent": "narration",
        "allowed_methods": [ProductionMethod.REUSE],
        "quality_tier": 1,
        "approval_status": CreativeApprovalStatus.APPROVED,
    }
    data.update(overrides)
    return ShotSpec.model_validate(data)


def _roundtrip(model):
    raw = model.model_dump(mode="json")
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return type(model).model_validate(json.loads(encoded))


# --------------------------------------------------------------------------- #
# Step 1 — provider neutrality
# --------------------------------------------------------------------------- #


def test_stable_semantic_contracts_have_no_provider_runtime_fields() -> None:
    for model in PROVIDER_NEUTRAL_MODELS:
        overlap = set(model.model_fields) & FORBIDDEN_PROVIDER_FIELDS
        assert overlap == set(), (model.__name__, overlap)


def test_execution_side_contracts_do_carry_provider_identity() -> None:
    # The boundary works the other way for execution-side contracts: provider
    # identity is required exactly here and nowhere upstream.
    assert {"provider", "model", "endpoint"} <= set(ProviderRequest.model_fields)
    assert {"provider_id", "model_or_tool_id"} <= set(ExecutionDecision.model_fields)


def test_prompt_plan_extensions_stay_semantic() -> None:
    plan = PromptPlan(
        id="PP-1",
        schema_version="1",
        version=1,
        target_ref="SH01",
        semantic_instruction="show the commit graph",
        compiler_version="c1",
        method_decision_ref="MD-1",
        subject_intent="terminal window",
        composition_intent="centered",
        negative_constraints=["no watermark"],
        output_requirements={"aspect_ratio": "16:9"},
    )
    assert "payload" not in plan.model_dump()
    assert plan.method_decision_ref == "MD-1"
    assert _roundtrip(plan) == plan


# --------------------------------------------------------------------------- #
# Step 2 — discriminated DirectorResult boundary
# --------------------------------------------------------------------------- #


def test_director_success_requires_normalized_specs() -> None:
    scene = SceneSpec.model_validate(
        {
            "id": "SC01",
            "schema_version": "1",
            "version": 1,
            "source_artifact_ref": "SCRIPT-1",
            "source_unit_refs": ["SEC-01"],
            "content_basis": _basis().model_dump(mode="json"),
            "purpose": "Explain SEC-01",
            "duration_target": 8.0,
            "required_beats": ["beat:SEC-01"],
            "allowed_methods": [ProductionMethod.REUSE],
            "approval_status": "APPROVED",
        }
    )
    success = DirectorSuccess(
        routing_decision_ref="RD-1",
        actual_director=DirectorKind.OPENMONTAGE,
        scenes=[scene],
        shots=[_shot()],
        validation_summary="contract+semantic PASS",
        provenance=_provenance(),
    )
    assert isinstance(success, DirectorSuccess)
    assert success.result_kind == "SUCCESS"
    assert _roundtrip(success) == success


def test_director_success_rejects_partial_or_malformed_shot() -> None:
    with pytest.raises(ValidationError):
        DirectorSuccess(
            routing_decision_ref="RD-1",
            actual_director=DirectorKind.OPENMONTAGE,
            scenes=[],
            shots=[{"id": "SH-broken"}],  # not a valid ShotSpec
            validation_summary="should not build",
            provenance=_provenance(),
        )


def test_director_failure_partial_output_is_diagnostic_reference_only() -> None:
    failure = DirectorFailure(
        routing_decision_ref="RD-1",
        attempted_director=DirectorKind.TAKE,
        failure_class=DirectorFailureClass.PARTIAL_OR_AMBIGUOUS_EXECUTION,
        retryable=False,
        fallback_eligible=False,
        error_code="PARTIAL_OUTPUT",
        message="director crashed after emitting 2 of 5 shots",
        partial_output_diagnostic_ref="diag:quarantine/RD-1",
    )
    assert failure.result_kind == "FAILURE"
    assert isinstance(failure.partial_output_diagnostic_ref, str)
    # A diagnostic pointer must not be able to smuggle real specs back in.
    with pytest.raises(ValidationError):
        DirectorFailure(
            routing_decision_ref="RD-1",
            attempted_director=DirectorKind.TAKE,
            failure_class=DirectorFailureClass.CONTRACT_OR_SEMANTIC_FAILURE,
            retryable=False,
            fallback_eligible=False,
            error_code="X",
            message="y",
            partial_output_diagnostic_ref={"shots": [_shot().model_dump(mode="json")]},
        )


def test_director_result_is_a_discriminated_union() -> None:
    from pydantic import TypeAdapter

    adapter = TypeAdapter(DirectorResult)
    parsed = adapter.validate_python(
        {
            "result_kind": "FAILURE",
            "routing_decision_ref": "RD-1",
            "attempted_director": "ARCREEL_NATIVE",
            "failure_class": "ROUTE_UNAVAILABLE",
            "retryable": True,
            "fallback_eligible": True,
            "error_code": "NO_ROUTE",
            "message": "donor unavailable",
        }
    )
    assert isinstance(parsed, DirectorFailure)


# --------------------------------------------------------------------------- #
# D01 RoutingDecision
# --------------------------------------------------------------------------- #


def test_routing_decision_records_policy_advisory_and_sticky_override() -> None:
    decision = RoutingDecision(
        routing_decision_id="RD-1",
        routing_policy_version="route-v1",
        input_profile_ref="profile:general",
        policy_selected_director=DirectorKind.OPENMONTAGE,
        advisory_recommendations=[DirectorKind.OPENMONTAGE],
        advisory_reasons=["general/factual content"],
        human_override=DirectorKind.TAKE,
        override_actor="human-showrunner",
        override_reason="wants cinematic treatment",
        selected_director=DirectorKind.TAKE,
        fallback_enabled=False,
        decided_at=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
        provenance=_provenance(),
    )
    assert decision.selected_director is DirectorKind.TAKE
    assert decision.fallback_enabled is False
    assert _roundtrip(decision) == decision


# --------------------------------------------------------------------------- #
# D05 scoped/typed visual identity
# --------------------------------------------------------------------------- #


def test_visual_identity_profile_gains_optional_scope_and_constraints() -> None:
    # Legacy flat profile still validates and round-trips unchanged.
    legacy = VisualIdentityProfile(
        id="VIP-1",
        schema_version="1",
        version=1,
        semantic_character_ref="character:maya",
    )
    assert legacy.scope_type is None
    assert legacy.identity_constraints == []
    assert _roundtrip(legacy) == legacy

    scoped = VisualIdentityProfile(
        id="VIP-2",
        schema_version="1",
        version=1,
        semantic_character_ref="character:maya",
        scope_type=IdentityScopeType.SCENE,
        scope_ref="SC01",
        identity_constraints=[
            IdentityConstraint(
                semantic_key="hairstyle",
                strength=IdentityStrength.LOCKED,
                semantic_value="short black bob",
            )
        ],
    )
    assert scoped.identity_constraints[0].strength is IdentityStrength.LOCKED
    assert _roundtrip(scoped) == scoped


def test_resolved_visual_identity_is_a_provider_neutral_view() -> None:
    resolved = ResolvedVisualIdentity(
        target_ref="SH01",
        status=ResolvedIdentityStatus.CONFLICTED,
        contributing_profile_refs=["VIP-1", "VIP-2"],
        resolved_constraints=[
            ResolvedIdentityConstraint(
                semantic_key="hairstyle",
                effective_strength=IdentityStrength.LOCKED,
                effective_value="short black bob",
                source_scope_ref="SC01",
            )
        ],
        conflicts=["hairstyle: LOCKED short black bob vs LOCKED long braid"],
        resolution_policy_version="identity-v1",
        observed_profile_versions=["VIP-1@1", "VIP-2@1"],
    )
    assert resolved.status is ResolvedIdentityStatus.CONFLICTED
    assert set(ResolvedVisualIdentity.model_fields).isdisjoint(FORBIDDEN_PROVIDER_FIELDS)
    assert _roundtrip(resolved) == resolved


# --------------------------------------------------------------------------- #
# D04 readiness extensions
# --------------------------------------------------------------------------- #


def test_production_readiness_carries_freshness_anchors_without_breaking_derivation() -> None:
    readiness = ProductionReadiness.model_validate(
        {
            "id": "READY-SH01",
            "target_id": "SH01",
            "requirements": [
                ReadinessRequirement(
                    requirement_id="char",
                    role="CHARACTER",
                    required=True,
                    status=ReadinessState.READY,
                    resolved_binding="B-1",
                    resolution_source="binding-snapshot@7",
                ).model_dump(mode="json"),
            ],
            "observed_target_version": "SH01@4",
            "observed_binding_snapshot_ref": "snapshot@7",
            "evaluation_policy_version": "readiness-v1",
        }
    )
    assert readiness.state is ReadinessState.READY
    assert readiness.observed_target_version == "SH01@4"
    assert _roundtrip(readiness) == readiness


def test_blocked_reason_forces_blocked_state_even_with_ready_requirements() -> None:
    readiness = ProductionReadiness.model_validate(
        {
            "id": "READY-SH01",
            "target_id": "SH01",
            "requirements": [],
            "blocked_reason": "IDENTITY_CONFLICT",
        }
    )
    assert readiness.state is ReadinessState.BLOCKED
    assert readiness.blocked_reason == "IDENTITY_CONFLICT"


# --------------------------------------------------------------------------- #
# D06 method decision extensions
# --------------------------------------------------------------------------- #


def test_method_decision_extensions_are_additive_and_neutral() -> None:
    decision = MethodDecision(
        id="MD-1",
        target_ref="SH01",
        method=ProductionMethod.DETERMINISTIC,
        rationale="diagram equivalent available",
        cost_class="LOW",
        quality_tier=1,
        method_policy_version="method-v1",
        eligible_methods=[ProductionMethod.DETERMINISTIC, ProductionMethod.GENERATED_IMAGE],
        rejected_methods=[
            {"method": ProductionMethod.REUSE, "reason_codes": ["NO_CURRENT_ASSET"]},
        ],
        decision_factors=["deterministic-before-generation"],
    )
    assert decision.method is ProductionMethod.DETERMINISTIC
    assert decision.rejected_methods[0].method is ProductionMethod.REUSE
    assert set(MethodDecision.model_fields).isdisjoint({"provider", "model", "endpoint"})
    assert _roundtrip(decision) == decision


# --------------------------------------------------------------------------- #
# D07 capability registry contracts
# --------------------------------------------------------------------------- #


def test_capability_descriptor_and_observation_axes_stay_distinct() -> None:
    descriptor = CapabilityDescriptor(
        capability_id="cap:local-sdxl",
        adapter_id="adapter:comfy",
        provider_id="local",
        execution_type=ExecutionType.LOCAL_GPU,
        supported_methods=[ProductionMethod.GENERATED_IMAGE],
        typed_features=["CHARACTER_REFERENCE"],
        descriptor_source="static-catalog",
        descriptor_version="cat-v1",
        provenance=_provenance(),
    )
    observation = CapabilityObservation(
        capability_id="cap:local-sdxl",
        observation_class="HARD_DYNAMIC",
        availability=CapabilityAvailability.AVAILABLE,
        observed_at=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
        observation_version="obs-7",
    )
    assert descriptor.execution_type is ExecutionType.LOCAL_GPU
    assert observation.availability is CapabilityAvailability.AVAILABLE
    assert _roundtrip(descriptor) == descriptor
    assert _roundtrip(observation) == observation


def test_capability_requirements_and_resolution_are_matcher_shaped() -> None:
    requirements = CapabilityRequirements(
        target_ref="SH01",
        method=ProductionMethod.GENERATED_IMAGE,
        hard_features=["CHARACTER_REFERENCE"],
        soft_features=["STYLE_REFERENCE"],
        requirement_set_hash="h" * 8,
        policy_version="req-v1",
    )
    resolution = CapabilityResolution(
        requirement_set_ref="h" * 8,
        registry_version="reg-v1",
        observation_snapshot_ref="obs-7",
        matcher_policy_version="match-v1",
        eligible_candidates=["cap:local-sdxl"],
        rejected_candidates=[{"candidate": "cap:api-x", "reasons": ["UNSUPPORTED"]}],
        unknown_candidates=["cap:api-y"],
    )
    assert resolution.rejected_candidates[0].candidate == "cap:api-x"
    assert CapabilitySupport.UNKNOWN.value == "UNKNOWN"
    assert _roundtrip(requirements) == requirements
    assert _roundtrip(resolution) == resolution


def test_capability_freshness_policy_holds_class_rules() -> None:
    policy = CapabilityFreshnessPolicy(
        policy_version="m4-cap-freshness-v1",
        rules=[
            CapabilityFreshnessRule(
                observation_class="HARD_DYNAMIC",
                max_age_seconds=30,
                revalidate_on_admission=True,
                invalidation_triggers=["credential_rotation"],
                expiry_behavior=ObservationExpiryBehavior.BECOME_UNKNOWN,
            ),
        ],
        provenance=_provenance(),
    )
    assert policy.rules[0].expiry_behavior is ObservationExpiryBehavior.BECOME_UNKNOWN
    assert _roundtrip(policy) == policy


# --------------------------------------------------------------------------- #
# D08 admission + immutable execution decision
# --------------------------------------------------------------------------- #


def test_generation_admission_normalized_outcomes() -> None:
    admission = GenerationAdmission(
        id="GA-1",
        target_ref="SH01",
        outcome=AdmissionOutcome.DENIED_BUDGET,
        method_decision_ref="MD-1",
        capability_resolution_ref="CR-1",
        prompt_plan_ref="PP-1",
        readiness_ref="READY-SH01",
        reason_codes=["HOST_RESERVE_DENIED"],
        evaluated_at=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
        provenance=_provenance(),
    )
    assert admission.outcome is AdmissionOutcome.DENIED_BUDGET
    assert _roundtrip(admission) == admission


def test_execution_decision_is_frozen_and_provider_bound() -> None:
    decision = ExecutionDecision(
        id="ED-1",
        target_ref="SH01",
        method_decision_ref="MD-1",
        prompt_plan_ref="PP-1",
        capability_resolution_ref="CR-1",
        adapter_id="adapter:comfy",
        provider_id="local",
        model_or_tool_id="sdxl-1.0",
        execution_type=ExecutionType.LOCAL_GPU,
        capability_descriptor_version="cat-v1",
        observation_snapshot_ref="obs-7",
        execution_identity_stability=ExecutionIdentityStability.IMMUTABLE_REVISION,
        request_semantics_hash="r" * 16,
        selection_policy_version="sel-v1",
        provenance=_provenance(),
    )
    assert decision.provider_id == "local"
    with pytest.raises((ValidationError, TypeError, AttributeError)):
        decision.provider_id = "somewhere-else"
    assert _roundtrip(decision) == decision


# --------------------------------------------------------------------------- #
# D10 failure / telemetry contracts
# --------------------------------------------------------------------------- #


def test_failure_record_carries_explicit_retry_disposition() -> None:
    record = FailureRecord(
        failure_id="F-1",
        occurred_at=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
        domain=FailureDomain.CAPABILITY,
        reason_code="CAPABILITY_UNKNOWN",
        classification=FailureClassification.EXPECTED_BLOCK,
        retry_disposition=RetryDisposition.NEW_EXECUTION_DECISION_REQUIRED,
        target_ref="SH01",
        decision_refs=["MD-1"],
        safe_message="no capability satisfied the hard requirement",
        provenance=_provenance(),
    )
    assert record.retry_disposition is RetryDisposition.NEW_EXECUTION_DECISION_REQUIRED
    assert _roundtrip(record) == record


def test_production_event_references_authoritative_objects_only() -> None:
    event = ProductionEvent(
        event_id="E-1",
        event_type="ADMISSION_DECIDED",
        timestamp=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
        production_run_id="run-1",
        target_ref="SH01",
        stage="admission",
        outcome="DENIED_BUDGET",
        reason_code="HOST_RESERVE_DENIED",
        decision_refs=["MD-1", "CR-1"],
        provenance=_provenance(),
    )
    assert event.stage == "admission"
    assert _roundtrip(event) == event
