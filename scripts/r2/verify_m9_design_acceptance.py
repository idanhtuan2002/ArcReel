#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator, FormatChecker

ACCEPTANCE_PATH = "docs/r2/evidence/R2_M9_DESIGN_ACCEPTANCE.json"


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def loads_unique_json(payload: bytes) -> dict[str, Any]:
    value = json.loads(payload, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def verify_review_bundle(
    acceptance: dict[str, Any],
    contract: dict[str, Any],
    reviews: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    if len(reviews) != 2:
        errors.append("exactly two valid sealed reviews are required")
    reviewer_ids = [str(review.get("reviewer_id", "")) for review in reviews]
    if len(reviewer_ids) != len(set(reviewer_ids)):
        errors.append("reviewer_id values must be distinct")

    required_checks = contract["rubric"]["required_checks"]
    expected_checks = set(required_checks)
    try:
        share_time = _timestamp(acceptance["reviews_shared_at"])
        reviewed_time = _timestamp(acceptance["reviewed_at"])
    except (KeyError, TypeError, ValueError):
        return [*errors, "acceptance review timestamps are invalid"]

    for review in reviews:
        reviewer_id = str(review.get("reviewer_id", "<missing>"))
        if review.get("reviewed_candidate_head") != acceptance.get("accepted_candidate_head"):
            errors.append(f"{reviewer_id} candidate head does not match acceptance")
        if review.get("review_contract_sha256") != acceptance.get("review_contract_sha256"):
            errors.append(f"{reviewer_id} review contract hash does not match acceptance")
        if review.get("rubric_id") != acceptance.get("rubric_id"):
            errors.append(f"{reviewer_id} rubric does not match acceptance")

        checks = review.get("required_checks", [])
        actual_checks = [item.get("check") for item in checks]
        if len(actual_checks) != len(required_checks) or set(actual_checks) != expected_checks:
            errors.append(f"{reviewer_id} rubric checks do not exactly match the contract")
        if any(item.get("status") != "PASS" for item in checks):
            errors.append(f"{reviewer_id} rubric check failed")
        if review.get("required_skips") != []:
            errors.append(f"{reviewer_id} required_skips must be empty")
        if review.get("material_unknowns") != []:
            errors.append(f"{reviewer_id} material_unknowns must be empty")
        if review.get("verdict") != "PASS":
            errors.append(f"{reviewer_id} verdict must be PASS")
        try:
            if _timestamp(review["sealed_at"]) >= share_time:
                errors.append("reviews_shared_at must follow every sealed_at")
        except (KeyError, TypeError, ValueError):
            errors.append(f"{reviewer_id} sealed_at is invalid")

    if reviewed_time < share_time:
        errors.append("reviewed_at must not precede reviews_shared_at")
    return errors


def verify_sealed_review_files(
    acceptance: dict[str, Any],
    contract: dict[str, Any],
    review_schema: dict[str, Any],
    payloads_by_ref: dict[str, bytes],
) -> list[str]:
    errors: list[str] = []
    reviews: list[dict[str, Any]] = []
    declared_refs = [item["review_output_ref"] for item in acceptance.get("reviewers", [])]
    if len(declared_refs) != len(set(declared_refs)):
        errors.append("review_output_ref values must be distinct")
    metadata_by_ref = {item["review_output_ref"]: item for item in acceptance.get("reviewers", [])}
    validator = Draft202012Validator(review_schema, format_checker=FormatChecker())

    for ref, payload in payloads_by_ref.items():
        metadata = metadata_by_ref.get(ref)
        if metadata is None:
            errors.append(f"review output not declared by acceptance: {ref}")
            continue
        if hashlib.sha256(payload).hexdigest() != metadata.get("review_output_sha256"):
            errors.append(f"review output hash mismatch: {ref}")
        try:
            review = loads_unique_json(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(f"invalid review output {ref}: {exc}")
            continue
        schema_errors = sorted(validator.iter_errors(review), key=lambda item: list(item.path))
        errors.extend(f"review schema violation {ref}: {item.message}" for item in schema_errors)
        if schema_errors:
            continue
        bound_fields = (
            "reviewer_id",
            "qualification_evidence",
            "conflict_declaration",
            "rubric_id",
            "review_contract_sha256",
            "reviewed_candidate_head",
            "verdict",
            "sealed_at",
        )
        if any(review.get(field) != metadata.get(field) for field in bound_fields):
            errors.append(f"reviewer metadata does not match sealed output: {ref}")
        reviews.append(review)

    missing_refs = set(metadata_by_ref) - set(payloads_by_ref)
    errors.extend(f"declared review output missing: {ref}" for ref in sorted(missing_refs))
    errors.extend(verify_review_bundle(acceptance, contract, reviews))
    return errors


def verify_acceptance_bindings(
    acceptance: dict[str, Any],
    contract: dict[str, Any],
    *,
    candidate_head: str,
    candidate_parent: str,
    acceptance_parent: str,
    candidate_blobs: dict[str, bytes],
    acceptance_blobs: dict[str, bytes],
    acceptance_changed_paths: set[str],
    observed_dirty_paths: list[str],
    candidate_parent_count: int,
    acceptance_parent_count: int,
) -> list[str]:
    errors: list[str] = []
    if acceptance.get("accepted_candidate_head") != candidate_head:
        errors.append("accepted candidate head does not match Git")
    if acceptance.get("accepted_candidate_parent") != candidate_parent:
        errors.append("accepted candidate parent does not match Git")
    if acceptance_parent != candidate_head:
        errors.append("acceptance commit parent is not the accepted candidate")
    if candidate_parent_count != 1:
        errors.append("candidate commit must have exactly one parent")
    if acceptance_parent_count != 1:
        errors.append("acceptance commit must have exactly one parent")

    artifact_records = acceptance.get("artifacts", {})
    artifact_paths = {record.get("path") for record in artifact_records.values()}
    required_paths = set(contract.get("candidate_artifacts", []))
    if artifact_paths != required_paths:
        errors.append("acceptance artifact paths do not exactly match the contract")
    for record in artifact_records.values():
        path = str(record.get("path", ""))
        payload = candidate_blobs.get(path)
        if payload is None:
            errors.append(f"candidate artifact missing: {path}")
        elif hashlib.sha256(payload).hexdigest() != record.get("sha256"):
            errors.append(f"artifact hash mismatch: {path}")

    root_hash_bindings = {
        "review_contract_sha256": "acceptance_contract",
        "acceptance_schema_sha256": "acceptance_schema",
        "review_schema_sha256": "review_schema",
        "verifier_sha256": "verifier",
    }
    for root_field, artifact_name in root_hash_bindings.items():
        artifact = artifact_records.get(artifact_name, {})
        if acceptance.get(root_field) != artifact.get("sha256"):
            errors.append(f"{root_field} does not match its artifact hash")

    adr_record = artifact_records.get("adr", {})
    adr_path = str(adr_record.get("path", ""))
    proposed_adr = candidate_blobs.get(adr_path)
    accepted_adr = acceptance_blobs.get(adr_path)
    if proposed_adr is None or accepted_adr is None:
        errors.append("ADR transition blobs are unavailable")
    else:
        expected_adr = proposed_adr.replace(b"status: proposed", b"status: accepted", 1)
        if expected_adr == proposed_adr or accepted_adr != expected_adr:
            errors.append("accepted ADR is not an exact status-only transition")
        if hashlib.sha256(accepted_adr).hexdigest() != acceptance.get("accepted_adr_sha256"):
            errors.append("accepted ADR hash mismatch")

    allowed_paths = set(contract["acceptance_commit_policy"].get("allowed_paths", []))
    unexpected_paths = sorted(acceptance_changed_paths - allowed_paths)
    if unexpected_paths:
        errors.append(f"acceptance commit changed paths outside the allowlist: {unexpected_paths}")
    if acceptance_changed_paths != allowed_paths:
        errors.append("acceptance commit does not contain the exact required path set")

    if acceptance.get("dirty_paths") != [] or observed_dirty_paths:
        errors.append(f"acceptance worktree is not clean: {observed_dirty_paths}")
    return errors


def verify_design_acceptance(
    acceptance: dict[str, Any],
    contract: dict[str, Any],
    acceptance_schema: dict[str, Any],
    review_schema: dict[str, Any],
    review_payloads_by_ref: dict[str, bytes],
    *,
    candidate_head: str,
    candidate_parent: str,
    acceptance_parent: str,
    candidate_blobs: dict[str, bytes],
    acceptance_blobs: dict[str, bytes],
    acceptance_changed_paths: set[str],
    observed_dirty_paths: list[str],
    candidate_parent_count: int,
    acceptance_parent_count: int,
) -> list[str]:
    validator = Draft202012Validator(acceptance_schema, format_checker=FormatChecker())
    schema_errors = sorted(validator.iter_errors(acceptance), key=lambda item: list(item.path))
    errors = [f"acceptance schema violation: {item.message}" for item in schema_errors]
    if errors:
        return errors
    errors.extend(
        verify_acceptance_bindings(
            acceptance,
            contract,
            candidate_head=candidate_head,
            candidate_parent=candidate_parent,
            acceptance_parent=acceptance_parent,
            candidate_blobs=candidate_blobs,
            acceptance_blobs=acceptance_blobs,
            acceptance_changed_paths=acceptance_changed_paths,
            observed_dirty_paths=observed_dirty_paths,
            candidate_parent_count=candidate_parent_count,
            acceptance_parent_count=acceptance_parent_count,
        )
    )
    errors.extend(
        verify_sealed_review_files(
            acceptance,
            contract,
            review_schema,
            review_payloads_by_ref,
        )
    )
    return errors


class EvidenceReader(Protocol):
    def blob(self, ref: str, path: str) -> bytes: ...

    def parent(self, ref: str) -> str: ...

    def parents(self, ref: str) -> list[str]: ...

    def changed_paths(self, ref: str) -> set[str]: ...

    def dirty_paths(self) -> list[str]: ...


class GitEvidenceReader:
    def __init__(self, repo: Path) -> None:
        self._repo = repo

    def _run(self, *args: str) -> bytes:
        result = subprocess.run(
            ["git", *args],
            cwd=self._repo,
            check=True,
            capture_output=True,
        )
        return result.stdout

    def blob(self, ref: str, path: str) -> bytes:
        return self._run("show", f"{ref}:{path}")

    def parent(self, ref: str) -> str:
        return self._run("rev-parse", f"{ref}^").decode().strip()

    def parents(self, ref: str) -> list[str]:
        fields = self._run("rev-list", "--parents", "-n", "1", ref).decode().split()
        return fields[1:]

    def changed_paths(self, ref: str) -> set[str]:
        output = self._run("diff-tree", "--no-commit-id", "--name-only", "-r", ref)
        return set(output.decode().splitlines())

    def dirty_paths(self) -> list[str]:
        output = self._run("status", "--porcelain=v1", "--untracked-files=all")
        return [line[3:] for line in output.decode().splitlines() if len(line) >= 4]


def verify_repository(
    repo: Path,
    *,
    acceptance_ref: str = "HEAD",
    reader: EvidenceReader | None = None,
) -> list[str]:
    source = reader or GitEvidenceReader(repo)
    try:
        acceptance = loads_unique_json(source.blob(acceptance_ref, ACCEPTANCE_PATH))
        candidate_head = str(acceptance["accepted_candidate_head"])
        contract_path = "docs/r2/evidence/R2_M9_DESIGN_ACCEPTANCE_CONTRACT_2026-09-15.json"
        contract = loads_unique_json(source.blob(candidate_head, contract_path))
        acceptance_schema_path = str(contract["output"]["schema_path"])
        review_schema_path = str(contract["output"]["review_schema_path"])
        acceptance_schema = loads_unique_json(source.blob(candidate_head, acceptance_schema_path))
        review_schema = loads_unique_json(source.blob(candidate_head, review_schema_path))
        candidate_blobs = {path: source.blob(candidate_head, path) for path in contract["candidate_artifacts"]}
        review_payloads = {
            item["review_output_ref"]: source.blob(acceptance_ref, item["review_output_ref"])
            for item in acceptance["reviewers"]
        }
        adr_path = str(acceptance["artifacts"]["adr"]["path"])
        acceptance_blobs = {adr_path: source.blob(acceptance_ref, adr_path)}
    except (KeyError, OSError, subprocess.CalledProcessError, UnicodeDecodeError, ValueError) as exc:
        return [f"acceptance evidence load failure: {exc}"]

    candidate_parents = source.parents(candidate_head)
    acceptance_parents = source.parents(acceptance_ref)
    return verify_design_acceptance(
        acceptance,
        contract,
        acceptance_schema,
        review_schema,
        review_payloads,
        candidate_head=candidate_head,
        candidate_parent=candidate_parents[0] if candidate_parents else "",
        acceptance_parent=acceptance_parents[0] if acceptance_parents else "",
        candidate_blobs=candidate_blobs,
        acceptance_blobs=acceptance_blobs,
        acceptance_changed_paths=source.changed_paths(acceptance_ref),
        observed_dirty_paths=source.dirty_paths(),
        candidate_parent_count=len(candidate_parents),
        acceptance_parent_count=len(acceptance_parents),
    )


def main() -> int:
    errors = verify_repository(Path.cwd())
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("R2 M9 design acceptance verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
