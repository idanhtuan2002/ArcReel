from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from .common import ContractIdentity, NonEmptyStr, R2ContractModel
from .enums import (
    ProductionBindingRole,
    ProductionBindingTarget,
    ReadinessState,
)


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

    @field_validator("approved_reference_refs")
    @classmethod
    def normalize_reference_refs(cls, value: list[str]) -> list[str]:
        return sorted(set(value))


class ReadinessRequirement(R2ContractModel):
    requirement_id: NonEmptyStr
    role: ProductionBindingRole
    required: bool
    status: ReadinessState
    resolved_binding: NonEmptyStr | None = None
    reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_resolution(self):
        if (
            self.required
            and self.status is ReadinessState.READY
            and self.resolved_binding is None
        ):
            raise ValueError(
                "required READY requirement must include resolved_binding"
            )
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

    @model_validator(mode="before")
    @classmethod
    def derive_and_validate_state(cls, data: Any):
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        expected = _derive_readiness_state(normalized.get("requirements", []))
        supplied = normalized.get("state")

        if supplied is not None:
            try:
                supplied_state = ReadinessState(supplied)
            except (TypeError, ValueError):
                # Preserve the value so the state field reports the validation error.
                return normalized
            if supplied_state is not expected:
                raise ValueError(
                    f"readiness state {supplied_state.value} contradicts requirements; "
                    f"expected {expected.value}"
                )

        normalized["state"] = expected
        return normalized
