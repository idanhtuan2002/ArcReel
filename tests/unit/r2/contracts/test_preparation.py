import pytest
from pydantic import ValidationError

from r2.contracts import (
    ProductionBinding,
    ProductionBindingRole,
    ProductionBindingTarget,
    ProductionReadiness,
    ReadinessRequirement,
    ReadinessState,
    VisualIdentityProfile,
)


def test_production_binding_keeps_semantic_and_production_identity_separate():
    binding = ProductionBinding(
        id="B001",
        schema_version="2.1",
        version=1,
        target_type=ProductionBindingTarget.SHOT,
        target_id="SH042",
        semantic_ref="character:maya",
        production_ref="character-profile:maya-v3",
        role=ProductionBindingRole.CHARACTER,
        asset_refs=["asset:b", "asset:a", "asset:b"],
    )
    assert binding.semantic_ref != binding.production_ref
    assert binding.asset_refs == ["asset:a", "asset:b"]


def test_readiness_state_is_derived_from_required_requirements():
    blocked = ProductionReadiness.model_validate(
        {
            "id": "READY-SH042",
            "target_id": "SH042",
            "requirements": [
                ReadinessRequirement(
                    requirement_id="char",
                    role=ProductionBindingRole.CHARACTER,
                    required=True,
                    status=ReadinessState.BLOCKED,
                    reason="character binding missing",
                ),
                ReadinessRequirement(
                    requirement_id="style",
                    role=ProductionBindingRole.STYLE,
                    required=False,
                    status=ReadinessState.BLOCKED,
                    reason="optional style reference missing",
                ),
            ],
        }
    )
    assert blocked.state is ReadinessState.BLOCKED

    ready = ProductionReadiness.model_validate(
        {
            "id": "READY-SH043",
            "target_id": "SH043",
            "requirements": [
                ReadinessRequirement(
                    requirement_id="char",
                    role=ProductionBindingRole.CHARACTER,
                    required=True,
                    status=ReadinessState.READY,
                    resolved_binding="B001",
                ),
                ReadinessRequirement(
                    requirement_id="style",
                    role=ProductionBindingRole.STYLE,
                    required=False,
                    status=ReadinessState.BLOCKED,
                ),
            ],
        }
    )
    assert ready.state is ReadinessState.READY


def test_readiness_rejects_explicit_contradictory_state():
    with pytest.raises(ValidationError, match="contradicts requirements"):
        ProductionReadiness(
            id="READY-SH044",
            target_id="SH044",
            state=ReadinessState.READY,
            requirements=[
                ReadinessRequirement(
                    requirement_id="char",
                    role=ProductionBindingRole.CHARACTER,
                    required=True,
                    status=ReadinessState.BLOCKED,
                    reason="missing",
                )
            ],
        )


def test_readiness_round_trip_preserves_derived_state():
    original = ProductionReadiness.model_validate(
        {
            "id": "READY-SH045",
            "target_id": "SH045",
            "requirements": [
                ReadinessRequirement(
                    requirement_id="char",
                    role=ProductionBindingRole.CHARACTER,
                    required=True,
                    status=ReadinessState.READY,
                    resolved_binding="B045",
                )
            ],
        }
    )
    restored = ProductionReadiness.model_validate(original.model_dump(mode="json"))
    assert restored == original
    assert restored.state is ReadinessState.READY


def test_required_ready_requirement_must_have_resolved_binding():
    with pytest.raises(ValidationError, match="resolved_binding"):
        ReadinessRequirement(
            requirement_id="char",
            role=ProductionBindingRole.CHARACTER,
            required=True,
            status=ReadinessState.READY,
        )


def test_visual_identity_profile_preserves_lock_order():
    profile = VisualIdentityProfile(
        id="VIP-MAYA",
        schema_version="2.1",
        version=1,
        semantic_character_ref="character:maya",
        costume_locks=["jacket", "boots"],
        accessory_locks=["ring", "watch"],
        approved_reference_refs=["asset:b", "asset:a", "asset:b"],
    )
    assert profile.costume_locks == ["jacket", "boots"]
    assert profile.approved_reference_refs == ["asset:a", "asset:b"]
