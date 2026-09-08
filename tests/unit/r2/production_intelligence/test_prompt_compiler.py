"""D08 — provider-specific PromptCompiler translation below the semantic boundary."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.contracts import (
    CapabilityDescriptor,
    ExecutionDecision,
    ExecutionIdentityStability,
    ExecutionType,
    ProductionMethod,
    PromptPlan,
    Provenance,
    ProvenanceActor,
)
from r2.production_intelligence.prompting import (
    AdapterCompileProfile,
    DefaultPromptCompiler,
    PromptCompilationIncompatible,
)

_NOW_PROV = Provenance(created_by=ProvenanceActor.SYSTEM, created_at=datetime(2026, 9, 7, 12, 0, tzinfo=UTC))


def _plan(*, controls=("narration",), references=("hairstyle",)) -> PromptPlan:
    return PromptPlan(
        id="PP:SH01",
        schema_version="1",
        version=1,
        target_ref="SH01",
        semantic_instruction="Maya reacts",
        compiler_version="m4-prompt-planner-v1",
        method_decision_ref="MD:SH01",
        subject_intent="Maya close up",
        composition_intent="close-up",
        camera_intent="locked",
        timing_intent="4s",
        reference_requirements=list(references),
        visual_identity_constraints=["hairstyle=short black bob(LOCKED)"],
        required_controls=list(controls),
        negative_constraints=["no watermark"],
    )


def _descriptor(
    *, adapter_id: str = "adapter:x", features=("IMAGE_OUTPUT", "CHARACTER_REFERENCE")
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id="cap:a",
        adapter_id=adapter_id,
        provider_id="provider-x",
        execution_type=ExecutionType.API,
        supported_methods=[ProductionMethod.GENERATED_IMAGE],
        typed_features=list(features),
        descriptor_source="static",
        descriptor_version="cat-v1",
        provenance=_NOW_PROV,
    )


def _decision(*, adapter_id: str = "adapter:x") -> ExecutionDecision:
    return ExecutionDecision(
        id="ED:SH01:cap:a:abc",
        target_ref="SH01",
        method_decision_ref="MD:SH01",
        prompt_plan_ref="PP:SH01",
        capability_resolution_ref="req-hash",
        adapter_id=adapter_id,
        provider_id="provider-x",
        model_or_tool_id="cap:a",
        execution_type=ExecutionType.API,
        capability_descriptor_version="cat-v1",
        observation_snapshot_ref="obs-1",
        execution_identity_stability=ExecutionIdentityStability.IMMUTABLE_REVISION,
        request_semantics_hash="r" * 16,
        selection_policy_version="sel-v1",
        provenance=_NOW_PROV,
    )


def _compiler(*descriptors: CapabilityDescriptor) -> DefaultPromptCompiler:
    return DefaultPromptCompiler.for_descriptors(descriptors or (_descriptor(),))


def test_compiles_plan_to_provider_request_without_dropping_semantics() -> None:
    request = _compiler().compile(plan=_plan(), decision=_decision())
    assert request.provider == "provider-x"
    assert request.model == "cap:a"
    assert request.prompt_plan_ref == "PP:SH01"
    payload = request.payload
    assert "narration" in payload["controls"]
    assert "hairstyle" in payload["references"]
    assert payload["instruction"] == "Maya reacts"


def test_unknown_adapter_fails_closed() -> None:
    with pytest.raises(PromptCompilationIncompatible) as excinfo:
        _compiler(_descriptor(adapter_id="adapter:x")).compile(
            plan=_plan(), decision=_decision(adapter_id="adapter:not-registered")
        )
    assert "COMPILATION_INCOMPATIBLE" in excinfo.value.reason_codes
    assert any(r.startswith("UNKNOWN_ADAPTER:") for r in excinfo.value.reason_codes)


def test_candidate_without_character_reference_cannot_compile_an_identity_ref() -> None:
    descriptor = _descriptor(features=("IMAGE_OUTPUT",))  # no CHARACTER_REFERENCE
    with pytest.raises(PromptCompilationIncompatible) as excinfo:
        _compiler(descriptor).compile(plan=_plan(references=("hairstyle",)), decision=_decision())
    assert any(r == "UNSUPPORTED_REFERENCE:hairstyle" for r in excinfo.value.reason_codes)


def test_candidate_with_character_reference_compiles_the_identity_ref() -> None:
    request = _compiler(_descriptor(features=("IMAGE_OUTPUT", "CHARACTER_REFERENCE"))).compile(
        plan=_plan(references=("hairstyle",)), decision=_decision()
    )
    assert "hairstyle" in request.payload["references"]


def test_unsupported_required_control_fails_closed() -> None:
    with pytest.raises(PromptCompilationIncompatible) as excinfo:
        _compiler().compile(plan=_plan(controls=("narration", "UNMAPPABLE_CONTROL")), decision=_decision())
    assert "COMPILATION_INCOMPATIBLE" in excinfo.value.reason_codes
    assert "UNSUPPORTED_CONTROL:UNMAPPABLE_CONTROL" in excinfo.value.reason_codes


def test_each_adapter_gets_its_own_endpoint() -> None:
    compiler = _compiler(_descriptor(adapter_id="adapter:x"), _descriptor(adapter_id="adapter:y"))
    ep_x = compiler.compile(plan=_plan(), decision=_decision(adapter_id="adapter:x")).endpoint
    ep_y = compiler.compile(plan=_plan(), decision=_decision(adapter_id="adapter:y")).endpoint
    assert ep_x != ep_y
    assert "adapter:x" in ep_x
    assert "adapter:y" in ep_y


def test_profile_from_descriptor_keeps_the_fail_closed_contract() -> None:
    profile = AdapterCompileProfile.from_descriptor(_descriptor(features=("IMAGE_OUTPUT",)))
    assert "hairstyle" not in profile.supported_reference_kinds
    assert "narration" in profile.supported_controls


def test_provider_identity_comes_only_from_the_execution_decision() -> None:
    request = _compiler().compile(plan=_plan(), decision=_decision())
    assert request.provider == _decision().provider_id
    assert request.model == _decision().model_or_tool_id
    assert "provider" not in set(PromptPlan.model_fields)


def test_compiler_module_does_not_import_the_method_router() -> None:
    from pathlib import Path

    source = Path(DefaultPromptCompiler.__module__.replace(".", "/") + ".py")
    text = (Path(__file__).resolve().parents[4] / source).read_text(encoding="utf-8")
    assert "method_router" not in text


def test_compilation_is_deterministic() -> None:
    a = _compiler().compile(plan=_plan(), decision=_decision())
    b = _compiler().compile(plan=_plan(), decision=_decision())
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
