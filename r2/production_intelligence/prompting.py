"""D08 — provider-neutral PromptPlan construction.

The planner expresses *what execution must achieve*. Provider endpoint/payload
syntax never appears here; that translation happens later at the PromptCompiler.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from r2.contracts import (
    CapabilityDescriptor,
    ExecutionDecision,
    IdentityStrength,
    JSONValue,
    MethodDecision,
    PromptPlan,
    ProviderRequest,
    ResolvedVisualIdentity,
    ShotSpec,
    ensure_json_value,
)

PROMPT_PLANNER_VERSION = "m4-prompt-planner-v1"
PROMPT_COMPILER_VERSION = "m4-prompt-compiler-v1"

# Every adapter can express plain narration/dialogue/silence and the
# non-identity reference kinds. Identity references and keyframe/continuity
# controls are only representable when the candidate's descriptor declares the
# matching typed feature.
_BASE_CONTROLS = frozenset({"narration", "dialogue", "silent"})
_BASE_REFERENCE_KINDS = frozenset({"wardrobe", "style", "structure", "location", "prop"})
_CHARACTER_REFERENCE_KINDS = frozenset({"hairstyle", "face_master", "character"})
_FEATURE_CONTROLS: dict[str, frozenset[str]] = {
    "KEYFRAME_CONTROL": frozenset({"opening_frame", "ending_frame"}),
    "SHOT_CONTINUITY": frozenset({"previous_shot"}),
}


class PromptPlanner:
    def build(
        self,
        *,
        shot: ShotSpec,
        method_decision: MethodDecision,
        identity: ResolvedVisualIdentity,
    ) -> PromptPlan:
        identity_constraints = [
            f"{c.semantic_key}={c.effective_value}({c.effective_strength.value})" for c in identity.resolved_constraints
        ]
        reference_requirements = sorted(
            c.semantic_key for c in identity.resolved_constraints if c.effective_strength is IdentityStrength.LOCKED
        )
        return PromptPlan(
            id=f"PP:{shot.id}",
            schema_version="1",
            version=1,
            target_ref=shot.id,
            semantic_instruction=shot.purpose,
            compiler_version=PROMPT_PLANNER_VERSION,
            method_decision_ref=method_decision.id,
            subject_intent=shot.purpose,
            composition_intent=shot.framing,
            camera_intent=shot.camera,
            timing_intent=f"{shot.target_duration:g}s",
            reference_requirements=reference_requirements,
            visual_identity_constraints=identity_constraints,
            required_controls=sorted({shot.audio_intent}) if shot.audio_intent else [],
            output_requirements={"target_duration_seconds": shot.target_duration},
        )


class PromptCompilationIncompatible(RuntimeError):
    """A required semantic cannot be represented for the selected execution
    candidate. The compiler fails closed rather than silently dropping it."""

    def __init__(self, reason_codes: tuple[str, ...]) -> None:
        super().__init__(", ".join(reason_codes))
        self.reason_codes = reason_codes


class PromptCompiler(Protocol):
    def compile(self, *, plan: PromptPlan, decision: ExecutionDecision) -> ProviderRequest:
        """Translate semantic intent into one provider request. Never routes,
        never selects a provider, never relaxes an identity constraint."""
        ...


@dataclass(frozen=True)
class AdapterCompileProfile:
    """The representable surface of one execution adapter, derived from the
    selected candidate's real capability descriptor."""

    adapter_id: str
    supported_controls: frozenset[str]
    supported_reference_kinds: frozenset[str]
    endpoint: str

    @classmethod
    def from_descriptor(cls, descriptor: CapabilityDescriptor) -> AdapterCompileProfile:
        features = set(descriptor.typed_features)
        controls = set(_BASE_CONTROLS)
        for feature, extra in _FEATURE_CONTROLS.items():
            if feature in features:
                controls |= extra
        reference_kinds = set(_BASE_REFERENCE_KINDS)
        if "CHARACTER_REFERENCE" in features:
            reference_kinds |= _CHARACTER_REFERENCE_KINDS
        return cls(
            adapter_id=descriptor.adapter_id,
            supported_controls=frozenset(controls),
            supported_reference_kinds=frozenset(reference_kinds),
            endpoint=f"{descriptor.adapter_id}/generate/{descriptor.execution_type.value.lower()}",
        )


class DefaultPromptCompiler:
    """Per-adapter translation-only compiler. Provider/model identity comes solely
    from the ExecutionDecision; the representable surface is the selected
    candidate's own ``AdapterCompileProfile``. An unregistered adapter or an
    unmappable required semantic raises ``PromptCompilationIncompatible``."""

    def __init__(self, *, adapter_profiles: Mapping[str, AdapterCompileProfile] | None = None) -> None:
        self._profiles: dict[str, AdapterCompileProfile] = dict(adapter_profiles or {})

    @classmethod
    def for_descriptors(cls, descriptors: Iterable[CapabilityDescriptor]) -> DefaultPromptCompiler:
        return cls(adapter_profiles={d.adapter_id: AdapterCompileProfile.from_descriptor(d) for d in descriptors})

    def compile(self, *, plan: PromptPlan, decision: ExecutionDecision) -> ProviderRequest:
        profile = self._profiles.get(decision.adapter_id)
        if profile is None:
            raise PromptCompilationIncompatible(("COMPILATION_INCOMPATIBLE", f"UNKNOWN_ADAPTER:{decision.adapter_id}"))

        unmapped_controls = [c for c in plan.required_controls if c not in profile.supported_controls]
        unmapped_refs = [r for r in plan.reference_requirements if r not in profile.supported_reference_kinds]
        if unmapped_controls or unmapped_refs:
            reasons = ["COMPILATION_INCOMPATIBLE"]
            reasons += [f"UNSUPPORTED_CONTROL:{c}" for c in unmapped_controls]
            reasons += [f"UNSUPPORTED_REFERENCE:{r}" for r in unmapped_refs]
            raise PromptCompilationIncompatible(tuple(reasons))

        payload = cast(
            "dict[str, JSONValue]",
            ensure_json_value(
                {
                    "instruction": plan.semantic_instruction,
                    "subject": plan.subject_intent,
                    "environment": plan.environment_intent,
                    "action": plan.action_motion_intent,
                    "composition": plan.composition_intent,
                    "camera": plan.camera_intent,
                    "timing": plan.timing_intent,
                    "positive": plan.positive_prompt,
                    "negative": " | ".join(plan.negative_constraints) or plan.negative_prompt,
                    "references": sorted(plan.reference_requirements),
                    "identity": sorted(plan.visual_identity_constraints),
                    "controls": sorted(plan.required_controls),
                }
            ),
        )
        return ProviderRequest(
            id=f"REQ:{decision.id}",
            method_decision_ref=decision.method_decision_ref,
            prompt_plan_ref=plan.id,
            provider=decision.provider_id,
            model=decision.model_or_tool_id,
            endpoint=profile.endpoint,
            payload=payload,
            execution_options={
                "request_semantics_hash": decision.request_semantics_hash,
                "identity_stability": decision.execution_identity_stability.value,
            },
            adapter_version=decision.capability_descriptor_version,
        )
