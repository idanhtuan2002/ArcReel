"""Pure quality contracts validate bindings without granting runtime authority."""

from __future__ import annotations

import copy
import importlib
from datetime import UTC, datetime, timedelta
from itertools import permutations
from typing import Any

import pytest
from pydantic import ValidationError

from r2.artifact_identity import episode_video_key

DIGEST = "sha256:" + "a" * 64
UUID = "0199f00d-0000-7000-8000-000000000001"
OTHER_UUID = "0199f00d-0000-7000-8000-000000000002"
NOW = datetime(2026, 10, 26, tzinfo=UTC)


def policy_data() -> dict[str, Any]:
    return {
        "schema_id": "m10.quality-policy.v1",
        "rule_ids": ["probe", "review", "fresh"],
        "probe_rules": [
            {
                "rule_id": "probe",
                "probe_kind": "layout",
                "tool_identity": "ffprobe",
                "tool_version_constraint": "7",
                "config_schema_id": "layout.v1",
                "config_digest": DIGEST,
                "applicability_policy_id": "apply",
                "applicability_policy_digest": DIGEST,
                "threshold_policy_id": "threshold",
                "threshold_policy_digest": DIGEST,
                "max_runtime_ms": 1000,
                "max_output_bytes": 4096,
            }
        ],
        "assessment_requirements": [
            {
                "requirement_id": "review-required",
                "mode": "ALL",
                "slots": [
                    {
                        "slot_id": "human",
                        "kind": "NARRATIVE",
                        "assessor_class": "HUMAN",
                        "qualification_policy_id": "qualified",
                        "qualification_policy_digest": DIGEST,
                        "rule_ids": ["review"],
                        "allowed_applicability_states": ["PASS", "FAIL", "INDETERMINATE", "INAPPLICABLE"],
                        "producer_conflict_forbidden": True,
                        "required_independence_groups": 1,
                    }
                ],
                "minimum_satisfied_slots": 1,
                "disagreement_policy_id": "disagree",
                "disagreement_policy_digest": DIGEST,
                "escalation_requirement_id": None,
            }
        ],
        "freshness_rules": [
            {
                "rule_id": "fresh",
                "evidence_kind": "NARRATIVE",
                "max_age_seconds": 60,
                "supersession_effect": "REEVALUATE_CURRENT",
            }
        ],
        "disposition_rule": {
            "max_disposition_ttl_seconds": 604800,
            "max_waiver_ttl_seconds": 86400,
            "waiverable_rule_ids": ["review"],
            "non_waiverable_failure_codes": ["IDENTITY_INVALID"],
        },
        "accessibility_rules": [
            {
                "conformance_target": "WCAG-AA",
                "language": "vi",
                "caption_rubric_id": "captions",
                "caption_rubric_digest": DIGEST,
                "audio_description_policy_id": "description",
                "audio_description_policy_digest": DIGEST,
            }
        ],
        "reference_eligibility_policy_id": "reference",
        "reference_eligibility_policy_digest": DIGEST,
    }


def metadata_data(resource: str, *, dependencies: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "metadata_schema_version": "1",
        "contract_ref": {"contract_type": "ShotSpec", "id": resource, "version": 3, "schema_version": "1"},
        "content_basis": {"basis_type": "NARRATIVE", "basis_version": "1", "refs": ["story:source"]},
        "direct_dependencies": dependencies or [],
        "content_fingerprint": "sha256:" + "f" * 64,
        "approved_master": {
            "selected_candidate_id": "CAND-" + resource + "-V1",
            "host_version_ref": "2",
            "approval_record": "approval-" + resource,
            "selected_at": "2026-10-26T00:00:00Z",
            "selected_by": "human",
        },
    }


def binding_data() -> dict[str, Any]:
    root, child = episode_video_key(1, "FINAL"), episode_video_key(1, "SH01")

    def head(key: str, resource: str, digit: str) -> dict[str, Any]:
        return {
            "artifact_key": key,
            "master_version": 7,
            "candidate_id": "m7c:" + digit * 40,
            "object_ref": "private/" + resource,
            "content_digest": digit * 64,
            "approval_record": "approval-" + resource,
        }

    return {
        "schema_id": "m10.master-binding.v1",
        "user_id": "owner",
        "project_name": "project",
        "root": head(root, "FINAL", "1"),
        "dependency_heads": [head(child, "SH01", "2")],
        "metadata_snapshots": [
            {
                "artifact_key": root,
                "body": metadata_data(
                    "FINAL",
                    dependencies=[
                        {"ref": "master:SH01", "version": "CAND-SH01-V1@2", "fingerprint": "sha256:" + "2" * 64}
                    ],
                ),
                "metadata_digest": DIGEST,
            },
            {"artifact_key": child, "body": metadata_data("SH01"), "metadata_digest": DIGEST},
        ],
        "dependency_edges": [
            {"parent_artifact_key": root, "child_artifact_key": child, "dependency_ref": "master:SH01"}
        ],
    }


def draft_data() -> dict[str, Any]:
    return {
        "user_id": "owner",
        "project_name": "project",
        "profile_id": UUID,
        "revision": 1,
        "parent_revision": None,
        "cohort_id": "cohort",
        "product_surface": "video",
        "policy": policy_data(),
        "policy_digest": DIGEST,
        "supersession_effect": "HISTORICAL_ONLY",
        "created_by": "actor",
        "created_at": NOW,
    }


def disposition_data(*, decision: str = "PASS", seconds: int = 60) -> dict[str, Any]:
    return {
        "disposition_id": UUID,
        "subject_digest": DIGEST,
        "quality_run_id": UUID,
        "quality_run_digest": DIGEST,
        "profile_id": UUID,
        "profile_revision": 1,
        "profile_digest": DIGEST,
        "decision": decision,
        "waiver_bindings": [],
        "issuer_id": "actor",
        "custodian_authorization_id": "grant",
        "custodian_policy_id": "policy",
        "custodian_policy_version": "1",
        "custodian_evidence_digest": DIGEST,
        "custodian_admitted_at": NOW,
        "reason": "Reviewed",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(seconds=seconds),
        "supersedes_disposition_id": None,
    }


def subject_data() -> dict[str, Any]:
    return {
        "master_binding": binding_data(),
        "master_binding_digest": DIGEST,
        "artifact_ref": "private/FINAL",
        "artifact_digest": "sha256:" + "1" * 64,
        "content_basis_digest": DIGEST,
        "caption_digest": None,
        "audio_digest": None,
    }


def observation_data(kind: str = "TECHNICAL") -> dict[str, Any]:
    common = {
        "observation_id": UUID,
        "observation_type": kind,
        "requirement_id": "review-required",
        "slot_id": "human",
        "assessor_identity": "reviewer",
        "assessor_version": "1",
        "assessor_qualification_ref": "qualification",
        "assessor_qualification_digest": DIGEST,
        "independence_group": "independent",
        "producer_conflict": False,
        "config_digest": DIGEST,
        "subject_digest": DIGEST,
        "status": "PASS",
        "findings": [],
        "evidence_refs": ["evidence"],
        "evidence_digest": DIGEST,
        "observed_at": NOW,
    }
    variants = {
        "TECHNICAL": {
            "rule_id": "probe",
            "probe_receipt_ref": "receipt",
            "probe_receipt_digest": DIGEST,
            "tool_identity_digest": DIGEST,
            "measurement_schema_id": "measurement.v1",
            "measurement_digest": DIGEST,
            "interval_evidence_digest": None,
        },
        "FACTUAL": {
            "claim_ledger_projection_ref": "claims",
            "claim_ledger_projection_digest": DIGEST,
            "research_pack_ref": "research",
            "research_pack_digest": DIGEST,
            "correction_head_digest": DIGEST,
            "coverage_digest": DIGEST,
            "withdrawn": False,
        },
        "NARRATIVE": {
            "rubric_id": "rubric",
            "rubric_digest": DIGEST,
            "segment_closure_digest": DIGEST,
            "reviewer_evidence_digest": DIGEST,
        },
        "CONTINUITY": {
            "canon_projection_digest": DIGEST,
            "epistemic_projection_digest": DIGEST,
            "visual_identity_projection_digest": DIGEST,
            "invariant_ids": ["invariant"],
        },
        "PERCEPTUAL_REGRESSION": {
            "reference_relationship": "eligible-reference",
            "reference_subject_digest": DIGEST,
            "distorted_subject_digest": DIGEST,
            "alignment_policy_digest": DIGEST,
            "model_identity_digest": DIGEST,
            "segment_result_digest": DIGEST,
        },
        "PERCEPTUAL_REVIEW": {
            "rubric_id": "rubric",
            "rubric_digest": DIGEST,
            "model_or_human_identity_digest": DIGEST,
            "calibration_cohort_digest": DIGEST,
            "sampling_policy_digest": DIGEST,
        },
        "ACCESSIBILITY": {
            "conformance_target": "WCAG-AA",
            "language": "vi",
            "caption_artifact_digest": None,
            "audio_description_artifact_digest": None,
            "speech_coverage_digest": DIGEST,
            "non_speech_coverage_digest": DIGEST,
            "synchronization_digest": DIGEST,
            "legibility_collision_digest": DIGEST,
        },
    }
    return common | variants[kind]


def command_data(operation: str) -> dict[str, Any]:
    return {
        "user_id": "owner",
        "project_name": "project",
        "actor_id": "actor",
        "operation": operation,
        "command_id": "command",
        "request_digest": DIGEST,
    }


def completion_data() -> dict[str, Any]:
    return {
        "user_id": "owner",
        "project_name": "project",
        "actor_id": "actor",
        "run_id": UUID,
        "subject": subject_data(),
        "subject_digest": DIGEST,
        "profile_id": UUID,
        "profile_revision": 1,
        "profile_digest": DIGEST,
        "observations": [
            {
                "observation_id": UUID,
                "observation_type": "TECHNICAL",
                "observation_digest": DIGEST,
                "requirement_id": "review-required",
                "slot_id": "human",
            }
        ],
        "observation_closure_digest": DIGEST,
        "requirements_digest": DIGEST,
        "execution_refs": ["execution"],
    }


@pytest.mark.parametrize(
    "kind",
    ["TECHNICAL", "FACTUAL", "NARRATIVE", "CONTINUITY", "PERCEPTUAL_REGRESSION", "PERCEPTUAL_REVIEW", "ACCESSIBILITY"],
)
def test_closed_observation_union_retains_every_variant_field(kind: str) -> None:
    q = importlib.import_module("r2.contracts.quality")
    from pydantic import TypeAdapter

    adapter = TypeAdapter(q.QualityObservation)
    observation = adapter.validate_python(observation_data(kind))
    assert observation.observation_type == kind
    assert adapter.validate_json(adapter.dump_json(observation)) == observation
    with pytest.raises(ValidationError):
        adapter.validate_python(observation_data(kind) | {"observation_type": "EXPORT"})
    with pytest.raises(ValidationError):
        adapter.validate_python(observation_data(kind) | {"provider": "unbound"})


@pytest.mark.parametrize("change", ["scope", "actor", "revision", "operation"])
def test_publication_request_requires_complete_draft_command_and_parent_binding(change: str) -> None:
    q = importlib.import_module("r2.contracts.quality")
    subject = {
        "user_id": "owner",
        "project_name": "project",
        "actor_id": "actor",
        "profile_draft": draft_data(),
        "profile_draft_digest": DIGEST,
        "expected_profile_revision": 0,
    }
    command = command_data("PUBLISH_PROFILE")
    valid = q.ProfilePublicationAuthorizationRequest.model_validate({"command": command, "subject": subject})
    assert q.ProfilePublicationAuthorizationRequest.model_validate_json(valid.model_dump_json()) == valid
    if change == "scope":
        command["project_name"] = "other"
    elif change == "actor":
        subject["profile_draft"]["created_by"] = "other"
    elif change == "revision":
        subject["expected_profile_revision"] = 1
    else:
        command["operation"] = "ISSUE_DISPOSITION"
    with pytest.raises(ValidationError):
        q.ProfilePublicationAuthorizationRequest.model_validate({"command": command, "subject": subject})


@pytest.mark.parametrize(
    "change", ["actor", "master_scope", "duplicate_observation", "duplicate_execution", "operation"]
)
def test_completion_request_retains_identity_profile_and_tagged_observation_closure(change: str) -> None:
    q = importlib.import_module("r2.contracts.quality")
    subject = completion_data()
    command = command_data("COMPLETE_RUN")
    valid = q.CompleteRunCommand.model_validate({"command": command, "subject": subject})
    assert valid.subject.run_id == UUID
    assert valid.subject.profile_revision == 1
    assert q.CompleteRunCommand.model_validate_json(valid.model_dump_json()) == valid
    if change == "actor":
        command["actor_id"] = "other"
    elif change == "master_scope":
        subject["subject"]["master_binding"]["user_id"] = "other"
    elif change == "duplicate_observation":
        subject["observations"].append(copy.deepcopy(subject["observations"][0]))
    elif change == "duplicate_execution":
        subject["execution_refs"].append("execution")
    else:
        command["operation"] = "PUBLISH_PROFILE"
    with pytest.raises(ValidationError):
        q.CompleteRunCommand.model_validate({"command": command, "subject": subject})


def test_request_expiry_is_absolute_intent_without_a_constructor_clock() -> None:
    q = importlib.import_module("r2.contracts.quality")
    subject = {
        "user_id": "owner",
        "project_name": "project",
        "actor_id": "actor",
        "subject_digest": DIGEST,
        "quality_run_id": UUID,
        "quality_run_digest": DIGEST,
        "profile_id": UUID,
        "profile_revision": 1,
        "profile_digest": DIGEST,
        "decision": "PASS",
        "waiver_bindings": [],
        "reason": "Reviewed",
        "requested_expires_at": datetime(2099, 1, 1, tzinfo=UTC),
        "expected_disposition_version": 0,
    }
    value = q.DispositionAuthorizationRequest.model_validate(
        {"command": command_data("ISSUE_DISPOSITION"), "subject": subject}
    )
    assert value.subject.requested_expires_at.year == 2099
    with pytest.raises(ValidationError):
        q.DispositionSubject.model_validate(subject | {"requested_expires_at": datetime(2099, 1, 1)})
    with pytest.raises(ValidationError):
        q.DispositionAuthorizationRequest.model_validate({"command": command_data("COMPLETE_RUN"), "subject": subject})


@pytest.mark.parametrize(
    "change", ["duplicate_slot", "parallel_digests", "missing_union", "unknown_escalation", "double_count"]
)
def test_run_local_refs_do_not_double_count_or_lose_observations(change: str) -> None:
    q = importlib.import_module("r2.contracts.quality")
    slot = {
        "requirement_id": "review-required",
        "slot_id": "human",
        "observation_refs": [UUID],
        "observation_digests": [DIGEST],
        "distinct_independence_groups": ["independent"],
        "state": "SATISFIED",
        "escalation_observation_refs": [],
    }
    run = {
        "run_id": UUID,
        "subject": subject_data(),
        "subject_digest": DIGEST,
        "profile_id": UUID,
        "profile_revision": 1,
        "profile_digest": DIGEST,
        "observation_refs": [UUID],
        "observation_closure_digest": DIGEST,
        "slot_results": [slot],
        "requirements_digest": DIGEST,
        "execution_refs": ["execution"],
        "completed_at": NOW,
    }
    assert q.QualityRun.model_validate(run).slot_results[0].state == "SATISFIED"
    if change == "duplicate_slot":
        run["slot_results"].append(copy.deepcopy(slot))
    elif change == "parallel_digests":
        slot["observation_digests"] = []
    elif change == "missing_union":
        run["observation_refs"].append(OTHER_UUID)
    elif change == "unknown_escalation":
        slot["escalation_observation_refs"] = [OTHER_UUID]
    else:
        run["slot_results"].append(slot | {"slot_id": "other"})
    with pytest.raises(ValidationError):
        q.QualityRun.model_validate(run)


def test_policy_roundtrips_frozen_and_preserves_declared_order() -> None:
    q = importlib.import_module("r2.contracts.quality")
    data = policy_data()
    policy = q.QualityPolicyV1.model_validate(data)
    data["rule_ids"].append("later")
    assert policy.rule_ids == ("probe", "review", "fresh")
    assert q.QualityPolicyV1.model_validate_json(policy.model_dump_json()) == policy
    with pytest.raises(ValidationError):
        policy.rule_ids = ()
    with pytest.raises(ValidationError):
        q.QualityPolicyV1.model_validate(policy_data() | {"extra": True})


@pytest.mark.parametrize("family", ["probe", "freshness", "slot", "waiverable"])
@pytest.mark.parametrize("change", ["unknown", "duplicate"])
def test_policy_catalog_closes_every_rule_reference(family: str, change: str) -> None:
    q = importlib.import_module("r2.contracts.quality")
    data = policy_data()
    if family in {"probe", "freshness"}:
        rows = data[family + "_rules"]
        if change == "unknown":
            rows[0]["rule_id"] = "unknown"
        else:
            rows.append(copy.deepcopy(rows[0]))
    else:
        rows = (
            data["assessment_requirements"][0]["slots"][0]["rule_ids"]
            if family == "slot"
            else data["disposition_rule"]["waiverable_rule_ids"]
        )
        rows.append("unknown" if change == "unknown" else rows[0])
    with pytest.raises(ValidationError):
        q.QualityPolicyV1.model_validate(data)


@pytest.mark.parametrize("value", [True, "1", 1.0, 0])
def test_policy_counts_require_strict_positive_integers(value: object) -> None:
    q = importlib.import_module("r2.contracts.quality")
    data = policy_data()
    data["probe_rules"][0]["max_runtime_ms"] = value
    with pytest.raises(ValidationError):
        q.QualityPolicyV1.model_validate(data)


@pytest.mark.parametrize(
    "change",
    ["catalog_duplicate", "empty_slots", "bad_n_of_m", "unknown_escalation", "cyclic_escalation", "duplicate_slot"],
)
def test_requirement_graph_refuses_invalid_counts_references_and_cycles(change: str) -> None:
    q = importlib.import_module("r2.contracts.quality")
    data = policy_data()
    requirement = data["assessment_requirements"][0]
    if change == "catalog_duplicate":
        data["rule_ids"].append("probe")
    elif change == "empty_slots":
        requirement["slots"] = []
    elif change == "bad_n_of_m":
        requirement.update(mode="N_OF_M", minimum_satisfied_slots=2)
    elif change == "unknown_escalation":
        requirement["escalation_requirement_id"] = "missing"
    elif change == "cyclic_escalation":
        requirement["escalation_requirement_id"] = requirement["requirement_id"]
    else:
        requirement["slots"].append(copy.deepcopy(requirement["slots"][0]))
        requirement["minimum_satisfied_slots"] = 2
    with pytest.raises(ValidationError):
        q.QualityPolicyV1.model_validate(data)


def test_same_rule_may_cross_families_and_distinct_freshness_kinds() -> None:
    q = importlib.import_module("r2.contracts.quality")
    data = policy_data()
    data["probe_rules"][0]["rule_id"] = "review"
    data["freshness_rules"].append(data["freshness_rules"][0] | {"evidence_kind": "CONTINUITY"})
    assert len(q.QualityPolicyV1.model_validate(data).freshness_rules) == 2


def test_master_binding_preserves_distinct_candidate_and_version_namespaces_immutably() -> None:
    q = importlib.import_module("r2.contracts.quality")
    data = binding_data()
    binding = q.MasterBindingV1.model_validate(data)
    data["metadata_snapshots"][0]["body"]["content_basis"]["refs"].append("changed")
    assert "changed" not in binding.metadata_snapshots[0].body.model_dump_json()
    assert q.MasterBindingV1.model_validate_json(binding.model_dump_json()) == binding
    assert binding.root.master_version == 7
    assert binding.root.candidate_id.startswith("m7c:")
    for snapshot in binding.metadata_snapshots:
        body = snapshot.body.model_dump(mode="json")
        assert body["approved_master"]["selected_candidate_id"].startswith("CAND-")
        assert body["contract_ref"]["version"] == 3
        assert body["approved_master"]["host_version_ref"] == "2"


@pytest.mark.parametrize(
    "change",
    [
        "root_id",
        "child_id",
        "approval",
        "raw_bool_version",
        "raw_string_version",
        "edge_alias",
        "cross_episode",
        "wrong_dep_version",
        "wrong_fingerprint",
        "invalid_digest",
        "duplicate_head",
        "missing_snapshot",
        "extra_edge",
        "unapproved",
        "non_normalized_body",
        "metadata_bool_version",
        "coherent_edge_alias",
        "coherent_cross_episode",
        "cycle",
        "unreachable_head",
        "noncanonical_key",
        "wrong_child_contract",
    ],
)
def test_master_binding_refuses_structural_identity_or_closure_mismatch(change: str) -> None:
    q = importlib.import_module("r2.contracts.quality")
    data = binding_data()
    root, child = data["metadata_snapshots"]
    if change == "root_id":
        root["body"]["contract_ref"]["id"] = "OTHER"
    elif change == "child_id":
        child["body"]["contract_ref"]["id"] = "OTHER"
    elif change == "approval":
        root["body"]["approved_master"]["approval_record"] = "wrong"
    elif change == "raw_bool_version":
        data["root"]["master_version"] = True
    elif change == "raw_string_version":
        data["root"]["master_version"] = "7"
    elif change == "edge_alias":
        data["dependency_edges"][0]["dependency_ref"] = "master:OTHER"
    elif change == "cross_episode":
        data["dependency_edges"][0]["child_artifact_key"] = episode_video_key(2, "SH01")
    elif change == "wrong_dep_version":
        root["body"]["direct_dependencies"][0]["version"] = "m7c:wrong@7"
    elif change == "wrong_fingerprint":
        root["body"]["direct_dependencies"][0]["fingerprint"] = "3" * 64
    elif change == "invalid_digest":
        data["root"]["content_digest"] = "opaque"
    elif change == "duplicate_head":
        data["dependency_heads"].append(copy.deepcopy(data["dependency_heads"][0]))
    elif change == "missing_snapshot":
        data["metadata_snapshots"].pop()
    elif change == "extra_edge":
        data["dependency_edges"].append(copy.deepcopy(data["dependency_edges"][0]))
    elif change == "unapproved":
        root["body"]["approved_master"] = None
    elif change == "metadata_bool_version":
        root["body"]["contract_ref"]["version"] = True
    elif change == "coherent_edge_alias":
        root["body"]["direct_dependencies"][0]["ref"] = "master:OTHER"
        data["dependency_edges"][0]["dependency_ref"] = "master:OTHER"
    elif change == "coherent_cross_episode":
        key = episode_video_key(2, "SH01")
        data["dependency_heads"][0]["artifact_key"] = key
        child["artifact_key"] = key
        data["dependency_edges"][0]["child_artifact_key"] = key
    elif change == "cycle":
        child["body"]["direct_dependencies"] = [
            {"ref": "master:FINAL", "version": "CAND-FINAL-V1@2", "fingerprint": "1" * 64}
        ]
        data["dependency_edges"].append(
            {
                "parent_artifact_key": child["artifact_key"],
                "child_artifact_key": root["artifact_key"],
                "dependency_ref": "master:FINAL",
            }
        )
    elif change == "unreachable_head":
        root["body"]["direct_dependencies"] = []
        data["dependency_edges"] = []
    elif change == "noncanonical_key":
        key = root["artifact_key"] + "="
        root["artifact_key"] = key
        data["root"]["artifact_key"] = key
        data["dependency_edges"][0]["parent_artifact_key"] = key
    elif change == "wrong_child_contract":
        child["body"]["contract_ref"]["contract_type"] = "NarrativePlan"
    else:
        root["body"]["content_basis"]["refs"].append("story:source")
    with pytest.raises(ValidationError):
        q.MasterBindingV1.model_validate(data)


def test_media_normalization_preserves_foreign_wire_and_allows_prefixed_or_uppercase_hex() -> None:
    q = importlib.import_module("r2.contracts.quality")
    data = binding_data()
    data["dependency_heads"][0]["content_digest"] = "AB" * 32
    data["metadata_snapshots"][0]["body"]["direct_dependencies"][0]["fingerprint"] = "sha256:" + "ab" * 32
    binding = q.MasterBindingV1.model_validate(data)
    assert binding.dependency_heads[0].content_digest == "AB" * 32
    subject = q.AssessedSubject.model_validate(subject_data() | {"master_binding": data})
    assert subject.artifact_digest == "sha256:" + "1" * 64


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_metadata_cannot_enter_an_immutable_snapshot(value: float) -> None:
    q = importlib.import_module("r2.contracts.quality")
    snapshot = binding_data()["metadata_snapshots"][0]
    snapshot["body"]["unbound_number"] = value
    with pytest.raises(ValidationError):
        q.ArtifactMetadataSnapshot.model_validate(snapshot)


@pytest.mark.parametrize("resource", [".", "..", "a/b", "a\\b", "a:b", "a\x00b"])
def test_dependency_free_root_still_requires_a_safe_resource(resource: str) -> None:
    q = importlib.import_module("r2.contracts.quality")
    data = binding_data()
    key = episode_video_key(1, resource)
    data.update(dependency_heads=[], dependency_edges=[])
    data["root"]["artifact_key"] = key
    data["metadata_snapshots"] = [{"artifact_key": key, "body": metadata_data(resource), "metadata_digest": DIGEST}]
    with pytest.raises(ValidationError):
        q.MasterBindingV1.model_validate(data)


@pytest.mark.parametrize("value", [" owner", "owner ", "owner\n", "owner\x7f", ""])
def test_foreign_scope_is_exact_and_never_silently_normalized(value: str) -> None:
    q = importlib.import_module("r2.contracts.quality")
    with pytest.raises(ValidationError):
        q.QualityProfileDraft.model_validate(draft_data() | {"user_id": value})


@pytest.mark.parametrize("change", ["uuid4", "bool_revision", "bad_parent", "naive_time"])
def test_profile_draft_rejects_entity_revision_and_timestamp_mismatch(change: str) -> None:
    q = importlib.import_module("r2.contracts.quality")
    data = draft_data()
    if change == "uuid4":
        data["profile_id"] = "0199f00d-0000-4000-8000-000000000001"
    elif change == "bool_revision":
        data["revision"] = True
    elif change == "bad_parent":
        data["parent_revision"] = 1
    else:
        data["created_at"] = NOW.replace(tzinfo=None)
    with pytest.raises(ValidationError):
        q.QualityProfileDraft.model_validate(data)


@pytest.mark.parametrize("kind", ["ProfilePublicationAuthorizationLease", "DispositionAuthorizationLease"])
@pytest.mark.parametrize("seconds", [0, -1, 30, 31])
def test_action_leases_bound_only_their_explicit_time_pair(kind: str, seconds: int) -> None:
    q = importlib.import_module("r2.contracts.quality")
    model = getattr(q, kind)
    data = {
        "authorization_id": "foreign-grant",
        "action": "PROFILE_PUBLICATION" if kind.startswith("Profile") else "QUALITY_DISPOSITION",
        "user_id": "owner",
        "project_name": "project",
        "actor_id": "actor",
        "command_id": "command",
        "request_digest": DIGEST,
        "subject_digest": DIGEST,
        "policy_id": "policy",
        "policy_version": "1",
        "evidence_digest": DIGEST,
        "issued_at": NOW,
        "admit_not_after": NOW + timedelta(seconds=seconds),
    }
    if seconds == 30:
        assert model.model_validate(data).admit_not_after == NOW + timedelta(seconds=30)
    else:
        with pytest.raises(ValidationError):
            model.model_validate(data)


@pytest.mark.parametrize("seconds", [0, -1, 604800, 604801])
def test_final_disposition_has_a_seven_day_hard_bound(seconds: int) -> None:
    q = importlib.import_module("r2.contracts.quality")
    if seconds == 604800:
        assert q.QualityDisposition.model_validate(disposition_data(seconds=seconds)).decision == "PASS"
    else:
        with pytest.raises(ValidationError):
            q.QualityDisposition.model_validate(disposition_data(seconds=seconds))


def test_waivers_sort_full_canonical_bindings_with_null_and_refuse_logical_duplicates() -> None:
    q = importlib.import_module("r2.contracts.quality")
    rows = [
        {"rule_id": "review", "finding_id": None, "scope": "frame:1", "justification": "Reason"},
        {"rule_id": "review", "finding_id": UUID, "scope": "frame:1", "justification": "Reason"},
        {"rule_id": "probe", "finding_id": None, "scope": "frame:2", "justification": "Reason"},
    ]
    outputs = []
    for permutation in permutations(rows):
        value = q.QualityDisposition.model_validate(
            disposition_data(decision="WAIVE", seconds=86400) | {"waiver_bindings": list(permutation)}
        )
        outputs.append(value.model_dump_json())
    assert len(set(outputs)) == 1
    for duplicates in [[*rows, rows[0]], [*rows, rows[0] | {"justification": "Conflicting"}]]:
        with pytest.raises(ValidationError):
            q.QualityDisposition.model_validate(disposition_data(decision="WAIVE") | {"waiver_bindings": duplicates})
    with pytest.raises(ValidationError):
        q.QualityDisposition.model_validate(
            disposition_data(decision="WAIVE", seconds=86401) | {"waiver_bindings": rows}
        )
    with pytest.raises(ValidationError):
        q.QualityDisposition.model_validate(disposition_data(decision="WAIVE"))
    with pytest.raises(ValidationError):
        q.QualityDisposition.model_validate(disposition_data() | {"waiver_bindings": rows})
    with pytest.raises(ValidationError):
        q.QualityDisposition.model_validate(disposition_data() | {"custodian_admitted_at": NOW - timedelta(seconds=1)})


def test_findings_receipts_and_final_profiles_roundtrip_without_authority_side_effects() -> None:
    q = importlib.import_module("r2.contracts.quality")
    profile = draft_data() | {
        "profile_digest": DIGEST,
        "publication_authorization_id": "grant",
        "publication_policy_id": "policy",
        "publication_policy_version": "1",
        "publication_evidence_digest": DIGEST,
        "publication_admitted_at": NOW,
        "publication_subject_digest": DIGEST,
        "publication_request_digest": DIGEST,
    }
    records = [
        (
            q.QualityFinding,
            {
                "finding_id": UUID,
                "rule_id": "review",
                "severity": "BLOCKING",
                "subject_locator": "frame:1",
                "evidence_digest": DIGEST,
            },
        ),
        (
            q.CommandReceipt,
            {
                "command": command_data("PUBLISH_PROFILE"),
                "result_ref": "profile:1",
                "result_digest": DIGEST,
                "committed_at": NOW,
            },
        ),
        (q.QualityProfileRevision, profile),
        (q.AssessedSubject, subject_data()),
    ]
    for model, body in records:
        value = model.model_validate(body)
        assert model.model_validate_json(value.model_dump_json()) == value
    next_revision = q.QualityProfileRevision.model_validate(profile | {"revision": 2, "parent_revision": 1})
    assert next_revision.parent_revision == 1
    with pytest.raises(ValidationError):
        q.QualityProfileRevision.model_validate(profile | {"revision": 3, "parent_revision": 1})


def test_command_and_lease_actions_are_closed_without_creating_a_grant() -> None:
    q = importlib.import_module("r2.contracts.quality")
    with pytest.raises(ValidationError):
        q.CommandEnvelope.model_validate(command_data("EXPORT"))
    body = {
        "authorization_id": "foreign-grant",
        "action": "QUALITY_DISPOSITION",
        "user_id": "owner",
        "project_name": "project",
        "actor_id": "actor",
        "command_id": "command",
        "request_digest": DIGEST,
        "subject_digest": DIGEST,
        "policy_id": "policy",
        "policy_version": "1",
        "evidence_digest": DIGEST,
        "issued_at": NOW,
        "admit_not_after": NOW + timedelta(seconds=30),
    }
    with pytest.raises(ValidationError):
        q.ProfilePublicationAuthorizationLease.model_validate(body)
    with pytest.raises(ValidationError):
        q.DispositionAuthorizationLease.model_validate(body | {"action": "PROFILE_PUBLICATION"})
