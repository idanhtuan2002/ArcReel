"""D07 — one normalized capability subsystem.

Descriptor catalog (what an adapter/model/tool can do) + observation overlay
(whether it can be used now) -> deterministic matcher -> CapabilityResolution.
It is an execution inventory/matcher only: it never rewrites a MethodDecision,
persists artifacts, or routes providers. ``UNKNOWN`` for a hard requirement makes
a candidate ineligible and is never rewritten to ``SUPPORTED``/``UNSUPPORTED``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime

from r2.contracts import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityFreshnessPolicy,
    CapabilityFreshnessRule,
    CapabilityObservation,
    CapabilityRequirements,
    CapabilityResolution,
    CapabilitySupport,
    ExecutionType,
    IdentityStrength,
    MethodDecision,
    ObservationExpiryBehavior,
    ProductionMethod,
    Provenance,
    ProvenanceActor,
    RejectedCapabilityCandidate,
    ResolvedVisualIdentity,
    ShotSpec,
    ensure_json_value,
)
from r2.contracts.fingerprints import canonical_json_bytes

CAPABILITY_REQUIREMENTS_POLICY_VERSION = "m4-capability-requirements-v1"
CAPABILITY_MATCHER_POLICY_VERSION = "m4-capability-matcher-v1"
CAPABILITY_FRESHNESS_POLICY_VERSION = "m4-cap-freshness-v1"

_CLASS_AVAILABILITY = "HARD_DYNAMIC_AVAILABILITY"
_CLASS_RESOURCE_FIT = "HARD_DYNAMIC_RESOURCE_FIT"
_CLASS_QUOTA = "HARD_DYNAMIC_QUOTA"

_METHOD_FEATURE: dict[ProductionMethod, str] = {
    ProductionMethod.REUSE: "ASSET_REUSE",
    ProductionMethod.STOCK: "STOCK_LIBRARY",
    ProductionMethod.SCREEN_CAPTURE: "SCREEN_CAPTURE",
    ProductionMethod.DETERMINISTIC: "DETERMINISTIC_RENDER",
    ProductionMethod.GENERATED_IMAGE: "IMAGE_OUTPUT",
    ProductionMethod.GENERATED_VIDEO: "VIDEO_OUTPUT",
    ProductionMethod.COMPOSITE: "COMPOSITE_ASSEMBLY",
}

_EXEC_RANK: dict[ExecutionType, int] = {
    ExecutionType.LOCAL: 0,
    ExecutionType.LOCAL_GPU: 1,
    ExecutionType.API: 2,
    ExecutionType.HYBRID: 3,
}


def default_freshness_policy(*, created_at: datetime | None = None) -> CapabilityFreshnessPolicy:
    """Concrete Capability Freshness Policy v1 (see plan Global Constraints)."""

    now = created_at or datetime.now(UTC)
    return CapabilityFreshnessPolicy(
        policy_version=CAPABILITY_FRESHNESS_POLICY_VERSION,
        rules=[
            CapabilityFreshnessRule(
                observation_class=_CLASS_AVAILABILITY,
                max_age_seconds=30,
                revalidate_on_admission=True,
                invalidation_triggers=["credential_rotation", "endpoint_restart", "process_restart"],
                expiry_behavior=ObservationExpiryBehavior.BECOME_UNKNOWN,
            ),
            CapabilityFreshnessRule(
                observation_class=_CLASS_RESOURCE_FIT,
                max_age_seconds=5,
                revalidate_on_admission=True,
                invalidation_triggers=["local_resource_change"],
                expiry_behavior=ObservationExpiryBehavior.BECOME_UNKNOWN,
            ),
            CapabilityFreshnessRule(
                observation_class=_CLASS_QUOTA,
                max_age_seconds=15,
                revalidate_on_admission=True,
                invalidation_triggers=["quota_reset"],
                expiry_behavior=ObservationExpiryBehavior.BECOME_UNKNOWN,
            ),
            CapabilityFreshnessRule(
                observation_class="SOFT_DYNAMIC_LATENCY",
                max_age_seconds=300,
                revalidate_on_admission=False,
                invalidation_triggers=[],
                expiry_behavior=ObservationExpiryBehavior.REVALIDATE,
            ),
            CapabilityFreshnessRule(
                observation_class="SOFT_DYNAMIC_COST",
                max_age_seconds=60,
                revalidate_on_admission=False,
                invalidation_triggers=[],
                expiry_behavior=ObservationExpiryBehavior.REVALIDATE,
            ),
        ],
        provenance=Provenance(created_by=ProvenanceActor.SYSTEM, created_at=now),
    )


class CapabilityRequirementBuilder:
    def build(
        self,
        *,
        method_decision: MethodDecision,
        identity: ResolvedVisualIdentity,
        shot: ShotSpec,
    ) -> CapabilityRequirements:
        hard = [_METHOD_FEATURE[method_decision.method]]
        soft: list[str] = []
        for constraint in identity.resolved_constraints:
            if constraint.effective_strength is IdentityStrength.LOCKED:
                if constraint.semantic_key in {"face_master", "hairstyle"}:
                    hard.append("CHARACTER_REFERENCE")
                else:
                    hard.append(f"IDENTITY_LOCK:{constraint.semantic_key}")
            else:
                soft.append(f"IDENTITY_PREF:{constraint.semantic_key}")
        return self.build_from_features(
            target_ref=shot.id, method=method_decision.method, hard_features=hard, soft_features=soft
        )

    def build_from_features(
        self,
        *,
        target_ref: str,
        method: ProductionMethod,
        hard_features: Sequence[str],
        soft_features: Sequence[str],
    ) -> CapabilityRequirements:
        hard = sorted(set(hard_features))
        soft = sorted(set(soft_features))
        digest = hashlib.sha256(
            canonical_json_bytes(ensure_json_value({"method": method.value, "hard": hard, "soft": soft}))
        ).hexdigest()
        return CapabilityRequirements(
            target_ref=target_ref,
            method=method,
            hard_features=hard,
            soft_features=soft,
            requirement_set_hash=digest,
            policy_version=CAPABILITY_REQUIREMENTS_POLICY_VERSION,
        )


class CapabilityRegistry:
    def __init__(
        self,
        *,
        descriptors: Sequence[CapabilityDescriptor],
        observations: Sequence[CapabilityObservation],
        registry_version: str,
    ) -> None:
        self.registry_version = registry_version
        self._descriptors = sorted(descriptors, key=lambda d: d.capability_id)
        self._observations = sorted(
            observations, key=lambda o: (o.capability_id, o.observation_class, o.observation_version)
        )

    @property
    def descriptors(self) -> list[CapabilityDescriptor]:
        return list(self._descriptors)

    def observations_for(self, capability_id: str) -> list[CapabilityObservation]:
        return [o for o in self._observations if o.capability_id == capability_id]

    def observation_snapshot_ref(self) -> str:
        payload = [[o.capability_id, o.observation_class, o.observation_version] for o in self._observations]
        return hashlib.sha256(canonical_json_bytes(ensure_json_value(payload))).hexdigest()[:16]


class CapabilityMatcher:
    def resolve(
        self,
        *,
        requirements: CapabilityRequirements,
        registry: CapabilityRegistry,
        freshness_policy: CapabilityFreshnessPolicy,
        now: datetime,
    ) -> CapabilityResolution:
        rules = {rule.observation_class: rule for rule in freshness_policy.rules}
        eligible: list[tuple[int, str]] = []
        rejected: list[RejectedCapabilityCandidate] = []
        unknown: set[str] = set()

        for descriptor in registry.descriptors:
            cap_id = descriptor.capability_id
            obs_list = registry.observations_for(cap_id)
            obs_by_class: dict[str, CapabilityObservation] = {}
            feature_support: dict[str, CapabilitySupport] = dict.fromkeys(
                descriptor.typed_features, CapabilitySupport.SUPPORTED
            )
            for observation in obs_list:
                obs_by_class[observation.observation_class] = observation
                for entry in observation.feature_support:
                    feature_support[entry.feature_key] = entry.support

            if requirements.method not in descriptor.supported_methods:
                rejected.append(RejectedCapabilityCandidate(candidate=cap_id, reasons=["METHOD_UNSUPPORTED"]))
                continue

            hard_states = [feature_support.get(f, CapabilitySupport.UNKNOWN) for f in requirements.hard_features]
            if CapabilitySupport.UNSUPPORTED in hard_states:
                missing = [
                    f
                    for f in requirements.hard_features
                    if feature_support.get(f, CapabilitySupport.UNKNOWN) is CapabilitySupport.UNSUPPORTED
                ]
                rejected.append(
                    RejectedCapabilityCandidate(candidate=cap_id, reasons=[f"FEATURE_UNSUPPORTED:{f}" for f in missing])
                )
                continue
            if CapabilitySupport.UNKNOWN in hard_states:
                unknown.add(cap_id)
                rejected.append(RejectedCapabilityCandidate(candidate=cap_id, reasons=["CAPABILITY_UNKNOWN"]))
                continue

            availability = obs_by_class.get(_CLASS_AVAILABILITY)
            if availability is None:
                unknown.add(cap_id)
                rejected.append(RejectedCapabilityCandidate(candidate=cap_id, reasons=["NO_AVAILABILITY_PROOF"]))
                continue
            if availability.availability is CapabilityAvailability.UNAVAILABLE:
                rejected.append(RejectedCapabilityCandidate(candidate=cap_id, reasons=["UNAVAILABLE"]))
                continue
            if availability.availability is CapabilityAvailability.UNKNOWN:
                unknown.add(cap_id)
                rejected.append(RejectedCapabilityCandidate(candidate=cap_id, reasons=["AVAILABILITY_UNKNOWN"]))
                continue
            if _is_stale(availability, rules, now):
                unknown.add(cap_id)
                rejected.append(RejectedCapabilityCandidate(candidate=cap_id, reasons=["STALE_AVAILABILITY"]))
                continue

            resource_fit = obs_by_class.get(_CLASS_RESOURCE_FIT)
            if resource_fit is not None:
                if _is_stale(resource_fit, rules, now):
                    unknown.add(cap_id)
                    rejected.append(RejectedCapabilityCandidate(candidate=cap_id, reasons=["STALE_RESOURCE_FIT"]))
                    continue
                if resource_fit.resource_fit is False:
                    rejected.append(RejectedCapabilityCandidate(candidate=cap_id, reasons=["RESOURCE_UNFIT"]))
                    continue

            quota = obs_by_class.get(_CLASS_QUOTA)
            if quota is not None:
                if _is_stale(quota, rules, now):
                    unknown.add(cap_id)
                    rejected.append(RejectedCapabilityCandidate(candidate=cap_id, reasons=["STALE_QUOTA"]))
                    continue
                if quota.quota_state == "EXCEEDED":
                    rejected.append(RejectedCapabilityCandidate(candidate=cap_id, reasons=["QUOTA_EXCEEDED"]))
                    continue

            eligible.append((_EXEC_RANK[descriptor.execution_type], cap_id))

        eligible_candidates = [cap_id for _, cap_id in sorted(eligible)]
        return CapabilityResolution(
            requirement_set_ref=requirements.requirement_set_hash,
            registry_version=registry.registry_version,
            observation_snapshot_ref=registry.observation_snapshot_ref(),
            matcher_policy_version=CAPABILITY_MATCHER_POLICY_VERSION,
            eligible_candidates=eligible_candidates,
            rejected_candidates=sorted(rejected, key=lambda r: r.candidate),
            unknown_candidates=sorted(unknown),
            diagnostics=[],
        )


def _is_stale(
    observation: CapabilityObservation,
    rules: dict[str, CapabilityFreshnessRule],
    now: datetime,
) -> bool:
    rule = rules.get(observation.observation_class)
    if rule is None or rule.max_age_seconds is None:
        return False
    age_seconds = (now - observation.observed_at).total_seconds()
    return age_seconds > rule.max_age_seconds
