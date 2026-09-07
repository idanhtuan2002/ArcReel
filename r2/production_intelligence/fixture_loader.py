"""D09 — deterministic loader for the canonical 12-shot mixed-method fixture.

Loads canonical data only. It builds no provider clients and holds no state; the
verification-only Director/execution doubles live in
``scripts/r2/m4_test_doubles.py``, never in this runtime package.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from r2.contracts import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityObservation,
    ContentBasis,
    ContentBasisType,
    CreativeApprovalStatus,
    DirectorKind,
    ExecutionType,
    IdentityConstraint,
    IdentityScopeType,
    IdentityStrength,
    ProductionBinding,
    ProductionBindingRole,
    ProductionBindingTarget,
    ProductionMethod,
    Provenance,
    ProvenanceActor,
    SceneSpec,
    ShotSpec,
    VisualIdentityProfile,
)

_EPOCH = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)

_METHOD_FEATURE: dict[ProductionMethod, str] = {
    ProductionMethod.REUSE: "ASSET_REUSE",
    ProductionMethod.STOCK: "STOCK_LIBRARY",
    ProductionMethod.SCREEN_CAPTURE: "SCREEN_CAPTURE",
    ProductionMethod.DETERMINISTIC: "DETERMINISTIC_RENDER",
    ProductionMethod.GENERATED_IMAGE: "IMAGE_OUTPUT",
    ProductionMethod.GENERATED_VIDEO: "VIDEO_OUTPUT",
    ProductionMethod.COMPOSITE: "COMPOSITE_ASSEMBLY",
}


@dataclass(frozen=True)
class M4ShotCase:
    shot: ShotSpec
    scene: SceneSpec
    director: DirectorKind
    method: ProductionMethod
    content_basis: ContentBasis
    bindings: tuple[ProductionBinding, ...]
    identity_profiles: tuple[VisualIdentityProfile, ...]
    descriptor: CapabilityDescriptor
    observation: CapabilityObservation
    allowed_methods: tuple[ProductionMethod, ...]
    source_authenticity_required: bool
    reusable_asset_current: bool
    deterministic_equivalent_available: bool
    paid: bool
    requires_approval: bool

    @property
    def scope_ancestry(self) -> dict[IdentityScopeType, str]:
        """The scope refs this shot descends from, for identity resolution."""
        return {
            IdentityScopeType.SCENE: self.scene.id,
            IdentityScopeType.SHOT: self.shot.id,
        }


@dataclass(frozen=True)
class M4GoldenFixture:
    fixture_id: str
    cases: tuple[M4ShotCase, ...]

    def by_id(self, shot_id: str) -> M4ShotCase:
        for case in self.cases:
            if case.shot.id == shot_id:
                return case
        raise KeyError(shot_id)


def _default_path() -> Path:
    return Path(__file__).with_name("fixtures") / "m4_golden_12_shots.json"


def load_m4_golden_12(path: Path | None = None) -> M4GoldenFixture:
    data = json.loads((path or _default_path()).read_text(encoding="utf-8"))
    cases = tuple(_build_case(entry) for entry in data["shots"])
    _validate(cases)
    return M4GoldenFixture(fixture_id=data["fixture_id"], cases=cases)


def _build_case(entry: dict[str, object]) -> M4ShotCase:
    shot_id = str(entry["id"])
    director = DirectorKind(str(entry["director"]))
    method = ProductionMethod(str(entry["method"]))
    basis_type = ContentBasisType(str(entry["content_basis_type"]))
    needs_identity = bool(entry["needs_character_identity"])
    paid = bool(entry["paid"])
    allowed_raw = entry["allowed_methods"]
    if not isinstance(allowed_raw, list):
        raise ValueError(f"{shot_id}: allowed_methods must be a list")
    allowed = tuple(ProductionMethod(str(m)) for m in allowed_raw)
    source_authenticity_required = bool(entry["source_authenticity_required"])
    reusable_asset_current = bool(entry["reusable_asset_current"])
    deterministic_equivalent_available = bool(entry["deterministic_equivalent_available"])

    basis = ContentBasis(
        basis_type=basis_type,
        basis_version="golden-12-v1",
        refs=["research:RP-12"] if basis_type is ContentBasisType.FACTUAL else ["event:EVT-12"],
    )
    scene = SceneSpec(
        id=f"SC-{shot_id}",
        schema_version="1",
        version=1,
        source_artifact_ref="SCRIPT-GOLDEN-12",
        source_unit_refs=[f"SEC-{shot_id}"],
        content_basis=basis,
        purpose=f"Scene for {shot_id}",
        duration_target=6.0,
        required_beats=[f"beat:{shot_id}"],
        allowed_methods=list(allowed),
        approval_status=CreativeApprovalStatus.APPROVED,
    )
    shot = ShotSpec(
        id=shot_id,
        schema_version="1",
        version=1,
        scene_id=scene.id,
        content_basis=basis,
        purpose=f"Visualize {shot_id}",
        target_duration=6.0,
        framing="standard",
        camera="static",
        audio_intent="narration",
        required_reference_roles=[ProductionBindingRole.CHARACTER] if needs_identity else [],
        allowed_methods=[method],
        quality_tier=1,
        approval_status=CreativeApprovalStatus.APPROVED,
    )

    bindings: tuple[ProductionBinding, ...] = ()
    identity_profiles: tuple[VisualIdentityProfile, ...] = ()
    hard_features = [_METHOD_FEATURE[method]]
    if needs_identity:
        bindings = (
            ProductionBinding(
                id=f"B-{shot_id}",
                schema_version="1",
                version=1,
                target_type=ProductionBindingTarget.SHOT,
                target_id=shot_id,
                semantic_ref="character:lead",
                production_ref="character-profile:lead-v1",
                role=ProductionBindingRole.CHARACTER,
                asset_refs=[f"asset:{shot_id}-char"],
            ),
        )
        identity_profiles = (
            VisualIdentityProfile(
                id=f"VIP-{shot_id}",
                schema_version="1",
                version=1,
                semantic_character_ref="character:lead",
                scope_type=IdentityScopeType.SCENE,
                scope_ref=scene.id,
                identity_constraints=[
                    IdentityConstraint(
                        semantic_key="hairstyle",
                        strength=IdentityStrength.LOCKED,
                        semantic_value="short crop",
                    )
                ],
            ),
        )
        hard_features.append("CHARACTER_REFERENCE")

    descriptor = CapabilityDescriptor(
        capability_id=f"cap:{shot_id.lower()}",
        adapter_id=f"adapter:{shot_id.lower()}",
        provider_id="local" if not paid else "cloud",
        execution_type=ExecutionType.API if paid else ExecutionType.LOCAL,
        supported_methods=[method],
        typed_features=sorted(set(hard_features)),
        descriptor_source="golden-12-catalog",
        descriptor_version="cat-12-v1",
        provenance=Provenance(created_by=ProvenanceActor.SYSTEM, created_at=_EPOCH),
    )
    observation = CapabilityObservation(
        capability_id=descriptor.capability_id,
        observation_class="HARD_DYNAMIC_AVAILABILITY",
        availability=CapabilityAvailability.AVAILABLE,
        credentials_ready=True,
        endpoint_healthy=True,
        runtime_dependencies_ready=True,
        observed_at=_EPOCH,
        observation_version=f"{descriptor.capability_id}-obs-1",
    )

    return M4ShotCase(
        shot=shot,
        scene=scene,
        director=director,
        method=method,
        content_basis=basis,
        bindings=bindings,
        identity_profiles=identity_profiles,
        descriptor=descriptor,
        observation=observation,
        allowed_methods=allowed,
        source_authenticity_required=source_authenticity_required,
        reusable_asset_current=reusable_asset_current,
        deterministic_equivalent_available=deterministic_equivalent_available,
        paid=paid,
        requires_approval=method is ProductionMethod.GENERATED_VIDEO,
    )


def _validate(cases: tuple[M4ShotCase, ...]) -> None:
    if len(cases) != 12:
        raise ValueError(f"golden-12 must have exactly 12 shots, got {len(cases)}")
    if len({c.shot.id for c in cases}) != 12:
        raise ValueError("golden-12 shot ids must be unique")
    if {c.director for c in cases} != set(DirectorKind):
        raise ValueError("golden-12 must exercise all three Directors")
    if {c.method for c in cases} != set(ProductionMethod):
        raise ValueError("golden-12 must exercise all seven ProductionMethods")
    for case in cases:
        if case.method not in case.allowed_methods:
            raise ValueError(f"{case.shot.id}: expected method {case.method.value} missing from allowed_methods")
        if len(case.allowed_methods) < 2:
            raise ValueError(f"{case.shot.id}: needs >=2 allowed_methods so routing proves an authoritative choice")
