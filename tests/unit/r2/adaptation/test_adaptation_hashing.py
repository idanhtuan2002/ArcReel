from __future__ import annotations

import json
from datetime import UTC, datetime

from r2.adaptation.hashing import (
    canonical_adaptation_bytes,
    compute_adaptation_hash,
    compute_decision_identity_hash,
    compute_profile_evaluation_report_digest,
)
from r2.contracts.adaptation import (
    AdaptationDecisionAction,
    AdaptationDecisionAuthorization,
    AdaptationMapEntry,
    AdaptationMapV2,
    AdaptationOperation,
    AdaptationProfileId,
    AdaptationProfileRef,
    ArtifactVersionRef,
    MapApprovalCommand,
    ProfileEvaluationReport,
    ScreenplayArtifactV2,
    ScreenplayScene,
    ShuangwenAnalysis,
    ShuangwenType,
    WesternDramaAnalysis,
)
from r2.contracts.content_basis import ContentBasis
from r2.contracts.enums import ContentBasisType, CreativeApprovalStatus

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
BRANCH_REF = ArtifactVersionRef(artifact_id="branch-1", version=1, content_hash="sha256:" + "a" * 64)
WESTERN_PROFILE_REF = AdaptationProfileRef(
    profile_id=AdaptationProfileId.WESTERN_GENERIC, profile_version="1", policy_pack_digest="sha256:" + "b" * 64
)


def _entry(**overrides: object) -> AdaptationMapEntry:
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


def _map(**overrides: object) -> AdaptationMapV2:
    defaults: dict[str, object] = {
        "adaptation_map_id": "map-1",
        "schema_version": "r2-adaptation-map-v2",
        "version": 1,
        "adaptation_branch_ref": BRANCH_REF,
        "entries": [_entry()],
        "content_hash": "sha256:" + "0" * 64,
    }
    defaults.update(overrides)
    return AdaptationMapV2(**defaults)


def _screenplay(**overrides: object) -> ScreenplayArtifactV2:
    defaults: dict[str, object] = {
        "screenplay_id": "sp-1",
        "schema_version": "r2-screenplay-artifact-v2",
        "version": 1,
        "adaptation_branch_ref": BRANCH_REF,
        "content_basis": ContentBasis(basis_type=ContentBasisType.ADAPTATION, basis_version="1", refs=["r1"]),
        "scenes": [
            ScreenplayScene(
                scene_id="sc-1",
                purpose="open",
                duration_target=30.0,
                location_ref="loc-1",
                character_refs=["hero"],
                source_mapping_refs=["entry-1"],
                dramatic_text="The hero wakes.",
            )
        ],
        "characters": ["hero"],
        "source_mapping_refs": ["entry-1"],
        "approval_status": CreativeApprovalStatus.PROPOSED,
        "locked_for_direction": False,
        "content_hash": "sha256:" + "0" * 64,
        "adaptation_map_ref": BRANCH_REF,
    }
    defaults.update(overrides)
    return ScreenplayArtifactV2(**defaults)


# --- canonical_adaptation_bytes: stable under insertion order --------------------------


def test_canonical_bytes_are_stable_under_dictionary_insertion_order() -> None:
    a = canonical_adaptation_bytes({"z": 1, "a": 2, "m": 3})
    b = canonical_adaptation_bytes({"a": 2, "m": 3, "z": 1})
    assert a == b
    assert json.loads(a) == {"a": 2, "m": 3, "z": 1}


# --- compute_adaptation_hash: map ------------------------------------------------------


def test_map_hash_changes_for_every_semantic_binding() -> None:
    base = compute_adaptation_hash(_map())
    assert base != compute_adaptation_hash(_map(entries=[_entry(rationale="different rationale")]))
    assert base != compute_adaptation_hash(_map(entries=[_entry(operation=AdaptationOperation.OMIT)]))
    assert base != compute_adaptation_hash(_map(entries=[_entry(source_refs=["other-src"])]))
    assert base != compute_adaptation_hash(
        _map(profile_analysis_refs=[ArtifactVersionRef(artifact_id="p1", version=1, content_hash="sha256:" + "c" * 64)])
    )


def test_map_hash_ignores_its_own_storage_id_and_version() -> None:
    # Two submissions of byte-identical semantic content under different
    # adaptation_map_id/version are the same content.
    left = compute_adaptation_hash(_map(adaptation_map_id="map-1", version=1))
    right = compute_adaptation_hash(_map(adaptation_map_id="map-2", version=7))
    assert left == right


def test_map_hash_is_stable_and_deterministic() -> None:
    assert compute_adaptation_hash(_map()) == compute_adaptation_hash(_map())


# --- compute_adaptation_hash: screenplay -----------------------------------------------


def test_screenplay_hash_changes_for_every_semantic_binding() -> None:
    base = compute_adaptation_hash(_screenplay())
    assert base != compute_adaptation_hash(_screenplay(characters=["villain"]))
    assert base != compute_adaptation_hash(_screenplay(locked_for_direction=True))
    assert base != compute_adaptation_hash(_screenplay(approval_status=CreativeApprovalStatus.APPROVED))


def test_screenplay_hash_ignores_its_own_storage_id_and_version() -> None:
    left = compute_adaptation_hash(_screenplay(screenplay_id="sp-1", version=1))
    right = compute_adaptation_hash(_screenplay(screenplay_id="sp-9", version=3))
    assert left == right


# --- compute_adaptation_hash: sidecars -------------------------------------------------


def test_western_analysis_hash_changes_for_every_semantic_binding() -> None:
    base_kwargs: dict[str, object] = {
        "schema_version": "r2-western-drama-analysis-v1",
        "content_hash": "sha256:" + "0" * 64,
    }
    base = compute_adaptation_hash(WesternDramaAnalysis(**base_kwargs))
    changed = compute_adaptation_hash(WesternDramaAnalysis(**base_kwargs, rubric_observations=["a new observation"]))
    assert base != changed


def test_western_analysis_hash_ignores_its_own_content_hash_field() -> None:
    left = compute_adaptation_hash(
        WesternDramaAnalysis(schema_version="r2-western-drama-analysis-v1", content_hash="sha256:" + "1" * 64)
    )
    right = compute_adaptation_hash(
        WesternDramaAnalysis(schema_version="r2-western-drama-analysis-v1", content_hash="sha256:" + "2" * 64)
    )
    assert left == right


def test_shuangwen_analysis_hash_changes_for_shuang_type() -> None:
    base_kwargs: dict[str, object] = {
        "schema_version": "r2-shuangwen-analysis-v1",
        "content_hash": "sha256:" + "0" * 64,
        "chapter_start": 1,
        "chapter_end": 8,
        "hen_evidence": "e1",
        "shuang_evidence": "e2",
        "ji_evidence": "e3",
        "pan_evidence": "e4",
    }
    left = compute_adaptation_hash(ShuangwenAnalysis(**base_kwargs, shuang_type=ShuangwenType.HARD_TEAR))
    right = compute_adaptation_hash(ShuangwenAnalysis(**base_kwargs, shuang_type=ShuangwenType.PUBLIC_BET))
    assert left != right


# --- compute_profile_evaluation_report_digest ------------------------------------------


def test_report_digest_changes_for_every_semantic_binding() -> None:
    def report(**overrides: object) -> ProfileEvaluationReport:
        defaults: dict[str, object] = {
            "schema_version": "r2-profile-evaluation-report-v1",
            "artifact_hash": "sha256:" + "3" * 64,
            "profile_ref": WESTERN_PROFILE_REF,
            "evaluator_version": "1",
            "sidecar_ref": ArtifactVersionRef(artifact_id="side-1", version=1, content_hash="sha256:" + "4" * 64),
            "sidecar_digest": "sha256:" + "4" * 64,
            "report_digest": "sha256:" + "5" * 64,
            "created_at": NOW,
        }
        defaults.update(overrides)
        return ProfileEvaluationReport(**defaults)

    base = compute_profile_evaluation_report_digest(report())
    assert base != compute_profile_evaluation_report_digest(report(evaluator_version="2"))
    assert base != compute_profile_evaluation_report_digest(report(artifact_hash="sha256:" + "6" * 64))


def test_report_digest_ignores_created_at_and_its_own_digest() -> None:
    def report(**overrides: object) -> ProfileEvaluationReport:
        defaults: dict[str, object] = {
            "schema_version": "r2-profile-evaluation-report-v1",
            "artifact_hash": "sha256:" + "3" * 64,
            "profile_ref": WESTERN_PROFILE_REF,
            "evaluator_version": "1",
            "sidecar_ref": ArtifactVersionRef(artifact_id="side-1", version=1, content_hash="sha256:" + "4" * 64),
            "sidecar_digest": "sha256:" + "4" * 64,
            "report_digest": "sha256:" + "5" * 64,
            "created_at": NOW,
        }
        defaults.update(overrides)
        return ProfileEvaluationReport(**defaults)

    from datetime import timedelta

    left = compute_profile_evaluation_report_digest(report())
    right = compute_profile_evaluation_report_digest(
        report(report_digest="sha256:" + "9" * 64, created_at=NOW + timedelta(seconds=1))
    )
    assert left == right


# --- compute_decision_identity_hash ----------------------------------------------------


def _authorization(**overrides: object) -> AdaptationDecisionAuthorization:
    defaults: dict[str, object] = {
        "authenticated_principal": "showrunner-1",
        "authority_role": "HUMAN_SHOWRUNNER",
        "action": AdaptationDecisionAction.APPROVE,
        "command_identity_hash": "sha256:" + "7" * 64,
        "approval_receipt": "receipt-1",
        "authorized_at": NOW,
    }
    defaults.update(overrides)
    return AdaptationDecisionAuthorization(**defaults)


def _command(**overrides: object) -> MapApprovalCommand:
    defaults: dict[str, object] = {
        "user_id": "u1",
        "project_name": "proj",
        "decision_id": "d-1",
        "branch_id": "branch-1",
        "map_ref": BRANCH_REF,
        "profile_ref": WESTERN_PROFILE_REF,
        "relied_report_refs": [],
        "expected_predecessor_id": None,
        "action": AdaptationDecisionAction.APPROVE,
    }
    defaults.update(overrides)
    return MapApprovalCommand(**defaults)


def test_decision_identity_hash_is_deterministic_for_the_same_command_and_authorization() -> None:
    command = _command()
    authorization = _authorization()
    assert compute_decision_identity_hash(command, authorization) == compute_decision_identity_hash(
        command, authorization
    )


def test_decision_identity_hash_changes_when_the_command_changes() -> None:
    authorization = _authorization()
    base = compute_decision_identity_hash(_command(), authorization)
    assert base != compute_decision_identity_hash(_command(decision_id="d-2"), authorization)


def test_decision_identity_hash_changes_when_the_authorization_changes() -> None:
    command = _command()
    base = compute_decision_identity_hash(command, _authorization())
    assert base != compute_decision_identity_hash(command, _authorization(approval_receipt="receipt-2"))
