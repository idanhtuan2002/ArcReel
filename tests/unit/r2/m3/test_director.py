from r2.contracts import ContentBasisType
from r2.m3.director import FixtureOpenMontageBackend, GoldenAOpenMontageAdapter
from r2.m3.factual_fixture import load_golden_a_factual_bundle

FORBIDDEN = {"provider", "model", "endpoint", "payload", "provider_job_id"}


def logical_id(obj):
    for name in ("id", "scene_id", "shot_id"):
        if hasattr(obj, name):
            return getattr(obj, name)
    raise AssertionError(type(obj))


def test_fixture_director_emits_three_scenes_and_four_shots():
    result = GoldenAOpenMontageAdapter(FixtureOpenMontageBackend()).direct(load_golden_a_factual_bundle().script)
    assert len(result.scenes) == 3
    assert len(result.shots) == 4
    assert {logical_id(x) for x in result.scenes} == {"SC01", "SC02", "SC03"}


def test_direction_preserves_lineage_and_factual_basis():
    script = load_golden_a_factual_bundle().script
    result = GoldenAOpenMontageAdapter(FixtureOpenMontageBackend()).direct(script)
    section_ids = {s.id for s in script.sections}
    scene_ids = {logical_id(s) for s in result.scenes}

    for scene in result.scenes:
        if hasattr(scene, "source_unit_refs"):
            assert set(scene.source_unit_refs) <= section_ids
        if hasattr(scene, "content_basis"):
            assert scene.content_basis.basis_type is ContentBasisType.FACTUAL

    for shot in result.shots:
        assert shot.scene_id in scene_ids
        if hasattr(shot, "content_basis"):
            assert shot.content_basis.basis_type is ContentBasisType.FACTUAL


def test_direction_contracts_remain_provider_neutral():
    result = GoldenAOpenMontageAdapter(FixtureOpenMontageBackend()).direct(load_golden_a_factual_bundle().script)
    for obj in (*result.scenes, *result.shots):
        assert not (set(obj.model_dump(mode="json")) & FORBIDDEN)
