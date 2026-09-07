"""D08 — immutable per-attempt ExecutionDecision."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from r2.contracts import (
    AdmissionOutcome,
    CapabilityDescriptor,
    CapabilityResolution,
    ExecutionType,
    GenerationAdmission,
    ProductionMethod,
    PromptPlan,
    Provenance,
    ProvenanceActor,
)
from r2.production_intelligence.execution import ExecutionDecisionService, ExecutionNotAdmitted

_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _descriptor(cap_id: str, provider: str) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=cap_id,
        adapter_id=f"adapter:{provider}",
        provider_id=provider,
        execution_type=ExecutionType.API,
        supported_methods=[ProductionMethod.GENERATED_IMAGE],
        typed_features=["CHARACTER_REFERENCE"],
        descriptor_source="static",
        descriptor_version="cat-v1",
        provenance=Provenance(created_by=ProvenanceActor.SYSTEM, created_at=_NOW),
    )


def _resolution() -> CapabilityResolution:
    return CapabilityResolution(
        requirement_set_ref="req-hash",
        registry_version="reg-v1",
        observation_snapshot_ref="obs-1",
        matcher_policy_version="match-v1",
        eligible_candidates=["cap:a", "cap:b"],
    )


def _plan() -> PromptPlan:
    return PromptPlan(
        id="PP:SH01",
        schema_version="1",
        version=1,
        target_ref="SH01",
        semantic_instruction="do the thing",
        compiler_version="c1",
        method_decision_ref="MD:SH01",
        visual_identity_constraints=["hairstyle=short black bob(LOCKED)"],
    )


def _admission(
    outcome: AdmissionOutcome = AdmissionOutcome.ADMITTED, *, reservation: str | None = "RSV:1"
) -> GenerationAdmission:
    return GenerationAdmission(
        id="GA:SH01",
        target_ref="SH01",
        outcome=outcome,
        method_decision_ref="MD:SH01",
        capability_resolution_ref="req-hash",
        prompt_plan_ref="PP:SH01",
        readiness_ref="READY:SH01",
        budget_reservation_ref=reservation,
        evaluated_at=_NOW,
        provenance=Provenance(created_by=ProvenanceActor.SYSTEM, created_at=_NOW),
    )


def _create(cap_id: str, provider: str):
    return ExecutionDecisionService().create(
        admission=_admission(),
        capability_resolution=_resolution(),
        prompt_plan=_plan(),
        selected_capability_id=cap_id,
        descriptor=_descriptor(cap_id, provider),
    )


def test_execution_decision_locks_provider_and_is_frozen() -> None:
    ed = _create("cap:a", "provider-x")
    assert ed.provider_id == "provider-x"
    assert ed.adapter_id == "adapter:provider-x"
    assert ed.capability_descriptor_version == "cat-v1"
    assert ed.observation_snapshot_ref == "obs-1"
    assert ed.budget_reservation_ref == "RSV:1"
    assert ed.request_semantics_hash
    with pytest.raises(ValidationError):
        ed.provider_id = "provider-y"


def test_same_method_provider_fallback_creates_a_new_execution_decision_id() -> None:
    a = _create("cap:a", "provider-x")
    b = _create("cap:b", "provider-y")
    assert a.method_decision_ref == b.method_decision_ref == "MD:SH01"
    assert a.id != b.id
    assert a.request_semantics_hash != b.request_semantics_hash


def test_same_inputs_produce_a_stable_execution_decision() -> None:
    a = _create("cap:a", "provider-x")
    b = _create("cap:a", "provider-x")
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_non_admitted_admission_cannot_create_an_execution_decision() -> None:
    with pytest.raises(ExecutionNotAdmitted):
        ExecutionDecisionService().create(
            admission=_admission(AdmissionOutcome.DENIED_BUDGET),
            capability_resolution=_resolution(),
            prompt_plan=_plan(),
            selected_capability_id="cap:a",
            descriptor=_descriptor("cap:a", "provider-x"),
        )


def test_rejects_a_selected_capability_absent_from_eligible_candidates() -> None:
    with pytest.raises(ValueError, match="eligible"):
        _create("cap:not-eligible", "provider-x")


def test_rejects_a_descriptor_whose_capability_id_is_not_the_selected_one() -> None:
    with pytest.raises(ValueError, match="descriptor"):
        ExecutionDecisionService().create(
            admission=_admission(),
            capability_resolution=_resolution(),
            prompt_plan=_plan(),
            selected_capability_id="cap:a",
            descriptor=_descriptor("cap:b", "provider-x"),
        )


def test_rejects_admission_whose_resolution_ref_does_not_match_the_resolution() -> None:
    other = CapabilityResolution(
        requirement_set_ref="a-different-hash",
        registry_version="reg-v1",
        observation_snapshot_ref="obs-1",
        matcher_policy_version="match-v1",
        eligible_candidates=["cap:a", "cap:b"],
    )
    with pytest.raises(ValueError, match="capability_resolution_ref"):
        ExecutionDecisionService().create(
            admission=_admission(),
            capability_resolution=other,
            prompt_plan=_plan(),
            selected_capability_id="cap:a",
            descriptor=_descriptor("cap:a", "provider-x"),
        )


def test_rejects_admission_whose_prompt_plan_ref_does_not_match_the_plan() -> None:
    plan = _plan().model_copy(update={"id": "PP:DIFFERENT"})
    with pytest.raises(ValueError, match="prompt_plan_ref"):
        ExecutionDecisionService().create(
            admission=_admission(),
            capability_resolution=_resolution(),
            prompt_plan=plan,
            selected_capability_id="cap:a",
            descriptor=_descriptor("cap:a", "provider-x"),
        )


def test_rejects_a_candidate_the_admission_did_not_select() -> None:
    admission = _admission()
    admission = admission.model_copy(update={"selected_capability_id": "cap:b"})
    with pytest.raises(ValueError, match="selected"):
        ExecutionDecisionService().create(
            admission=admission,
            capability_resolution=_resolution(),
            prompt_plan=_plan(),
            selected_capability_id="cap:a",
            descriptor=_descriptor("cap:a", "provider-x"),
        )


def test_rejects_admission_and_plan_that_disagree_on_the_target() -> None:
    plan = _plan().model_copy(update={"target_ref": "SH99"})
    with pytest.raises(ValueError, match="target"):
        ExecutionDecisionService().create(
            admission=_admission(),
            capability_resolution=_resolution(),
            prompt_plan=plan,
            selected_capability_id="cap:a",
            descriptor=_descriptor("cap:a", "provider-x"),
        )


def test_execution_decision_service_has_no_method_change_surface() -> None:
    service = ExecutionDecisionService()
    assert not any("method" in name.lower() and "change" in name.lower() for name in dir(service))
    ed = _create("cap:a", "provider-x")
    assert ed.method_decision_ref == "MD:SH01"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
