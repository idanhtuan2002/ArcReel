"""M10-B packaging contracts: the PACKAGING kernel member, policy V2 and package/export bindings stay pure and closed."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from r2.advanced_creative.digests import digest_payload
from r2.contracts import packaging as p
from r2.contracts import quality as q
from r2.contracts.advanced_creative import CandidatePayload, ExplorationKind, ExplorationRevision, PackagingCandidate
from r2.quality.digests import (
    DIGEST_DOMAINS,
    compute_digest,
    policy_domain,
    verify_caches,
    verify_packaging_closures,
)
from tests.unit.r2.contracts.test_quality import DIGEST, NOW, OTHER_UUID, UUID, draft_data, policy_data

OTHER_DIGEST = "sha256:" + "b" * 64


def constraints_data() -> dict[str, Any]:
    return {
        "schema_id": "m10.platform-constraints.v1",
        "platform_profile_id": "youtube-long",
        "platform_profile_revision": 1,
        "min_duration_ms": 60000,
        "max_duration_ms": 900000,
        "width": 1920,
        "height": 1080,
        "title_max_chars": 100,
        "description_max_chars": 5000,
        "max_tags": 15,
        "max_tag_chars": 30,
        "max_hashtags": 3,
        "required_topic_terms": ["history"],
        "banned_phrases": ["click here"],
        "chapter_min_ms": 10000,
        "max_chapters": 20,
        "required_locales": ["en"],
        "max_variant_groups": 2,
        "max_variants_per_group": 3,
        "asset_roles": [
            {
                "role": "video",
                "constraint_rule_id": "asset-video",
                "required": True,
                "media_types": ["video/mp4"],
                "max_bytes": 2**31 - 1,
            },
            {
                "role": "thumbnail",
                "constraint_rule_id": "asset-thumbnail",
                "required": False,
                "media_types": ["image/png", "image/jpeg"],
                "max_bytes": 2097152,
            },
        ],
        "rules": [
            {"rule_id": "asset-video", "rule_class": "REQUIRED_ASSET", "severity": "BLOCKING"},
            {"rule_id": "asset-thumbnail", "rule_class": "INTEGRITY", "severity": "BLOCKING"},
            {"rule_id": "title-length", "rule_class": "METADATA_LINT", "severity": "BLOCKING"},
            {"rule_id": "duration", "rule_class": "DURATION", "severity": "BLOCKING"},
            {"rule_id": "closure", "rule_class": "CLOSURE", "severity": "BLOCKING"},
            {"rule_id": "current", "rule_class": "CURRENTNESS", "severity": "BLOCKING"},
        ],
    }


def policy_v2_data() -> dict[str, Any]:
    return policy_data() | {
        "schema_id": "m10.quality-policy.v2",
        "platform_constraints": constraints_data(),
        "packaging_waiverable_rule_ids": ["title-length", "duration"],
    }


def candidate_body() -> dict[str, Any]:
    return {
        "kind": "PACKAGING",
        "approved_master_id": "master",
        "approved_master_digest": DIGEST,
        "assessed_subject_digest": DIGEST,
        "quality_profile_id": UUID,
        "quality_profile_revision": 1,
        "quality_profile_digest": DIGEST,
        "platform_profile_id": "youtube-long",
        "platform_profile_revision": 1,
        "constraint_snapshot_digest": DIGEST,
        "title": "A history of the river",
        "description": "How the river shaped the valley.",
        "tags": ["history", "river"],
        "hashtags": ["#history"],
        "chapters": [{"start_ms": 0, "title": "Source"}, {"start_ms": 60000, "title": "Delta"}],
        "localization_variants": [
            {
                "locale": "en",
                "title": "A history of the river",
                "description": "How the river shaped the valley.",
                "tags": ["history"],
                "hashtags": [],
                "chapters": [{"start_ms": 0, "title": "Source"}],
            }
        ],
        "audience_classification": {
            "audience_category": "general",
            "age_restriction": None,
            "classification_policy_digest": DIGEST,
        },
        "disclosure": {"synthetic_media": True, "paid_promotion": False, "disclosure_policy_digest": DIGEST},
        "variant_groups": [
            {
                "group_id": "titles",
                "field": "title",
                "variants": [
                    {"variant_id": "t1", "value": {"text": "A history of the river"}, "asset_role": None},
                    {"variant_id": "t2", "value": {"text": "The river that made a valley"}, "asset_role": None},
                ],
            }
        ],
        "assets": [
            {
                "role": "video",
                "variant_id": None,
                "source_ref": "masters/final.mp4",
                "content_digest": DIGEST,
                "media_type": "video/mp4",
                "byte_size": 1048576,
                "constraint_rule_id": "asset-video",
            }
        ],
        "content_closure_digest": DIGEST,
        "presentation_closure_digest": DIGEST,
        "provenance": [
            {"field_group": "content", "author_kind": "AGENT", "actor_id": "agent"},
            {"field_group": "presentation", "author_kind": "HUMAN", "actor_id": "owner"},
        ],
    }


def candidate_data() -> dict[str, Any]:
    body = candidate_body()
    sealed = PackagingCandidate.model_validate(body)
    return body | {
        "content_closure_digest": compute_digest("m10.packaging-content.v1", sealed),
        "presentation_closure_digest": compute_digest("m10.packaging-presentation.v1", sealed),
    }


def lineage_data() -> dict[str, Any]:
    return {
        "project_name": "project",
        "content_basis_digest": DIGEST,
        "approved_master_id": "master",
        "approved_master_digest": DIGEST,
        "creative_profile_id": UUID,
        "creative_profile_version": "1",
        "policy_digest": DIGEST,
    }


def slot_data() -> dict[str, Any]:
    return {
        "user_id": "owner",
        "project_name": "project",
        "source_artifact_key": "episode:1:video",
        "cohort_id": "cohort",
        "product_surface": "video",
    }


def preview_data() -> dict[str, Any]:
    return {
        "preview_id": UUID,
        "slot": slot_data(),
        "candidate_id": "package",
        "candidate_revision": 1,
        "candidate_payload_digest": DIGEST,
        "approved_master_id": "master",
        "approved_master_digest": DIGEST,
        "quality_run_id": UUID,
        "quality_run_digest": DIGEST,
        "disposition_id": UUID,
        "disposition_digest": DIGEST,
        "profile_id": UUID,
        "profile_revision": 1,
        "profile_digest": DIGEST,
        "packaging_observation_id": UUID,
        "packaging_observation_digest": DIGEST,
        "selected_variant_ids": ["t2"],
        "waivers": [],
        "expected_head_version": 0,
        "created_at": NOW,
        "expires_at": NOW.replace(minute=10),
    }


def packaging_subject_data() -> dict[str, Any]:
    return {
        "base_subject_digest": DIGEST,
        "packaging_candidate_id": "package",
        "packaging_candidate_revision": 1,
        "packaging_candidate_digest": DIGEST,
        "constraint_snapshot_digest": DIGEST,
    }


def packaging_observation_data() -> dict[str, Any]:
    subject = p.PackagingAssessedSubject.model_validate(packaging_subject_data())
    return {
        "observation_id": UUID,
        "observation_type": "PACKAGING",
        "requirement_id": "packaging",
        "slot_id": "package-check",
        "assessor_identity": "host-packaging-check",
        "assessor_version": "1",
        "assessor_qualification_ref": "deterministic",
        "assessor_qualification_digest": DIGEST,
        "independence_group": "host-deterministic-packaging",
        "producer_conflict": False,
        "config_digest": DIGEST,
        "subject_digest": compute_digest("m10.packaging-subject.v1", subject),
        "status": "PASS",
        "findings": [],
        "evidence_refs": ["rules"],
        "evidence_digest": DIGEST,
        "observed_at": NOW,
        "packaging_subject": packaging_subject_data(),
        "constraint_snapshot_digest": DIGEST,
        "check_config_digest": DIGEST,
        "rule_results_digest": DIGEST,
    }


def manifest_data() -> dict[str, Any]:
    return {
        "schema_id": "m10.export-manifest.v1",
        "slot": slot_data(),
        "selection_id": UUID,
        "selection_digest": DIGEST,
        "disposition_id": UUID,
        "disposition_digest": DIGEST,
        "candidate_payload_digest": DIGEST,
        "builder_identity_digest": DIGEST,
        "entries": [
            {"path": "video/output.mp4", "media_type": "video/mp4", "byte_size": 1048576, "content_digest": DIGEST},
            {
                "path": "metadata/metadata.json",
                "media_type": "application/json",
                "byte_size": 512,
                "content_digest": OTHER_DIGEST,
            },
        ],
    }


def command_data(operation: str) -> dict[str, Any]:
    return {
        "user_id": "owner",
        "project_name": "project",
        "actor_id": "owner",
        "operation": operation,
        "command_id": "command",
        "request_digest": DIGEST,
    }


# Frozen B1 digest vectors: a change here is a contract change and needs a reviewed amendment.
GOLDEN = {
    "m10.platform-constraints.v1": "sha256:a06104de8445f05b5695c79f6a228702e19c793ccc1c81345597e1b721a33213",
    "m10.quality-policy.v2": "sha256:73b68d6d5bc898051e59706e42a43f5c70858f7bb6692ebdac6707e79d2fe8b1",
    "m10.packaging-content.v1": "sha256:7b2bc131715a0465066b1d1fd2442d7738c89c400a7b2fa1e8834008e0ff4c5f",
    "m10.packaging-presentation.v1": "sha256:1f4bd51e0917fa9f48f5071eb025c63495d29a4605a1bf0ea51318486223fe32",
    "m10.packaging-candidate.v1": "sha256:ec2005e040ed401686b1eb161da8569267663aebe8ae0b9b675cbda4b555c96d",
    "m10.packaging-subject.v1": "sha256:f208230301d3d046a0d3ef218d1a093b708caf69f95caa932e267de5987fadf1",
    "m10.package-preview.v1": "sha256:0793a828d317d220e3d890e6b0124fb98fab6503b93d051e9c1e291aeac8b21c",
    "m10.export-manifest.v1": "sha256:de44826bd665d57065919d6d665fa0dffa70f5db64b8a22c96e6119a37d44a9d",
    "m8.packaging-payload": "sha256:6bab64988f88fff35d00c20db9479b686e46a55dc3e540e4508d2078b2b3aaae",
}


def golden_inputs() -> dict[str, tuple[str, object]]:
    candidate = PackagingCandidate.model_validate(candidate_data())
    return {
        "m10.platform-constraints.v1": ("m10.platform-constraints.v1", constraints_data()),
        "m10.quality-policy.v2": ("m10.quality-policy.v2", policy_v2_data()),
        "m10.packaging-content.v1": ("m10.packaging-content.v1", candidate),
        "m10.packaging-presentation.v1": ("m10.packaging-presentation.v1", candidate),
        "m10.packaging-candidate.v1": ("m10.packaging-candidate.v1", candidate),
        "m10.packaging-subject.v1": ("m10.packaging-subject.v1", packaging_subject_data()),
        "m10.package-preview.v1": ("m10.package-preview.v1", preview_data()),
        "m10.export-manifest.v1": ("m10.export-manifest.v1", manifest_data()),
    }


@pytest.mark.parametrize("name", sorted(set(GOLDEN) - {"m8.packaging-payload"}))
def test_m10_b_digest_vectors_are_frozen(name: str) -> None:
    domain, value = golden_inputs()[name]
    assert domain in DIGEST_DOMAINS
    assert compute_digest(domain, value) == GOLDEN[name]


def test_m8_packaging_payload_digest_is_frozen_and_kind_bound() -> None:
    from r2.contracts.advanced_creative import LineageBinding

    payload = PackagingCandidate.model_validate(candidate_data())
    lineage = LineageBinding.model_validate(lineage_data())
    assert digest_payload(payload, lineage) == GOLDEN["m8.packaging-payload"]
    revision = ExplorationRevision.model_validate(
        {
            "candidate_id": "package",
            "revision": 1,
            "kind": "PACKAGING",
            "parent_revision": None,
            "payload": candidate_data(),
            "payload_digest": GOLDEN["m8.packaging-payload"],
            "lineage": lineage_data(),
            "created_by": "owner",
            "created_at": NOW,
        }
    )
    assert isinstance(revision.payload, PackagingCandidate)
    with pytest.raises(ValidationError, match="revision kind must equal payload kind"):
        ExplorationRevision.model_validate(revision.model_dump(mode="python") | {"kind": ExplorationKind.FORMAT})


def test_the_kernel_union_admits_packaging_and_refuses_unknown_kinds() -> None:
    adapter = TypeAdapter(CandidatePayload)
    assert isinstance(adapter.validate_python(candidate_data()), PackagingCandidate)
    with pytest.raises(ValidationError):
        adapter.validate_python(candidate_data() | {"kind": "PUBLISH"})


@pytest.mark.parametrize(
    "change",
    ["mutation", "extra_field", "variant_without_source", "variant_with_both", "empty_group", "negative_size"],
)
def test_packaging_payload_is_immutable_and_closed(change: str) -> None:
    data = candidate_data()
    if change == "mutation":
        payload = PackagingCandidate.model_validate(data)
        with pytest.raises(ValidationError):
            payload.title = "changed"
        return
    if change == "extra_field":
        data["upload_url"] = "https://example.invalid"
    elif change == "variant_without_source":
        data["variant_groups"][0]["variants"][0]["value"] = None
    elif change == "variant_with_both":
        data["variant_groups"][0]["variants"][0]["asset_role"] = "thumbnail"
    elif change == "empty_group":
        data["variant_groups"][0]["variants"] = []
    else:
        data["assets"][0]["byte_size"] = -1
    with pytest.raises(ValidationError):
        PackagingCandidate.model_validate(data)


@pytest.mark.parametrize("field", ["title", "tags", "assets", "provenance"])
def test_closure_digests_bind_exactly_their_groups(field: str) -> None:
    candidate = PackagingCandidate.model_validate(candidate_data())
    verify_packaging_closures(candidate)
    data = candidate_data()
    if field == "title":
        data["title"] = "Changed"
    elif field == "tags":
        data["tags"] = ["river", "history"]
    elif field == "assets":
        data["assets"][0]["content_digest"] = OTHER_DIGEST
    else:
        data["provenance"][0]["author_kind"] = "HUMAN"
    changed = PackagingCandidate.model_validate(data)
    if field == "provenance":
        verify_packaging_closures(changed)
        assert compute_digest("m10.packaging-candidate.v1", changed) != compute_digest(
            "m10.packaging-candidate.v1", candidate
        )
    else:
        with pytest.raises(ValueError, match="digest mismatch"):
            verify_packaging_closures(changed)


def test_policy_v1_keeps_its_domain_and_v2_is_a_distinct_schema() -> None:
    v1 = q.QualityPolicyV1.model_validate(policy_data())
    v2 = q.QualityPolicyV2.model_validate(policy_v2_data())
    assert (policy_domain(v1), policy_domain(v2)) == ("m10.quality-policy.v1", "m10.quality-policy.v2")
    assert not isinstance(v2, q.QualityPolicyV1)
    assert isinstance(v1, q.QualityPolicyFields)
    assert isinstance(v2, q.QualityPolicyFields)
    assert v2.probe_rules == v1.probe_rules
    with pytest.raises(ValidationError):
        q.QualityPolicyV1.model_validate(policy_v2_data())


def test_profile_drafts_discriminate_policy_by_schema_id() -> None:
    assert isinstance(q.QualityProfileDraft.model_validate(draft_data()).policy, q.QualityPolicyV1)
    draft = draft_data() | {"policy": policy_v2_data()}
    draft["policy_digest"] = compute_digest("m10.quality-policy.v2", policy_v2_data())
    parsed = q.QualityProfileDraft.model_validate(draft)
    assert isinstance(parsed.policy, q.QualityPolicyV2)
    verify_caches(parsed)
    draft["policy_digest"] = compute_digest("m10.quality-policy.v1", policy_data())
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_caches(q.QualityProfileDraft.model_validate(draft))


@pytest.mark.parametrize("rule_id", ["asset-video", "asset-thumbnail", "closure", "current"])
def test_authority_integrity_closure_and_currentness_are_never_waivable(rule_id: str) -> None:
    with pytest.raises(ValidationError, match="never waivable"):
        q.QualityPolicyV2.model_validate(policy_v2_data() | {"packaging_waiverable_rule_ids": [rule_id]})


@pytest.mark.parametrize(
    "change", ["unknown_waiver", "duplicate_waiver", "empty_window", "duplicate_role", "unknown_asset_rule", "zip64"]
)
def test_policy_v2_and_constraints_refuse_incoherent_rules(change: str) -> None:
    data = policy_v2_data()
    constraints = data["platform_constraints"]
    if change == "unknown_waiver":
        data["packaging_waiverable_rule_ids"] = ["missing"]
    elif change == "duplicate_waiver":
        data["packaging_waiverable_rule_ids"] = ["duration", "duration"]
    elif change == "empty_window":
        constraints["min_duration_ms"] = constraints["max_duration_ms"]
    elif change == "duplicate_role":
        constraints["asset_roles"].append(copy.deepcopy(constraints["asset_roles"][0]))
    elif change == "unknown_asset_rule":
        constraints["asset_roles"][0]["constraint_rule_id"] = "missing"
    else:
        constraints["asset_roles"][0]["max_bytes"] = 2**31
    with pytest.raises(ValidationError):
        q.QualityPolicyV2.model_validate(data)


def test_packaging_observation_binds_its_package_subject_not_a_run_subject() -> None:
    observation = p.PackagingObservation.model_validate(packaging_observation_data())
    verify_caches(observation)
    tampered = packaging_observation_data() | {"subject_digest": DIGEST}
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_caches(p.PackagingObservation.model_validate(tampered))
    with pytest.raises(ValidationError, match="constraint snapshot mismatch"):
        p.PackagingObservation.model_validate(
            packaging_observation_data() | {"constraint_snapshot_digest": OTHER_DIGEST}
        )
    assert q.ObservationType.PACKAGING not in {q.ObservationType(k) for k in ("TECHNICAL", "NARRATIVE")}
    assert "PACKAGING" not in {kind.value for kind in q.AssessorKind}


@pytest.mark.parametrize(
    "path",
    ["../escape.mp4", "/abs.mp4", "video/./output.mp4", "Video/output.mp4", "video//output.mp4", "vidéo.mp4", ""],
)
def test_export_manifest_paths_are_relative_normalized_lowercase_ascii(path: str) -> None:
    data = manifest_data()
    data["entries"][0]["path"] = path
    with pytest.raises(ValidationError):
        p.ExportManifest.model_validate(data)


@pytest.mark.parametrize("change", ["duplicate", "manifest_listed", "oversized", "empty"])
def test_export_manifest_refuses_collisions_and_envelope_breaches(change: str) -> None:
    data = manifest_data()
    if change == "duplicate":
        data["entries"].append(copy.deepcopy(data["entries"][0]))
    elif change == "manifest_listed":
        data["entries"][0]["path"] = "manifest.json"
    elif change == "oversized":
        data["entries"][0]["byte_size"] = 2**31 - 1
    else:
        data["entries"] = []
    with pytest.raises(ValidationError):
        p.ExportManifest.model_validate(data)


def test_export_manifest_orders_entries_by_path_regardless_of_input_order() -> None:
    forward = p.ExportManifest.model_validate(manifest_data())
    data = manifest_data()
    data["entries"].reverse()
    assert p.ExportManifest.model_validate(data) == forward
    assert [entry.path for entry in forward.entries] == ["metadata/metadata.json", "video/output.mp4"]


@pytest.mark.parametrize("operation", ["SELECT_PACKAGE", "EXPORT_PACKAGE"])
def test_package_requests_bind_their_own_operation_and_scope(operation: str) -> None:
    selection_subject = {
        "user_id": "owner",
        "project_name": "project",
        "actor_id": "owner",
        "preview_id": UUID,
        "preview_digest": DIGEST,
        "expected_head_version": 0,
    }
    export_subject = {
        "user_id": "owner",
        "project_name": "project",
        "actor_id": "owner",
        "slot": slot_data(),
        "selection_id": UUID,
        "selection_digest": DIGEST,
    }
    model, subject = (
        (p.PackageSelectionRequest, selection_subject)
        if operation == "SELECT_PACKAGE"
        else (p.ExportRequest, export_subject)
    )
    model.model_validate({"command": command_data(operation), "subject": subject})
    other = "EXPORT_PACKAGE" if operation == "SELECT_PACKAGE" else "SELECT_PACKAGE"
    with pytest.raises(ValidationError, match="mismatch"):
        model.model_validate({"command": command_data(other), "subject": subject})
    with pytest.raises(ValidationError, match="mismatch"):
        model.model_validate({"command": command_data(operation) | {"actor_id": "agent"}, "subject": subject})
    if operation == "EXPORT_PACKAGE":
        foreign = export_subject | {"slot": slot_data() | {"project_name": "other"}}
        with pytest.raises(ValidationError, match="slot scope"):
            p.ExportRequest.model_validate({"command": command_data(operation), "subject": foreign})


def test_selection_is_the_previews_successor_and_its_cache_is_verified() -> None:
    preview = p.PackagePreview.model_validate(preview_data())
    selection = {
        "selection_id": OTHER_UUID,
        "command_id": "command",
        "request_digest": DIGEST,
        "preview": preview_data(),
        "preview_digest": compute_digest("m10.package-preview.v1", preview),
        "head_version": 1,
        "selector_id": "owner",
        "custodian_authorization_id": "lease",
        "custodian_policy_id": "custody",
        "custodian_policy_version": "1",
        "custodian_evidence_digest": DIGEST,
        "selected_at": NOW,
    }
    verify_caches(p.PackageSelection.model_validate(selection))
    with pytest.raises(ValidationError, match="successor"):
        p.PackageSelection.model_validate(selection | {"head_version": 2})
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_caches(p.PackageSelection.model_validate(selection | {"preview_digest": DIGEST}))


@pytest.mark.parametrize("seconds", [0, 901])
def test_preview_expiry_is_bounded(seconds: int) -> None:
    from datetime import timedelta

    with pytest.raises(ValidationError, match="time window"):
        p.PackagePreview.model_validate(preview_data() | {"expires_at": NOW + timedelta(seconds=seconds)})


def test_preview_orders_variants_and_waivers_and_refuses_duplicates() -> None:
    data = preview_data() | {
        "selected_variant_ids": ["t2", "a1"],
        "waivers": [
            {"rule_id": "duration", "finding_id": OTHER_UUID, "reason": "platform allows it"},
            {"rule_id": "title-length", "finding_id": UUID, "reason": "brand title"},
        ],
    }
    preview = p.PackagePreview.model_validate(data)
    assert preview.selected_variant_ids == ("a1", "t2")
    assert [w.finding_id for w in preview.waivers] == [UUID, OTHER_UUID]
    with pytest.raises(ValidationError):
        p.PackagePreview.model_validate(preview_data() | {"selected_variant_ids": ["t2", "t2"]})


def test_selection_lease_window_is_thirty_seconds() -> None:
    from datetime import timedelta

    lease = {
        "authorization_id": "lease",
        "action": "PACKAGING_SELECTION",
        "user_id": "owner",
        "project_name": "project",
        "actor_id": "owner",
        "command_id": "command",
        "request_digest": DIGEST,
        "subject_digest": DIGEST,
        "policy_id": "custody",
        "policy_version": "1",
        "evidence_digest": DIGEST,
        "issued_at": NOW,
        "admit_not_after": NOW + timedelta(seconds=30),
    }
    p.PackagingSelectionAuthorizationLease.model_validate(lease)
    with pytest.raises(ValidationError, match="time window"):
        p.PackagingSelectionAuthorizationLease.model_validate(lease | {"admit_not_after": NOW + timedelta(seconds=31)})
    with pytest.raises(ValidationError):
        p.PackagingSelectionAuthorizationLease.model_validate(lease | {"action": "QUALITY_DISPOSITION"})
