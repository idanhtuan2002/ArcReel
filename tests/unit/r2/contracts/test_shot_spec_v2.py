from __future__ import annotations

from typing import cast

import pytest
from pydantic import TypeAdapter, ValidationError

from r2.contracts import (
    ContentBasis,
    ContentBasisType,
    CreativeApprovalStatus,
    ProductionBinding,
    ProductionBindingRole,
    ProductionBindingTarget,
    ProductionMethod,
    canonical_json_bytes,
    compute_content_fingerprint,
)
from r2.contracts.production import (
    AnyShotSpec,
    CameraAngle,
    CameraMovement,
    ShotSize,
    ShotSpec,
    ShotSpecV1,
    ShotSpecV2,
)

# --- accepted v1 compatibility vectors, captured before v2 existed --------------------

_V1_GOLDEN_BYTES = (
    b'{"allowed_methods":["GENERATED_VIDEO"],"approval_status":"APPROVED","audio_intent":null,'
    b'"camera":"locked","content_basis":{"basis_type":"NARRATIVE","basis_version":"canon-v7",'
    b'"refs":["event:1"]},"entity_refs":["character:maya"],"framing":"close-up","id":"SH042",'
    b'"purpose":"Reaction close-up","quality_tier":3,"required_continuity":["costume:v3"],'
    b'"required_reference_roles":["CHARACTER"],"scene_id":"SC001","schema_version":"2.1",'
    b'"target_duration":4.0,"version":1}'
)
_V1_GOLDEN_FINGERPRINT = "b4ea250c4a2062093e525dcd6f4adf079a92ed1723c725e79d46d0b3d5aa0a26"


def _v1_shot(**overrides: object) -> ShotSpec:
    defaults: dict[str, object] = {
        "id": "SH042",
        "schema_version": "2.1",
        "version": 1,
        "scene_id": "SC001",
        "content_basis": ContentBasis(
            basis_type=ContentBasisType.NARRATIVE, basis_version="canon-v7", refs=["event:1"]
        ),
        "purpose": "Reaction close-up",
        "target_duration": 4.0,
        "framing": "close-up",
        "camera": "locked",
        "entity_refs": ["character:maya"],
        "required_continuity": ["costume:v3"],
        "required_reference_roles": [ProductionBindingRole.CHARACTER],
        "allowed_methods": [ProductionMethod.GENERATED_VIDEO],
        "quality_tier": 3,
        "approval_status": CreativeApprovalStatus.APPROVED,
    }
    defaults.update(overrides)
    return ShotSpec(**defaults)


def _v1_binding() -> ProductionBinding:
    return ProductionBinding(
        id="B001",
        schema_version="2.1",
        version=1,
        target_type=ProductionBindingTarget.SHOT,
        target_id="SH042",
        semantic_ref="character:maya",
        production_ref="character-profile:maya-v3",
        role=ProductionBindingRole.CHARACTER,
        asset_refs=["asset:char-master"],
    )


def test_accepted_v1_serialized_bytes_are_unchanged() -> None:
    assert canonical_json_bytes(_v1_shot().model_dump(mode="json")) == _V1_GOLDEN_BYTES


def test_accepted_v1_content_fingerprint_is_unchanged() -> None:
    fingerprint = compute_content_fingerprint(
        shot_spec=_v1_shot(),
        bindings=[_v1_binding()],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )
    assert fingerprint == _V1_GOLDEN_FINGERPRINT


def test_shot_spec_v1_is_the_same_class_as_shot_spec() -> None:
    assert ShotSpecV1 is ShotSpec


# --- ShotSpecV2 -------------------------------------------------------------------------


def _v2_shot(**overrides: object) -> ShotSpecV2:
    defaults: dict[str, object] = {
        "id": "SH042",
        "schema_version": "2.1",
        "version": 1,
        "scene_id": "SC001",
        "content_basis": ContentBasis(
            basis_type=ContentBasisType.NARRATIVE, basis_version="canon-v7", refs=["event:1"]
        ),
        "purpose": "Reaction close-up",
        "target_duration": 4.0,
        "framing": "close-up",
        "camera": "locked",
        "shot_size": ShotSize.CLOSE,
        "camera_angle": CameraAngle.EYE_LEVEL,
        "camera_movement": CameraMovement.STATIC,
        "entity_refs": ["character:maya"],
        "required_continuity": ["costume:v3"],
        "required_reference_roles": [ProductionBindingRole.CHARACTER],
        "allowed_methods": [ProductionMethod.GENERATED_VIDEO],
        "quality_tier": 3,
        "approval_status": CreativeApprovalStatus.APPROVED,
    }
    defaults.update(overrides)
    return ShotSpecV2(**defaults)


def test_shot_size_has_exactly_seven_pinned_values() -> None:
    assert len(ShotSize) == 7


def test_camera_angle_has_exactly_eight_pinned_values() -> None:
    assert len(CameraAngle) == 8


def test_camera_movement_has_exactly_fourteen_pinned_values() -> None:
    assert len(CameraMovement) == 14


def test_shot_spec_v2_preserves_every_v1_field() -> None:
    v2 = _v2_shot()
    assert v2.scene_id == "SC001"
    assert v2.framing == "close-up"
    assert v2.camera == "locked"
    assert v2.purpose == "Reaction close-up"


def test_shot_spec_v2_rejects_an_unknown_shot_size() -> None:
    with pytest.raises(ValidationError):
        _v2_shot(shot_size="not-a-size")


def test_shot_spec_v2_round_trips_exactly() -> None:
    v2 = _v2_shot()
    assert ShotSpecV2.model_validate(v2.model_dump()) == v2


def test_every_v2_semantic_field_changes_the_content_fingerprint() -> None:
    base = compute_content_fingerprint(
        shot_spec=_v2_shot(),
        bindings=[_v1_binding()],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )
    for changed in (
        _v2_shot(shot_size=ShotSize.WIDE),
        _v2_shot(camera_angle=CameraAngle.LOW),
        _v2_shot(camera_movement=CameraMovement.DOLLY_IN),
    ):
        changed_fp = compute_content_fingerprint(
            shot_spec=changed,
            bindings=[_v1_binding()],
            visual_identity_refs=["vip:a"],
            approved_source_asset_refs=["src:a"],
        )
        assert changed_fp != base


def test_v1_and_v2_of_otherwise_identical_content_have_different_fingerprints() -> None:
    # v2 carries strictly more semantic information (shot_size/camera_angle/
    # camera_movement) than v1 ever could, so their fingerprints must differ.
    v1_fp = compute_content_fingerprint(
        shot_spec=_v1_shot(),
        bindings=[_v1_binding()],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )
    v2_fp = compute_content_fingerprint(
        shot_spec=_v2_shot(),
        bindings=[_v1_binding()],
        visual_identity_refs=["vip:a"],
        approved_source_asset_refs=["src:a"],
    )
    assert v1_fp != v2_fp


# --- discriminated AnyShotSpec union ------------------------------------------------------


def test_any_shot_spec_resolves_a_v1_shaped_payload_to_shot_spec_v1() -> None:
    adapter: TypeAdapter[object] = TypeAdapter(cast(type, AnyShotSpec))
    resolved = adapter.validate_python(_v1_shot().model_dump(mode="json"))
    assert isinstance(resolved, ShotSpecV1)
    assert not isinstance(resolved, ShotSpecV2)


def test_any_shot_spec_resolves_a_v2_shaped_payload_to_shot_spec_v2() -> None:
    adapter: TypeAdapter[object] = TypeAdapter(cast(type, AnyShotSpec))
    resolved = adapter.validate_python(_v2_shot().model_dump(mode="json"))
    assert isinstance(resolved, ShotSpecV2)


def test_any_shot_spec_rejects_a_payload_that_is_neither() -> None:
    adapter: TypeAdapter[object] = TypeAdapter(cast(type, AnyShotSpec))
    payload = _v1_shot().model_dump(mode="json")
    payload.pop("scene_id")
    with pytest.raises(ValidationError):
        adapter.validate_python(payload)
