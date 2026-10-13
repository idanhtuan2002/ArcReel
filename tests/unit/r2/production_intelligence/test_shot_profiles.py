"""Admission of a spatial shot to the first Wan two-view profile, and its exact provider prompt."""

from __future__ import annotations

import json
from pathlib import Path

from r2.contracts import MethodDecision, ProductionMethod, PromptPlan, ResolvedIdentityStatus, ResolvedVisualIdentity
from r2.contracts.spatial_constraint import SpatialConstraintSetV1
from r2.production_intelligence.prompting import PromptPlanner
from r2.production_intelligence.shot_profiles import (
    IMAGE_ROLE_LINE,
    WAN27_TWO_VIEW_PROFILE,
    admission_refusals,
    project_spatial_prompt,
    prompt_digest,
)
from r2.production_intelligence.spatial_constraints import apply_spatial_constraints
from tests.unit.r2.contracts.test_shot_spec_v2 import _v2_shot

VECTOR = json.loads(
    (Path(__file__).resolve().parents[3] / "fixtures" / "r2" / "m8c_spatial_constraint_set_vector.json").read_text(
        encoding="utf-8"
    )
)
SET = SpatialConstraintSetV1.model_validate(VECTOR["body"])


def _shot(**overrides: object):
    return _v2_shot(target_duration=5.0, **overrides)


def _plan(shot, *, with_set: bool = True) -> PromptPlan:
    plan = PromptPlanner().build(
        shot=shot,
        method_decision=MethodDecision(
            id=f"MD:{shot.id}",
            target_ref=shot.id,
            method=ProductionMethod.GENERATED_VIDEO,
            rationale="two-view spatial shot",
            cost_class="standard",
            quality_tier=3,
        ),
        identity=ResolvedVisualIdentity(
            target_ref=shot.id, status=ResolvedIdentityStatus.RESOLVED, resolution_policy_version="v1"
        ),
    )
    return apply_spatial_constraints(plan, SET) if with_set else plan


def test_a_silent_free_five_second_spatial_shot_is_admitted() -> None:
    shot = _shot()

    assert admission_refusals(shot, _plan(shot), WAN27_TWO_VIEW_PROFILE) == ()


def test_the_prompt_binds_image_roles_and_carries_only_visible_constraints() -> None:
    prompt = project_spatial_prompt(_plan(_shot()))

    lines = prompt.splitlines()
    assert lines[0] == IMAGE_ROLE_LINE
    assert "- Keep the red fire extinguisher cabinet on the front wall." in lines
    assert "- Show the yellow painting on the left wall where both views meet." in lines
    for warning in SET.coverage_warnings:
        assert warning.relation not in prompt


def test_one_changed_constraint_changes_the_prompt_digest() -> None:
    changed = SET.model_dump(mode="json")
    changed["constraints"][0]["subject_ref"] = "green cabinet"
    shot = _shot()
    base = _plan(shot)
    mutated = apply_spatial_constraints(_plan(shot, with_set=False), SpatialConstraintSetV1.model_validate(changed))

    assert prompt_digest(project_spatial_prompt(mutated)) != prompt_digest(project_spatial_prompt(base))
    assert prompt_digest(project_spatial_prompt(base)) == prompt_digest(project_spatial_prompt(_plan(shot)))


def test_unsupported_shots_are_refused_before_queueing() -> None:
    narrated = _shot(audio_intent="narration")
    four_seconds = _v2_shot(target_duration=4.0)

    assert "profile_unsupported_controls" in admission_refusals(narrated, _plan(narrated), WAN27_TWO_VIEW_PROFILE)
    assert "profile_duration_mismatch" in admission_refusals(four_seconds, _plan(four_seconds), WAN27_TWO_VIEW_PROFILE)
    assert admission_refusals(_shot(), _plan(_shot(), with_set=False), WAN27_TWO_VIEW_PROFILE) == (
        "profile_requires_spatial_set",
    )


def test_identity_references_and_overlong_prompts_are_refused() -> None:
    shot = _shot()
    locked = _plan(shot).model_copy(update={"reference_requirements": ["face_master"]})
    long_subject = _plan(_shot(purpose="x" * 6000))

    assert admission_refusals(shot, locked, WAN27_TWO_VIEW_PROFILE) == ("profile_unsupported_identity",)
    assert admission_refusals(_shot(purpose="x" * 6000), long_subject, WAN27_TWO_VIEW_PROFILE) == (
        "profile_prompt_too_long",
    )
