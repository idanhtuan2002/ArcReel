"""High-4 / C05 §17.3.1 — the Quality Ladder.

For a generative shot the MethodDecision is authoritative and tier-independent:
swapping the execution tier (local / cheap-cloud / premium-cloud) must leave the
MethodDecision untouched while moving the ExecutionDecision and its
execution_fingerprint.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.contracts import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityObservation,
    ExecutionType,
    compute_execution_fingerprint,
)
from r2.production_intelligence.capability_registry import (
    CapabilityMatcher,
    CapabilityRegistry,
    CapabilityRequirementBuilder,
    default_freshness_policy,
)
from r2.production_intelligence.execution import ExecutionDecisionService
from r2.production_intelligence.identity import VisualIdentityResolver
from r2.production_intelligence.prompting import DefaultPromptCompiler

_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)

# (tier label, execution type, provider)
_TIERS = [
    ("local", ExecutionType.LOCAL_GPU, "local-gpu"),
    ("cheap_cloud", ExecutionType.API, "cheap-cloud"),
    ("premium_cloud", ExecutionType.API, "premium-cloud"),
]


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
    assert result.admission is not None

    resolved_identity = VisualIdentityResolver().resolve(
        target_ref=case.shot.id,
        scope_ancestry=case.scope_ancestry,
        profiles=list(case.identity_profiles),
    )
    requirements = CapabilityRequirementBuilder().build(
        method_decision=result.method_decision, identity=resolved_identity, shot=case.shot
    )

    method_decisions = set()
    execution_ids = set()
    fingerprints = set()

    for label, execution_type, provider in _TIERS:
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

        execution_decision = ExecutionDecisionService().create(
            admission=result.admission,
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

        method_decisions.add((result.method_decision.method, result.method_decision.id))
        execution_ids.add(execution_decision.id)
        fingerprints.add(fingerprint)

    # Method authority never moved; every execution-side identity did.
    assert method_decisions == {(case.method, result.method_decision.id)}
    assert len(execution_ids) == len(_TIERS)
    assert len(fingerprints) == len(_TIERS)
