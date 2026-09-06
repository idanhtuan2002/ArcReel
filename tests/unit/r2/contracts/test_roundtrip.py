import json
from datetime import datetime, timezone
from r2.contracts import (
    ApprovedMaster, CandidateSelectionStatus, ContentBasis, ContentBasisType,
    CreativeApprovalStatus, GenerationCandidate, GenerationLifecycleStatus, MethodDecision,
    ProductionBinding, ProductionBindingRole, ProductionBindingTarget, ProductionMethod,
    ProductionReadiness, PromptPlan, Provenance, ProvenanceActor, ProviderRequest,
    QualityFinding, QualityReport, ReadinessRequirement, ReadinessState, ReviewerType,
    SceneSpec, ShotSpec, VisualIdentityProfile,
)

def _roundtrip(model):
    raw = model.model_dump(mode="json")
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, allow_nan=False)
    restored = type(model).model_validate(json.loads(encoded))
    assert restored == model

def _basis():
    return ContentBasis(basis_type=ContentBasisType.NARRATIVE, basis_version="canon-v7", refs=["event:1"])

def test_foundation_contracts_round_trip():
    _roundtrip(_basis())
    _roundtrip(Provenance(created_by=ProvenanceActor.SYSTEM, source_refs=["source:1"], created_at=datetime(2026,9,6,10,0,tzinfo=timezone.utc)))

def test_scene_and_shot_round_trip():
    _roundtrip(SceneSpec(
        id="SC001", schema_version="2.1", version=1, source_artifact_ref="script:1",
        source_unit_refs=["unit:1"], content_basis=_basis(), purpose="Opening",
        duration_target=20, required_beats=["setup", "reveal"],
        allowed_methods=[ProductionMethod.REUSE], approval_status=CreativeApprovalStatus.APPROVED,
    ))
    _roundtrip(ShotSpec(
        id="SH001", schema_version="2.1", version=1, scene_id="SC001", content_basis=_basis(),
        purpose="Reaction", target_duration=4.0, framing="close-up", camera="locked",
        required_reference_roles=[ProductionBindingRole.CHARACTER],
        allowed_methods=[ProductionMethod.GENERATED_VIDEO], quality_tier=3,
        approval_status=CreativeApprovalStatus.APPROVED,
    ))

def test_preparation_contracts_round_trip():
    binding = ProductionBinding(
        id="B001", schema_version="2.1", version=1, target_type=ProductionBindingTarget.SHOT,
        target_id="SH001", semantic_ref="character:maya", production_ref="character-profile:maya-v3",
        role=ProductionBindingRole.CHARACTER, asset_refs=["asset:char-master"],
    )
    _roundtrip(binding)
    _roundtrip(VisualIdentityProfile(
        id="VIP-MAYA", schema_version="2.1", version=1, semantic_character_ref="character:maya",
        face_master_ref="asset:face", approved_reference_refs=["asset:face"],
    ))
    _roundtrip(ProductionReadiness(
        id="READY-SH001", target_id="SH001",
        requirements=[ReadinessRequirement(
            requirement_id="char", role=ProductionBindingRole.CHARACTER, required=True,
            status=ReadinessState.READY, resolved_binding=binding.id,
        )],
    ))

def test_execution_contracts_round_trip():
    _roundtrip(MethodDecision(
        id="MD-SH001", target_ref="SH001", method=ProductionMethod.GENERATED_VIDEO,
        rationale="motion needed", capability_requirements=["i2v"], cost_class="MEDIUM",
        quality_tier=3, fallback_methods=[ProductionMethod.GENERATED_IMAGE],
    ))
    _roundtrip(PromptPlan(
        id="PP-SH001", schema_version="2.1", version=1, target_ref="SH001",
        semantic_instruction="Maya reacts", positive_prompt="reaction close-up", compiler_version="compiler-v1",
    ))
    _roundtrip(ProviderRequest(
        id="REQ-SH001-1", method_decision_ref="MD-SH001", prompt_plan_ref="PP-SH001",
        provider="seedance", model="2.5", endpoint="i2v",
        payload={"prompt":"hello","nested":[1,True,None,{"x":0.5}]},
        execution_options={"seed":42,"resolution":"1080p"}, adapter_version="adapter-v1",
    ))

def test_result_contracts_round_trip():
    _roundtrip(GenerationCandidate(
        id="CAND-1", target_ref="SH001", content_fingerprint="a"*64, execution_fingerprint="b"*64,
        provider_execution_ref="job:1", output_asset_ref="asset:1",
        lifecycle_state=GenerationLifecycleStatus.GENERATED,
        selection_state=CandidateSelectionStatus.UNREVIEWED,
    ))
    _roundtrip(ApprovedMaster(
        id="MASTER-SH001", target_ref="SH001", selected_candidate_id="CAND-1",
        approval_record="approval:1", selected_at=datetime(2026,9,6,10,0,tzinfo=timezone.utc),
        selected_by="showrunner:1",
    ))
    _roundtrip(QualityReport(
        id="QR-1", target_ref="CAND-1", checks=["identity"], score=0.95,
        blocking_findings=[], advisory_findings=[QualityFinding(code="MINOR",message="tiny drift",blocking=False)],
        reviewer_type=ReviewerType.AGENT, created_at=datetime(2026,9,6,10,0,tzinfo=timezone.utc),
    ))
