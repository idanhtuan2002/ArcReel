import json
from datetime import UTC, datetime

from pydantic import TypeAdapter

from r2.contracts import (
    AnyShotSpec,
    ApprovedMaster,
    CameraAngle,
    CameraMovement,
    CandidateSelectionStatus,
    ContentBasis,
    ContentBasisType,
    CreativeApprovalStatus,
    GenerationCandidate,
    GenerationLifecycleStatus,
    MethodDecision,
    ProductionBinding,
    ProductionBindingRole,
    ProductionBindingTarget,
    ProductionMethod,
    ProductionReadiness,
    PromptPlan,
    Provenance,
    ProvenanceActor,
    ProviderRequest,
    QualityFinding,
    QualityReport,
    ReadinessRequirement,
    ReadinessState,
    ReviewerType,
    SceneSpec,
    ShotSize,
    ShotSpec,
    ShotSpecV2,
    VisualIdentityProfile,
)


def _roundtrip(model):
    raw = model.model_dump(mode="json")
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return type(model).model_validate(json.loads(encoded))


def _basis():
    return ContentBasis(
        basis_type=ContentBasisType.NARRATIVE,
        basis_version="canon-v7",
        refs=["event:1"],
    )


def test_foundation_contracts_round_trip():
    basis = _basis()
    assert _roundtrip(basis) == basis

    provenance = Provenance(
        created_by=ProvenanceActor.SYSTEM,
        source_refs=["source:1"],
        created_at=datetime(2026, 9, 6, 10, 0, tzinfo=UTC),
    )
    assert _roundtrip(provenance) == provenance


def test_scene_and_shot_round_trip():
    scene = SceneSpec(
        id="SC001",
        schema_version="2.1",
        version=1,
        source_artifact_ref="script:1",
        source_unit_refs=["unit:1"],
        content_basis=_basis(),
        purpose="Opening",
        duration_target=20,
        required_beats=["setup", "reveal"],
        allowed_methods=[ProductionMethod.REUSE],
        approval_status=CreativeApprovalStatus.APPROVED,
    )
    assert _roundtrip(scene) == scene

    shot = ShotSpec(
        id="SH001",
        schema_version="2.1",
        version=1,
        scene_id="SC001",
        content_basis=_basis(),
        purpose="Reaction",
        target_duration=4.0,
        framing="close-up",
        camera="locked",
        required_reference_roles=[ProductionBindingRole.CHARACTER],
        allowed_methods=[ProductionMethod.GENERATED_VIDEO],
        quality_tier=3,
        approval_status=CreativeApprovalStatus.APPROVED,
    )
    assert _roundtrip(shot) == shot


def test_shot_spec_v2_round_trips_and_discriminates_from_v1():
    """Dual-read (plan Task 14): ``AnyShotSpec`` round-trips a v2 payload back to the
    exact ``ShotSpecV2`` type, and a v1 payload back to ``ShotSpec`` — the discriminator
    never conflates the two arms."""
    shot_v2 = ShotSpecV2(
        id="SH001",
        schema_version="r2-shot-spec-v2",
        version=1,
        scene_id="SC001",
        content_basis=_basis(),
        purpose="Reaction",
        target_duration=4.0,
        framing="close-up",
        camera="locked",
        shot_size=ShotSize.CLOSE,
        camera_angle=CameraAngle.EYE_LEVEL,
        camera_movement=CameraMovement.STATIC,
        required_reference_roles=[ProductionBindingRole.CHARACTER],
        allowed_methods=[ProductionMethod.GENERATED_VIDEO],
        quality_tier=3,
        approval_status=CreativeApprovalStatus.APPROVED,
    )
    assert _roundtrip(shot_v2) == shot_v2

    shot_v1 = ShotSpec(
        id="SH002",
        schema_version="2.1",
        version=1,
        scene_id="SC001",
        content_basis=_basis(),
        purpose="Reaction",
        target_duration=4.0,
        framing="close-up",
        camera="locked",
        required_reference_roles=[ProductionBindingRole.CHARACTER],
        allowed_methods=[ProductionMethod.GENERATED_VIDEO],
        quality_tier=3,
        approval_status=CreativeApprovalStatus.APPROVED,
    )

    adapter: TypeAdapter[AnyShotSpec] = TypeAdapter(AnyShotSpec)
    raw_v1 = json.dumps(shot_v1.model_dump(mode="json"), sort_keys=True)
    raw_v2 = json.dumps(shot_v2.model_dump(mode="json"), sort_keys=True)
    assert adapter.validate_python(json.loads(raw_v1)) == shot_v1
    assert adapter.validate_python(json.loads(raw_v2)) == shot_v2
    assert type(adapter.validate_python(json.loads(raw_v1))) is ShotSpec
    assert type(adapter.validate_python(json.loads(raw_v2))) is ShotSpecV2


def test_preparation_contracts_round_trip():
    binding = ProductionBinding(
        id="B001",
        schema_version="2.1",
        version=1,
        target_type=ProductionBindingTarget.SHOT,
        target_id="SH001",
        semantic_ref="character:maya",
        production_ref="character-profile:maya-v3",
        role=ProductionBindingRole.CHARACTER,
        asset_refs=["asset:char-master"],
    )
    assert _roundtrip(binding) == binding

    identity = VisualIdentityProfile(
        id="VIP-MAYA",
        schema_version="2.1",
        version=1,
        semantic_character_ref="character:maya",
        face_master_ref="asset:face",
        approved_reference_refs=["asset:face"],
    )
    assert _roundtrip(identity) == identity

    readiness = ProductionReadiness.model_validate(
        {
            "id": "READY-SH001",
            "target_id": "SH001",
            "requirements": [
                ReadinessRequirement(
                    requirement_id="char",
                    role=ProductionBindingRole.CHARACTER,
                    required=True,
                    status=ReadinessState.READY,
                    resolved_binding=binding.id,
                )
            ],
        }
    )
    assert _roundtrip(readiness) == readiness


def test_execution_contracts_round_trip():
    decision = MethodDecision(
        id="MD-SH001",
        target_ref="SH001",
        method=ProductionMethod.GENERATED_VIDEO,
        rationale="motion needed",
        capability_requirements=["i2v"],
        cost_class="MEDIUM",
        quality_tier=3,
        fallback_methods=[ProductionMethod.GENERATED_IMAGE],
    )
    assert _roundtrip(decision) == decision

    prompt = PromptPlan(
        id="PP-SH001",
        schema_version="2.1",
        version=1,
        target_ref="SH001",
        semantic_instruction="Maya reacts",
        positive_prompt="reaction close-up",
        compiler_version="compiler-v1",
    )
    assert _roundtrip(prompt) == prompt

    request = ProviderRequest(
        id="REQ-SH001-1",
        method_decision_ref="MD-SH001",
        prompt_plan_ref="PP-SH001",
        provider="seedance",
        model="2.5",
        endpoint="i2v",
        payload={"prompt": "hello", "nested": [1, True, None, {"x": 0.5}]},
        execution_options={"seed": 42, "resolution": "1080p"},
        adapter_version="adapter-v1",
    )
    assert _roundtrip(request) == request


def test_result_contracts_round_trip():
    candidate = GenerationCandidate(
        id="CAND-1",
        target_ref="SH001",
        content_fingerprint="a" * 64,
        execution_fingerprint="b" * 64,
        provider_execution_ref="job:1",
        output_asset_ref="asset:1",
        lifecycle_state=GenerationLifecycleStatus.GENERATED,
        selection_state=CandidateSelectionStatus.UNREVIEWED,
    )
    assert _roundtrip(candidate) == candidate

    master = ApprovedMaster(
        id="MASTER-SH001",
        target_ref="SH001",
        selected_candidate_id="CAND-1",
        approval_record="approval:1",
        selected_at=datetime(2026, 9, 6, 10, 0, tzinfo=UTC),
        selected_by="showrunner:1",
    )
    assert _roundtrip(master) == master

    report = QualityReport(
        id="QR-1",
        target_ref="CAND-1",
        checks=["identity"],
        score=0.95,
        blocking_findings=[],
        advisory_findings=[
            QualityFinding(
                code="MINOR",
                message="tiny drift",
                blocking=False,
            )
        ],
        reviewer_type=ReviewerType.AGENT,
        created_at=datetime(2026, 9, 6, 10, 0, tzinfo=UTC),
    )
    assert _roundtrip(report) == report
