import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.r2.verify_m9_design_acceptance import (
    loads_unique_json,
    verify_acceptance_bindings,
    verify_design_acceptance,
    verify_repository,
    verify_review_bundle,
    verify_sealed_review_files,
)

REQUIRED_CHECKS = [
    "authority ownership and prerequisite fail-closed behavior",
    "contract fields, digest domains and cohort isolation",
    "exact command replay, concurrent-first-call serialization, CAS and lock order",
    "custodian authorization lease subject, policy, replay and admission deadline",
    "provider capability, retention, deletion and unknown-outcome boundaries",
    "Canvas and Factual bridge non-escalation",
    "invalidation closure and historical-read behavior",
    "packet state, A0 boundary, stop-code and artifact synchronization",
    "donor behavioral parity excluding all license questions by sponsor direction",
    "operational envelope, accessibility and executable evidence requirements",
]


def _review(reviewer_id: str, sealed_at: str) -> dict:
    return {
        "schema_version": "1",
        "status": "SEALED_M9_DESIGN_REVIEW",
        "reviewer_id": reviewer_id,
        "qualification_evidence": ["independent architecture review"],
        "conflict_declaration": "independent of author and other reviewer",
        "rubric_id": "R2_M9_DESIGN_REVIEW_V1",
        "review_contract_sha256": "a" * 64,
        "reviewed_candidate_head": "b" * 40,
        "required_checks": [{"check": check, "status": "PASS"} for check in REQUIRED_CHECKS],
        "findings": [],
        "required_skips": [],
        "material_unknowns": [],
        "verdict": "PASS",
        "sealed_at": sealed_at,
    }


def _review_schema() -> dict:
    path = Path("docs/r2/evidence/schemas/R2_M9_DESIGN_REVIEW.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _acceptance() -> dict:
    return {
        "accepted_candidate_head": "b" * 40,
        "review_contract_sha256": "a" * 64,
        "rubric_id": "R2_M9_DESIGN_REVIEW_V1",
        "reviews_shared_at": "2026-09-16T02:00:00Z",
        "reviewed_at": "2026-09-16T02:01:00Z",
    }


def _contract() -> dict:
    return {"rubric": {"required_checks": REQUIRED_CHECKS}}


def test_review_bundle_accepts_two_independent_complete_reviews():
    reviews = [
        _review("reviewer-1", "2026-09-16T01:00:00Z"),
        _review("reviewer-2", "2026-09-16T01:30:00Z"),
    ]

    assert verify_review_bundle(_acceptance(), _contract(), reviews) == []


def test_review_bundle_rejects_duplicate_reviewer_identity():
    reviews = [
        _review("reviewer-1", "2026-09-16T01:00:00Z"),
        _review("reviewer-1", "2026-09-16T01:30:00Z"),
    ]

    errors = verify_review_bundle(_acceptance(), _contract(), reviews)

    assert "reviewer_id values must be distinct" in errors


def test_review_bundle_rejects_cross_record_mismatch_and_early_share():
    reviews = [
        _review("reviewer-1", "2026-09-16T01:00:00Z"),
        _review("reviewer-2", "2026-09-16T02:30:00Z"),
    ]
    reviews[1]["reviewed_candidate_head"] = "c" * 40
    reviews[1]["review_contract_sha256"] = "d" * 64

    errors = verify_review_bundle(_acceptance(), _contract(), reviews)

    assert "reviewer-2 candidate head does not match acceptance" in errors
    assert "reviewer-2 review contract hash does not match acceptance" in errors
    assert "reviews_shared_at must follow every sealed_at" in errors


def test_review_bundle_rejects_missing_or_failed_rubric_check():
    reviews = [
        _review("reviewer-1", "2026-09-16T01:00:00Z"),
        _review("reviewer-2", "2026-09-16T01:30:00Z"),
    ]
    reviews[0]["required_checks"].pop()
    reviews[1]["required_checks"][0]["status"] = "FAIL"

    errors = verify_review_bundle(_acceptance(), _contract(), reviews)

    assert "reviewer-1 rubric checks do not exactly match the contract" in errors
    assert "reviewer-2 rubric check failed" in errors


def test_review_bundle_rejects_skips_unknowns_and_non_pass_verdict():
    reviews = [
        _review("reviewer-1", "2026-09-16T01:00:00Z"),
        _review("reviewer-2", "2026-09-16T01:30:00Z"),
    ]
    reviews[0]["required_skips"] = ["one"]
    reviews[0]["material_unknowns"] = ["two"]
    reviews[0]["verdict"] = "FAIL"

    errors = verify_review_bundle(_acceptance(), _contract(), reviews)

    assert "reviewer-1 required_skips must be empty" in errors
    assert "reviewer-1 material_unknowns must be empty" in errors
    assert "reviewer-1 verdict must be PASS" in errors


def test_review_bundle_rejects_reviewed_at_before_share():
    acceptance = deepcopy(_acceptance())
    acceptance["reviewed_at"] = "2026-09-16T01:59:59Z"
    reviews = [
        _review("reviewer-1", "2026-09-16T01:00:00Z"),
        _review("reviewer-2", "2026-09-16T01:30:00Z"),
    ]

    errors = verify_review_bundle(acceptance, _contract(), reviews)

    assert "reviewed_at must not precede reviews_shared_at" in errors


def test_sealed_review_schema_accepts_complete_pass():
    validator = Draft202012Validator(_review_schema())

    assert list(validator.iter_errors(_review("reviewer-1", "2026-09-16T01:00:00Z"))) == []


def test_sealed_review_schema_rejects_missing_check_and_nonempty_unknowns():
    validator = Draft202012Validator(_review_schema())
    review = _review("reviewer-1", "2026-09-16T01:00:00Z")
    review["required_checks"].pop()
    review["material_unknowns"] = ["unresolved authority"]

    errors = list(validator.iter_errors(review))

    assert errors


def test_unique_json_loader_rejects_duplicate_keys():
    with pytest.raises(ValueError, match="duplicate JSON key: reviewer_id"):
        loads_unique_json(b'{"reviewer_id":"one","reviewer_id":"two"}')


def test_sealed_review_files_bind_refs_hashes_schema_and_content():
    reviews = [
        _review("reviewer-1", "2026-09-16T01:00:00Z"),
        _review("reviewer-2", "2026-09-16T01:30:00Z"),
    ]
    payloads = {
        f"docs/r2/evidence/reviews/m9/review-{index}.json": json.dumps(review).encode()
        for index, review in enumerate(reviews, start=1)
    }
    acceptance = _acceptance()
    acceptance["reviewers"] = [
        {
            "reviewer_id": review["reviewer_id"],
            "qualification_evidence": review["qualification_evidence"],
            "conflict_declaration": review["conflict_declaration"],
            "rubric_id": review["rubric_id"],
            "review_contract_sha256": review["review_contract_sha256"],
            "reviewed_candidate_head": review["reviewed_candidate_head"],
            "review_output_ref": ref,
            "review_output_sha256": hashlib.sha256(payload).hexdigest(),
            "verdict": review["verdict"],
            "sealed_at": review["sealed_at"],
        }
        for review, (ref, payload) in zip(reviews, payloads.items(), strict=True)
    ]

    assert (
        verify_sealed_review_files(
            acceptance,
            _contract(),
            _review_schema(),
            payloads,
        )
        == []
    )


def test_sealed_review_files_reject_hash_and_metadata_mismatch():
    review = _review("reviewer-1", "2026-09-16T01:00:00Z")
    ref = "docs/r2/evidence/reviews/m9/review-1.json"
    acceptance = _acceptance()
    acceptance["reviewers"] = [
        {
            "reviewer_id": "different-reviewer",
            "qualification_evidence": ["different qualification"],
            "conflict_declaration": review["conflict_declaration"],
            "rubric_id": review["rubric_id"],
            "review_contract_sha256": review["review_contract_sha256"],
            "reviewed_candidate_head": review["reviewed_candidate_head"],
            "review_output_ref": ref,
            "review_output_sha256": "0" * 64,
            "verdict": review["verdict"],
            "sealed_at": review["sealed_at"],
        }
    ]

    errors = verify_sealed_review_files(
        acceptance,
        _contract(),
        _review_schema(),
        {ref: json.dumps(review).encode()},
    )

    assert f"review output hash mismatch: {ref}" in errors
    assert f"reviewer metadata does not match sealed output: {ref}" in errors


def test_sealed_review_files_reject_duplicate_output_refs():
    review = _review("reviewer-1", "2026-09-16T01:00:00Z")
    ref = "docs/r2/evidence/reviews/m9/review-1.json"
    payload = json.dumps(review).encode()
    acceptance = _acceptance()
    acceptance["reviewers"] = [
        {
            "reviewer_id": "reviewer-1",
            "qualification_evidence": review["qualification_evidence"],
            "conflict_declaration": review["conflict_declaration"],
            "rubric_id": review["rubric_id"],
            "review_contract_sha256": review["review_contract_sha256"],
            "reviewed_candidate_head": review["reviewed_candidate_head"],
            "review_output_ref": ref,
            "review_output_sha256": hashlib.sha256(payload).hexdigest(),
            "verdict": review["verdict"],
            "sealed_at": review["sealed_at"],
        },
        {
            "reviewer_id": "reviewer-2",
            "qualification_evidence": review["qualification_evidence"],
            "conflict_declaration": review["conflict_declaration"],
            "rubric_id": review["rubric_id"],
            "review_contract_sha256": review["review_contract_sha256"],
            "reviewed_candidate_head": review["reviewed_candidate_head"],
            "review_output_ref": ref,
            "review_output_sha256": hashlib.sha256(payload).hexdigest(),
            "verdict": review["verdict"],
            "sealed_at": review["sealed_at"],
        },
    ]

    errors = verify_sealed_review_files(
        acceptance,
        _contract(),
        _review_schema(),
        {ref: payload},
    )

    assert "review_output_ref values must be distinct" in errors


def test_sealed_review_files_reject_qualification_metadata_mismatch():
    reviews = [
        _review("reviewer-1", "2026-09-16T01:00:00Z"),
        _review("reviewer-2", "2026-09-16T01:30:00Z"),
    ]
    payloads = {
        f"docs/r2/evidence/reviews/m9/review-{index}.json": json.dumps(review).encode()
        for index, review in enumerate(reviews, start=1)
    }
    acceptance = _acceptance()
    acceptance["reviewers"] = [
        {
            "reviewer_id": review["reviewer_id"],
            "qualification_evidence": ["different qualification"],
            "conflict_declaration": review["conflict_declaration"],
            "rubric_id": review["rubric_id"],
            "review_contract_sha256": review["review_contract_sha256"],
            "reviewed_candidate_head": review["reviewed_candidate_head"],
            "review_output_ref": ref,
            "review_output_sha256": hashlib.sha256(payload).hexdigest(),
            "verdict": review["verdict"],
            "sealed_at": review["sealed_at"],
        }
        for review, (ref, payload) in zip(reviews, payloads.items(), strict=True)
    ]

    errors = verify_sealed_review_files(
        acceptance,
        _contract(),
        _review_schema(),
        payloads,
    )

    assert any("reviewer metadata does not match sealed output" in error for error in errors)


def _binding_fixture() -> tuple[dict, dict, dict[str, bytes], dict[str, bytes], set[str]]:
    candidate_head = "b" * 40
    candidate_parent = "c" * 40
    adr_path = "docs/adr/0081-m9-evidence-first-opportunity-intelligence.md"
    candidate_blobs = {
        adr_path: b"---\nstatus: proposed\n---\n# ADR\n",
        "docs/research/m9.md": b"research\n",
        "docs/r2/evidence/contract.json": b"contract\n",
        "docs/r2/evidence/acceptance.schema.json": b"acceptance-schema\n",
        "docs/r2/evidence/review.schema.json": b"review-schema\n",
        "scripts/r2/verifier.py": b"verifier\n",
        "tests/unit/scripts/r2/test_verifier.py": b"tests\n",
    }
    accepted_adr = candidate_blobs[adr_path].replace(b"status: proposed", b"status: accepted")
    acceptance_blobs = {adr_path: accepted_adr}
    artifact_names = {
        "adr": adr_path,
        "research": "docs/research/m9.md",
        "acceptance_contract": "docs/r2/evidence/contract.json",
        "acceptance_schema": "docs/r2/evidence/acceptance.schema.json",
        "review_schema": "docs/r2/evidence/review.schema.json",
        "verifier": "scripts/r2/verifier.py",
        "verifier_tests": "tests/unit/scripts/r2/test_verifier.py",
    }
    acceptance = {
        "accepted_candidate_head": candidate_head,
        "accepted_candidate_parent": candidate_parent,
        "accepted_adr_sha256": hashlib.sha256(accepted_adr).hexdigest(),
        "review_contract_sha256": hashlib.sha256(candidate_blobs[artifact_names["acceptance_contract"]]).hexdigest(),
        "acceptance_schema_sha256": hashlib.sha256(candidate_blobs[artifact_names["acceptance_schema"]]).hexdigest(),
        "review_schema_sha256": hashlib.sha256(candidate_blobs[artifact_names["review_schema"]]).hexdigest(),
        "verifier_sha256": hashlib.sha256(candidate_blobs[artifact_names["verifier"]]).hexdigest(),
        "artifacts": {
            name: {"path": path, "sha256": hashlib.sha256(candidate_blobs[path]).hexdigest()}
            for name, path in artifact_names.items()
        },
        "dirty_paths": [],
    }
    contract = {
        "candidate_artifacts": list(candidate_blobs),
        "acceptance_commit_policy": {
            "allowed_paths": [
                adr_path,
                "docs/r2/evidence/R2_M9_DESIGN_ACCEPTANCE.json",
                "docs/r2/evidence/reviews/m9/review-1.json",
                "docs/r2/evidence/reviews/m9/review-2.json",
            ]
        },
    }
    changed_paths = set(contract["acceptance_commit_policy"]["allowed_paths"])
    return acceptance, contract, candidate_blobs, acceptance_blobs, changed_paths


def test_acceptance_bindings_accept_exact_lineage_hashes_transition_and_commands():
    acceptance, contract, candidate_blobs, acceptance_blobs, changed_paths = _binding_fixture()

    assert (
        verify_acceptance_bindings(
            acceptance,
            contract,
            candidate_head="b" * 40,
            candidate_parent="c" * 40,
            acceptance_parent="b" * 40,
            candidate_blobs=candidate_blobs,
            acceptance_blobs=acceptance_blobs,
            acceptance_changed_paths=changed_paths,
            observed_dirty_paths=[],
            candidate_parent_count=1,
            acceptance_parent_count=1,
        )
        == []
    )


def test_acceptance_bindings_reject_false_lineage_hashes_scope_dirty_and_command():
    acceptance, contract, candidate_blobs, acceptance_blobs, changed_paths = _binding_fixture()
    acceptance["accepted_candidate_parent"] = "d" * 40
    acceptance["artifacts"]["research"]["sha256"] = "0" * 64
    changed_paths.add("r2/product_code.py")

    errors = verify_acceptance_bindings(
        acceptance,
        contract,
        candidate_head="b" * 40,
        candidate_parent="c" * 40,
        acceptance_parent="e" * 40,
        candidate_blobs=candidate_blobs,
        acceptance_blobs=acceptance_blobs,
        acceptance_changed_paths=changed_paths,
        observed_dirty_paths=["untracked.txt"],
        candidate_parent_count=2,
        acceptance_parent_count=2,
    )

    assert "accepted candidate parent does not match Git" in errors
    assert "acceptance commit parent is not the accepted candidate" in errors
    assert "artifact hash mismatch: docs/research/m9.md" in errors
    assert "acceptance commit changed paths outside the allowlist: ['r2/product_code.py']" in errors
    assert "candidate commit must have exactly one parent" in errors
    assert "acceptance commit must have exactly one parent" in errors
    assert "acceptance worktree is not clean: ['untracked.txt']" in errors


def test_acceptance_bindings_reject_root_hash_mismatch():
    acceptance, contract, candidate_blobs, acceptance_blobs, changed_paths = _binding_fixture()
    acceptance["verifier_sha256"] = "0" * 64

    errors = verify_acceptance_bindings(
        acceptance,
        contract,
        candidate_head="b" * 40,
        candidate_parent="c" * 40,
        acceptance_parent="b" * 40,
        candidate_blobs=candidate_blobs,
        acceptance_blobs=acceptance_blobs,
        acceptance_changed_paths=changed_paths,
        observed_dirty_paths=[],
        candidate_parent_count=1,
        acceptance_parent_count=1,
    )

    assert "verifier_sha256 does not match its artifact hash" in errors


def test_sealed_review_files_reject_missing_declared_review():
    reviews = [
        _review("reviewer-1", "2026-09-16T01:00:00Z"),
        _review("reviewer-2", "2026-09-16T01:30:00Z"),
    ]
    payloads = {
        f"docs/r2/evidence/reviews/m9/review-{index}.json": json.dumps(review).encode()
        for index, review in enumerate(reviews, start=1)
    }
    acceptance = _acceptance()
    acceptance["reviewers"] = [
        {
            "reviewer_id": review["reviewer_id"],
            "qualification_evidence": review["qualification_evidence"],
            "conflict_declaration": review["conflict_declaration"],
            "rubric_id": review["rubric_id"],
            "review_contract_sha256": review["review_contract_sha256"],
            "reviewed_candidate_head": review["reviewed_candidate_head"],
            "review_output_ref": ref,
            "review_output_sha256": hashlib.sha256(payload).hexdigest(),
            "verdict": review["verdict"],
            "sealed_at": review["sealed_at"],
        }
        for review, (ref, payload) in zip(reviews, payloads.items(), strict=True)
    ]
    missing_ref = "docs/r2/evidence/reviews/m9/review-2.json"
    payloads.pop(missing_ref)

    errors = verify_sealed_review_files(
        acceptance,
        _contract(),
        _review_schema(),
        payloads,
    )

    assert f"declared review output missing: {missing_ref}" in errors


def test_design_acceptance_entrypoint_runs_schema_bindings_and_review_checks():
    acceptance, contract, candidate_blobs, acceptance_blobs, changed_paths = _binding_fixture()
    acceptance.update(_acceptance())
    acceptance["accepted_candidate_head"] = "b" * 40
    reviews = [
        _review("reviewer-1", "2026-09-16T01:00:00Z"),
        _review("reviewer-2", "2026-09-16T01:30:00Z"),
    ]
    payloads = {
        f"docs/r2/evidence/reviews/m9/review-{index}.json": json.dumps(review).encode()
        for index, review in enumerate(reviews, start=1)
    }
    acceptance["reviewers"] = [
        {
            "reviewer_id": review["reviewer_id"],
            "qualification_evidence": review["qualification_evidence"],
            "conflict_declaration": review["conflict_declaration"],
            "rubric_id": review["rubric_id"],
            "review_contract_sha256": review["review_contract_sha256"],
            "reviewed_candidate_head": review["reviewed_candidate_head"],
            "review_output_ref": ref,
            "review_output_sha256": hashlib.sha256(payload).hexdigest(),
            "verdict": review["verdict"],
            "sealed_at": review["sealed_at"],
        }
        for review, (ref, payload) in zip(reviews, payloads.items(), strict=True)
    ]
    contract["rubric"] = _contract()["rubric"]

    errors = verify_design_acceptance(
        acceptance,
        contract,
        {"type": "object", "required": ["schema_version"]},
        _review_schema(),
        payloads,
        candidate_head="b" * 40,
        candidate_parent="c" * 40,
        acceptance_parent="b" * 40,
        candidate_blobs=candidate_blobs,
        acceptance_blobs=acceptance_blobs,
        acceptance_changed_paths=changed_paths,
        observed_dirty_paths=[],
        candidate_parent_count=1,
        acceptance_parent_count=1,
    )

    assert any("acceptance schema violation" in error for error in errors)


def test_repository_entrypoint_fails_closed_when_acceptance_blob_is_missing(tmp_path):
    class MissingAcceptanceReader:
        def blob(self, ref: str, path: str) -> bytes:
            raise KeyError((ref, path))

        def parent(self, ref: str) -> str:
            raise AssertionError(ref)

        def parents(self, ref: str) -> list[str]:
            raise AssertionError(ref)

        def changed_paths(self, ref: str) -> set[str]:
            raise AssertionError(ref)

        def dirty_paths(self) -> list[str]:
            raise AssertionError

    errors = verify_repository(tmp_path, reader=MissingAcceptanceReader())

    assert errors
    assert errors[0].startswith("acceptance evidence load failure")


def test_sealed_review_files_reject_malformed_timestamp_without_crashing():
    reviews = [
        _review("reviewer-1", "not-a-timestamp"),
        _review("reviewer-2", "2026-09-16T01:30:00Z"),
    ]
    payloads = {
        f"docs/r2/evidence/reviews/m9/review-{index}.json": json.dumps(review).encode()
        for index, review in enumerate(reviews, start=1)
    }
    acceptance = _acceptance()
    acceptance["reviewers"] = [
        {
            "reviewer_id": review["reviewer_id"],
            "qualification_evidence": review["qualification_evidence"],
            "conflict_declaration": review["conflict_declaration"],
            "rubric_id": review["rubric_id"],
            "review_contract_sha256": review["review_contract_sha256"],
            "reviewed_candidate_head": review["reviewed_candidate_head"],
            "review_output_ref": ref,
            "review_output_sha256": hashlib.sha256(payload).hexdigest(),
            "verdict": review["verdict"],
            "sealed_at": review["sealed_at"],
        }
        for review, (ref, payload) in zip(reviews, payloads.items(), strict=True)
    ]

    errors = verify_sealed_review_files(
        acceptance,
        _contract(),
        _review_schema(),
        payloads,
    )

    assert any("sealed_at is invalid" in error for error in errors)


def test_design_acceptance_stops_after_schema_failure_before_semantic_binding():
    acceptance = {"artifacts": []}

    errors = verify_design_acceptance(
        acceptance,
        {},
        {
            "type": "object",
            "required": ["accepted_candidate_head"],
            "properties": {"artifacts": {"type": "object"}},
        },
        {},
        {},
        candidate_head="b" * 40,
        candidate_parent="c" * 40,
        acceptance_parent="b" * 40,
        candidate_blobs={},
        acceptance_blobs={},
        acceptance_changed_paths=set(),
        observed_dirty_paths=[],
        candidate_parent_count=1,
        acceptance_parent_count=1,
    )

    assert errors
    assert all(error.startswith("acceptance schema violation") for error in errors)
