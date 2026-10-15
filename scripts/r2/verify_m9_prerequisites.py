"""Verify the Git-bound M9 design decision and combined prerequisite base."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator, FormatChecker

from scripts.r2.verify_m7_scope import _alembic_revision_metadata_at_ref
from scripts.r2.verify_m9_design_acceptance import GitEvidenceReader, loads_unique_json

SPONSOR_CANDIDATE = "24fa05e0610efa6fb60db50d1b22b10de48f2786"
SPONSOR_ACCEPTANCE = "9d4e4ce6a01a4d1077de263b5cbadf4412055103"
M8_ACCEPTANCE = "23cf146a61c3b7acfb78440d2b1498fd9d77db4b"
M8_PATH = "docs/r2/evidence/R2_M8_IMPLEMENTATION_ACCEPTANCE.json"
M9_PATH = "docs/r2/evidence/R2_M9_DESIGN_ACCEPTANCE.json"
P0_PATH = "docs/r2/evidence/R2_M9_PREREQUISITE_ACCEPTANCE.json"
P0_SCHEMA = "docs/r2/evidence/schemas/R2_M9_PREREQUISITE_ACCEPTANCE.schema.json"
P0_SCRIPT = "scripts/r2/verify_m9_prerequisites.py"
SPONSOR_SCHEMA = "docs/r2/evidence/schemas/R2_M9_SPONSOR_DESIGN_ACCEPTANCE.schema.json"
CONTRACT = "docs/r2/evidence/R2_M9_DESIGN_ACCEPTANCE_CONTRACT_2026-09-15.json"
ADR = "docs/adr/0081-m9-evidence-first-opportunity-intelligence.md"
AMENDMENT = "docs/adr/0110-m9-design-acceptance-by-explicit-sponsor-decision.md"
SPONSOR_PATHS = {ADR, AMENDMENT, M9_PATH, SPONSOR_SCHEMA, "docs/r2/evidence/R2_M9_DESIGN_REVIEW_HANDOFF_2026-10-15.md"}
LOAD_ERRORS = (KeyError, OSError, subprocess.CalledProcessError, UnicodeDecodeError, ValueError, TypeError)


class EvidenceSource(Protocol):
    def blob(self, ref: str, path: str) -> bytes: ...
    def parents(self, ref: str) -> list[str]: ...
    def changed_paths(self, ref: str) -> set[str]: ...
    def dirty_paths(self) -> list[str]: ...
    def is_ancestor(self, ancestor: str, descendant: str) -> bool: ...
    def migration_metadata(self, ref: str) -> tuple[tuple[str, ...], str]: ...
    def head(self) -> str: ...


class GitPrerequisiteReader(GitEvidenceReader):
    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=self._repo,
            capture_output=True,
            check=False,
        )
        if result.returncode not in (0, 1):
            raise ValueError("Git could not resolve acceptance ancestry")
        return result.returncode == 0

    def migration_metadata(self, ref: str) -> tuple[tuple[str, ...], str]:
        return _alembic_revision_metadata_at_ref(self._repo, ref)

    def head(self) -> str:
        return self._run("rev-parse", "HEAD").decode().strip()


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _schema_errors(source: EvidenceSource, ref: str, path: str, value: dict[str, Any]) -> list[str]:
    schema = loads_unique_json(source.blob(ref, path))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [f"schema violation: {error.message}" for error in validator.iter_errors(value)]


def verify_sponsor_design(
    source: EvidenceSource,
    acceptance_ref: str = SPONSOR_ACCEPTANCE,
    *,
    current_ref: str | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        if acceptance_ref != SPONSOR_ACCEPTANCE:
            return ["M9_DESIGN_NOT_ACCEPTED: sponsor exception is limited to the recorded acceptance commit"]
        record = loads_unique_json(source.blob(acceptance_ref, M9_PATH))
        errors.extend(_schema_errors(source, SPONSOR_ACCEPTANCE, SPONSOR_SCHEMA, record))
        if errors:
            return [f"M9_DESIGN_NOT_ACCEPTED: {error}" for error in errors]
        if source.parents(acceptance_ref) != [SPONSOR_CANDIDATE]:
            errors.append("sponsor acceptance is not the sole child of its candidate")
        if source.parents(SPONSOR_CANDIDATE) != [record["accepted_candidate_parent"]]:
            errors.append("candidate parent mismatch")
        if source.changed_paths(acceptance_ref) != SPONSOR_PATHS:
            errors.append("sponsor acceptance changed paths outside its exact ceremony")
        contract_bytes = source.blob(SPONSOR_CANDIDATE, CONTRACT)
        contract = loads_unique_json(contract_bytes)
        if _sha(contract_bytes) != record["review_contract_sha256"]:
            errors.append("original review contract hash mismatch")
        base_contract = contract["base_review_contract"]
        base_bytes = source.blob(SPONSOR_CANDIDATE, base_contract["path"])
        if (
            _sha(base_bytes) != base_contract["sha256"]
            or loads_unique_json(base_bytes)["status"] != base_contract["required_status"]
        ):
            errors.append("base review contract hash or status mismatch")
        if set(record["artifacts"]) != set(contract["candidate_artifacts"]):
            errors.append("accepted artifact set differs from the original contract")
        for path, digest in record["artifacts"].items():
            original = source.blob(SPONSOR_CANDIDATE, path)
            if _sha(original) != digest:
                errors.append(f"accepted candidate artifact hash mismatch: {path}")
            expected = original.replace(b"status: proposed", b"status: accepted", 1) if path == ADR else original
            if source.blob(acceptance_ref, path) != expected:
                errors.append(f"acceptance artifact drift: {path}")
            if current_ref is not None and source.blob(current_ref, path) != expected:
                errors.append(f"combined-base design artifact drift: {path}")
        if _sha(source.blob(acceptance_ref, ADR)) != record["accepted_adr_sha256"]:
            errors.append("accepted ADR hash mismatch")
        if _sha(source.blob(acceptance_ref, AMENDMENT)) != record["amendment"]["sha256"]:
            errors.append("sponsor amendment hash mismatch")
        if current_ref is not None:
            errors.extend(
                f"combined-base sponsor evidence drift: {path}"
                for path in (M9_PATH, AMENDMENT, SPONSOR_SCHEMA)
                if source.blob(current_ref, path) != source.blob(acceptance_ref, path)
            )
    except LOAD_ERRORS as exc:
        errors.append(f"evidence load failure: {exc}")
    return [f"M9_DESIGN_NOT_ACCEPTED: {error}" for error in errors]


def verify_prerequisite_record(
    record: dict[str, Any],
    source: EvidenceSource,
    *,
    acceptance_ref: str,
    candidate: bool = False,
) -> list[str]:
    errors: list[str] = []
    try:
        errors.extend(_schema_errors(source, acceptance_ref, P0_SCHEMA, record))
        if errors:
            return [f"M9_REQUIRED_EVIDENCE_MISSING: {error}" for error in errors]
        base = str(record["combined_base_head"])
        current_head = source.head()
        if current_head != acceptance_ref and not source.is_ancestor(acceptance_ref, current_head):
            errors.append("checked-out HEAD does not descend from the prerequisite ceremony")
        if source.dirty_paths():
            errors.append("acceptance worktree is dirty")
        if source.parents(acceptance_ref) != [base]:
            errors.append("prerequisite commit is not the sole child of the combined base")
        if source.changed_paths(acceptance_ref) != {P0_PATH}:
            errors.append("prerequisite commit must change only its acceptance record")
        expected_status = "M9_PREREQUISITES_CANDIDATE" if candidate else "M9_PREREQUISITES_ACCEPTED"
        if record["status"] != expected_status:
            return ["M9_REQUIRED_EVIDENCE_MISSING: independent review is required before prerequisite acceptance"]
        if not candidate:
            if record["review"]["reviewed_candidate_head"] != base:
                errors.append("independent review does not bind the exact combined base")
            reviewed = loads_unique_json(source.blob(base, P0_PATH))
            errors.extend(verify_prerequisite_record(reviewed, source, acceptance_ref=base, candidate=True))
            transition_fields = {"status", "combined_base_head", "review"}
            if {key: value for key, value in record.items() if key not in transition_fields} != {
                key: value for key, value in reviewed.items() if key not in transition_fields
            }:
                errors.append("accepted evidence differs from the reviewed prerequisite candidate")
        for name, expected_ref, path, status in (
            ("m8", M8_ACCEPTANCE, M8_PATH, "M8_IMPLEMENTATION_ACCEPTED"),
            ("m9", SPONSOR_ACCEPTANCE, M9_PATH, "M9_DESIGN_ACCEPTED"),
        ):
            binding = record["acceptances"][name]
            if binding["acceptance_commit"] != expected_ref:
                errors.append(f"{name} acceptance commit is not the accepted authority")
            if not source.is_ancestor(expected_ref, base):
                errors.append(f"combined base does not descend from {name} acceptance")
            payload = source.blob(expected_ref, path)
            if loads_unique_json(payload)["status"] != status:
                errors.append(f"{name} acceptance has the wrong status")
            if _sha(payload) != binding["sha256"] or source.blob(base, path) != payload:
                errors.append(f"{name} acceptance hash or combined-base binding mismatch")
            if source.blob(acceptance_ref, path) != payload:
                errors.append(f"{name} acceptance drift at verification HEAD")
        errors.extend(verify_sponsor_design(source, SPONSOR_ACCEPTANCE, current_ref=base))
        m8_record = loads_unique_json(source.blob(M8_ACCEPTANCE, M8_PATH))
        if source.parents(M8_ACCEPTANCE) != [m8_record["accepted_candidate_head"]]:
            errors.append("M8 acceptance candidate lineage mismatch")
        heads, graph_digest = source.migration_metadata(base)
        if heads != (record["alembic_head"],):
            errors.append("combined base does not have the exact singleton Alembic head")
        if graph_digest != record["revision_graph_digest"]:
            errors.append("combined-base revision graph digest mismatch")
        if (heads, graph_digest) != source.migration_metadata(M8_ACCEPTANCE):
            errors.append("migration graph changed from the accepted M8 prerequisite")
        if source.blob(base, P0_SCHEMA) != source.blob(acceptance_ref, P0_SCHEMA):
            errors.append("prerequisite schema changed after the combined base")
        if _sha(source.blob(acceptance_ref, P0_SCHEMA)) != record["schema_sha256"]:
            errors.append("prerequisite schema hash mismatch")
        errors.extend(
            "prerequisite verifier hash mismatch"
            for ref in (base, acceptance_ref)
            if _sha(source.blob(ref, P0_SCRIPT)) != record["tooling"]["sha256"]
        )
    except LOAD_ERRORS as exc:
        errors.append(f"evidence load failure: {exc}")
    return [error if error.startswith("M9_") else f"M9_REQUIRED_EVIDENCE_MISSING: {error}" for error in errors]


def verify_repository(
    repo: Path,
    *,
    reader: EvidenceSource | None = None,
    candidate: bool = False,
    design_only: bool = False,
    acceptance_ref: str | None = None,
) -> list[str]:
    source = reader or GitPrerequisiteReader(repo)
    try:
        head = source.head()
        if design_only:
            if source.dirty_paths():
                return ["M9_REQUIRED_EVIDENCE_MISSING: design verification worktree is dirty"]
            return verify_sponsor_design(source, current_ref=head)
        ref = acceptance_ref or head
        if len(ref) != 40 or any(char not in "0123456789abcdef" for char in ref):
            return ["M9_REQUIRED_EVIDENCE_MISSING: acceptance ref must be a full Git commit SHA"]
        record = loads_unique_json(source.blob(ref, P0_PATH))
        errors = verify_prerequisite_record(record, source, acceptance_ref=ref, candidate=candidate)
        if source.head() != head or source.dirty_paths():
            errors.append("M9_REQUIRED_EVIDENCE_MISSING: worktree changed during prerequisite verification")
        return errors
    except LOAD_ERRORS as exc:
        return [f"M9_REQUIRED_EVIDENCE_MISSING: evidence load failure: {exc}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--candidate", action="store_true", help="verify P0 candidate without authorizing M9-A")
    modes.add_argument("--design-only", action="store_true", help="verify the explicit sponsor design acceptance")
    parser.add_argument("--acceptance-ref", help="full accepted prerequisite commit SHA for a descendant worktree")
    args = parser.parse_args()
    if args.design_only and args.acceptance_ref:
        parser.error("--acceptance-ref applies to prerequisite verification, not --design-only")
    errors = verify_repository(
        Path.cwd(), candidate=args.candidate, design_only=args.design_only, acceptance_ref=args.acceptance_ref
    )
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    if args.design_only:
        print("M9_DESIGN_ACCEPTED: explicit sponsor decision; independent reviews were waived for this candidate")
    elif args.candidate:
        print("M9_PREREQUISITES_CANDIDATE: checks PASS; independent review pending; M9-A remains blocked")
    else:
        print("M9_PREREQUISITES_ACCEPTED: combined-base checks PASS; A0 environment checks remain required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
