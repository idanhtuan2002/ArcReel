from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from .common import (
    ContractIdentity,
    JSONValue,
    NonEmptyStr,
    R2ContractModel,
    ensure_json_value,
)
from .enums import ProductionMethod


class MethodDecision(R2ContractModel):
    id: NonEmptyStr
    target_ref: NonEmptyStr
    method: ProductionMethod
    rationale: NonEmptyStr
    capability_requirements: list[NonEmptyStr] = Field(default_factory=list)
    cost_class: NonEmptyStr
    quality_tier: int = Field(ge=0)
    fallback_methods: list[ProductionMethod] = Field(default_factory=list)


class PromptPlan(ContractIdentity):
    target_ref: NonEmptyStr
    semantic_instruction: NonEmptyStr
    positive_prompt: str = ""
    negative_prompt: str = ""
    identity_tokens: list[NonEmptyStr] = Field(default_factory=list)
    style_tokens: list[NonEmptyStr] = Field(default_factory=list)
    reference_binding_ids: list[NonEmptyStr] = Field(default_factory=list)
    exclusions: list[NonEmptyStr] = Field(default_factory=list)
    compiler_version: NonEmptyStr


class ProviderRequest(R2ContractModel):
    id: NonEmptyStr
    method_decision_ref: NonEmptyStr
    prompt_plan_ref: NonEmptyStr | None = None
    provider: NonEmptyStr
    model: NonEmptyStr
    endpoint: NonEmptyStr
    payload: dict[str, JSONValue]
    execution_options: dict[str, JSONValue] = Field(default_factory=dict)
    adapter_version: NonEmptyStr

    @field_validator("payload", "execution_options", mode="before")
    @classmethod
    def validate_json_mappings(cls, value: Any) -> dict[str, JSONValue]:
        normalized = ensure_json_value(value)
        if not isinstance(normalized, dict):
            raise ValueError(
                "provider execution fields must be JSON-compatible mappings"
            )
        return normalized
