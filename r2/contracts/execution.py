from __future__ import annotations

from typing import Any

from pydantic import AwareDatetime, ConfigDict, Field, ValidationInfo, field_validator

from .common import (
    ContractIdentity,
    JSONValue,
    NonEmptyStr,
    R2ContractModel,
    ensure_json_value,
)
from .enums import (
    AdmissionOutcome,
    ExecutionIdentityStability,
    ExecutionType,
    ProductionMethod,
)
from .provenance import Provenance
from .provider_syntax import reject_provider_syntax


class RejectedMethod(R2ContractModel):
    method: ProductionMethod
    reason_codes: list[NonEmptyStr] = Field(default_factory=list)


class MethodDecision(R2ContractModel):
    id: NonEmptyStr
    target_ref: NonEmptyStr
    method: ProductionMethod
    rationale: NonEmptyStr
    capability_requirements: list[NonEmptyStr] = Field(default_factory=list)
    cost_class: NonEmptyStr
    quality_tier: int = Field(ge=0)
    fallback_methods: list[ProductionMethod] = Field(default_factory=list)
    # M4 D06 — additive routing provenance. Provider/model never appears here.
    method_policy_version: NonEmptyStr | None = None
    eligible_methods: list[ProductionMethod] = Field(default_factory=list)
    rejected_methods: list[RejectedMethod] = Field(default_factory=list)
    decision_factors: list[NonEmptyStr] = Field(default_factory=list)
    human_override: ProductionMethod | None = None
    override_actor: NonEmptyStr | None = None
    override_reason: NonEmptyStr | None = None


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
    # M4 D08 — provider-neutral semantic intent. No provider endpoint/payload/syntax.
    method_decision_ref: NonEmptyStr | None = None
    subject_intent: str = ""
    environment_intent: str = ""
    action_motion_intent: str = ""
    composition_intent: str = ""
    camera_intent: str = ""
    timing_intent: str = ""
    reference_requirements: list[NonEmptyStr] = Field(default_factory=list)
    visual_identity_constraints: list[NonEmptyStr] = Field(default_factory=list)
    required_controls: list[NonEmptyStr] = Field(default_factory=list)
    negative_constraints: list[NonEmptyStr] = Field(default_factory=list)
    output_requirements: dict[str, JSONValue] = Field(default_factory=dict)

    @field_validator(
        "semantic_instruction",
        "positive_prompt",
        "negative_prompt",
        "subject_intent",
        "environment_intent",
        "action_motion_intent",
        "composition_intent",
        "camera_intent",
        "timing_intent",
    )
    @classmethod
    def _reject_provider_syntax_text(cls, value: str, info: ValidationInfo) -> str:
        reject_provider_syntax(value, field=info.field_name or "value")
        return value

    @field_validator(
        "visual_identity_constraints",
        "reference_requirements",
        "identity_tokens",
        "style_tokens",
        "negative_constraints",
        "exclusions",
    )
    @classmethod
    def _reject_provider_syntax_items(cls, value: list[str], info: ValidationInfo) -> list[str]:
        for item in value:
            reject_provider_syntax(item, field=info.field_name or "value")
        return value


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
            raise ValueError("provider execution fields must be JSON-compatible mappings")
        return normalized


class GenerationAdmission(R2ContractModel):
    """D08 Gate-2 outcome for one prospective execution attempt.

    Only ``ADMITTED`` may lead to an ``ExecutionDecision`` and expensive execution.
    """

    id: NonEmptyStr
    target_ref: NonEmptyStr
    outcome: AdmissionOutcome
    method_decision_ref: NonEmptyStr
    capability_resolution_ref: NonEmptyStr
    prompt_plan_ref: NonEmptyStr
    readiness_ref: NonEmptyStr
    # The candidate Gate 2 evaluated and revalidated this attempt for. An
    # ExecutionDecision must lock this exact capability.
    selected_capability_id: NonEmptyStr | None = None
    budget_reservation_ref: NonEmptyStr | None = None
    approval_ref: NonEmptyStr | None = None
    reason_codes: list[NonEmptyStr] = Field(default_factory=list)
    evaluated_at: AwareDatetime
    provenance: Provenance


class ExecutionDecision(R2ContractModel):
    """D08 immutable per-attempt execution lock.

    This is an execution-side contract: provider/model/tool identity is required
    here. Same-method provider change creates a new ``ExecutionDecision`` id;
    a material method change must go back through the Method Router.
    """

    model_config = ConfigDict(frozen=True)

    id: NonEmptyStr
    target_ref: NonEmptyStr
    method_decision_ref: NonEmptyStr
    prompt_plan_ref: NonEmptyStr
    capability_resolution_ref: NonEmptyStr
    adapter_id: NonEmptyStr
    provider_id: NonEmptyStr
    model_or_tool_id: NonEmptyStr
    execution_type: ExecutionType
    capability_descriptor_version: NonEmptyStr
    observation_snapshot_ref: NonEmptyStr
    execution_identity_stability: ExecutionIdentityStability
    resolved_model_or_tool_revision: NonEmptyStr | None = None
    request_semantics_hash: NonEmptyStr
    selection_policy_version: NonEmptyStr
    selection_reasons: list[NonEmptyStr] = Field(default_factory=list)
    budget_reservation_ref: NonEmptyStr | None = None
    approval_ref: NonEmptyStr | None = None
    provenance: Provenance
