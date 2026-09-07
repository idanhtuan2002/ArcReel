"""D08 — immutable per-attempt ExecutionDecision.

The decision is immutable for one execution-attempt choice. A same-method
provider/tool change produces a *new* ExecutionDecision id; a material method
change is out of this service's authority and must go back to the Method Router.
"""

from __future__ import annotations

import hashlib

from r2.contracts import (
    AdmissionOutcome,
    CapabilityDescriptor,
    CapabilityResolution,
    ExecutionDecision,
    ExecutionIdentityStability,
    GenerationAdmission,
    PromptPlan,
    Provenance,
    ProvenanceActor,
    ensure_json_value,
)
from r2.contracts.fingerprints import canonical_json_bytes

EXECUTION_DECISION_POLICY_VERSION = "m4-execution-decision-v1"


class ExecutionNotAdmitted(RuntimeError):
    """create() was called for an admission whose outcome is not ADMITTED."""


class ExecutionDecisionService:
    def create(
        self,
        *,
        admission: GenerationAdmission,
        capability_resolution: CapabilityResolution,
        prompt_plan: PromptPlan,
        selected_capability_id: str,
        descriptor: CapabilityDescriptor | None,
        identity_stability: ExecutionIdentityStability = ExecutionIdentityStability.UNKNOWN,
        resolved_model_or_tool_revision: str | None = None,
    ) -> ExecutionDecision:
        if admission.outcome is not AdmissionOutcome.ADMITTED:
            raise ExecutionNotAdmitted(f"admission outcome is {admission.outcome.value}")
        if descriptor is None:
            raise ExecutionNotAdmitted("no capability descriptor for the selected candidate")

        request_semantics_hash = _request_semantics_hash(prompt_plan, admission, selected_capability_id)
        return ExecutionDecision(
            id=f"ED:{prompt_plan.target_ref}:{selected_capability_id}:{request_semantics_hash[:12]}",
            target_ref=prompt_plan.target_ref,
            method_decision_ref=admission.method_decision_ref,
            prompt_plan_ref=prompt_plan.id,
            capability_resolution_ref=capability_resolution.requirement_set_ref,
            adapter_id=descriptor.adapter_id,
            provider_id=descriptor.provider_id,
            model_or_tool_id=selected_capability_id,
            execution_type=descriptor.execution_type,
            capability_descriptor_version=descriptor.descriptor_version,
            observation_snapshot_ref=capability_resolution.observation_snapshot_ref,
            execution_identity_stability=identity_stability,
            resolved_model_or_tool_revision=resolved_model_or_tool_revision,
            request_semantics_hash=request_semantics_hash,
            selection_policy_version=EXECUTION_DECISION_POLICY_VERSION,
            selection_reasons=[f"top-ranked eligible capability {selected_capability_id}"],
            budget_reservation_ref=admission.budget_reservation_ref,
            approval_ref=admission.approval_ref,
            provenance=Provenance(created_by=ProvenanceActor.SYSTEM, created_at=admission.evaluated_at),
        )


def _request_semantics_hash(
    prompt_plan: PromptPlan,
    admission: GenerationAdmission,
    selected_capability_id: str,
) -> str:
    payload = ensure_json_value(
        {
            "prompt_plan_id": prompt_plan.id,
            "method_decision_ref": admission.method_decision_ref,
            "semantic_instruction": prompt_plan.semantic_instruction,
            "subject_intent": prompt_plan.subject_intent,
            "environment_intent": prompt_plan.environment_intent,
            "composition_intent": prompt_plan.composition_intent,
            "camera_intent": prompt_plan.camera_intent,
            "timing_intent": prompt_plan.timing_intent,
            "reference_requirements": sorted(prompt_plan.reference_requirements),
            "visual_identity_constraints": sorted(prompt_plan.visual_identity_constraints),
            "required_controls": sorted(prompt_plan.required_controls),
            "negative_constraints": sorted(prompt_plan.negative_constraints),
            "selected_capability_id": selected_capability_id,
        }
    )
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
