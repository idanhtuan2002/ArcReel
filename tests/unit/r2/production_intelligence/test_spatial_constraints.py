"""A verified spatial constraint set changes the compiled prompt and the content fingerprint; nothing else does."""

from __future__ import annotations

import json
from pathlib import Path

from r2.contracts import compute_content_fingerprint, compute_content_fingerprint_v2
from r2.contracts.spatial_constraint import SpatialConstraintSetV1
from r2.production_binding.spatial_set import spatial_constraint_set_digest, spatial_constraint_set_id
from r2.production_intelligence.prompting import DefaultPromptCompiler
from r2.production_intelligence.spatial_constraints import (
    SPATIAL_PROMPT_CONSUMER_VERSION,
    apply_spatial_constraints,
)
from tests.unit.r2.contracts.test_shot_spec_v2 import _v1_binding, _v1_shot
from tests.unit.r2.production_intelligence.test_prompt_compiler import _decision, _descriptor, _plan

VECTOR = json.loads(
    (Path(__file__).resolve().parents[3] / "fixtures" / "r2" / "m8c_spatial_constraint_set_vector.json").read_text(
        encoding="utf-8"
    )
)
SET = SpatialConstraintSetV1.model_validate(VECTOR["body"])


def _compile(plan):
    return DefaultPromptCompiler.for_descriptors([_descriptor()]).compile(plan=plan, decision=_decision())


def test_visible_constraints_enter_the_environment_in_selection_order() -> None:
    applied = apply_spatial_constraints(_plan(), SET)

    assert applied.environment_intent.splitlines() == [
        "Keep the red fire extinguisher cabinet on the front wall.",
        "Keep the blue exit door on the back wall.",
        "Show the yellow painting on the left wall where both views meet.",
    ]
    assert applied.output_requirements["spatial_constraint_set"] == {
        "set_id": VECTOR["set_id"],
        "set_digest": VECTOR["digest"],
    }
    assert applied.compiler_version.endswith(SPATIAL_PROMPT_CONSUMER_VERSION)


def test_inferred_and_gap_rows_stay_warnings_and_never_become_facts() -> None:
    applied = apply_spatial_constraints(_plan(), SET)

    warnings = applied.output_requirements["spatial_coverage_warnings"]
    assert {w["evidence_class"] for w in warnings} == {"INFERRED", "GAP"}  # type: ignore[index, union-attr]
    for warning in SET.coverage_warnings:
        assert warning.relation not in applied.environment_intent


def test_the_set_changes_the_compiled_request_and_its_absence_changes_nothing() -> None:
    plain = _compile(_plan())

    assert _compile(_plan()).payload == plain.payload
    assert _compile(apply_spatial_constraints(_plan(), SET)).payload != plain.payload


def test_existing_environment_intent_is_kept_before_the_constraints() -> None:
    plan = _plan().model_copy(update={"environment_intent": "Night interior."})

    assert apply_spatial_constraints(plan, SET).environment_intent.splitlines()[0] == "Night interior."


def _fingerprint_v2(*, snapshot: str = "sha256:" + "1" * 64, spatial: tuple[str, ...] = ()) -> str:
    return compute_content_fingerprint_v2(
        shot_spec=_v1_shot(),
        bindings=[_v1_binding()],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
        binding_snapshot_digest=snapshot,
        spatial_set_digests=spatial,
    )


def test_fingerprint_v2_binds_the_spatial_set_with_every_v1_input_fixed() -> None:
    other = dict(VECTOR["body"])
    other["normalizer_version"] = "spatial-r2-v2"

    base = _fingerprint_v2(spatial=(VECTOR["digest"],))

    assert _fingerprint_v2(spatial=(spatial_constraint_set_digest(other),)) != base
    assert _fingerprint_v2() != base
    assert _fingerprint_v2(snapshot="sha256:" + "2" * 64, spatial=(VECTOR["digest"],)) != base
    assert _fingerprint_v2(spatial=(VECTOR["digest"],)) == base
    assert spatial_constraint_set_id(VECTOR["digest"]) == VECTOR["set_id"]


def test_fingerprint_v1_is_unchanged_by_v2() -> None:
    v1 = compute_content_fingerprint(
        shot_spec=_v1_shot(),
        bindings=[_v1_binding()],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )

    assert v1 != _fingerprint_v2()
