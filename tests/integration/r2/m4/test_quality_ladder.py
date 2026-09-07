"""Quality Ladder — the MethodDecision is authoritative and tier-independent.

For a generative shot, escalating the execution tier (local / cheap-cloud /
premium-cloud) re-runs Gate 2 and moves the ExecutionDecision, its
execution_fingerprint and the budget path, while the MethodDecision, the content
fingerprint and the LOCKED visual-identity constraints stay fixed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from r2.contracts import (
    AdmissionOutcome,
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityObservation,
    ExecutionType,
    IdentityStrength,
    compute_content_fingerprint,
    compute_execution_fingerprint,
)
from r2.production_intelligence.admission import GenerationAdmissionService, HardDynamicRevalidation
from r2.production_intelligence.capability_registry import (
    CapabilityMatcher,
    CapabilityRegistry,
    CapabilityRequirementBuilder,
    default_freshness_policy,
)
from r2.production_intelligence.execution import ExecutionDecisionService
from r2.production_intelligence.identity import VisualIdentityResolver
from r2.production_intelligence.prompting import DefaultPromptCompiler
from scripts.r2.run_m4_golden_12 import _FakeBudgetPort

_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)

# (label, execution type, provider, paid, cost)
_TIERS = [
    ("local", ExecutionType.LOCAL_GPU, "local-gpu", False, None),
    ("cheap_cloud", ExecutionType.API, "cheap-cloud", True, Decimal("1.00")),
    ("premium_cloud", ExecutionType.API, "premium-cloud", True, Decimal("6.00")),
]


async def _always_fresh(_capability_id: str) -> HardDynamicRevalidation:
    return HardDynamicRevalidation(ok=True)


def _tier_descriptor(case, label: str, execution_type: ExecutionType, provider: str) -> CapabilityDescriptor:
    return case.descriptor.model_copy(
        update={
            "capability_id": f"cap:{case.shot.id.lower()}-{label}",
            "adapter_id": f"adapter:{case.shot.id.lower()}-{label}",
            "provider_id": provider,
            "execution_type": execution_type,
        }
    )


def _tier_observation(descriptor: CapabilityDescriptor) -> CapabilityObservation:
    return CapabilityObservation(
        capability_id=descriptor.capability_id,
        observation_class="HARD_DYNAMIC_AVAILABILITY",
        availability=CapabilityAvailability.AVAILABLE,
        credentials_ready=True,
        endpoint_healthy=True,
        runtime_dependencies_ready=True,
        observed_at=_NOW,
        observation_version=f"{descriptor.capability_id}-obs",
    )


@pytest.mark.parametrize("shot_id", ["SH05", "SH06", "SH07"])
async def test_method_decision_is_stable_while_execution_moves_across_the_quality_ladder(
    golden_12, pipeline, shot_id: str
) -> None:
    case = golden_12.by_id(shot_id)
    result = await pipeline(case)
    assert result.method_decision is not None

    resolved_identity = VisualIdentityResolver().resolve(
        target_ref=case.shot.id,
        scope_ancestry=case.scope_ancestry,
        profiles=list(case.identity_profiles),
    )
    requirements = CapabilityRequirementBuilder().build(
        method_decision=result.method_decision, identity=resolved_identity, shot=case.shot
    )
    locked_identity = sorted(
        (c.semantic_key, c.effective_value)
        for c in resolved_identity.resolved_constraints
        if c.effective_strength is IdentityStrength.LOCKED
    )
    content_fp = compute_content_fingerprint(
        shot_spec=case.shot,
        bindings=list(case.bindings),
        visual_identity_refs=[c.semantic_key for c in resolved_identity.resolved_constraints],
        approved_source_asset_refs=[],
    )

    method_ids: set[tuple] = set()
    execution_ids: set[str] = set()
    fingerprints: set[str] = set()
    reserved_by_tier: dict[str, bool] = {}

    for label, execution_type, provider, paid, cost in _TIERS:
        descriptor = _tier_descriptor(case, label, execution_type, provider)
        registry = CapabilityRegistry(
            descriptors=[descriptor],
            observations=[_tier_observation(descriptor)],
            registry_version=f"reg-{label}",
        )
        resolution = CapabilityMatcher().resolve(
            requirements=requirements,
            registry=registry,
            freshness_policy=default_freshness_policy(created_at=_NOW),
            now=_NOW,
        )
        assert resolution.eligible_candidates == [descriptor.capability_id]

        # Each tier is a fresh Gate-2 evaluation for that candidate.
        admission = await GenerationAdmissionService(budget_port=_FakeBudgetPort()).evaluate(
            readiness=result.readiness,
            method_decision=result.method_decision,
            capability_resolution=resolution,
            prompt_plan=result.prompt_plan,
            budget_scope_ref=f"scope:{case.shot.id}:{label}" if paid else None,
            budget_amount=cost,
            budget_currency="USD" if paid else None,
            approval_ref=f"APPROVAL:{case.shot.id}" if case.requires_approval else None,
            now=_NOW,
            revalidate=_always_fresh,
            selected_capability_id=descriptor.capability_id,
            requires_approval=case.requires_approval,
        )
        assert admission.outcome is AdmissionOutcome.ADMITTED
        assert admission.selected_capability_id == descriptor.capability_id
        reserved_by_tier[label] = admission.budget_reservation_ref is not None

        execution_decision = ExecutionDecisionService().create(
            admission=admission,
            capability_resolution=resolution,
            prompt_plan=result.prompt_plan,
            selected_capability_id=descriptor.capability_id,
            descriptor=descriptor,
        )
        request = DefaultPromptCompiler.for_descriptors([descriptor]).compile(
            plan=result.prompt_plan, decision=execution_decision
        )
        fingerprint = compute_execution_fingerprint(
            provider=request.provider,
            model=request.model,
            endpoint=request.endpoint,
            seed=None,
            resolution=None,
            generation_settings={},
            prompt_compiler_version="m4-prompt-compiler-v1",
            provider_adapter_version=request.adapter_version,
        )

        # The content fingerprint and the LOCKED identity are tier-invariant.
        assert (
            compute_content_fingerprint(
                shot_spec=case.shot,
                bindings=list(case.bindings),
                visual_identity_refs=[c.semantic_key for c in resolved_identity.resolved_constraints],
                approved_source_asset_refs=[],
            )
            == content_fp
        )
        assert (
            sorted(
                (c.semantic_key, c.effective_value)
                for c in resolved_identity.resolved_constraints
                if c.effective_strength is IdentityStrength.LOCKED
            )
            == locked_identity
        )

        method_ids.add((result.method_decision.method, result.method_decision.id))
        execution_ids.add(execution_decision.id)
        fingerprints.add(fingerprint)

    # Method authority never moved; every execution-side identity did.
    assert method_ids == {(case.method, result.method_decision.id)}
    assert len(execution_ids) == len(_TIERS)
    assert len(fingerprints) == len(_TIERS)
    # The budget/approval path escalates: the local tier reserves nothing, the
    # cloud tiers each take a reservation.
    assert reserved_by_tier == {"local": False, "cheap_cloud": True, "premium_cloud": True}
