from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from r2.contracts.adaptation import (
    AdaptationAuthorityFamily,
    AdaptationBranchV2,
    AdaptationDecisionAction,
    AdaptationDecisionAuthorization,
    AdaptationDecisionReceipt,
    AdaptationHead,
    AdaptationMapEntry,
    AdaptationMapV2,
    AdaptationOperation,
    AdaptationPolicy,
    AdaptationProfileId,
    AdaptationProfileRef,
    AdmittedScreenplayRef,
    ArtifactVersionRef,
    DecisionRef,
    FindingDisposition,
    MapApprovalCommand,
    MapApprovalDecision,
    ProfileEvaluationReport,
    ProfileFinding,
    ProfileWaiverCommand,
    ScreenplayAdmissionCommand,
    ScreenplayArtifactV2,
    ScreenplayScene,
    ShuangwenAnalysis,
    ShuangwenType,
    WesternDramaAnalysis,
)
from r2.contracts.content_basis import ContentBasis
from r2.contracts.enums import ContentBasisType, CreativeApprovalStatus

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)

CANON_REF = ArtifactVersionRef(artifact_id="canon-1", version=1, content_hash="sha256:" + "a" * 64)
WESTERN_PROFILE_REF = AdaptationProfileRef(
    profile_id=AdaptationProfileId.WESTERN_GENERIC, profile_version="1", policy_pack_digest="sha256:" + "b" * 64
)


def _branch(**overrides: object) -> AdaptationBranchV2:
    defaults: dict[str, object] = {
        "branch_id": "branch-1",
        "schema_version": "r2-adaptation-branch-v2",
        "version": 1,
        "parent_branch_id": None,
        "parent_canon_version": CANON_REF,
        "medium": "short-drama",
        "adaptation_policy": AdaptationPolicy.FAITHFUL,
        "overlay_version": 1,
        "profile_ref": WESTERN_PROFILE_REF,
        "created_at": NOW,
        "created_by": "showrunner-1",
    }
    defaults.update(overrides)
    return AdaptationBranchV2(**defaults)


def _map_entry(**overrides: object) -> AdaptationMapEntry:
    defaults: dict[str, object] = {
        "entry_id": "entry-1",
        "source_refs": ["src-1"],
        "target_refs": ["tgt-1"],
        "operation": AdaptationOperation.PRESERVE,
        "rationale": "kept verbatim",
        "fidelity_risk": "low",
        "approval_status": CreativeApprovalStatus.PROPOSED,
    }
    defaults.update(overrides)
    return AdaptationMapEntry(**defaults)


def _screenplay_scene(**overrides: object) -> ScreenplayScene:
    defaults: dict[str, object] = {
        "scene_id": "sc-1",
        "purpose": "open the story",
        "duration_target": 30.0,
        "location_ref": "loc-1",
        "character_refs": ["hero"],
        "source_mapping_refs": ["entry-1"],
        "dramatic_text": "The hero wakes.",
    }
    defaults.update(overrides)
    return ScreenplayScene(**defaults)


# --- strict enums ----------------------------------------------------------------------


def test_adaptation_profile_id_rejects_an_unknown_value() -> None:
    with pytest.raises(ValidationError):
        AdaptationProfileRef(profile_id="NOT_A_PROFILE", profile_version="1", policy_pack_digest="d")


def test_shuangwen_type_accepts_only_the_six_pinned_values() -> None:
    assert set(ShuangwenType) == {
        ShuangwenType.HARD_TEAR,
        ShuangwenType.REFUSE_TO_SIGN,
        ShuangwenType.EXPOSE_FAKE_ACCOUNT,
        ShuangwenType.FEIGN_WEAKNESS_TO_FISH,
        ShuangwenType.PUBLIC_BET,
        ShuangwenType.BORROW_THIRD_PARTY_FORCE,
    }
    with pytest.raises(ValueError, match="不存在"):
        ShuangwenType("不存在")


def test_adaptation_operation_has_exactly_nine_values() -> None:
    assert len(AdaptationOperation) == 9


# --- immutable models --------------------------------------------------------------------


def test_evidence_models_are_frozen() -> None:
    branch = _branch()
    with pytest.raises(ValidationError):
        branch.branch_id = "other"


def test_decision_models_are_frozen() -> None:
    authorization = AdaptationDecisionAuthorization(
        authenticated_principal="showrunner-1",
        authority_role="HUMAN_SHOWRUNNER",
        action=AdaptationDecisionAction.APPROVE,
        command_identity_hash="sha256:" + "c" * 64,
        approval_receipt="receipt-1",
        authorized_at=NOW,
    )
    with pytest.raises(ValidationError):
        authorization.authenticated_principal = "someone-else"


def test_commands_are_not_frozen() -> None:
    # Commands are plain caller input, not persisted evidence — only evidence/decision
    # models are frozen (plan Task 1: "Evidence/decision models add ConfigDict(frozen=True)").
    command = MapApprovalCommand(
        user_id="u1",
        project_name="proj",
        decision_id="d-1",
        branch_id="branch-1",
        map_ref=CANON_REF,
        profile_ref=WESTERN_PROFILE_REF,
        relied_report_refs=[],
        expected_predecessor_id=None,
        action=AdaptationDecisionAction.APPROVE,
    )
    command.decision_id = "d-2"
    assert command.decision_id == "d-2"


# --- ordered refs ------------------------------------------------------------------------


def test_map_entry_preserves_ref_order_without_sorting() -> None:
    entry = _map_entry(source_refs=["z", "a", "m"], target_refs=["y", "b"])
    assert entry.source_refs == ["z", "a", "m"]
    assert entry.target_refs == ["y", "b"]


def test_map_entry_requires_at_least_one_source_and_target_ref() -> None:
    with pytest.raises(ValidationError):
        _map_entry(source_refs=[])
    with pytest.raises(ValidationError):
        _map_entry(target_refs=[])


# --- complete AdaptationProfileRef --------------------------------------------------------


def test_adaptation_profile_ref_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AdaptationProfileRef(
            profile_id=AdaptationProfileId.WESTERN_GENERIC,
            profile_version="1",
            policy_pack_digest="d",
            extra_field="nope",  # type: ignore[call-arg]
        )


def test_adaptation_profile_ref_requires_every_field() -> None:
    with pytest.raises(ValidationError):
        AdaptationProfileRef(profile_id=AdaptationProfileId.WESTERN_GENERIC, profile_version="1")  # type: ignore[call-arg]


# --- schema selectors ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("factory", "wrong_selector"),
    [
        (lambda selector: _branch(schema_version=selector), "r2-adaptation-branch-v1"),
    ],
)
def test_schema_selector_is_exact(factory, wrong_selector: str) -> None:
    with pytest.raises(ValidationError):
        factory(wrong_selector)


def test_adaptation_map_v2_selector_is_exact() -> None:
    with pytest.raises(ValidationError):
        AdaptationMapV2(
            adaptation_map_id="map-1",
            schema_version="r2-adaptation-map-v1",
            version=1,
            adaptation_branch_ref=CANON_REF,
            entries=[_map_entry()],
            content_hash="sha256:" + "d" * 64,
        )


def test_screenplay_artifact_v2_selector_is_exact() -> None:
    with pytest.raises(ValidationError):
        _screenplay(schema_version="r2-screenplay-artifact-v1")


def _screenplay(**overrides: object) -> ScreenplayArtifactV2:
    defaults: dict[str, object] = {
        "screenplay_id": "sp-1",
        "schema_version": "r2-screenplay-artifact-v2",
        "version": 1,
        "adaptation_branch_ref": CANON_REF,
        "content_basis": ContentBasis(basis_type=ContentBasisType.ADAPTATION, basis_version="1", refs=["r1"]),
        "scenes": [_screenplay_scene()],
        "characters": ["hero"],
        "source_mapping_refs": ["entry-1"],
        "approval_status": CreativeApprovalStatus.PROPOSED,
        "locked_for_direction": False,
        "content_hash": "sha256:" + "e" * 64,
        "adaptation_map_ref": CANON_REF,
    }
    defaults.update(overrides)
    return ScreenplayArtifactV2(**defaults)


# --- exact round trips -----------------------------------------------------------------------


def test_adaptation_branch_v2_round_trips_exactly() -> None:
    branch = _branch()
    assert AdaptationBranchV2.model_validate(branch.model_dump()) == branch


def test_screenplay_artifact_v2_round_trips_exactly() -> None:
    screenplay = _screenplay()
    assert ScreenplayArtifactV2.model_validate(screenplay.model_dump()) == screenplay


def test_adaptation_decision_union_round_trips_by_discriminator() -> None:
    decision = MapApprovalDecision(
        command=MapApprovalCommand(
            user_id="u1",
            project_name="proj",
            decision_id="d-1",
            branch_id="branch-1",
            map_ref=CANON_REF,
            profile_ref=WESTERN_PROFILE_REF,
            relied_report_refs=[],
            expected_predecessor_id=None,
            action=AdaptationDecisionAction.APPROVE,
        ),
        authorization=AdaptationDecisionAuthorization(
            authenticated_principal="showrunner-1",
            authority_role="HUMAN_SHOWRUNNER",
            action=AdaptationDecisionAction.APPROVE,
            command_identity_hash="sha256:" + "c" * 64,
            approval_receipt="receipt-1",
            authorized_at=NOW,
        ),
        sequence=1,
        decision_digest="sha256:" + "f" * 64,
        created_at=NOW,
    )
    restored = MapApprovalDecision.model_validate(decision.model_dump())
    assert restored == decision
    assert restored.decision_kind == "MAP_APPROVAL"


# --- forbidden "latest" ------------------------------------------------------------------------


def test_artifact_version_ref_rejects_a_latest_sentinel_for_version() -> None:
    # There is no "latest" lookup anywhere in the design (spec: "No runtime `latest`
    # lookup for parent Canon, profile, policy, map, screenplay, report, waiver,
    # Director output, candidate or master"). At the contract layer that means
    # `version` is always a real integer — never a "latest" string sentinel.
    with pytest.raises(ValidationError):
        ArtifactVersionRef(artifact_id="x", version="latest", content_hash="sha256:" + "0" * 64)


# --- profile / fidelity separation --------------------------------------------------------------


def test_profile_id_and_policy_are_distinct_types_not_interchangeable() -> None:
    # "WESTERN_GENERIC and CN_SHORT_DRAMA_SHUANGWEN are profile IDs, never fidelity
    # values" (plan Global Constraints) — passing a profile id where a policy is
    # expected must fail, not silently coerce because both are StrEnum-backed strings.
    with pytest.raises(ValidationError):
        _branch(adaptation_policy=AdaptationProfileId.WESTERN_GENERIC)


def test_policy_is_rejected_where_a_profile_id_is_expected() -> None:
    with pytest.raises(ValidationError):
        AdaptationProfileRef(profile_id=AdaptationPolicy.FAITHFUL, profile_version="1", policy_pack_digest="d")


# --- foreign sidecar rejection -----------------------------------------------------------------


def test_western_analysis_rejects_shuangwen_only_fields() -> None:
    # A "foreign" (wrong-profile) sidecar shape is rejected by the type's own
    # strictness (extra="forbid"), not by a later cross-reference check — the two
    # sidecar contracts share no fields by design.
    with pytest.raises(ValidationError):
        WesternDramaAnalysis(
            schema_version="r2-western-drama-analysis-v1",
            content_hash="sha256:" + "1" * 64,
            chapter_start=1,  # type: ignore[call-arg]
            chapter_end=8,  # type: ignore[call-arg]
            shuang_type=ShuangwenType.HARD_TEAR,  # type: ignore[call-arg]
        )


def test_shuangwen_analysis_rejects_western_only_fields() -> None:
    with pytest.raises(ValidationError):
        ShuangwenAnalysis(
            schema_version="r2-shuangwen-analysis-v1",
            content_hash="sha256:" + "2" * 64,
            chapter_start=1,
            chapter_end=8,
            hen_evidence=None,
            shuang_evidence=None,
            ji_evidence=None,
            pan_evidence=None,
            shuang_type=None,
            rubric_observations=["should not be accepted here"],  # type: ignore[call-arg]
        )


def test_shuangwen_analysis_allows_no_evidence_for_a_not_applicable_chapter() -> None:
    analysis = ShuangwenAnalysis(
        schema_version="r2-shuangwen-analysis-v1",
        content_hash="sha256:" + "3" * 64,
        chapter_start=9,
        chapter_end=9,
        hen_evidence=None,
        shuang_evidence=None,
        ji_evidence=None,
        pan_evidence=None,
        shuang_type=None,
        findings=[
            ProfileFinding(
                finding_id="f-1",
                rule_id="hen-shuang-ji-pan",
                rule_version="1",
                disposition=FindingDisposition.NOT_APPLICABLE,
                applicability="CHAPTER",
                severity="LOW",
                target_path="chapters[9]",
                source_span="chapter:9",
            )
        ],
    )
    assert analysis.findings[0].disposition == FindingDisposition.NOT_APPLICABLE


def test_profile_evaluation_report_binds_profile_and_sidecar() -> None:
    report = ProfileEvaluationReport(
        schema_version="r2-profile-evaluation-report-v1",
        artifact_hash="sha256:" + "4" * 64,
        profile_ref=WESTERN_PROFILE_REF,
        evaluator_version="1",
        sidecar_ref=ArtifactVersionRef(artifact_id="sidecar-1", version=1, content_hash="sha256:" + "5" * 64),
        sidecar_digest="sha256:" + "5" * 64,
        report_digest="sha256:" + "6" * 64,
        created_at=NOW,
    )
    assert ProfileEvaluationReport.model_validate(report.model_dump()) == report


# --- heads / receipts (mutable projections, not frozen) -------------------------------------


def test_adaptation_head_is_not_frozen() -> None:
    head = AdaptationHead(
        user_id="u1",
        project_name="proj",
        family=AdaptationAuthorityFamily.MAP_APPROVAL,
        head_key="branch-1",
        latest_decision_id="d-1",
        effective_decision_id="d-1",
        selected_artifact_ref=CANON_REF,
        generation=1,
    )
    head.generation = 2
    assert head.generation == 2


def test_decision_receipt_and_admitted_screenplay_ref_round_trip() -> None:
    receipt = AdaptationDecisionReceipt(
        decision_ref=DecisionRef(decision_id="d-1", decision_digest="sha256:" + "7" * 64),
        family=AdaptationAuthorityFamily.SCREENPLAY_ADMISSION,
        head_key="branch-1",
        outcome="RECORDED",
        current_at_return=True,
    )
    assert AdaptationDecisionReceipt.model_validate(receipt.model_dump()) == receipt

    admitted = AdmittedScreenplayRef(
        screenplay_ref=CANON_REF,
        admission_ref=DecisionRef(decision_id="d-2", decision_digest="sha256:" + "8" * 64),
        profile_ref=WESTERN_PROFILE_REF,
    )
    assert AdmittedScreenplayRef.model_validate(admitted.model_dump()) == admitted


# --- ScreenplayAdmissionCommand / ProfileWaiverCommand shape sanity --------------------------


def test_profile_waiver_command_requires_at_least_one_finding_and_rule_version() -> None:
    with pytest.raises(ValidationError):
        ProfileWaiverCommand(
            user_id="u1",
            project_name="proj",
            decision_id="d-1",
            branch_id="branch-1",
            artifact_ref=CANON_REF,
            profile_ref=WESTERN_PROFILE_REF,
            report_ref=DecisionRef(decision_id="rep-1", decision_digest="sha256:" + "9" * 64),
            finding_ids=[],
            rule_versions=["1"],
            rationale="waived",
            expected_predecessor_id=None,
            action=AdaptationDecisionAction.WAIVE,
        )


def test_screenplay_admission_command_requires_at_least_one_report_ref() -> None:
    with pytest.raises(ValidationError):
        ScreenplayAdmissionCommand(
            user_id="u1",
            project_name="proj",
            decision_id="d-1",
            branch_id="branch-1",
            proposal_ref=CANON_REF,
            admitted_screenplay=_screenplay(),
            profile_ref=WESTERN_PROFILE_REF,
            effective_map_approval_ref=DecisionRef(decision_id="map-1", decision_digest="sha256:" + "a" * 64),
            report_refs=[],
            expected_predecessor_id=None,
            action=AdaptationDecisionAction.ADMIT,
        )
