import pytest
from pydantic import ValidationError

from r2.contracts import (
    MethodDecision,
    ProductionMethod,
    PromptPlan,
    ProviderRequest,
)


def _provider_request(**overrides):
    values = {
        "id": "REQ-SH042-1",
        "method_decision_ref": "MD-SH042",
        "prompt_plan_ref": "PP-SH042",
        "provider": "seedance",
        "model": "seedance-2.5",
        "endpoint": "i2v",
        "payload": {"prompt": "hello", "refs": ["asset:1"]},
        "execution_options": {"seed": 42, "resolution": "1080p"},
        "adapter_version": "seedance-adapter-v2",
    }
    values.update(overrides)
    return ProviderRequest(**values)


def test_method_decision_is_provider_neutral():
    decision = MethodDecision(
        id="MD-SH042",
        target_ref="SH042",
        method=ProductionMethod.GENERATED_VIDEO,
        rationale="Continuity requires motion",
        capability_requirements=["i2v", "reference-image"],
        cost_class="MEDIUM",
        quality_tier=3,
        fallback_methods=[
            ProductionMethod.GENERATED_IMAGE,
            ProductionMethod.REUSE,
        ],
    )
    with pytest.raises(ValidationError):
        MethodDecision.model_validate({**decision.model_dump(), "provider": "seedance"})


def test_prompt_plan_is_provider_neutral():
    plan = PromptPlan(
        id="PP-SH042",
        schema_version="2.1",
        version=1,
        target_ref="SH042",
        semantic_instruction="Maya reacts to the reveal",
        positive_prompt="close-up reaction",
        negative_prompt="identity drift",
        identity_tokens=["maya-v3"],
        style_tokens=["noir", "soft-key"],
        reference_binding_ids=["B001"],
        exclusions=["extra fingers"],
        compiler_version="butterfly-compiler-v1",
    )
    with pytest.raises(ValidationError):
        PromptPlan.model_validate({**plan.model_dump(), "endpoint": "https://example.invalid"})


def test_provider_request_accepts_execution_fields_and_rejects_python_objects():
    request = _provider_request()
    assert request.provider == "seedance"

    class NotJSON:
        pass

    with pytest.raises(ValidationError, match="JSON-compatible"):
        ProviderRequest(
            **{
                **request.model_dump(),
                "payload": {"bad": NotJSON()},
            }
        )


def test_provider_request_requires_exactly_one_origin_ref():
    with pytest.raises(ValidationError, match="exactly one origin"):
        _provider_request(method_decision_ref=None)

    with pytest.raises(ValidationError, match="exactly one origin"):
        _provider_request(host_task_ref="task-1")


def test_provider_request_serializes_only_the_selected_origin_ref():
    m4_dump = _provider_request().model_dump(mode="json")
    assert m4_dump["method_decision_ref"] == "MD-SH042"
    assert "host_task_ref" not in m4_dump

    host_dump = _provider_request(method_decision_ref=None, host_task_ref="task-1").model_dump(mode="json")
    assert host_dump["host_task_ref"] == "task-1"
    assert "method_decision_ref" not in host_dump


def test_provider_request_rejects_non_finite_execution_values():
    with pytest.raises(ValidationError, match="finite"):
        ProviderRequest(
            id="REQ-SH042-2",
            method_decision_ref="MD-SH042",
            provider="seedance",
            model="seedance-2.5",
            endpoint="i2v",
            payload={"prompt": "hello"},
            execution_options={"cfg": float("nan")},
            adapter_version="seedance-adapter-v2",
        )
