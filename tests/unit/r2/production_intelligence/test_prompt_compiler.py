"""D08 — provider-specific PromptCompiler translation below the semantic boundary."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.contracts import (
    ExecutionDecision,
    ExecutionIdentityStability,
    ExecutionType,
    PromptPlan,
    Provenance,
    ProvenanceActor,
)
from r2.production_intelligence.prompting import (
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


def _decision() -> ExecutionDecision:
    return ExecutionDecision(
        id="ED:SH01:cap:a:abc",
        target_ref="SH01",
        method_decision_ref="MD:SH01",
        prompt_plan_ref="PP:SH01",
        capability_resolution_ref="req-hash",
        adapter_id="adapter:x",
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


def test_compiles_plan_to_provider_request_without_dropping_semantics() -> None:
    request = DefaultPromptCompiler().compile(plan=_plan(), decision=_decision())
    assert request.provider == "provider-x"
    assert request.model == "cap:a"
    assert request.prompt_plan_ref == "PP:SH01"
    payload = request.payload
    assert "narration" in payload["controls"]
    assert "hairstyle" in payload["references"]
    assert payload["instruction"] == "Maya reacts"


def test_unsupported_required_control_fails_closed() -> None:
    with pytest.raises(PromptCompilationIncompatible) as excinfo:
        DefaultPromptCompiler(supported_controls={"narration"}).compile(
            plan=_plan(controls=("narration", "UNMAPPABLE_CONTROL")), decision=_decision()
        )
    assert "COMPILATION_INCOMPATIBLE" in excinfo.value.reason_codes


def test_provider_identity_comes_only_from_the_execution_decision() -> None:
    request = DefaultPromptCompiler().compile(plan=_plan(), decision=_decision())
    assert request.provider == _decision().provider_id
    assert request.model == _decision().model_or_tool_id
    assert "provider" not in set(PromptPlan.model_fields)


def test_compiler_module_does_not_import_the_method_router() -> None:
    from pathlib import Path

    source = Path(DefaultPromptCompiler.__module__.replace(".", "/") + ".py")
    text = (Path(__file__).resolve().parents[4] / source).read_text(encoding="utf-8")
    assert "method_router" not in text


def test_compilation_is_deterministic() -> None:
    a = DefaultPromptCompiler().compile(plan=_plan(), decision=_decision())
    b = DefaultPromptCompiler().compile(plan=_plan(), decision=_decision())
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
