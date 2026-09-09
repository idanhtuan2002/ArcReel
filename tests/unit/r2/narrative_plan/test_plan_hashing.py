from __future__ import annotations

from r2.narrative_plan.hashing import compute_plan_content_hash, compute_scene_semantic_hash
from tests.unit.r2.narrative_plan._helpers import node, plan_content, scene_contract


def test_scene_semantic_hash_ignores_version_and_hash_fields() -> None:
    base = scene_contract(version=1, purpose="discover ring")
    bumped = base.model_copy(update={"version": 7})
    assert compute_scene_semantic_hash(base) == compute_scene_semantic_hash(bumped)
    assert base.semantic_hash == compute_scene_semantic_hash(base)


def test_scene_semantic_hash_changes_with_an_executable_field() -> None:
    a = scene_contract(purpose="discover ring")
    b = scene_contract(purpose="hide ring")
    assert compute_scene_semantic_hash(a) != compute_scene_semantic_hash(b)


def test_plan_content_hash_is_deterministic_and_covers_scene_identity_and_canon_basis() -> None:
    scenes = [scene_contract(scene_id="scene-1", version=2)]
    content = plan_content(scenes=scenes)
    assert compute_plan_content_hash(content) == compute_plan_content_hash(plan_content(scenes=list(scenes)))
    assert compute_plan_content_hash(content) != compute_plan_content_hash(
        plan_content(scenes=scenes, canon_version_id="canon-v2")
    )
    rehashed = [scenes[0].model_copy(update={"version": 3})]
    assert compute_plan_content_hash(content) != compute_plan_content_hash(plan_content(scenes=rehashed))


def test_plan_content_hash_covers_the_hierarchy() -> None:
    without = plan_content()
    with_arc = plan_content(arc_plans=[node("arc-1", "ARC")])
    assert compute_plan_content_hash(without) != compute_plan_content_hash(with_arc)
