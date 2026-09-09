from __future__ import annotations

from datetime import UTC, datetime

from r2.contracts import CanonBasis, NarrativePlanContent, SceneContract, SceneFactConstraint, SceneTemporalWindow
from r2.narrative_plan.hashing import (
    compute_plan_content_hash,
    compute_plan_content_hash_v2,
    compute_scene_semantic_hash,
    compute_scene_semantic_hash_dispatch,
    compute_scene_semantic_hash_v2,
)
from r2.narrative_plan.schema_upgrade import minimum_scene_selector
from tests.unit.r2.narrative_plan._helpers import (
    plan_content_v2,
    relationship_constraint,
    scene_contract,
    scene_contract_v2,
    thread_constraint,
)

_FROM = datetime(2026, 3, 1, 10, tzinfo=UTC)
_UNTIL = datetime(2026, 3, 1, 12, tzinfo=UTC)

# Regression anchors captured from the frozen v1 implementation. v2 code must not move them.
V1_GOLDEN_SCENE = SceneContract(
    scene_contract_id="golden-scene",
    version=1,
    semantic_hash="sh:placeholder",
    sequence_index=0,
    purpose="discover ring",
    pov="hero",
    location_ref="loc-cave",
    temporal_window=SceneTemporalWindow(effective_from=_FROM, effective_until=_UNTIL),
    participants=["hero", "mentor"],
    entry_state_constraints=[
        SceneFactConstraint(constraint_id="c1", subject_ref="obj-ring", predicate="owner", comparison="PRESENT")
    ],
)
V1_GOLDEN_SCENE_HASH = "sh:66c8077044977a3fa1245bb4db66a803c5ed0da5502f208e99feb0267acafd24"
V1_GOLDEN_PLAN_HASH = "np:133bf9df6dd1fe175abe1967efa2f657a80bee184100d98c91d9ae26acf28af5"


def _v1_golden_plan() -> NarrativePlanContent:
    sealed = V1_GOLDEN_SCENE.model_copy(update={"semantic_hash": V1_GOLDEN_SCENE_HASH})
    return NarrativePlanContent(
        canon_basis=CanonBasis(branch_id="main", canon_version_id="canon-v1"),
        story_frame="frame",
        scene_contracts=[sealed],
    )


def test_v1_golden_scene_hash_is_unchanged_by_v2_code() -> None:
    assert compute_scene_semantic_hash(V1_GOLDEN_SCENE) == V1_GOLDEN_SCENE_HASH
    assert compute_scene_semantic_hash_dispatch(V1_GOLDEN_SCENE) == V1_GOLDEN_SCENE_HASH


def test_v1_golden_plan_hash_is_unchanged_by_v2_code() -> None:
    assert compute_plan_content_hash(_v1_golden_plan()) == V1_GOLDEN_PLAN_HASH


def test_dispatch_routes_v2_scene_to_the_v2_domain() -> None:
    scene = scene_contract_v2(entry_state_constraints=[relationship_constraint()])
    assert compute_scene_semantic_hash_dispatch(scene) == compute_scene_semantic_hash_v2(scene)
    assert compute_scene_semantic_hash_dispatch(scene).startswith("sh:")


def test_v2_scene_hash_differs_from_the_equivalent_v1_scene_hash() -> None:
    v1 = scene_contract()
    v2 = scene_contract_v2(scene_id=v1.scene_contract_id, purpose=v1.purpose)
    assert compute_scene_semantic_hash_v2(v2) != compute_scene_semantic_hash(v1)


def test_scene_with_relationship_semantic_must_select_v2() -> None:
    assert minimum_scene_selector(scene_contract_v2(entry_state_constraints=[relationship_constraint()])) == (
        "r2-scene-contract-content-v2"
    )
    assert minimum_scene_selector(scene_contract_v2(exit_state_targets=[thread_constraint()])) == (
        "r2-scene-contract-content-v2"
    )
    assert minimum_scene_selector(scene_contract_v2(omniscient=True)) == "r2-scene-contract-content-v2"


def test_minimum_selector_is_v1_for_a_v1_scene_and_for_a_v2_scene_with_no_v2_semantics() -> None:
    assert minimum_scene_selector(scene_contract()) == "r2-scene-contract-content-v1"
    assert minimum_scene_selector(scene_contract_v2()) == "r2-scene-contract-content-v1"


def test_each_v2_executable_field_mutation_changes_the_semantic_hash() -> None:
    base = scene_contract_v2(entry_state_constraints=[relationship_constraint()])
    assert compute_scene_semantic_hash_v2(base) != compute_scene_semantic_hash_v2(
        base.model_copy(update={"omniscient_authoring_allowed_by_scene": True})
    )
    assert compute_scene_semantic_hash_v2(base) != compute_scene_semantic_hash_v2(
        base.model_copy(update={"exit_state_targets": [thread_constraint(required_state="OPEN")]})
    )
    assert compute_scene_semantic_hash_v2(base) != compute_scene_semantic_hash_v2(
        base.model_copy(update={"purpose": "hide ring"})
    )


def test_v2_scene_semantic_hash_ignores_version_and_hash_fields() -> None:
    base = scene_contract_v2(entry_state_constraints=[relationship_constraint()])
    bumped = base.model_copy(update={"version": 9})
    assert compute_scene_semantic_hash_v2(base) == compute_scene_semantic_hash_v2(bumped)
    assert base.semantic_hash == compute_scene_semantic_hash_v2(base)


def test_v2_plan_hash_is_deterministic_and_covers_scene_semantic_hash_version() -> None:
    v1_member = scene_contract(scene_id="scene-1")
    v2_member = scene_contract_v2(scene_id="scene-2", entry_state_constraints=[relationship_constraint()])
    content = plan_content_v2(scenes=[v1_member, v2_member])
    assert compute_plan_content_hash_v2(content) == compute_plan_content_hash_v2(
        plan_content_v2(scenes=[v1_member, v2_member])
    )
    assert compute_plan_content_hash_v2(content) != compute_plan_content_hash_v2(
        plan_content_v2(scenes=[v1_member, v2_member], canon_version_id="canon-v2")
    )


def test_v2_plan_may_retain_v1_scene_members_byte_for_byte() -> None:
    v1_member = scene_contract(scene_id="scene-1", version=4)
    content = plan_content_v2(scenes=[v1_member])
    (retained,) = content.scene_contracts
    assert retained.semantic_hash == v1_member.semantic_hash
    assert retained.version == 4
    assert retained.semantic_hash_version == "r2-scene-contract-content-v1"
