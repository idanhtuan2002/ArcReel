import math

import pytest

from r2.contracts import (
    CameraAngle,
    CameraMovement,
    ContentBasis,
    ContentBasisType,
    CreativeApprovalStatus,
    ProductionBinding,
    ProductionBindingRole,
    ProductionBindingTarget,
    ProductionMethod,
    ShotSize,
    ShotSpec,
    ShotSpecV2,
    canonical_json_bytes,
    compute_content_fingerprint,
    compute_execution_fingerprint,
)


def _shot(purpose="Reaction close-up", basis_version="canon-v7"):
    return ShotSpec(
        id="SH042",
        schema_version="2.1",
        version=1,
        scene_id="SC001",
        content_basis=ContentBasis(
            basis_type=ContentBasisType.NARRATIVE,
            basis_version=basis_version,
            refs=["event:1"],
        ),
        purpose=purpose,
        target_duration=4.0,
        framing="close-up",
        camera="locked",
        entity_refs=["character:maya"],
        required_continuity=["costume:v3"],
        required_reference_roles=[ProductionBindingRole.CHARACTER],
        allowed_methods=[ProductionMethod.GENERATED_VIDEO],
        quality_tier=3,
        approval_status=CreativeApprovalStatus.APPROVED,
    )


def _shot_v2(purpose="Reaction close-up", basis_version="canon-v7"):
    return ShotSpecV2(
        id="SH042",
        schema_version="r2-shot-spec-v2",
        version=1,
        scene_id="SC001",
        content_basis=ContentBasis(
            basis_type=ContentBasisType.NARRATIVE,
            basis_version=basis_version,
            refs=["event:1"],
        ),
        purpose=purpose,
        target_duration=4.0,
        framing="close-up",
        camera="locked",
        shot_size=ShotSize.CLOSE,
        camera_angle=CameraAngle.EYE_LEVEL,
        camera_movement=CameraMovement.STATIC,
        entity_refs=["character:maya"],
        required_continuity=["costume:v3"],
        required_reference_roles=[ProductionBindingRole.CHARACTER],
        allowed_methods=[ProductionMethod.GENERATED_VIDEO],
        quality_tier=3,
        approval_status=CreativeApprovalStatus.APPROVED,
    )


def _binding(binding_id="B001", version=1):
    return ProductionBinding(
        id=binding_id,
        schema_version="2.1",
        version=version,
        target_type=ProductionBindingTarget.SHOT,
        target_id="SH042",
        semantic_ref="character:maya",
        production_ref="character-profile:maya-v3",
        role=ProductionBindingRole.CHARACTER,
        asset_refs=["asset:char-master"],
    )


def test_canonical_json_is_stable_across_mapping_order_and_unicode():
    a = canonical_json_bytes({"z": 1, "a": "Maya – 夜"})
    b = canonical_json_bytes({"a": "Maya – 夜", "z": 1})
    assert a == b
    assert b"\\u" not in a


def test_canonical_json_rejects_non_finite_floats():
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError, match="finite"):
            canonical_json_bytes({"bad": value})


def test_content_fingerprint_is_deterministic_and_ignores_set_input_order():
    a = compute_content_fingerprint(
        shot_spec=_shot(),
        bindings=[_binding("B002"), _binding("B001")],
        visual_identity_refs=["vip:b", "vip:a", "vip:b"],
        approved_source_asset_refs=["src:b", "src:a", "src:b"],
    )
    b = compute_content_fingerprint(
        shot_spec=_shot(),
        bindings=[_binding("B001"), _binding("B002")],
        visual_identity_refs=["vip:a", "vip:b"],
        approved_source_asset_refs=["src:a", "src:b"],
    )
    assert a == b
    assert len(a) == 64
    assert a == a.lower()


def test_provider_changes_only_execution_fingerprint():
    content = compute_content_fingerprint(
        shot_spec=_shot(),
        bindings=[_binding()],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )
    e1 = compute_execution_fingerprint(
        provider="seedance",
        model="2.5",
        endpoint="i2v",
        seed=42,
        resolution="1080p",
        generation_settings={"cfg": 7.0},
        prompt_compiler_version="compiler-v1",
        provider_adapter_version="adapter-v1",
    )
    e2 = compute_execution_fingerprint(
        provider="h3",
        model="h3-v1",
        endpoint="i2v",
        seed=42,
        resolution="1080p",
        generation_settings={"cfg": 7.0},
        prompt_compiler_version="compiler-v1",
        provider_adapter_version="adapter-v1",
    )
    assert e1 != e2
    assert content == compute_content_fingerprint(
        shot_spec=_shot(),
        bindings=[_binding()],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )


def test_semantic_changes_change_content_fingerprint():
    original = compute_content_fingerprint(
        shot_spec=_shot("Reaction close-up", "canon-v7"),
        bindings=[_binding(version=1)],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )
    changed_shot = compute_content_fingerprint(
        shot_spec=_shot("Angry reaction close-up", "canon-v7"),
        bindings=[_binding(version=1)],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )
    changed_basis = compute_content_fingerprint(
        shot_spec=_shot("Reaction close-up", "canon-v8"),
        bindings=[_binding(version=1)],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )
    changed_binding = compute_content_fingerprint(
        shot_spec=_shot("Reaction close-up", "canon-v7"),
        bindings=[_binding(version=2)],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )
    assert len({original, changed_shot, changed_basis, changed_binding}) == 4


def test_upgrading_a_shot_to_v2_changes_the_content_fingerprint() -> None:
    """Dual-read (plan Task 14): the same shot upgraded from v1 to v2 shape (identical
    semantic fields, plus the pinned Take vocabulary) is different *content* and must
    fingerprint differently — this is what naturally invalidates any readiness/
    candidate keyed by the stale v1 fingerprint. A historical ApprovedMaster keyed by
    the original v1 fingerprint is untouched by this: it is never recomputed, only a
    fresh evaluation for the same target would observe the new fingerprint."""
    v1_fingerprint = compute_content_fingerprint(
        shot_spec=_shot(),
        bindings=[_binding()],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )
    v2_fingerprint = compute_content_fingerprint(
        shot_spec=_shot_v2(),
        bindings=[_binding()],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )
    assert v1_fingerprint != v2_fingerprint

    # The v1 fingerprint itself is stable and reproducible regardless of ShotSpecV2's
    # existence elsewhere in the schema — a historical v1 master's own fingerprint
    # never shifts underneath it.
    assert v1_fingerprint == compute_content_fingerprint(
        shot_spec=_shot(),
        bindings=[_binding()],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )


def test_execution_fingerprint_is_mapping_order_stable():
    a = compute_execution_fingerprint(
        provider="seedance",
        model="2.5",
        endpoint="i2v",
        seed=42,
        resolution="1080p",
        generation_settings={"cfg": 7.0, "steps": 20},
        prompt_compiler_version="compiler-v1",
        provider_adapter_version="adapter-v1",
    )
    b = compute_execution_fingerprint(
        provider="seedance",
        model="2.5",
        endpoint="i2v",
        seed=42,
        resolution="1080p",
        generation_settings={"steps": 20, "cfg": 7.0},
        prompt_compiler_version="compiler-v1",
        provider_adapter_version="adapter-v1",
    )
    assert a == b
