"""D08 — provider-neutral PromptPlan construction."""

from __future__ import annotations

import json

import pytest

from r2.contracts import (
    ContentBasis,
    ContentBasisType,
    CreativeApprovalStatus,
    IdentityStrength,
    MethodDecision,
    ProductionMethod,
    ResolvedIdentityConstraint,
    ResolvedIdentityStatus,
    ResolvedVisualIdentity,
    ShotSpec,
)
from r2.production_intelligence.prompting import PromptPlanner

FORBIDDEN = {"endpoint", "payload", "provider", "model", "provider_job_id", "submitted_base_url", "api_key"}


def _shot() -> ShotSpec:
    return ShotSpec(
        id="SH01",
        schema_version="1",
        version=1,
        scene_id="SC01",
        content_basis=ContentBasis(basis_type=ContentBasisType.FACTUAL, basis_version="v1", refs=["research:RP-1"]),
        purpose="Maya reacts to the reveal",
        target_duration=4.0,
        framing="close-up",
        camera="locked",
        audio_intent="narration",
        required_reference_roles=["CHARACTER"],
        allowed_methods=["GENERATED_VIDEO"],
        quality_tier=2,
        approval_status=CreativeApprovalStatus.APPROVED,
    )


def _method() -> MethodDecision:
    return MethodDecision(
        id="MD:SH01",
        target_ref="SH01",
        method=ProductionMethod.GENERATED_VIDEO,
        rationale="motion needed",
        cost_class="HIGH",
        quality_tier=2,
    )


def _identity() -> ResolvedVisualIdentity:
    return ResolvedVisualIdentity(
        target_ref="SH01",
        status=ResolvedIdentityStatus.RESOLVED,
        resolved_constraints=[
            ResolvedIdentityConstraint(
                semantic_key="hairstyle",
                effective_strength=IdentityStrength.LOCKED,
                effective_value="short black bob",
                source_scope_ref="SC01",
            )
        ],
        resolution_policy_version="identity-v1",
    )


def test_prompt_plan_is_provider_neutral_and_semantic() -> None:
    plan = PromptPlanner().build(shot=_shot(), method_decision=_method(), identity=_identity())
    dump = plan.model_dump(mode="json")
    assert set(dump).isdisjoint(FORBIDDEN)
    assert plan.method_decision_ref == "MD:SH01"
    assert plan.target_ref == "SH01"
    assert plan.semantic_instruction
    assert any("hairstyle" in c for c in plan.visual_identity_constraints)


def test_prompt_plan_round_trips() -> None:
    plan = PromptPlanner().build(shot=_shot(), method_decision=_method(), identity=_identity())
    raw = json.dumps(plan.model_dump(mode="json"), sort_keys=True)
    from r2.contracts import PromptPlan

    assert PromptPlan.model_validate(json.loads(raw)) == plan


def test_prompt_plan_is_deterministic() -> None:
    a = PromptPlanner().build(shot=_shot(), method_decision=_method(), identity=_identity())
    b = PromptPlanner().build(shot=_shot(), method_decision=_method(), identity=_identity())
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
