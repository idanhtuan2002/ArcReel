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


def rule(rule_id: str, check_id: str, rule_class: str, severity: str = "BLOCKING") -> dict[str, str]:
    return {"rule_id": rule_id, "check_id": check_id, "rule_class": rule_class, "severity": severity}


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
        "description_min_chars": 20,
        "description_max_chars": 5000,
        "plain_text_only": True,
        "title_required_terms": ["history"],
        "description_required_terms": ["river"],
        "banned_phrases": ["click here"],
        "tag_charset": "UNICODE_LETTERS_DIGITS_SPACE",
        "min_tags": 1,
        "max_tags": 15,
        "max_tag_chars": 30,
        "min_hashtags": 0,
        "max_hashtags": 3,
        "max_hashtag_chars": 30,
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
            rule("asset-video", "asset.required", "REQUIRED_ASSET"),
            rule("asset-thumbnail", "asset.integrity", "INTEGRITY"),
            rule("closure", "closure.content", "CLOSURE"),
            rule("closure-presentation", "closure.presentation", "CLOSURE"),
            rule("closure-subject", "closure.subject", "CLOSURE"),
            rule("current", "binding.master", "CURRENTNESS"),
            rule("current-profile", "binding.profile", "CURRENTNESS"),
            rule("title-length", "title.length", "METADATA_LINT"),
            rule("duration", "duration.window", "DURATION"),
            rule("tone", "phrases.banned", "METADATA_LINT", "ADVISORY"),
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
                    {
                        "variant_id": "t1",
                        "value": {"text": "A history of the river"},
                        "asset_role": None,
                        "provenance": {"author_kind": "AGENT", "actor_id": "agent"},
                    },
                    {
                        "variant_id": "t2",
                        "value": {"text": "The river that made a valley"},
                        "asset_role": None,
                        "provenance": {"author_kind": "HUMAN", "actor_id": "owner"},
                    },
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
        "chosen_variants": [{"group_id": "titles", "variant_id": "t2"}],
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


def selection_subject_data() -> dict[str, Any]:
    return {
        "user_id": "owner",
        "project_name": "project",
        "actor_id": "owner",
        "preview_id": UUID,
        "preview_digest": DIGEST,
        "expected_head_version": 0,
    }


def export_subject_data() -> dict[str, Any]:
    return {
        "user_id": "owner",
        "project_name": "project",
        "actor_id": "owner",
        "slot": slot_data(),
        "selection_id": UUID,
        "selection_digest": DIGEST,
    }


def check_request_data() -> dict[str, Any]:
    subject = {
        "user_id": "owner",
        "project_name": "project",
        "actor_id": "owner",
        "candidate_id": "package",
        "candidate_revision": 1,
        "candidate_payload_digest": DIGEST,
        "quality_run_id": UUID,
        "quality_run_digest": DIGEST,
    }
    return {"command": command_data("CHECK_PACKAGE"), "subject": subject}


def selection_request_data() -> dict[str, Any]:
    return {"command": command_data("SELECT_PACKAGE"), "subject": selection_subject_data()}


def export_request_data() -> dict[str, Any]:
    return {"command": command_data("EXPORT_PACKAGE"), "subject": export_subject_data()}


def selection_data() -> dict[str, Any]:
    return {
        "selection_id": OTHER_UUID,
        "command_id": "command",
        "request_digest": DIGEST,
        "preview": preview_data(),
        "preview_digest": compute_digest("m10.package-preview.v1", p.PackagePreview.model_validate(preview_data())),
        "head_version": 1,
        "selector_id": "owner",
        "custodian_authorization_id": "lease",
        "custodian_policy_id": "custody",
        "custodian_policy_version": "1",
        "custodian_evidence_digest": DIGEST,
        "selected_at": NOW,
    }


def execution_data() -> dict[str, Any]:
    return {
        "schema_id": "m10.export-execution.v1",
        "slot": slot_data(),
        "selection_id": UUID,
        "selection_digest": DIGEST,
        "manifest_digest": DIGEST,
        "builder_identity_digest": DIGEST,
        "adapter_version": "host-export-v1",
    }


# Frozen B1 digest vectors: a change here is a contract change and needs a reviewed amendment.
GOLDEN = {
    "m10.platform-constraints.v1": "sha256:3ce7b28f33a0981256555d1cbd9db35dddb40892b114f7453c8ab4a77fde71da",
    "m10.quality-policy.v2": "sha256:f804c9eabf17bdc089b3a70d7b55388db3c9454220a1576062008a960dd921c8",
    "m10.packaging-content.v1": "sha256:5272efe2dfcea555de9d5661fbe21f2fd85b6f044ffd740f648820026fa111ee",
    "m10.packaging-presentation.v1": "sha256:1f4bd51e0917fa9f48f5071eb025c63495d29a4605a1bf0ea51318486223fe32",
    "m10.packaging-candidate.v1": "sha256:af3f525fe6021b2dc16fca8b248d38b0d03bfc6e2f8503d04683983b2051b4e9",
    "m10.packaging-subject.v1": "sha256:f208230301d3d046a0d3ef218d1a093b708caf69f95caa932e267de5987fadf1",
    "m10.package-preview.v1": "sha256:0793a828d317d220e3d890e6b0124fb98fab6503b93d051e9c1e291aeac8b21c",
    "m10.packaging-observation.v1": "sha256:813d52209fa4aa9b0963652aa4ec5317cf7f079a8dd76dcca8a2708a845df2d4",
    "m10.package-check-request.v1": "sha256:57a3153e866c251da60683215bfe0e6e5ee757ad7d3d7b49af82f9d049bb8713",
    "m10.package-selection-request.v1": "sha256:ebba74e34d7f90494fbb6d701f0b01dbd40487c1dc1b7e1af78791970bd19407",
    "m10.package-selection.v1": "sha256:abbdb9846b39a3f1b86dd745663bfc5e21bfa9e6ac31bbf390c41bedabc4334c",
    "m10.export-request.v1": "sha256:e384613a6d1316a4108a3ef76136c8ff4275b9c53723048e0332d7d7cb5497bc",
    "m10.export-execution.v1": "sha256:d7421be947924cc3675b320a89c6e8dc5de3c88e49992045bb70e89def229ce2",
    "m10.export-manifest.v1": "sha256:0854151c809e896faddca8db3b8382afa299bd5d36bc89a76b500c2cf8aed013",
    "m8.packaging-payload": "sha256:f324f8e7c15c3ed7883349bdff1c1a50e5fcd36334cf74838fb3f6f910e1ab7d",
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
        "m10.packaging-observation.v1": ("m10.packaging-observation.v1", packaging_observation_data()),
        "m10.package-check-request.v1": ("m10.package-check-request.v1", check_request_data()),
        "m10.package-selection-request.v1": ("m10.package-selection-request.v1", selection_request_data()),
        "m10.package-selection.v1": ("m10.package-selection.v1", selection_data()),
        "m10.export-request.v1": ("m10.export-request.v1", export_request_data()),
        "m10.export-execution.v1": ("m10.export-execution.v1", execution_data()),
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
    selection_subject = selection_subject_data()
    export_subject = export_subject_data()
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
    selection = selection_data()
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


@pytest.mark.parametrize(
    "change",
    [
        "relabel_required_asset",
        "advisory_safety",
        "role_bound_to_lint",
        "required_role_on_integrity_rule",
        "missing_mandatory_check",
        "duplicate_check",
        "empty_tag_bound",
    ],
)
def test_safety_semantics_follow_server_owned_checks_not_author_labels(change: str) -> None:
    data = constraints_data()
    rules = {r["rule_id"]: r for r in data["rules"]}
    if change == "relabel_required_asset":
        rules["asset-video"]["rule_class"] = "METADATA_LINT"
    elif change == "advisory_safety":
        rules["asset-video"]["severity"] = "ADVISORY"
    elif change == "role_bound_to_lint":
        data["asset_roles"][0]["constraint_rule_id"] = "title-length"
    elif change == "required_role_on_integrity_rule":
        data["asset_roles"][1]["required"] = True
    elif change == "missing_mandatory_check":
        data["rules"] = [r for r in data["rules"] if r["check_id"] != "closure.subject"]
    elif change == "duplicate_check":
        data["rules"].append(rule("title-again", "title.length", "METADATA_LINT"))
    else:
        data["min_tags"] = data["max_tags"] + 1
    with pytest.raises(ValidationError):
        q.PlatformConstraintSnapshot.model_validate(data)


def test_a_relabelled_required_asset_cannot_be_published_as_waivable() -> None:
    data = policy_v2_data()
    for item in data["platform_constraints"]["rules"]:
        if item["rule_id"] == "asset-video":
            item["rule_class"] = "METADATA_LINT"
    data["packaging_waiverable_rule_ids"] = ["asset-video"]
    with pytest.raises(ValidationError):
        q.QualityPolicyV2.model_validate(data)
    with pytest.raises(ValidationError):
        q.QualityProfileDraft.model_validate(draft_data() | {"policy": data})


def test_every_alternative_keeps_its_own_author_and_binds_the_content_closure() -> None:
    candidate = PackagingCandidate.model_validate(candidate_data())
    authors = [variant.provenance.author_kind for variant in candidate.variant_groups[0].variants]
    assert authors == ["AGENT", "HUMAN"]
    data = candidate_data()
    data["variant_groups"][0]["variants"][1]["provenance"] = {"author_kind": "AGENT", "actor_id": "agent"}
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_packaging_closures(PackagingCandidate.model_validate(data))
    data["variant_groups"][0]["variants"][1].pop("provenance")
    with pytest.raises(ValidationError):
        PackagingCandidate.model_validate(data)


def test_manifest_records_one_canonical_choice_per_variant_group() -> None:
    data = manifest_data()
    data["chosen_variants"] = [{"group_id": "titles", "variant_id": "t2"}, {"group_id": "thumbs", "variant_id": "a"}]
    manifest = p.ExportManifest.model_validate(data)
    assert [choice.group_id for choice in manifest.chosen_variants] == ["thumbs", "titles"]
    data["chosen_variants"].append({"group_id": "titles", "variant_id": "t1"})
    with pytest.raises(ValidationError, match="duplicate"):
        p.ExportManifest.model_validate(data)
    assert compute_digest("m10.export-manifest.v1", manifest_data()) != compute_digest(
        "m10.export-manifest.v1", manifest_data() | {"chosen_variants": [{"group_id": "titles", "variant_id": "t1"}]}
    )


@pytest.mark.parametrize("domain", ["m10.package-selection-request.v1", "m10.export-request.v1"])
def test_request_digests_exclude_their_own_cache_and_bind_every_subject_field(domain: str) -> None:
    body = selection_request_data() if domain == "m10.package-selection-request.v1" else export_request_data()
    base = compute_digest(domain, body)
    cached = copy.deepcopy(body)
    cached["command"]["request_digest"] = OTHER_DIGEST
    assert compute_digest(domain, cached) == base
    changed = copy.deepcopy(body)
    changed["subject"]["selection_id" if "selection_id" in changed["subject"] else "preview_id"] = OTHER_UUID
    assert compute_digest(domain, changed) != base


@pytest.mark.parametrize(
    ("field", "value", "asset_role"),
    [
        ("tags", {"tags": "history"}, None),
        ("tags", {"tags": ["history"], "extra": 1}, None),
        ("tags", {"tags": [1]}, None),
        ("chapters", {"chapters": [{"start_ms": -1, "title": "A"}]}, None),
        ("chapters", {"chapters": "0:00 Intro"}, None),
        ("title", {"tags": ["history"]}, None),
        ("description", {"text": 3}, None),
        ("title", None, "thumbnail"),
        ("thumbnail", {"text": "x"}, None),
    ],
)
def test_malformed_alternatives_cannot_be_constructed(field: str, value: Any, asset_role: str | None) -> None:
    data = candidate_data()
    data["variant_groups"] = [
        {
            "group_id": "g",
            "field": field,
            "variants": [
                {
                    "variant_id": "v",
                    "value": value,
                    "asset_role": asset_role,
                    "provenance": {"author_kind": "AGENT", "actor_id": "agent"},
                }
            ],
        }
    ]
    with pytest.raises(ValidationError):
        PackagingCandidate.model_validate(data)
