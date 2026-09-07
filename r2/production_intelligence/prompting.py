"""D08 — provider-neutral PromptPlan construction.

The planner expresses *what execution must achieve*. Provider endpoint/payload
syntax never appears here; that translation happens later at the PromptCompiler.
"""

from __future__ import annotations

from r2.contracts import (
    IdentityStrength,
    MethodDecision,
    PromptPlan,
    ResolvedVisualIdentity,
    ShotSpec,
)

PROMPT_PLANNER_VERSION = "m4-prompt-planner-v1"


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
