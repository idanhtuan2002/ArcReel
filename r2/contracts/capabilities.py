"""D07 — Hybrid normalized capability registry contracts.

Descriptor catalog (what an adapter/model/tool can do) is kept separate from the
observation overlay (whether it can be used right now) and from preference.
This is an execution inventory/matcher, never an artifact registry.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import AwareDatetime, Field

from .common import JSONValue, NonEmptyStr, R2ContractModel
from .enums import (
    CapabilityAvailability,
    CapabilitySupport,
    ExecutionType,
    ObservationExpiryBehavior,
    ProductionMethod,
)
from .provenance import Provenance


class CapabilityDescriptor(R2ContractModel):
    capability_id: NonEmptyStr
    adapter_id: NonEmptyStr
    provider_id: NonEmptyStr
    execution_type: ExecutionType
    supported_methods: list[ProductionMethod] = Field(default_factory=list)
    input_modalities: list[NonEmptyStr] = Field(default_factory=list)
    output_modalities: list[NonEmptyStr] = Field(default_factory=list)
    typed_features: list[NonEmptyStr] = Field(default_factory=list)
    limits: dict[str, JSONValue] = Field(default_factory=dict)
    resource_requirements: dict[str, JSONValue] = Field(default_factory=dict)
    stability: NonEmptyStr | None = None
    descriptor_source: NonEmptyStr
    descriptor_version: NonEmptyStr
    provenance: Provenance


class CapabilityFeatureSupport(R2ContractModel):
    feature_key: NonEmptyStr
    support: CapabilitySupport


class CapabilityObservation(R2ContractModel):
    capability_id: NonEmptyStr
    observation_class: NonEmptyStr
    availability: CapabilityAvailability
    credentials_ready: bool | None = None
    endpoint_healthy: bool | None = None
    runtime_dependencies_ready: bool | None = None
    resource_fit: bool | None = None
    quota_state: NonEmptyStr | None = None
    estimated_cost: Decimal | None = None
    estimated_latency_ms: int | None = Field(default=None, ge=0)
    reliability: float | None = Field(default=None, ge=0.0, le=1.0)
    feature_support: list[CapabilityFeatureSupport] = Field(default_factory=list)
    observed_at: AwareDatetime
    observation_version: NonEmptyStr


class CapabilityRequirements(R2ContractModel):
    target_ref: NonEmptyStr
    method: ProductionMethod
    hard_features: list[NonEmptyStr] = Field(default_factory=list)
    soft_features: list[NonEmptyStr] = Field(default_factory=list)
    required_execution_types: list[ExecutionType] = Field(default_factory=list)
    requirement_set_hash: NonEmptyStr
    policy_version: NonEmptyStr


class RejectedCapabilityCandidate(R2ContractModel):
    candidate: NonEmptyStr
    reasons: list[NonEmptyStr] = Field(default_factory=list)


class CapabilityResolution(R2ContractModel):
    requirement_set_ref: NonEmptyStr
    registry_version: NonEmptyStr
    observation_snapshot_ref: NonEmptyStr
    matcher_policy_version: NonEmptyStr
    eligible_candidates: list[NonEmptyStr] = Field(default_factory=list)
    rejected_candidates: list[RejectedCapabilityCandidate] = Field(default_factory=list)
    unknown_candidates: list[NonEmptyStr] = Field(default_factory=list)
    diagnostics: list[NonEmptyStr] = Field(default_factory=list)


class CapabilityFreshnessRule(R2ContractModel):
    observation_class: NonEmptyStr
    max_age_seconds: int | None = Field(default=None, ge=0)
    revalidate_on_admission: bool
    invalidation_triggers: list[NonEmptyStr] = Field(default_factory=list)
    expiry_behavior: ObservationExpiryBehavior


class CapabilityFreshnessPolicy(R2ContractModel):
    policy_version: NonEmptyStr
    rules: list[CapabilityFreshnessRule] = Field(default_factory=list)
    provenance: Provenance
