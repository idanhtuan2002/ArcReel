import pytest
from pydantic import ValidationError

from r2.contracts import (
    ContentBasis,
    ContentBasisType,
    CreativeApprovalStatus,
    ProductionBindingRole,
    ProductionMethod,
    SceneSpec,
    ShotSpec,
)


def _basis():
    return ContentBasis(
        basis_type=ContentBasisType.NARRATIVE,
        basis_version="canon-v7",
        refs=["event:1"],
    )


def test_scene_spec_requires_content_basis_and_rejects_provider_fields():
    scene = SceneSpec(
        id="SC001",
        schema_version="2.1",
        version=1,
        source_artifact_ref="screenplay:7",
        source_unit_refs=["beat:2", "beat:1", "beat:2"],
        content_basis=_basis(),
        purpose="Establish the confrontation",
        duration_target=30.0,
        entity_refs=["char:b", "char:a", "char:b"],
        required_beats=["reveal", "reaction"],
        continuity_requirements=["costume:v3"],
        allowed_methods=[
            ProductionMethod.REUSE,
            ProductionMethod.GENERATED_VIDEO,
        ],
        approval_status=CreativeApprovalStatus.APPROVED,
    )
    assert scene.source_unit_refs == ["beat:1", "beat:2"]
    assert scene.entity_refs == ["char:a", "char:b"]

    with pytest.raises(ValidationError):
        SceneSpec(**scene.model_dump(), provider="seedance")


def test_shot_spec_requires_positive_duration_and_rejects_provider_fields():
    shot = ShotSpec(
        id="SH042",
        schema_version="2.1",
        version=1,
        scene_id="SC001",
        content_basis=_basis(),
        purpose="Reaction close-up",
        target_duration=4.0,
        framing="close-up",
        camera="locked",
        entity_refs=["char:a"],
        required_continuity=["costume:v3"],
        required_reference_roles=[ProductionBindingRole.CHARACTER],
        allowed_methods=[ProductionMethod.GENERATED_VIDEO],
        quality_tier=3,
        approval_status=CreativeApprovalStatus.APPROVED,
    )
    assert shot.target_duration == 4.0

    with pytest.raises(ValidationError):
        ShotSpec(**shot.model_dump(), model="h3")

    with pytest.raises(ValidationError):
        ShotSpec(**{**shot.model_dump(), "target_duration": 0})


def test_required_beat_order_is_preserved():
    scene = SceneSpec(
        id="SC002",
        schema_version="2.1",
        version=1,
        source_artifact_ref="screenplay:7",
        source_unit_refs=["beat:1"],
        content_basis=_basis(),
        purpose="Escalation",
        duration_target=40,
        required_beats=["first", "second", "third"],
        allowed_methods=[ProductionMethod.DETERMINISTIC],
        approval_status=CreativeApprovalStatus.DRAFT,
    )
    assert scene.required_beats == ["first", "second", "third"]
