from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from .common import ContractIdentity, NonEmptyStr, R2ContractModel
from .enums import (
    IdentityScopeType,
    IdentityStrength,
    ProductionBindingRole,
    ProductionBindingTarget,
    ReadinessState,
    ResolvedIdentityStatus,
)
from .provenance import Provenance


class ProductionBinding(ContractIdentity):
    target_type: ProductionBindingTarget
    target_id: NonEmptyStr
    semantic_ref: NonEmptyStr
    production_ref: NonEmptyStr
    role: ProductionBindingRole
    asset_refs: list[NonEmptyStr] = Field(default_factory=list)
    variant_ref: NonEmptyStr | None = None
    state_ref: NonEmptyStr | None = None

    @field_validator("asset_refs")
    @classmethod
    def normalize_asset_refs(cls, value: list[str]) -> list[str]:
        return sorted(set(value))


class IdentityConstraint(R2ContractModel):
    """One typed identity/continuity/style constraint carried by a scoped profile.

    ``semantic_value`` is a normalized intent string, never provider syntax.
    ``binding_role_ref`` is a semantic pointer to a ProductionBinding role, not
    asset ownership.
    """

    semantic_key: NonEmptyStr
    strength: IdentityStrength
    semantic_value: NonEmptyStr
    binding_role_ref: ProductionBindingRole | None = None
    provenance: Provenance | None = None


class VisualIdentityProfile(ContractIdentity):
    semantic_character_ref: NonEmptyStr
    face_master_ref: NonEmptyStr | None = None
    full_body_master_ref: NonEmptyStr | None = None
    side_profile_ref: NonEmptyStr | None = None
    hairstyle_lock: NonEmptyStr | None = None
    costume_locks: list[NonEmptyStr] = Field(default_factory=list)
    accessory_locks: list[NonEmptyStr] = Field(default_factory=list)
    state_variants: list[NonEmptyStr] = Field(default_factory=list)
    approved_reference_refs: list[NonEmptyStr] = Field(default_factory=list)
    # M4 D05 — optional scoped/typed overlay. Absent on legacy flat profiles.
    scope_type: IdentityScopeType | None = None
    scope_ref: NonEmptyStr | None = None
    identity_constraints: list[IdentityConstraint] = Field(default_factory=list)

    @field_validator("approved_reference_refs")
    @classmethod
    def normalize_reference_refs(cls, value: list[str]) -> list[str]:
        return sorted(set(value))


class ResolvedIdentityConstraint(R2ContractModel):
    semantic_key: NonEmptyStr
    effective_strength: IdentityStrength
    effective_value: NonEmptyStr
    source_scope_ref: NonEmptyStr


class ResolvedVisualIdentity(R2ContractModel):
    """Deterministic computed view over scoped profiles. Not a new authority store."""

    target_ref: NonEmptyStr
    status: ResolvedIdentityStatus
    contributing_profile_refs: list[NonEmptyStr] = Field(default_factory=list)
    resolved_constraints: list[ResolvedIdentityConstraint] = Field(default_factory=list)
    conflicts: list[NonEmptyStr] = Field(default_factory=list)
    resolution_policy_version: NonEmptyStr
    observed_profile_versions: list[NonEmptyStr] = Field(default_factory=list)
    provenance: Provenance | None = None


class ReadinessRequirement(R2ContractModel):
    requirement_id: NonEmptyStr
    role: ProductionBindingRole
    required: bool
    status: ReadinessState
    resolved_binding: NonEmptyStr | None = None
    resolution_source: NonEmptyStr | None = None
    reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_resolution(self):
        if self.required and self.status is ReadinessState.READY and self.resolved_binding is None:
            raise ValueError("required READY requirement must include resolved_binding")
        return self


def _derive_readiness_state(requirements: list[Any]) -> ReadinessState:
    for requirement in requirements:
        if isinstance(requirement, ReadinessRequirement):
            required = requirement.required
            status = requirement.status
        elif isinstance(requirement, dict):
            required = bool(requirement.get("required", False))
            raw_status = requirement.get("status")
            try:
                status = ReadinessState(raw_status)
            except (TypeError, ValueError):
                # Let normal field validation report the malformed status.
                continue
        else:
            # Let normal field validation report the malformed requirement.
            continue

        if required and status is not ReadinessState.READY:
            return ReadinessState.BLOCKED
    return ReadinessState.READY


class ProductionReadiness(R2ContractModel):
    id: NonEmptyStr
    target_id: NonEmptyStr
    state: ReadinessState
    requirements: list[ReadinessRequirement] = Field(default_factory=list)
    # M4 D04 — Gate-1 freshness anchors; a stale READY must be re-evaluated
    # before Gate 2.
    observed_target_version: NonEmptyStr | None = None
    observed_binding_snapshot_ref: NonEmptyStr | None = None
    evaluation_policy_version: NonEmptyStr | None = None
    # Non-binding-derived block cause (e.g. IDENTITY_CONFLICT). When set, the
    # state is BLOCKED regardless of the requirement list.
    blocked_reason: NonEmptyStr | None = None

    @model_validator(mode="before")
    @classmethod
    def derive_and_validate_state(cls, data: Any):
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        expected = _derive_readiness_state(normalized.get("requirements", []))
        if normalized.get("blocked_reason"):
            expected = ReadinessState.BLOCKED
        supplied = normalized.get("state")

        if supplied is not None:
            try:
                supplied_state = ReadinessState(supplied)
            except (TypeError, ValueError):
                # Preserve the value so the state field reports the validation error.
                return normalized
            if supplied_state is not expected:
                raise ValueError(
                    f"readiness state {supplied_state.value} contradicts requirements; expected {expected.value}"
                )

        normalized["state"] = expected
        return normalized
