"""D07 — capability descriptor/observation separation, UNKNOWN handling, freshness."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from r2.contracts import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityFeatureSupport,
    CapabilityObservation,
    CapabilitySupport,
    ExecutionType,
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


def _prov() -> Provenance:
    return Provenance(created_by=ProvenanceActor.SYSTEM, created_at=_NOW)


def _descriptor(
    cap_id: str,
    *,
    methods: list[ProductionMethod],
    features: list[str],
    execution_type: ExecutionType = ExecutionType.API,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=cap_id,
        adapter_id=f"adapter:{cap_id}",
        provider_id=f"provider:{cap_id}",
        execution_type=execution_type,
        supported_methods=methods,
        typed_features=features,
        descriptor_source="static-catalog",
        descriptor_version="cat-v1",
        provenance=_prov(),
    )


def _availability(
    cap_id: str,
    *,
    availability=CapabilityAvailability.AVAILABLE,
    age_seconds: float = 1.0,
    credentials_ready: bool | None = True,
    endpoint_healthy: bool | None = True,
    runtime_dependencies_ready: bool | None = True,
):
    return CapabilityObservation(
        capability_id=cap_id,
        observation_class="HARD_DYNAMIC_AVAILABILITY",
        availability=availability,
        credentials_ready=credentials_ready,
        endpoint_healthy=endpoint_healthy,
        runtime_dependencies_ready=runtime_dependencies_ready,
        observed_at=_NOW - timedelta(seconds=age_seconds),
        observation_version=f"{cap_id}-avail",
    )


def _feature_obs(cap_id: str, feature: str, support: CapabilitySupport, *, age_seconds: float = 1.0):
    return CapabilityObservation(
        capability_id=cap_id,
        observation_class="HARD_DYNAMIC_AVAILABILITY",
        availability=CapabilityAvailability.AVAILABLE,
        credentials_ready=True,
        endpoint_healthy=True,
        runtime_dependencies_ready=True,
        feature_support=[CapabilityFeatureSupport(feature_key=feature, support=support)],
        observed_at=_NOW - timedelta(seconds=age_seconds),
        observation_version=f"{cap_id}-feat",
    )


def _requirements(hard: list[str], method: ProductionMethod = ProductionMethod.GENERATED_IMAGE):
    return CapabilityRequirementBuilder().build_from_features(
        target_ref="SH01", method=method, hard_features=hard, soft_features=[]
    )


def _resolve(descriptors, observations, hard):
    registry = CapabilityRegistry(descriptors=descriptors, observations=observations, registry_version="reg-v1")
    return CapabilityMatcher().resolve(
        requirements=_requirements(hard),
        registry=registry,
        freshness_policy=default_freshness_policy(created_at=_NOW),
        now=_NOW,
    )


def test_supported_hard_feature_makes_candidate_eligible() -> None:
    res = _resolve(
        [_descriptor("cap:a", methods=[ProductionMethod.GENERATED_IMAGE], features=["CHARACTER_REFERENCE"])],
        [_availability("cap:a")],
        ["CHARACTER_REFERENCE"],
    )
    assert res.eligible_candidates == ["cap:a"]
    assert res.unknown_candidates == []


def test_unsupported_hard_feature_rejects_candidate() -> None:
    res = _resolve(
        [_descriptor("cap:a", methods=[ProductionMethod.GENERATED_IMAGE], features=[])],
        [
            _availability("cap:a"),
            _feature_obs("cap:a", "CHARACTER_REFERENCE", CapabilitySupport.UNSUPPORTED),
        ],
        ["CHARACTER_REFERENCE"],
    )
    assert res.eligible_candidates == []
    assert any(r.candidate == "cap:a" for r in res.rejected_candidates)


def test_unknown_hard_feature_is_ineligible_with_capability_unknown() -> None:
    res = _resolve(
        [_descriptor("cap:a", methods=[ProductionMethod.GENERATED_IMAGE], features=[])],
        [_availability("cap:a")],
        ["CHARACTER_REFERENCE"],
    )
    assert res.eligible_candidates == []
    assert res.unknown_candidates == ["cap:a"]
    reasons = [r for r in res.rejected_candidates if r.candidate == "cap:a"]
    assert reasons
    assert "CAPABILITY_UNKNOWN" in reasons[0].reasons


def test_method_not_supported_rejects_candidate() -> None:
    res = _resolve(
        [_descriptor("cap:a", methods=[ProductionMethod.GENERATED_VIDEO], features=["CHARACTER_REFERENCE"])],
        [_availability("cap:a")],
        ["CHARACTER_REFERENCE"],
    )
    assert res.eligible_candidates == []
    assert any(r.candidate == "cap:a" and "METHOD_UNSUPPORTED" in r.reasons for r in res.rejected_candidates)


def test_stale_hard_availability_observation_becomes_unknown() -> None:
    res = _resolve(
        [_descriptor("cap:a", methods=[ProductionMethod.GENERATED_IMAGE], features=["CHARACTER_REFERENCE"])],
        [_availability("cap:a", age_seconds=31)],  # HARD_DYNAMIC_AVAILABILITY max_age = 30
        ["CHARACTER_REFERENCE"],
    )
    assert res.eligible_candidates == []
    assert res.unknown_candidates == ["cap:a"]


def test_stale_resource_fit_observation_becomes_unknown() -> None:
    obs = [
        _availability("cap:a"),
        CapabilityObservation(
            capability_id="cap:a",
            observation_class="HARD_DYNAMIC_RESOURCE_FIT",
            availability=CapabilityAvailability.AVAILABLE,
            resource_fit=True,
            observed_at=_NOW - timedelta(seconds=6),  # max_age = 5
            observation_version="cap:a-vram",
        ),
    ]
    res = _resolve(
        [
            _descriptor(
                "cap:a",
                methods=[ProductionMethod.GENERATED_IMAGE],
                features=["CHARACTER_REFERENCE"],
                execution_type=ExecutionType.LOCAL_GPU,
            )
        ],
        obs,
        ["CHARACTER_REFERENCE"],
    )
    assert res.unknown_candidates == ["cap:a"]


def test_stale_quota_observation_becomes_unknown() -> None:
    obs = [
        _availability("cap:a"),
        CapabilityObservation(
            capability_id="cap:a",
            observation_class="HARD_DYNAMIC_QUOTA",
            availability=CapabilityAvailability.AVAILABLE,
            quota_state="OK",
            observed_at=_NOW - timedelta(seconds=16),  # max_age = 15
            observation_version="cap:a-quota",
        ),
    ]
    res = _resolve(
        [_descriptor("cap:a", methods=[ProductionMethod.GENERATED_IMAGE], features=["CHARACTER_REFERENCE"])],
        obs,
        ["CHARACTER_REFERENCE"],
    )
    assert res.unknown_candidates == ["cap:a"]


def test_fresh_soft_latency_observation_does_not_block() -> None:
    obs = [
        _availability("cap:a"),
        CapabilityObservation(
            capability_id="cap:a",
            observation_class="SOFT_DYNAMIC_LATENCY",
            availability=CapabilityAvailability.AVAILABLE,
            estimated_latency_ms=800,
            observed_at=_NOW - timedelta(seconds=120),  # max_age = 300 -> still current
            observation_version="cap:a-lat",
        ),
    ]
    res = _resolve(
        [_descriptor("cap:a", methods=[ProductionMethod.GENERATED_IMAGE], features=["CHARACTER_REFERENCE"])],
        obs,
        ["CHARACTER_REFERENCE"],
    )
    assert res.eligible_candidates == ["cap:a"]


def test_no_availability_observation_is_unknown_not_available() -> None:
    res = _resolve(
        [_descriptor("cap:a", methods=[ProductionMethod.GENERATED_IMAGE], features=["CHARACTER_REFERENCE"])],
        [],
        ["CHARACTER_REFERENCE"],
    )
    assert res.unknown_candidates == ["cap:a"]


def test_unavailable_observation_rejects_candidate() -> None:
    res = _resolve(
        [_descriptor("cap:a", methods=[ProductionMethod.GENERATED_IMAGE], features=["CHARACTER_REFERENCE"])],
        [_availability("cap:a", availability=CapabilityAvailability.UNAVAILABLE)],
        ["CHARACTER_REFERENCE"],
    )
    assert res.eligible_candidates == []
    assert any(r.candidate == "cap:a" and "UNAVAILABLE" in r.reasons for r in res.rejected_candidates)


def test_eligible_candidates_ranked_local_before_api() -> None:
    res = _resolve(
        [
            _descriptor(
                "cap:api",
                methods=[ProductionMethod.GENERATED_IMAGE],
                features=["CHARACTER_REFERENCE"],
                execution_type=ExecutionType.API,
            ),
            _descriptor(
                "cap:local",
                methods=[ProductionMethod.GENERATED_IMAGE],
                features=["CHARACTER_REFERENCE"],
                execution_type=ExecutionType.LOCAL,
            ),
        ],
        [_availability("cap:api"), _availability("cap:local")],
        ["CHARACTER_REFERENCE"],
    )
    assert res.eligible_candidates == ["cap:local", "cap:api"]


@pytest.mark.parametrize(
    ("predicate", "reason"),
    [
        ("credentials_ready", "CREDENTIALS_NOT_READY"),
        ("endpoint_healthy", "ENDPOINT_UNHEALTHY"),
        ("runtime_dependencies_ready", "RUNTIME_DEPENDENCIES_NOT_READY"),
    ],
)
def test_a_false_hard_dynamic_predicate_rejects_the_candidate(predicate: str, reason: str) -> None:
    res = _resolve(
        [_descriptor("cap:a", methods=[ProductionMethod.GENERATED_IMAGE], features=["CHARACTER_REFERENCE"])],
        [_availability("cap:a", **{predicate: False})],
        ["CHARACTER_REFERENCE"],
    )
    assert res.eligible_candidates == []
    assert any(r.candidate == "cap:a" and reason in r.reasons for r in res.rejected_candidates)


@pytest.mark.parametrize("predicate", ["credentials_ready", "endpoint_healthy", "runtime_dependencies_ready"])
def test_an_unobserved_hard_dynamic_predicate_makes_the_candidate_unknown(predicate: str) -> None:
    res = _resolve(
        [_descriptor("cap:a", methods=[ProductionMethod.GENERATED_IMAGE], features=["CHARACTER_REFERENCE"])],
        [_availability("cap:a", **{predicate: None})],
        ["CHARACTER_REFERENCE"],
    )
    assert res.eligible_candidates == []
    assert res.unknown_candidates == ["cap:a"]


def test_required_execution_types_excludes_a_disallowed_execution_type() -> None:
    requirements = CapabilityRequirementBuilder().build_from_features(
        target_ref="SH01",
        method=ProductionMethod.GENERATED_IMAGE,
        hard_features=["CHARACTER_REFERENCE"],
        soft_features=[],
    )
    requirements = requirements.model_copy(update={"required_execution_types": [ExecutionType.LOCAL]})
    registry = CapabilityRegistry(
        descriptors=[
            _descriptor(
                "cap:api",
                methods=[ProductionMethod.GENERATED_IMAGE],
                features=["CHARACTER_REFERENCE"],
                execution_type=ExecutionType.API,
            )
        ],
        observations=[_availability("cap:api")],
        registry_version="reg-v1",
    )
    res = CapabilityMatcher().resolve(
        requirements=requirements,
        registry=registry,
        freshness_policy=default_freshness_policy(created_at=_NOW),
        now=_NOW,
    )
    assert res.eligible_candidates == []
    assert any(r.candidate == "cap:api" and "EXECUTION_TYPE_DISALLOWED" in r.reasons for r in res.rejected_candidates)


def test_required_execution_types_admits_a_matching_execution_type() -> None:
    requirements = CapabilityRequirementBuilder().build_from_features(
        target_ref="SH01",
        method=ProductionMethod.GENERATED_IMAGE,
        hard_features=["CHARACTER_REFERENCE"],
        soft_features=[],
    )
    requirements = requirements.model_copy(update={"required_execution_types": [ExecutionType.LOCAL]})
    registry = CapabilityRegistry(
        descriptors=[
            _descriptor(
                "cap:local",
                methods=[ProductionMethod.GENERATED_IMAGE],
                features=["CHARACTER_REFERENCE"],
                execution_type=ExecutionType.LOCAL,
            )
        ],
        observations=[_availability("cap:local")],
        registry_version="reg-v1",
    )
    res = CapabilityMatcher().resolve(
        requirements=requirements,
        registry=registry,
        freshness_policy=default_freshness_policy(created_at=_NOW),
        now=_NOW,
    )
    assert res.eligible_candidates == ["cap:local"]


def test_freshness_policy_constants_match_global_constraints() -> None:
    policy = default_freshness_policy(created_at=_NOW)
    rules = {r.observation_class: r for r in policy.rules}
    assert rules["HARD_DYNAMIC_AVAILABILITY"].max_age_seconds == 30
    assert rules["HARD_DYNAMIC_RESOURCE_FIT"].max_age_seconds == 5
    assert rules["HARD_DYNAMIC_QUOTA"].max_age_seconds == 15
    assert rules["SOFT_DYNAMIC_LATENCY"].max_age_seconds == 300
    assert rules["SOFT_DYNAMIC_COST"].max_age_seconds == 60
    assert rules["HARD_DYNAMIC_AVAILABILITY"].revalidate_on_admission is True
    assert rules["SOFT_DYNAMIC_LATENCY"].revalidate_on_admission is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
