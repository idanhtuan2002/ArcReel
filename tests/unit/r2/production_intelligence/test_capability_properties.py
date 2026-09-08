"""D07/D11-L2 — property invariants for capability resolution (Hypothesis)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from r2.contracts import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityObservation,
    ExecutionType,
    MethodDecision,
    ProductionMethod,
    Provenance,
    ProvenanceActor,
)
from r2.production_intelligence.capability_registry import (
    CapabilityMatcher,
    CapabilityRegistry,
    CapabilityRequirementBuilder,
    default_freshness_policy,
)

_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
_METHOD = ProductionMethod.GENERATED_IMAGE
_HARD = ["CHARACTER_REFERENCE"]
_FEATURE_POOL = ["CHARACTER_REFERENCE", "STYLE_REFERENCE", "STRUCTURE_REFERENCE"]


def _prov() -> Provenance:
    return Provenance(created_by=ProvenanceActor.SYSTEM, created_at=_NOW)


_cap_ids = st.builds(lambda n: f"cap:{n}", st.integers(min_value=0, max_value=40))


@st.composite
def _descriptor(draw) -> CapabilityDescriptor:
    cap_id = draw(_cap_ids)
    supports_method = draw(st.booleans())
    return CapabilityDescriptor(
        capability_id=cap_id,
        adapter_id=f"adapter:{cap_id}",
        provider_id=f"provider:{cap_id}",
        execution_type=draw(st.sampled_from(list(ExecutionType))),
        supported_methods=[_METHOD] if supports_method else [ProductionMethod.GENERATED_VIDEO],
        typed_features=draw(st.lists(st.sampled_from(_FEATURE_POOL), unique=True, max_size=3)),
        descriptor_source="static",
        descriptor_version="v1",
        provenance=_prov(),
    )


@st.composite
def _observation(draw, cap_id: str) -> CapabilityObservation:
    return CapabilityObservation(
        capability_id=cap_id,
        observation_class="HARD_DYNAMIC_AVAILABILITY",
        availability=draw(st.sampled_from(list(CapabilityAvailability))),
        observed_at=_NOW - timedelta(seconds=draw(st.floats(min_value=0.0, max_value=90.0))),
        observation_version=f"{cap_id}-obs",
    )


@st.composite
def _scenario(draw):
    descriptors = draw(st.lists(_descriptor(), min_size=1, max_size=6, unique_by=lambda d: d.capability_id))
    observations = [draw(_observation(d.capability_id)) for d in descriptors if draw(st.booleans())]
    return descriptors, observations


def _requirements():
    return CapabilityRequirementBuilder().build_from_features(
        target_ref="SH01", method=_METHOD, hard_features=_HARD, soft_features=[]
    )


def _resolve(descriptors, observations):
    registry = CapabilityRegistry(descriptors=descriptors, observations=observations, registry_version="reg-v1")
    return CapabilityMatcher().resolve(
        requirements=_requirements(),
        registry=registry,
        freshness_policy=default_freshness_policy(created_at=_NOW),
        now=_NOW,
    )


@settings(max_examples=150, deadline=None)
@given(_scenario())
def test_every_eligible_candidate_satisfies_every_hard_requirement(scenario) -> None:
    descriptors, observations = scenario
    res = _resolve(descriptors, observations)
    by_id = {d.capability_id: d for d in descriptors}
    obs_by_id = {o.capability_id: o for o in observations}
    for cap_id in res.eligible_candidates:
        descriptor = by_id[cap_id]
        assert _METHOD in descriptor.supported_methods
        assert set(_HARD) <= set(descriptor.typed_features)
        assert cap_id in obs_by_id
        assert obs_by_id[cap_id].availability is CapabilityAvailability.AVAILABLE


@settings(max_examples=100, deadline=None)
@given(_scenario())
def test_adding_a_strictly_ineligible_descriptor_cannot_change_the_winner(scenario) -> None:
    descriptors, observations = scenario
    base = _resolve(descriptors, observations)

    junk = CapabilityDescriptor(
        capability_id="cap:junk-999",
        adapter_id="adapter:junk",
        provider_id="provider:junk",
        execution_type=ExecutionType.API,
        supported_methods=[ProductionMethod.GENERATED_VIDEO],  # wrong method -> always ineligible
        typed_features=[],
        descriptor_source="static",
        descriptor_version="v1",
        provenance=_prov(),
    )
    widened = _resolve([*descriptors, junk], observations)
    assert widened.eligible_candidates == base.eligible_candidates


@settings(max_examples=80, deadline=None)
@given(_scenario())
def test_resolution_never_mutates_the_method_decision(scenario) -> None:
    descriptors, observations = scenario
    decision = MethodDecision(
        id="MD:SH01",
        target_ref="SH01",
        method=_METHOD,
        rationale="fixed",
        cost_class="MEDIUM",
        quality_tier=0,
    )
    before = decision.model_dump(mode="json")
    _resolve(descriptors, observations)
    assert decision.model_dump(mode="json") == before


@settings(max_examples=120, deadline=None)
@given(_scenario(), st.randoms())
def test_input_ordering_does_not_change_the_deterministic_result(scenario, rng) -> None:
    descriptors, observations = scenario
    shuffled_d = list(descriptors)
    shuffled_o = list(observations)
    rng.shuffle(shuffled_d)
    rng.shuffle(shuffled_o)
    a = _resolve(descriptors, observations)
    b = _resolve(shuffled_d, shuffled_o)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")
