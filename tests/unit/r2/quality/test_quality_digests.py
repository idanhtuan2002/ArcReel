"""Quality digests bind exact normative bodies using the accepted canonical algorithm."""

from __future__ import annotations

import copy
import importlib
import json
import subprocess
import sys
from datetime import timedelta
from itertools import permutations
from pathlib import Path
from typing import Any

import pytest

from r2.advanced_creative.digests import digest_canonical
from tests.unit.r2.contracts.test_quality import (
    DIGEST,
    NOW,
    OTHER_UUID,
    UUID,
    binding_data,
    command_data,
    completion_data,
    disposition_data,
    draft_data,
    non_array,
    observation_data,
    policy_data,
    subject_data,
)

DOMAINS = (
    "m10.quality-policy.v1",
    "m10.quality-profile-draft.v1",
    "m10.quality-profile.v1",
    "m10.artifact-metadata.v1",
    "m10.master-binding.v1",
    "m10.content-basis.v1",
    "m10.assessed-subject.v1",
    "m10.technical-observation.v1",
    "m10.factual-observation.v1",
    "m10.narrative-observation.v1",
    "m10.continuity-observation.v1",
    "m10.perceptual-regression-observation.v1",
    "m10.perceptual-review-observation.v1",
    "m10.accessibility-observation.v1",
    "m10.observation-closure.v1",
    "m10.assessment-requirements.v1",
    "m10.quality-run.v1",
    "m10.waiver-binding.v1",
    "m10.quality-disposition.v1",
    "m10.profile-publication-subject.v1",
    "m10.disposition-subject.v1",
    "m10.profile-publication-request.v1",
    "m10.run-completion-request.v1",
    "m10.disposition-request.v1",
    "m10.command-key-guard.v1",
)


def examples() -> dict[str, Any]:
    draft = draft_data()
    profile = draft | {
        "profile_digest": DIGEST,
        "publication_authorization_id": "grant",
        "publication_policy_id": "policy",
        "publication_policy_version": "1",
        "publication_evidence_digest": DIGEST,
        "publication_admitted_at": NOW,
        "publication_subject_digest": DIGEST,
        "publication_request_digest": DIGEST,
    }
    publication = {
        "user_id": "owner",
        "project_name": "project",
        "actor_id": "actor",
        "profile_draft": draft,
        "profile_draft_digest": DIGEST,
        "expected_profile_revision": 0,
    }
    disposition = {
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
        "requested_expires_at": NOW,
        "expected_disposition_version": 0,
    }
    completion = completion_data()
    run = {
        "run_id": UUID,
        "subject": subject_data(),
        "subject_digest": DIGEST,
        "profile_id": UUID,
        "profile_revision": 1,
        "profile_digest": DIGEST,
        "observation_refs": [UUID],
        "observation_closure_digest": DIGEST,
        "slot_results": [
            {
                "requirement_id": "review-required",
                "slot_id": "human",
                "observation_refs": [UUID],
                "observation_digests": [DIGEST],
                "distinct_independence_groups": ["independent"],
                "state": "SATISFIED",
                "escalation_observation_refs": [],
            }
        ],
        "requirements_digest": DIGEST,
        "execution_refs": ["execution"],
        "completed_at": NOW,
    }
    values = {
        "m10.quality-policy.v1": policy_data(),
        "m10.quality-profile-draft.v1": draft,
        "m10.quality-profile.v1": profile,
        "m10.artifact-metadata.v1": binding_data()["metadata_snapshots"][0],
        "m10.master-binding.v1": binding_data(),
        "m10.content-basis.v1": binding_data()["metadata_snapshots"][0]["body"]["content_basis"],
        "m10.assessed-subject.v1": subject_data(),
        "m10.observation-closure.v1": completion["observations"],
        "m10.assessment-requirements.v1": policy_data()["assessment_requirements"],
        "m10.quality-run.v1": run,
        "m10.waiver-binding.v1": {
            "rule_id": "review",
            "finding_id": None,
            "scope": "frame:1",
            "justification": "Reason",
        },
        "m10.quality-disposition.v1": disposition_data(),
        "m10.profile-publication-subject.v1": publication,
        "m10.disposition-subject.v1": disposition,
        "m10.profile-publication-request.v1": {"command": command_data("PUBLISH_PROFILE"), "subject": publication},
        "m10.run-completion-request.v1": {"command": command_data("COMPLETE_RUN"), "subject": completion},
        "m10.disposition-request.v1": {"command": command_data("ISSUE_DISPOSITION"), "subject": disposition},
        "m10.command-key-guard.v1": command_data("PUBLISH_PROFILE"),
    }
    for kind, domain in [
        ("TECHNICAL", "technical"),
        ("FACTUAL", "factual"),
        ("NARRATIVE", "narrative"),
        ("CONTINUITY", "continuity"),
        ("PERCEPTUAL_REGRESSION", "perceptual-regression"),
        ("PERCEPTUAL_REVIEW", "perceptual-review"),
        ("ACCESSIBILITY", "accessibility"),
    ]:
        values[f"m10.{domain}-observation.v1"] = observation_data(kind)
    return values


@pytest.mark.parametrize("domain", DOMAINS)
def test_every_domain_hashes_the_complete_hand_built_normative_body(domain: str) -> None:
    d = importlib.import_module("r2.quality.digests")
    body = examples()[domain]
    expected = copy.deepcopy(body)
    if domain == "m10.quality-profile.v1":
        expected.pop("profile_digest")
    elif domain == "m10.artifact-metadata.v1":
        expected.pop("metadata_digest")
    elif domain.endswith("-request.v1"):
        expected["command"] = {
            key: expected["command"][key] for key in ("user_id", "project_name", "actor_id", "operation")
        }
    elif domain == "m10.command-key-guard.v1":
        expected.pop("request_digest")
    expected_digest = digest_canonical({"domain": domain, "contract_version": "1", "body": expected})
    assert d.compute_digest(domain, body) == expected_digest
    assert d.compute_digest(domain, copy.deepcopy(body)) == expected_digest


@pytest.mark.parametrize(
    "domain",
    [
        "m10.unknown.v1",
    ],
)
def test_reserved_b_and_unknown_domains_never_use_a_prefix_fallback(domain: str) -> None:
    d = importlib.import_module("r2.quality.digests")
    with pytest.raises(ValueError, match="unregistered"):
        d.compute_digest(domain, {})


def test_only_own_top_level_caches_are_excluded() -> None:
    d = importlib.import_module("r2.quality.digests")
    for domain, own in [("m10.quality-profile.v1", "profile_digest"), ("m10.artifact-metadata.v1", "metadata_digest")]:
        body = examples()[domain]
        changed = copy.deepcopy(body)
        changed[own] = "sha256:" + "b" * 64
        assert d.compute_digest(domain, body) == d.compute_digest(domain, changed)
    body = examples()["m10.master-binding.v1"]
    changed = copy.deepcopy(body)
    changed["metadata_snapshots"][0]["metadata_digest"] = "sha256:" + "b" * 64
    assert d.compute_digest("m10.master-binding.v1", body) != d.compute_digest("m10.master-binding.v1", changed)


@pytest.mark.parametrize(
    "domain", ["m10.profile-publication-request.v1", "m10.run-completion-request.v1", "m10.disposition-request.v1"]
)
def test_request_semantics_exclude_physical_command_id_but_guard_binds_it(domain: str) -> None:
    d = importlib.import_module("r2.quality.digests")
    body = examples()[domain]
    changed = copy.deepcopy(body)
    changed["command"]["command_id"] = "retry"
    assert d.compute_digest(domain, body) == d.compute_digest(domain, changed)
    assert d.compute_digest("m10.command-key-guard.v1", body["command"]) != d.compute_digest(
        "m10.command-key-guard.v1", changed["command"]
    )
    changed["command"]["request_digest"] = "sha256:" + "b" * 64
    assert d.compute_digest(domain, body) == d.compute_digest(domain, changed)


@pytest.mark.parametrize("field", ["user_id", "project_name", "actor_id", "operation", "command_id"])
def test_command_guard_binds_all_five_scoped_identity_fields(field: str) -> None:
    d = importlib.import_module("r2.quality.digests")
    body = command_data("PUBLISH_PROFILE")
    changed = body | {field: "COMPLETE_RUN" if field == "operation" else "different"}
    assert d.compute_digest("m10.command-key-guard.v1", body) != d.compute_digest("m10.command-key-guard.v1", changed)


@pytest.mark.parametrize("field", ["candidate_id", "master_version", "object_ref"])
def test_master_head_fields_and_distinct_generation_identity_remain_semantic(field: str) -> None:
    d = importlib.import_module("r2.quality.digests")
    body = binding_data()
    changed = copy.deepcopy(body)
    changed["root"][field] = 8 if field == "master_version" else "other-foreign-identity"
    assert d.compute_digest("m10.master-binding.v1", body) != d.compute_digest("m10.master-binding.v1", changed)
    changed = copy.deepcopy(body)
    changed["metadata_snapshots"][0]["body"]["approved_master"]["selected_candidate_id"] = "CAND-OTHER"
    assert d.compute_digest("m10.master-binding.v1", body) != d.compute_digest("m10.master-binding.v1", changed)


def test_all_waiver_permutations_are_identical_in_subject_request_and_final_digests() -> None:
    d = importlib.import_module("r2.quality.digests")
    rows = [
        {"rule_id": "review", "finding_id": None, "scope": "frame:1", "justification": "Reason"},
        {"rule_id": "review", "finding_id": UUID, "scope": "frame:1", "justification": "Reason"},
        {"rule_id": "probe", "finding_id": None, "scope": "frame:2", "justification": "Reason"},
    ]
    values = []
    for ordered in permutations(rows):
        subject = examples()["m10.disposition-subject.v1"] | {"decision": "WAIVE", "waiver_bindings": list(ordered)}
        request = {"command": command_data("ISSUE_DISPOSITION"), "subject": subject}
        final = disposition_data(decision="WAIVE") | {"waiver_bindings": list(ordered)}
        values.append(
            tuple(
                d.compute_digest(domain, body)
                for domain, body in [
                    ("m10.disposition-subject.v1", subject),
                    ("m10.disposition-request.v1", request),
                    ("m10.quality-disposition.v1", final),
                ]
            )
        )
    assert len(set(values)) == 1
    for field, value in [
        ("rule_id", "fresh"),
        ("finding_id", OTHER_UUID),
        ("scope", "frame:other"),
        ("justification", "Different"),
    ]:
        changed = copy.deepcopy(rows)
        changed[0][field] = value
        assert d.compute_digest("m10.waiver-binding.v1", rows[0]) != d.compute_digest(
            "m10.waiver-binding.v1", changed[0]
        )
        subject = examples()["m10.disposition-subject.v1"] | {"decision": "WAIVE", "waiver_bindings": changed}
        request = {"command": command_data("ISSUE_DISPOSITION"), "subject": subject}
        final = disposition_data(decision="WAIVE") | {"waiver_bindings": changed}
        for (domain, body), baseline in zip(
            [
                ("m10.disposition-subject.v1", subject),
                ("m10.disposition-request.v1", request),
                ("m10.quality-disposition.v1", final),
            ],
            values[0],
            strict=True,
        ):
            assert d.compute_digest(domain, body) != baseline


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("m10.waiver-binding.v1", "sha256:0414f6408b6572610465a35568c14f2230a38d009ed1bc601125fefd7277a9ec"),
        ("m10.command-key-guard.v1", "sha256:4b7082182947e559019ee2b7bb1c3ad3808b3ffd267c392b84b684f1ad9f2fe4"),
    ],
)
def test_literal_encoding_vectors_keep_null_and_exact_scoped_guard_fields(domain: str, expected: str) -> None:
    d = importlib.import_module("r2.quality.digests")
    assert d.compute_digest(domain, examples()[domain]) == expected


@pytest.mark.parametrize(
    ("kind", "domain"),
    [
        ("TECHNICAL", "m10.technical-observation.v1"),
        ("FACTUAL", "m10.factual-observation.v1"),
        ("NARRATIVE", "m10.narrative-observation.v1"),
        ("CONTINUITY", "m10.continuity-observation.v1"),
        ("PERCEPTUAL_REGRESSION", "m10.perceptual-regression-observation.v1"),
        ("PERCEPTUAL_REVIEW", "m10.perceptual-review-observation.v1"),
        ("ACCESSIBILITY", "m10.accessibility-observation.v1"),
    ],
)
def test_each_observation_variant_binds_every_nested_finding_field(kind: str, domain: str) -> None:
    d = importlib.import_module("r2.quality.digests")
    finding = {
        "finding_id": UUID,
        "rule_id": "review",
        "severity": "ADVISORY",
        "subject_locator": "frame:1",
        "evidence_digest": DIGEST,
    }
    body = observation_data(kind) | {"findings": [finding]}
    baseline = d.compute_digest(domain, body)
    for field, value in [
        ("finding_id", OTHER_UUID),
        ("rule_id", "fresh"),
        ("severity", "BLOCKING"),
        ("subject_locator", "frame:2"),
        ("evidence_digest", "sha256:" + "b" * 64),
    ]:
        changed = copy.deepcopy(body)
        changed["findings"][0][field] = value
        assert d.compute_digest(domain, changed) != baseline


def test_closure_sort_is_variant_tagged_and_rejects_duplicate_ids() -> None:
    d = importlib.import_module("r2.quality.digests")
    body = completion_data()["observations"]
    body.append(body[0] | {"observation_id": OTHER_UUID, "observation_type": "NARRATIVE"})
    assert d.compute_digest("m10.observation-closure.v1", body) == d.compute_digest(
        "m10.observation-closure.v1", list(reversed(body))
    )
    changed = copy.deepcopy(body)
    changed[0]["observation_type"] = "ACCESSIBILITY"
    assert d.compute_digest("m10.observation-closure.v1", body) != d.compute_digest(
        "m10.observation-closure.v1", changed
    )
    with pytest.raises(ValueError, match="duplicate identity"):
        d.compute_digest("m10.observation-closure.v1", [*body, body[0]])


def test_an_empty_observation_closure_is_not_a_completion_binding() -> None:
    d = importlib.import_module("r2.quality.digests")
    with pytest.raises(ValueError, match="empty observation closure"):
        d.compute_digest("m10.observation-closure.v1", [])


def test_referenced_policy_order_is_semantic_and_requirement_cycles_refuse() -> None:
    d = importlib.import_module("r2.quality.digests")
    policy = policy_data()
    changed = copy.deepcopy(policy)
    changed["rule_ids"].reverse()
    assert d.compute_digest("m10.quality-policy.v1", policy) != d.compute_digest("m10.quality-policy.v1", changed)
    requirements = policy["assessment_requirements"]
    requirements[0]["escalation_requirement_id"] = "review-required"
    with pytest.raises(ValueError, match="cyclic escalation"):
        d.compute_digest("m10.assessment-requirements.v1", requirements)


def valid_subject() -> Any:
    q = importlib.import_module("r2.contracts.quality")
    d = importlib.import_module("r2.quality.digests")
    subject = subject_data()
    for snapshot in subject["master_binding"]["metadata_snapshots"]:
        snapshot["metadata_digest"] = d.compute_digest("m10.artifact-metadata.v1", snapshot)
    subject["master_binding_digest"] = d.compute_digest("m10.master-binding.v1", subject["master_binding"])
    subject["content_basis_digest"] = d.compute_digest(
        "m10.content-basis.v1", subject["master_binding"]["metadata_snapshots"][0]["body"]["content_basis"]
    )
    return q.AssessedSubject.model_validate(subject)


def test_available_cached_bodies_are_recomputed_without_claiming_external_authority() -> None:
    q = importlib.import_module("r2.contracts.quality")
    d = importlib.import_module("r2.quality.digests")
    subject = valid_subject()
    assert d.verify_caches(subject) is None
    with pytest.raises(ValueError, match="quality digest mismatch"):
        d.verify_caches(subject.model_copy(update={"master_binding_digest": DIGEST}))
    with pytest.raises(ValueError, match="quality digest mismatch"):
        d.verify_caches(subject.model_copy(update={"content_basis_digest": DIGEST}))
    changed = subject.model_dump(mode="python")
    changed["master_binding"]["metadata_snapshots"][0]["metadata_digest"] = DIGEST
    with pytest.raises(ValueError, match="quality digest mismatch"):
        d.verify_caches(q.AssessedSubject.model_validate(changed))
    policy = q.QualityPolicyV1.model_validate(policy_data())
    draft = draft_data() | {"policy_digest": d.compute_digest("m10.quality-policy.v1", policy)}
    valid = q.QualityProfileDraft.model_validate(draft)
    assert d.verify_caches(valid) is None
    with pytest.raises(ValueError, match="quality digest mismatch"):
        d.verify_caches(valid.model_copy(update={"policy_digest": DIGEST}))


def test_request_cache_verification_refuses_drift_while_future_result_fields_are_absent() -> None:
    q = importlib.import_module("r2.contracts.quality")
    d = importlib.import_module("r2.quality.digests")
    body = examples()["m10.disposition-request.v1"]
    body["command"]["request_digest"] = d.compute_digest("m10.disposition-request.v1", body)
    request = q.DispositionAuthorizationRequest.model_validate(body)
    assert d.verify_caches(request) is None
    body["subject"]["reason"] = "Changed intent"
    with pytest.raises(ValueError, match="quality digest mismatch"):
        d.verify_caches(q.DispositionAuthorizationRequest.model_validate(body))


def scalar_paths(value: Any, path: tuple[Any, ...] = ()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from scalar_paths(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from scalar_paths(child, (*path, index))
    else:
        yield path, value


@pytest.mark.parametrize("domain", DOMAINS)
def test_normative_scalar_changes_are_hashed_or_structurally_refused(domain: str) -> None:
    d = importlib.import_module("r2.quality.digests")
    body = examples()[domain]
    baseline = d.compute_digest(domain, body)
    excluded = (
        {("profile_digest",)}
        if domain == "m10.quality-profile.v1"
        else {("metadata_digest",)}
        if domain == "m10.artifact-metadata.v1"
        else {("request_digest",)}
        if domain == "m10.command-key-guard.v1"
        else {("command", "command_id"), ("command", "request_digest")}
        if domain.endswith("-request.v1")
        else set()
    )
    bound = 0
    for path, value in scalar_paths(body):
        if path in excluded:
            continue
        changed = copy.deepcopy(body)
        target = changed
        for part in path[:-1]:
            target = target[part]
        if isinstance(value, bool):
            replacement = not value
        elif isinstance(value, int):
            replacement = value + 1
        elif value is None:
            replacement = DIGEST if str(path[-1]).endswith("digest") else OTHER_UUID
        elif isinstance(value, str):
            replacement = (
                "sha256:" + "b" * 64
                if value.startswith("sha256:")
                else OTHER_UUID
                if value == UUID
                else {"ALL": "N_OF_M", "HISTORICAL_ONLY": "REEVALUATE_CURRENT", "PASS": "FAIL", "HUMAN": "MODEL"}.get(
                    value, value + "-mutated"
                )
            )
        else:
            replacement = value + timedelta(seconds=1)
        target[path[-1]] = replacement
        try:
            actual = d.compute_digest(domain, changed)
        except ValueError:
            continue
        assert actual != baseline, (domain, path)
        bound += 1
    assert bound > 0


@pytest.mark.parametrize("module", ["r2.contracts.quality", "r2.quality.digests"])
def test_cold_quality_imports_never_activate_host_or_outbound_authority(module: str) -> None:
    script = r"""
import sys,os,types,pathlib,builtins,socket,subprocess,json
sys.path.insert(0,sys.argv[1])
original=dict(os.environ)
def forbidden(*args,**kwargs):
    raise AssertionError("pure quality import attempted authority")
fake=types.ModuleType("dotenv")
fake.load_dotenv=forbidden
fake.dotenv_values=forbidden
sys.modules["dotenv"]=fake
pathlib.Path.mkdir=forbidden
os.mkdir=forbidden
os.makedirs=forbidden
subprocess.Popen=forbidden
socket.socket.connect=forbidden
old_open=builtins.open
def guarded_open(path,mode="r",*args,**kwargs):
    if any(flag in mode for flag in "wax+") or str(path).endswith(".env"):
        forbidden()
    return old_open(path,mode,*args,**kwargs)
builtins.open=guarded_open
__import__(sys.argv[2])
assert dict(os.environ)==original
assert not any(name in {"lib","server","lib.env_init"} for name in sys.modules)
print(json.dumps({"imported":sys.argv[2],"environment_unchanged":True}))
"""
    root = Path(__file__).resolve().parents[4]
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(root), module], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"imported": module, "environment_unchanged": True}


@pytest.mark.parametrize("domain", ["m10.assessment-requirements.v1", "m10.observation-closure.v1"])
@pytest.mark.parametrize("kind", ["set", "frozenset", "generator"])
def test_tuple_digest_domains_require_explicit_array_input(domain: str, kind: str) -> None:
    q = importlib.import_module("r2.contracts.quality")
    d = importlib.import_module("r2.quality.digests")
    model = q.AssessmentRequirement if domain == "m10.assessment-requirements.v1" else q.ObservationBinding
    values = [model.model_validate(row) for row in examples()[domain]]
    with pytest.raises(ValueError, match="ordered collection"):
        d.compute_digest(domain, non_array(kind, values))


def test_fresh_processes_refuse_unordered_policy_input_instead_of_hashing_it() -> None:
    script = r"""
import sys,json
sys.path.insert(0,sys.argv[1])
from r2.quality.digests import compute_digest
from tests.unit.r2.contracts.test_quality import policy_data
data=policy_data()
baseline=compute_digest("m10.quality-policy.v1",data)
data["rule_ids"]=set(data["rule_ids"])
try:
    compute_digest("m10.quality-policy.v1",data)
    refused=False
except ValueError as exc:
    assert "ordered collection" in str(exc)
    refused=True
print(json.dumps({"baseline":baseline,"unordered_refused":refused}))
"""
    root = Path(__file__).resolve().parents[4]
    expected = digest_canonical({"domain": "m10.quality-policy.v1", "contract_version": "1", "body": policy_data()})
    for _ in range(3):
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script, str(root)], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout) == {"baseline": expected, "unordered_refused": True}
