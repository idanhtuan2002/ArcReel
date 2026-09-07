"""D08 — immutable per-attempt ExecutionDecision.

The decision is immutable for one execution-attempt choice. A same-method
provider/tool change produces a *new* ExecutionDecision id; a material method
change is out of this service's authority and must go back to the Method Router.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

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
    ProviderRequest,
    RetryDisposition,
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

        # The attempt choice is locked here: the selected candidate must be one
        # Gate 2 actually found eligible, the descriptor must describe that same
        # candidate, and the admission / resolution / prompt-plan the decision
        # cites must all be the ones evaluated for this target.
        if selected_capability_id not in capability_resolution.eligible_candidates:
            raise ValueError(
                f"selected capability {selected_capability_id!r} is not in the eligible candidates "
                f"{list(capability_resolution.eligible_candidates)}"
            )
        if descriptor.capability_id != selected_capability_id:
            raise ValueError(
                f"descriptor capability_id {descriptor.capability_id!r} does not match the selected "
                f"capability {selected_capability_id!r}"
            )
        if admission.capability_resolution_ref != capability_resolution.requirement_set_ref:
            raise ValueError(
                f"admission capability_resolution_ref {admission.capability_resolution_ref!r} does not match "
                f"the resolution requirement_set_ref {capability_resolution.requirement_set_ref!r}"
            )
        if admission.prompt_plan_ref != prompt_plan.id:
            raise ValueError(
                f"admission prompt_plan_ref {admission.prompt_plan_ref!r} does not match the prompt plan "
                f"{prompt_plan.id!r}"
            )
        if admission.target_ref != prompt_plan.target_ref:
            raise ValueError(
                f"admission target_ref {admission.target_ref!r} and prompt plan target_ref "
                f"{prompt_plan.target_ref!r} disagree"
            )

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


# --------------------------------------------------------------------------- #
# C02 — same-execution Retry Identity Guard
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RetryGuardResult:
    allowed: bool
    disposition: RetryDisposition
    reason_codes: tuple[str, ...]


class RetryIdentityGuard:
    """A transient failure may retry under the SAME ExecutionDecision only when
    every identity-relevant fact is unchanged and no unsafe ambiguous side effect
    is unresolved. Otherwise a new admission/execution decision is required."""

    def evaluate(
        self,
        *,
        prior_decision: ExecutionDecision,
        current_decision: ExecutionDecision,
        prior_request: ProviderRequest,
        current_request: ProviderRequest,
        previous_attempt_side_effect_ambiguous: bool,
        provider_idempotency_supported: bool,
    ) -> RetryGuardResult:
        reasons: list[str] = []

        checks = {
            "ED_ID_MISMATCH": prior_decision.id != current_decision.id,
            "METHOD_DECISION_MISMATCH": prior_decision.method_decision_ref != current_decision.method_decision_ref,
            "PROMPT_PLAN_MISMATCH": prior_decision.prompt_plan_ref != current_decision.prompt_plan_ref,
            "ADAPTER_MISMATCH": prior_decision.adapter_id != current_decision.adapter_id,
            "PROVIDER_MISMATCH": prior_decision.provider_id != current_decision.provider_id,
            "MODEL_OR_TOOL_MISMATCH": prior_decision.model_or_tool_id != current_decision.model_or_tool_id,
            "DESCRIPTOR_VERSION_MISMATCH": (
                prior_decision.capability_descriptor_version != current_decision.capability_descriptor_version
            ),
            "REQUEST_SEMANTICS_MISMATCH": (
                prior_decision.request_semantics_hash != current_decision.request_semantics_hash
            ),
            "REQUEST_FINGERPRINT_MISMATCH": _request_fingerprint(prior_request)
            != _request_fingerprint(current_request),
        }
        reasons.extend(code for code, mismatched in checks.items() if mismatched)

        if (
            current_decision.execution_identity_stability is ExecutionIdentityStability.MUTABLE_ALIAS
            and current_decision.resolved_model_or_tool_revision is None
        ):
            reasons.append("MUTABLE_ALIAS_NO_REVISION_PROOF")

        if previous_attempt_side_effect_ambiguous and not provider_idempotency_supported:
            reasons.append("AMBIGUOUS_SIDE_EFFECT_NO_IDEMPOTENCY")

        if not reasons:
            return RetryGuardResult(True, RetryDisposition.RETRY_SAME_EXECUTION, ())

        ordered = tuple(sorted(set(reasons)))
        if "METHOD_DECISION_MISMATCH" in ordered:
            disposition = RetryDisposition.NEW_METHOD_DECISION_REQUIRED
        elif ordered == ("AMBIGUOUS_SIDE_EFFECT_NO_IDEMPOTENCY",):
            disposition = RetryDisposition.HUMAN_ACTION_REQUIRED
        else:
            disposition = RetryDisposition.NEW_EXECUTION_DECISION_REQUIRED
        return RetryGuardResult(False, disposition, ordered)


def _request_fingerprint(request: ProviderRequest) -> str:
    """Deterministic request identity excluding retry-variant transport metadata."""

    payload = ensure_json_value(
        {
            "provider": request.provider,
            "model": request.model,
            "endpoint": request.endpoint,
            "payload": request.payload,
            "adapter_version": request.adapter_version,
            "method_decision_ref": request.method_decision_ref,
            "prompt_plan_ref": request.prompt_plan_ref,
        }
    )
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
