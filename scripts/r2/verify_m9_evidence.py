"""Verify candidate-only M9-A proof against immutable code and retained log bytes.

This fold proves recorded gates and lineage, never independent approval or release.
Run with evidence.json --tested-head <clean-code-sha>; the evidence may be staged
on that code HEAD or committed as its sole schema/evidence child.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import os
import re
import shlex
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from r2.contracts.advanced_creative import DonorParityReport, M8ContractModel
from scripts.audit_tests import (
    collection_overrides,
    is_collected_test_class,
    is_collected_test_module,
    is_test_function,
    resolve_collection_scope,
)
from scripts.r2.verify_donor_parity import clone_file_hashes
from scripts.r2.verify_m8_evidence import artifact_problems, verify_m8_evidence
from scripts.r2.verify_m9_parity import ArtifactReference, retained_evidence, verified_artifact_bytes, verify_m9_parity
from scripts.r2.verify_m9_prerequisites import LOAD_ERRORS, GitPrerequisiteReader, loads_unique_json
from scripts.r2.verify_m9_scope import BASE, BASELINE, BRANCH, CONTRACT, SEAMS, verify_m9_scope

SCHEMA = "docs/r2/evidence/schemas/R2_M9_A_FOUNDATION.schema.json"
EVIDENCE = "docs/r2/evidence/R2_M9_A_FOUNDATION.json"
GATES = {"ruff", "format", "types", "imports", "dependencies", "tests", "audit", "diff", "scope", "migration", "parity"}


def verify_m9_evidence(document: object, schema: object, tested_head: str, bindings: Mapping[str, object]) -> list[str]:
    problems = verify_m8_evidence(document, schema, tested_head)
    if problems or not isinstance(document, dict):
        return problems
    problems.extend(
        f"immutable binding mismatch: {field}" for field, value in bindings.items() if document.get(field) != value
    )
    commands = document["commands"]
    gates = [command["gate"] for command in commands]
    if set(gates) != GATES or len(gates) != len(set(gates)):
        problems.append("required gates are missing, unknown or duplicated")
    artifacts = {(item["path"], item["sha256"]) for item in document["artifacts"]}
    required_refs = [document["test_report"], document["migration_report"], *document["parity_reports"]]
    required_refs.extend(command["result"] for command in commands)
    if any((ref["path"], ref["sha256"]) not in artifacts for ref in required_refs):
        problems.append("machine proof is not a retained artifact")
    for command in commands:
        if command["tested_head"] != tested_head:
            problems.append("command belongs to another tested HEAD")
        if command["gate"] == "tests" and command["passed"] <= 0:
            problems.append("test gate collected no passing tests")
        if (command["log"]["path"], command["log"]["sha256"]) not in artifacts:
            problems.append("command log is not a retained artifact")
    for proof in document["fault_matrix"].values():
        if proof["command_gate"] != "tests":
            problems.append("fault proof is not bound to the test gate")
    coverage = document["graph_coverage"]
    if not set(document["contracts"]).issubset(coverage["paths"]):
        problems.append("contract paths are absent from graph coverage")
    if (coverage["artifact"]["path"], coverage["artifact"]["sha256"]) not in artifacts:
        problems.append("graph coverage is not a retained artifact")
    return sorted(set(problems))


class FoundationEvidenceReader(GitPrerequisiteReader):
    def changed_since(self, base: str, head: str) -> set[str]:
        return set(self._run("diff", "--name-only", base, head).decode().splitlines())

    def branch(self) -> str:
        return self._run("branch", "--show-current").decode().strip()


def repository_bindings(source: GitPrerequisiteReader, tested_head: str) -> dict[str, Any]:
    baseline_raw = source.blob(tested_head, BASELINE)
    baseline = loads_unique_json(baseline_raw)
    parents = source.parents(tested_head)
    if len(parents) != 1:
        raise ValueError("tested code must have exactly one parent")
    migration = "alembic/versions/9a9c4a0e0001_add_m9_opportunity_foundation.py"

    def digest(path: str) -> str:
        return hashlib.sha256(source.blob(tested_head, path)).hexdigest()

    return {
        "tested_parent": parents[0],
        "branch": BRANCH,
        "baseline_sha256": hashlib.sha256(baseline_raw).hexdigest(),
        "documents": {path: digest(path) for path in baseline["documents"]},
        "contracts": {
            path: digest(path)
            for path in ("r2/contracts/opportunity.py", "r2/opportunity/digests.py", "r2/opportunity/ports.py")
        },
        "seams": {path: digest(path) for path in SEAMS},
        "migration": {
            "path": migration,
            "sha256": digest(migration),
            "head": "9a9c4a0e0001",
            "predecessor": "918c4a0e0001",
        },
        "scope_allowlist": baseline["scope_allowlist"],
        "donor_inventory": baseline["donors"],
    }


def command_log_problems(
    document: dict[str, Any], repo: Path, retained: Mapping[str, bytes] | None = None
) -> list[str]:
    problems = artifact_problems(document, repo)
    for command in document["commands"]:
        if command["gate"] not in {"tests", "migration"}:
            continue
        path = repo / command["log"]["path"]
        if not path.is_file():
            continue
        log = (
            retained[command["log"]["path"]].decode("utf-8")
            if retained is not None
            else path.read_text(encoding="utf-8")
        )
        summaries = re.findall(r"(\d+) passed(?:, (\d+) skipped)?", log)
        if (
            not summaries
            or int(summaries[-1][0]) != command["passed"]
            or int(summaries[-1][1] or 0) != command["skipped"]
        ):
            problems.append("test log summary differs from recorded logical counts")
    return sorted(set(problems))


MIGRATION_TEST_PATH = "tests/integration/lib/db/migrations/test_alembic_m9_foundation.py"
MIGRATION_CASES = frozenset(
    {
        "tests.integration.lib.db.migrations.test_alembic_m9_foundation::test_migration_extends_the_accepted_singleton_with_one_linear_revision",
        "tests.integration.lib.db.migrations.test_alembic_m9_foundation::test_five_table_round_trip_preserves_every_existing_table",
    }
)
FAULT_TESTS = {
    "replay": frozenset(
        {
            "tests.unit.r2.opportunity.test_profiles::test_lost_commit_acknowledgement_reconciles_from_receipt_without_reauthorization",
            "tests.integration.r2.opportunity.test_profile_concurrency::test_absent_receipt_races_serialize_but_full_key_and_digest_remain_authority",
        }
    ),
    "scope": frozenset(
        {
            "tests.unit.server.routers.test_opportunity_router::test_body_scope_injection_is_rejected_before_authorization",
            "tests.unit.r2.opportunity.test_profiles::test_read_boundary_does_not_return_hash_valid_foreign_scope_or_head",
        }
    ),
    "custody": frozenset(
        {
            "tests.unit.server.routers.test_opportunity_router::test_auth_disabled_or_api_key_cannot_reach_human_publication",
            "tests.integration.server.services.test_m9_custodian::test_a_principal_without_a_human_grant_cannot_issue_a_lease",
            "tests.integration.server.services.test_m9_custodian::test_expired_unadmitted_command_never_refreshes_its_lease",
            "tests.integration.server.services.test_m9_custodian::test_lease_replay_rejects_tampered_retained_signed_bytes_without_disclosing_them",
        }
    ),
    "rollback": frozenset(
        {
            "tests.integration.lib.db.repositories.test_opportunity_profiles::test_every_staged_flush_rolls_back_with_the_authority_transaction",
            "tests.integration.lib.db.repositories.test_opportunity_profiles::test_stale_head_cas_rolls_back_an_already_staged_revision",
        }
    ),
    "integrity": frozenset(
        {
            "tests.integration.lib.db.repositories.test_opportunity_profiles::test_reads_recompute_the_complete_profile_not_only_stored_digest_columns",
            "tests.integration.lib.db.repositories.test_opportunity_profiles::test_receipt_ref_cannot_substitute_a_different_valid_profile",
            "tests.integration.lib.db.repositories.test_opportunity_profiles::test_database_driver_failures_do_not_expose_profile_payload_in_exception_paths",
        }
    ),
    "concurrency": frozenset(
        {
            "tests.integration.r2.opportunity.test_profile_concurrency::test_different_commands_racing_genesis_commit_one_complete_aggregate",
            "tests.integration.r2.opportunity.test_profile_concurrency::test_append_waiter_reads_the_committed_head_before_admission",
            "tests.integration.r2.opportunity.test_profile_concurrency::test_project_policy_read_serializes_real_admission_in_both_directions",
        }
    ),
    "architecture": frozenset(
        {
            "tests.unit.r2.opportunity.test_m9_opportunity_boundaries::test_opportunity_module_exposes_only_protocols_at_external_seams",
            "tests.unit.r2.opportunity.test_m9_opportunity_boundaries::test_deep_module_cannot_import_credentials_providers_or_foreign_repositories",
            "tests.unit.r2.opportunity.test_m9_opportunity_boundaries::test_repository_never_commits_or_calls_another_authority",
        }
    ),
}


def command_shape_problems(gate: str, argv: tuple[str, ...], document: dict[str, Any]) -> list[str]:
    args = list(argv)
    if args[:2] == ["uv", "run"]:
        args = args[2:]
    if not args:
        return ["gate has no executable"]
    binary, rest = Path(args[0]).name, args[1:]
    exact = {
        "ruff": ("ruff", ["check", "."]),
        "format": ("ruff", ["format", "--check", "."]),
        "types": ("basedpyright", ["--warnings"]),
        "imports": ("lint-imports", []),
        "dependencies": ("deptry", ["lib", "server", "alembic", "scripts", "tests", "r2"]),
        "diff": ("git", ["diff", "--check"]),
    }
    if gate in exact:
        return [] if (binary, rest) == exact[gate] else ["command does not execute its declared gate"]
    if gate in {"audit", "scope"}:
        expected = (
            ["scripts/audit_tests.py", "--check"] if gate == "audit" else ["scripts/r2/verify_m9_scope.py", CONTRACT]
        )
        return [] if binary.startswith("python") and rest == expected else ["focused command mismatch"]
    if gate == "parity":
        if not binary.startswith("python") or len(rest) not in {6, 8} or rest[0] != "scripts/r2/verify_m9_parity.py":
            return ["parity command is not the pinned verifier"]
        if rest[2:4] != ["--head", document["tested_head"]] or rest[4] != "--donor-clone":
            return ["parity command does not bind the tested HEAD and local donor clone"]
        if rest[1] not in {ref["path"] for ref in document["parity_reports"]}:
            return ["parity command does not consume a retained report"]
        if len(rest) == 8 and rest[6] != "--evidence-root":
            return ["unapproved parity command option"]
        return []
    if gate not in {"tests", "migration"}:
        return ["unknown gate command"]
    if binary.startswith("python") and rest[:2] == ["-m", "pytest"]:
        rest = rest[2:]
    elif binary != "pytest":
        return ["test command is not pytest"]
    selected, junit_outputs = [], []
    index = 0
    value_options = {"-n", "--dist", "--junitxml", "--junit-xml", "--durations", "--tb"}
    while index < len(rest):
        value = rest[index]
        if value in value_options:
            if index + 1 >= len(rest):
                return ["test gate option lacks its value"]
            if value in {"--junitxml", "--junit-xml"}:
                junit_outputs.append(rest[index + 1])
            index += 2
            continue
        option = next((item for item in value_options if value.startswith(item + "=")), None)
        if option is not None:
            if option in {"--junitxml", "--junit-xml"}:
                junit_outputs.append(value.split("=", 1)[1])
            index += 1
            continue
        if re.fullmatch(r"-[qv]+", value) or value in {"--disable-warnings", "-x"}:
            index += 1
            continue
        if "::" in value or not (value == "tests" or value.startswith("tests/")):
            return ["required test gate uses an unapproved or partial selection"]
        selected.append(value.rstrip("/"))
        index += 1
    report = document["test_report" if gate == "tests" else "migration_report"]
    if junit_outputs != [report["path"]]:
        return ["pytest output path differs from the exact retained JUnit artifact"]
    if gate == "migration":
        return (
            []
            if selected == [MIGRATION_TEST_PATH]
            else ["migration command does not run the complete committed round-trip wrapper"]
        )
    required = [path for path in document["scope_allowlist"] if path.startswith("tests/") and path.endswith(".py")]
    if selected and any(not any(path == item or path.startswith(item + "/") for item in selected) for path in required):
        return ["test command omits an owned test file"]
    return []


def junit_identities(raw: bytes, passed: int) -> tuple[list[str], list[str]]:
    cases = list(ET.fromstring(raw).iter("testcase"))
    identities = [case.attrib["classname"] + "::" + case.attrib["name"] for case in cases]
    problems = []
    if not cases or len(cases) != passed or len(set(identities)) != len(cases):
        problems.append("JUnit cases differ from logical passing test count or repeat identities")
    if any(case.find(tag) is not None for case in cases for tag in ("failure", "error", "skipped")):
        problems.append("required JUnit cases contain failure, error or skip")
    return identities, problems


def expected_test_functions(document: dict[str, Any], source_bytes: Mapping[str, bytes]) -> set[str]:
    expected = set()
    for path in document["scope_allowlist"]:
        if not path.startswith("tests/") or not path.endswith(".py"):
            continue
        module = path.removesuffix(".py").replace("/", ".")
        tree = ast.parse(source_bytes[path])
        if not is_collected_test_module(Path(path), tree):
            continue
        collection_scope = resolve_collection_scope(tree)

        def visit(nodes, classes=(), qualified_module=module, collected=collection_scope):
            overrides = collection_overrides(nodes)
            for node in nodes:
                if isinstance(node, ast.ClassDef) and is_collected_test_class(node, collected):
                    visit(node.body, (*classes, node.name), qualified_module, collected)
                elif is_test_function(node, overrides):
                    expected.add(qualified_module + "".join("." + name for name in classes) + "::" + node.name)

        visit(tree.body)
    return expected


class RecordedCommandResult(M8ContractModel):
    schema_version: Literal["m9.command-result.v1"]
    gate: str
    tested_head: str = Field(pattern=r"^[0-9a-f]{40}$")
    argv: tuple[str, ...] = Field(min_length=1)
    exit: int
    passed: int = Field(ge=0)
    skipped: int = Field(ge=0)
    log: ArtifactReference
    test_report: ArtifactReference | None = None


def recorded_log_problems(
    document: dict[str, Any], repo: Path, source_bytes: Mapping[str, bytes] | None = None
) -> list[str]:
    try:
        retained = {ref["path"]: (repo / ref["path"]).read_bytes() for ref in document["artifacts"]}

        def read(ref):
            return verified_artifact_bytes(ArtifactReference.model_validate(ref), retained)

        for ref in document["artifacts"]:
            read(ref)
    except (KeyError, OSError, ValueError):
        return ["retained artifact snapshot is absent or does not match its recorded hash"]
    problems = command_log_problems(document, repo, retained)
    if problems:
        return problems
    try:
        for command in document["commands"]:
            result = RecordedCommandResult.model_validate(loads_unique_json(read(command["result"])))
            problems.extend(command_shape_problems(command["gate"], result.argv, document))
            expected_report = (
                document["test_report"]
                if command["gate"] == "tests"
                else document["migration_report"]
                if command["gate"] == "migration"
                else None
            )
            if (result.test_report.model_dump() if result.test_report is not None else None) != expected_report:
                problems.append("machine command result does not bind its exact JUnit artifact")
            if (
                result.gate,
                result.tested_head,
                shlex.join(result.argv),
                result.exit,
                result.passed,
                result.skipped,
                result.log.model_dump(),
            ) != (
                command["gate"],
                document["tested_head"],
                command["command"],
                command["exit"],
                command["passed"],
                command["skipped"],
                command["log"],
            ):
                problems.append("machine command result differs from recorded gate")
        test_command = next(command for command in document["commands"] if command["gate"] == "tests")
        identities, junit_problems = junit_identities(read(document["test_report"]), test_command["passed"])
        problems.extend(junit_problems)
        executed_functions = {identity.split("[", 1)[0] for identity in identities}
        if not expected_test_functions(document, source_bytes or {}).issubset(executed_functions):
            problems.append("passing JUnit run omits an owned test function")
        for category, anchors in FAULT_TESTS.items():
            expected_refs = {identity for identity in identities if identity.split("[", 1)[0] in anchors}
            claimed = document["fault_matrix"][category]["test_refs"]
            if (
                not anchors.issubset(executed_functions)
                or set(claimed) != expected_refs
                or len(set(claimed)) != len(claimed)
            ):
                problems.append("fault category does not bind its complete required executed test inventory")
        migration_command = next(command for command in document["commands"] if command["gate"] == "migration")
        migration_cases, migration_problems = junit_identities(
            read(document["migration_report"]), migration_command["passed"]
        )
        problems.extend(migration_problems)
        if frozenset(migration_cases) != MIGRATION_CASES:
            problems.append("migration wrapper does not prove every committed round-trip/head check")
        coverage = document["graph_coverage"]
        snapshot = loads_unique_json(read(coverage["artifact"]))
        metadata = snapshot["metadata"]
        if (
            snapshot["project"],
            snapshot["signal"],
            snapshot["tested_head"],
            snapshot["indexed_at"],
            metadata["generation"],
            metadata["generation_matches"],
            metadata["recording_status"],
        ) != (
            coverage["project"],
            "best_effort",
            document["tested_head"],
            coverage["generation"],
            coverage["generation"],
            True,
            "complete",
        ):
            problems.append("graph project/generation/tested HEAD or recording status mismatch")
        rows = snapshot["paths"]
        paths = [row["path"] for row in rows]
        if set(paths) != set(coverage["paths"]) or len(paths) != len(set(paths)):
            problems.append("graph snapshot differs from declared complete path inventory")
        needs_source = {
            row["path"]
            for row in rows
            if row["status"] != "no_recorded_issue" or row["freshness"] != "metadata_match" or row["coverage"]
        }
        fallback = snapshot["source_fallback_reads"]
        if set(coverage["source_fallback"]) != needs_source or set(fallback) != needs_source:
            problems.append("graph gap/staleness/exclusion lacks exact full-source fallback inventory")
        for path in needs_source:
            raw = (source_bytes or {})[path]
            if hashlib.sha256(raw).hexdigest() != fallback[path]:
                problems.append("graph source fallback differs from immutable tested code")
    except (KeyError, OSError, ValueError, TypeError, ET.ParseError, StopIteration):
        problems.append("retained machine result, JUnit or graph proof is absent or invalid")
    return sorted(set(problems))


def recorded_parity_problems(document: dict[str, Any], repo: Path, donor_root: Path) -> list[str]:
    os.environ["GIT_NO_LAZY_FETCH"] = "1"
    problems = []
    manifests = {item["commit"]: item for item in document["donor_inventory"]}
    seen = []
    for artifact in document["parity_reports"]:
        path = repo / artifact["path"]
        try:
            raw = path.read_bytes()
            verified_artifact_bytes(ArtifactReference.model_validate(artifact), {artifact["path"]: raw})
            body = loads_unique_json(raw)
            report = DonorParityReport.model_validate(body)
            pin = report.donor.commit_sha
            manifest = manifests[pin]
            seen.append(pin)
            hashes = clone_file_hashes(donor_root / (manifest["name"] + ".git"), pin, report.donor.selected_paths)
            problems.extend(
                verify_m9_parity(body, document["tested_head"], hashes, retained_evidence(report, path.parent))
            )
        except (KeyError, OSError, ValueError):
            problems.append("M9_DONOR_PARITY_INCOMPLETE: retained donor report or paired artifacts unavailable")
    if set(seen) != set(manifests) or len(seen) != len(set(seen)):
        problems.append("M9_DONOR_PARITY_INCOMPLETE: exact donor report inventory missing or duplicated")
    return sorted(set(problems))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--repo", type=Path, default=Path())
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    try:
        source = FoundationEvidenceReader(repo)
        document = loads_unique_json(args.evidence.read_bytes())
        schema = loads_unique_json((repo / SCHEMA).read_bytes())
        problems = verify_m9_evidence(document, schema, args.tested_head, repository_bindings(source, args.tested_head))
        if not problems:
            problems.extend(
                recorded_log_problems(
                    document,
                    repo,
                    {path: source.blob(args.tested_head, path) for path in document["graph_coverage"]["paths"]},
                )
            )
            problems.extend(verify_m9_scope(repo, loads_unique_json(source.blob(args.tested_head, CONTRACT))))
            donor_root = os.environ.get("ARCREEL_M9_DONOR_ROOT")
            if donor_root is None:
                problems.append("M9_DONOR_PARITY_INCOMPLETE: no pinned local donor root")
            else:
                problems.extend(recorded_parity_problems(document, repo, Path(donor_root)))
            changed = source.changed_since(BASE, args.tested_head)
            if not changed.issubset(document["scope_allowlist"]):
                problems.append("tested code exceeds owned scope")
            if not changed.issubset(document["graph_coverage"]["paths"]):
                problems.append("graph coverage omits changed paths")
            if source.branch() != BRANCH:
                problems.append("current branch is not M9-A implementation")
            if set(source.dirty_paths()) - {SCHEMA, EVIDENCE}:
                problems.append("unreviewed code or unrelated dirty paths are present")
            if (repo / SCHEMA).read_bytes() != source.blob(args.tested_head, SCHEMA):
                problems.append("verifier schema differs from tested code")
            head = source.head()
            if head != args.tested_head and (
                source.parents(head) != [args.tested_head]
                or not source.changed_paths(head).issubset({SCHEMA, EVIDENCE})
            ):
                problems.append("evidence is not on tested code or its sole schema/evidence child")
            if not source.is_ancestor(BASE, args.tested_head):
                problems.append("tested code does not descend from accepted P0")
    except LOAD_ERRORS:
        problems = ["M9_REQUIRED_EVIDENCE_MISSING: evidence or immutable code binding unavailable"]
    for problem in problems:
        print(problem)
    if problems:
        return 2
    print("M9_A_CANDIDATE_EVIDENCE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
