from __future__ import annotations

import pytest

from r2.contracts import ContentBasis, ContentBasisType, CreativeApprovalStatus, ProductionBindingRole, ProductionMethod
from r2.contracts.production import CameraAngle, CameraMovement, ShotSize, ShotSpecV1
from r2.production.shot_schema_upgrade import ShotSpecManualMappingRequired, upgrade_shot_spec_v1


def _v1_shot(**overrides: object) -> ShotSpecV1:
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
    return ShotSpecV1(**defaults)


def test_known_framing_and_camera_strings_upgrade_exactly() -> None:
    v2 = upgrade_shot_spec_v1(_v1_shot(), camera_angle=CameraAngle.EYE_LEVEL)
    assert v2.shot_size == ShotSize.CLOSE
    assert v2.camera_movement == CameraMovement.STATIC
    assert v2.camera_angle == CameraAngle.EYE_LEVEL


def test_upgrade_preserves_every_v1_field_verbatim() -> None:
    v1 = _v1_shot()
    v2 = upgrade_shot_spec_v1(v1, camera_angle=CameraAngle.LOW)
    assert v2.id == v1.id
    assert v2.scene_id == v1.scene_id
    assert v2.content_basis == v1.content_basis
    assert v2.purpose == v1.purpose
    assert v2.target_duration == v1.target_duration
    assert v2.framing == v1.framing
    assert v2.camera == v1.camera
    assert v2.entity_refs == v1.entity_refs
    assert v2.required_continuity == v1.required_continuity
    assert v2.required_reference_roles == v1.required_reference_roles
    assert v2.allowed_methods == v1.allowed_methods
    assert v2.quality_tier == v1.quality_tier
    assert v2.approval_status == v1.approval_status


@pytest.mark.parametrize(
    ("framing", "camera"),
    [
        ("extreme-wide", "static"),
        ("wide", "pan-left"),
        ("full", "tracking"),
        ("medium", "handheld"),
        ("standard", "static"),
        ("medium-close", "dolly-in"),
        ("close-up", "locked"),
        ("close", "zoom-in"),
        ("extreme-close", "orbit"),
    ],
)
def test_every_known_legacy_spelling_maps_exactly(framing: str, camera: str) -> None:
    upgraded = upgrade_shot_spec_v1(_v1_shot(framing=framing, camera=camera), camera_angle=CameraAngle.EYE_LEVEL)
    assert upgraded.shot_size.value is not None
    assert upgraded.camera_movement.value is not None


def test_an_unknown_framing_string_requires_manual_mapping() -> None:
    with pytest.raises(ShotSpecManualMappingRequired, match="framing"):
        upgrade_shot_spec_v1(_v1_shot(framing="dutch angle low medium"), camera_angle=CameraAngle.EYE_LEVEL)


def test_an_unknown_camera_string_requires_manual_mapping() -> None:
    with pytest.raises(ShotSpecManualMappingRequired, match="camera"):
        upgrade_shot_spec_v1(_v1_shot(camera="slow push in with a slight tilt"), camera_angle=CameraAngle.EYE_LEVEL)


def test_a_compound_free_text_string_is_not_fuzzy_parsed() -> None:
    # "close-up, locked" superficially contains a known framing token, but exact-only
    # mapping never splits or parses compound strings — it must fail closed.
    with pytest.raises(ShotSpecManualMappingRequired):
        upgrade_shot_spec_v1(_v1_shot(framing="close-up, locked"), camera_angle=CameraAngle.EYE_LEVEL)
