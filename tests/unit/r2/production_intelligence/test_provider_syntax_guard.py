"""Provider neutrality is enforced on semantic string *values*, not only on
top-level field names.

``IdentityConstraint`` / ``ResolvedIdentityConstraint`` / ``PromptPlan`` carry
free semantic strings. A denylist rejects provider payload/CLI syntax so it can
never reach a provider-neutral contract or the PromptPlan.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from r2.contracts import (
    IdentityConstraint,
    IdentityStrength,
    PromptPlan,
    ResolvedIdentityConstraint,
)
from r2.contracts.provider_syntax import detect_provider_syntax, reject_provider_syntax

_PROVIDER_SYNTAX = [
    "midjourney--cref",
    "--cw 100",
    "--ar 16:9 --stylize 250",
    "portrait ::2 cinematic",
    "<lora:add_detail:0.8>",
    "(red hair:1.3)",
    "stable diffusion xl",
    "sdxl base 1.0",
    "cfg_scale 7.5",
    "negative_prompt: blurry",
    "ComfyUI workflow ref",
]

_NEUTRAL_SEMANTICS = [
    "short black layered bob",
    "red wool trench coat, belted",
    "scar across left eyebrow",
    "aspect intent: widescreen 16:9 framing",
    "warm low-key lighting",
    "calm, resolute expression",
    "hairstyle=short_bob",
]


@pytest.mark.parametrize("value", _PROVIDER_SYNTAX)
def test_detect_flags_provider_syntax(value: str) -> None:
    assert detect_provider_syntax(value)


@pytest.mark.parametrize("value", _NEUTRAL_SEMANTICS)
def test_detect_passes_neutral_semantic_intent(value: str) -> None:
    assert detect_provider_syntax(value) == ()


@pytest.mark.parametrize("value", _PROVIDER_SYNTAX)
def test_reject_raises_value_error_on_provider_syntax(value: str) -> None:
    with pytest.raises(ValueError, match="provider syntax"):
        reject_provider_syntax(value, field="semantic_value")


def test_reject_returns_stripped_value_when_clean() -> None:
    assert reject_provider_syntax("  short black bob  ", field="semantic_value") == "short black bob"


@pytest.mark.parametrize("value", _PROVIDER_SYNTAX)
def test_identity_constraint_rejects_provider_syntax_in_value(value: str) -> None:
    with pytest.raises(ValidationError):
        IdentityConstraint(
            semantic_key="wardrobe",
            strength=IdentityStrength.LOCKED,
            semantic_value=value,
        )


def test_identity_constraint_rejects_provider_syntax_in_key() -> None:
    with pytest.raises(ValidationError):
        IdentityConstraint(
            semantic_key="midjourney--cref",
            strength=IdentityStrength.LOCKED,
            semantic_value="short black bob",
        )


def test_identity_constraint_accepts_neutral_intent() -> None:
    constraint = IdentityConstraint(
        semantic_key="wardrobe",
        strength=IdentityStrength.LOCKED,
        semantic_value="red wool trench coat, belted",
    )
    assert constraint.semantic_value == "red wool trench coat, belted"


def test_resolved_identity_constraint_rejects_provider_syntax_in_value() -> None:
    with pytest.raises(ValidationError):
        ResolvedIdentityConstraint(
            semantic_key="wardrobe",
            effective_strength=IdentityStrength.LOCKED,
            effective_value="<lora:add_detail:0.8>",
            source_scope_ref="SC01",
        )


def test_prompt_plan_rejects_provider_syntax_in_visual_identity_constraints() -> None:
    with pytest.raises(ValidationError):
        PromptPlan(
            id="PP:SH01",
            schema_version="1",
            version=1,
            target_ref="SH01",
            semantic_instruction="establish the courtyard",
            compiler_version="m4-prompt-planner-v1",
            visual_identity_constraints=["wardrobe=--stylize 250(ADVISORY)"],
        )


def test_prompt_plan_rejects_provider_syntax_in_reference_requirements() -> None:
    with pytest.raises(ValidationError):
        PromptPlan(
            id="PP:SH01",
            schema_version="1",
            version=1,
            target_ref="SH01",
            semantic_instruction="establish the courtyard",
            compiler_version="m4-prompt-planner-v1",
            reference_requirements=["<lora:face:1>"],
        )


@pytest.mark.parametrize(
    "field",
    [
        "semantic_instruction",
        "positive_prompt",
        "negative_prompt",
        "subject_intent",
        "environment_intent",
        "action_motion_intent",
        "composition_intent",
        "camera_intent",
    ],
)
def test_prompt_plan_rejects_provider_syntax_in_free_text_intent(field: str) -> None:
    base = {
        "id": "PP:SH01",
        "schema_version": "1",
        "version": 1,
        "target_ref": "SH01",
        "semantic_instruction": "establish the courtyard",
        "compiler_version": "m4-prompt-planner-v1",
    }
    with pytest.raises(ValidationError):
        PromptPlan(**{**base, field: "cinematic portrait --stylize 250 <lora:add_detail:0.8>"})


def test_prompt_plan_rejects_provider_syntax_in_token_lists() -> None:
    with pytest.raises(ValidationError):
        PromptPlan(
            id="PP:SH01",
            schema_version="1",
            version=1,
            target_ref="SH01",
            semantic_instruction="establish the courtyard",
            compiler_version="m4-prompt-planner-v1",
            style_tokens=["midjourney niji style"],
        )


def test_prompt_plan_accepts_neutral_free_text_intent() -> None:
    plan = PromptPlan(
        id="PP:SH01",
        schema_version="1",
        version=1,
        target_ref="SH01",
        semantic_instruction="Maya turns to face the doorway, resolute",
        compiler_version="m4-prompt-planner-v1",
        subject_intent="Maya, mid-shot, three-quarter angle",
        camera_intent="slow push-in, 16:9 framing",
        negative_prompt="no watermark, no text overlay",
    )
    assert plan.camera_intent == "slow push-in, 16:9 framing"


def test_prompt_plan_accepts_neutral_identity_constraints() -> None:
    plan = PromptPlan(
        id="PP:SH01",
        schema_version="1",
        version=1,
        target_ref="SH01",
        semantic_instruction="establish the courtyard",
        compiler_version="m4-prompt-planner-v1",
        visual_identity_constraints=["hairstyle=short black bob(LOCKED)"],
        reference_requirements=["face_master", "hairstyle"],
    )
    assert plan.visual_identity_constraints == ["hairstyle=short black bob(LOCKED)"]
