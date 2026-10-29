"""Verify candidate-only M9-B acquisition evidence against immutable code and retained artifacts.

The evidence proves recorded gates at one clean code HEAD, never independent approval, release or activation.
Run with ``evidence.json --tested-head <clean-code-sha>``; the evidence may be uncommitted on that HEAD or committed
as its sole evidence child (the evidence JSONs and the retained artifact directory only).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field

from r2.contracts.advanced_creative import M8ContractModel
from scripts.r2.verify_m8_evidence import verify_m8_evidence
from scripts.r2.verify_m9_evidence import expected_test_functions
from scripts.r2.verify_m9_parity import ArtifactReference
from scripts.r2.verify_m9_prerequisites import LOAD_ERRORS, GitPrerequisiteReader, loads_unique_json

BRANCH = "impl/r2-m9b-acquisition-observations"
ORIGINAL_RELEASE = "docs/r2/evidence/R2_M9_B_PACKET_RELEASE.json"
RECOVERY_RELEASE = "docs/r2/evidence/R2_M9_B_RECOVERY_V2_RELEASE.json"
SCHEMA = "docs/r2/evidence/schemas/R2_M9_B_ACQUISITION.schema.json"
EVIDENCE = "docs/r2/evidence/R2_M9_B_ACQUISITION.json"
RECOVERY_EVIDENCE = "docs/r2/evidence/R2_M9_B_RECOVERY_V2.json"
ARTIFACT_ROOT = "docs/r2/evidence/m9b-recovery-v2/"
MIGRATION_DIRECTORY = "tests/integration/lib/db/migrations"
RESTART_TESTS = "tests/integration/r2/opportunity/test_acquisition_v2_restarts.py"
SCOPE_COMMAND = ("scripts/r2/verify_m9b_recovery_scope.py", RECOVERY_RELEASE)
GATES = frozenset(
    {"ruff", "format", "types", "imports", "dependencies", "audit", "diff", "scope", "tests", "migration"}
)
EVIDENCE_OUTPUTS = frozenset({EVIDENCE, RECOVERY_EVIDENCE})
# Executed regressions every candidate must bind for each fault class, by `module::function`.
FAULT_TESTS: dict[str, frozenset[str]] = {
    "replay": frozenset(
        {
            "tests.integration.r2.opportunity.test_acquisition_v2::test_v2_acquire_uses_committed_custody_before_dispatch_and_replays_without_ports",
            "tests.integration.r2.opportunity.test_acquisition_v2::test_v2_http_declares_acquires_replays_and_reads_through_the_scoped_service",
        }
    ),
    "scope": frozenset(
        {
            "tests.unit.server.routers.test_opportunity_acquisition_router::test_body_scope_injection_is_rejected_before_the_application",
            "tests.integration.r2.opportunity.test_acquisition_v2::test_v2_snapshot_read_scope_and_missing_identity_never_open_material",
        }
    ),
    "interactive": frozenset(
        {
            "tests.unit.server.routers.test_opportunity_acquisition_router::test_api_keys_and_disabled_auth_cannot_mutate",
            "tests.integration.r2.opportunity.test_acquisition_v2::test_v2_http_on_an_unconfigured_host_refuses_before_source_or_custody_contact",
        }
    ),
    "retention": frozenset(
        {
            "tests.integration.r2.opportunity.test_acquisition_v2::test_v2_expiry_uses_original_deadline_without_any_content_or_port_call",
            "tests.integration.r2.opportunity.test_acquisition_v2::test_v2_snapshot_history_becomes_stale_then_unavailable_at_original_deadlines",
        }
    ),
    "revocation": frozenset(
        {
            "tests.integration.r2.opportunity.test_acquisition_v2::test_v2_snapshot_reader_refuses_current_from_known_newer_source_revocation",
            "tests.integration.r2.opportunity.test_acquisition_v2::test_v2_known_newer_source_revocation_prevents_admission_and_dispatch",
        }
    ),
    "erasure": frozenset(
        {
            "tests.integration.r2.opportunity.test_acquisition_v2::test_v2_cleanup_commits_only_after_real_private_and_public_erasure",
            "tests.integration.r2.opportunity.test_acquisition_v2::test_v2_cleanup_drains_admitted_reads_before_any_private_erasure",
            "tests.integration.r2.opportunity.test_acquisition_v2::test_v2_cleanup_retry_reconciles_physical_erasure_with_sql_rollback",
        }
    ),
}
_SIGNING = re.compile(rb"Ed25519PrivateKey|PrivateFormat|private_bytes\(|from_private_bytes")


class RepoView(Protocol):
    """Read-only repository facts the verifier needs; the CLI binds Git, tests bind fixed bytes."""

    def blob(self, ref: str, path: str) -> bytes: ...
    def parents(self, ref: str) -> list[str]: ...
    def head(self) -> str: ...
    def changed(self, base: str, head: str) -> set[str]: ...
    def artifact(self, path: str) -> bytes: ...
    def evidence(self, path: str) -> bytes: ...


class GitRepoView:
    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.git = GitPrerequisiteReader(repo)

    def blob(self, ref: str, path: str) -> bytes:
        return self.git.blob(ref, path)

    def parents(self, ref: str) -> list[str]:
        return list(self.git.parents(ref))

    def head(self) -> str:
        return self.git.head()

    def changed(self, base: str, head: str) -> set[str]:
        return set(self.git._run("diff", "--name-only", base, head).decode().splitlines())

    def artifact(self, path: str) -> bytes:
        resolved = (self.repo / path).resolve()
        if not path.startswith(ARTIFACT_ROOT) or self.repo.resolve() not in resolved.parents:
            raise ValueError("artifact outside the retained artifact directory")
        return resolved.read_bytes()

    def evidence(self, path: str) -> bytes:
        if path not in EVIDENCE_OUTPUTS:
            raise ValueError("not an evidence output")
        return (self.repo / path).read_bytes()


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


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def owned_paths(view: RepoView, head: str) -> list[str]:
    """Every path either release owns that exists at `head`, minus the evidence outputs themselves."""
    paths: set[str] = set()
    for release in (ORIGINAL_RELEASE, RECOVERY_RELEASE):
        document = loads_unique_json(view.blob(head, release))
        for key in ("owned_create_paths", "owned_modify_paths", "inherited_unimplemented_create_paths"):
            paths.update(document.get(key, []))
    present = []
    for path in sorted(paths - EVIDENCE_OUTPUTS):
        try:
            view.blob(head, path)
        except LOAD_ERRORS:
            continue
        present.append(path)
    return present


def repository_bindings(view: RepoView, tested_head: str) -> dict[str, Any]:
    parents = view.parents(tested_head)
    if len(parents) != 1:
        raise ValueError("tested code must have exactly one parent")
    return {
        "tested_parent": parents[0],
        "branch": BRANCH,
        "releases": {path: _sha(view.blob(tested_head, path)) for path in (ORIGINAL_RELEASE, RECOVERY_RELEASE)},
        "sources": {path: _sha(view.blob(tested_head, path)) for path in owned_paths(view, tested_head)},
    }


def runtime_signing_problems(view: RepoView, tested_head: str, sources: Mapping[str, str]) -> list[str]:
    runtime = [
        path
        for path in sources
        if path.endswith(".py") and path.split("/", 1)[0] in {"r2", "server", "lib"} and "/tests/" not in path
    ]
    return [
        "runtime source depends on a private signing key: " + path
        for path in runtime
        if _SIGNING.search(view.blob(tested_head, path))
    ]


def command_shape_problems(gate: str, argv: tuple[str, ...], document: Mapping[str, Any]) -> list[str]:
    args = list(argv)
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
        expected = ["scripts/audit_tests.py", "--check"] if gate == "audit" else list(SCOPE_COMMAND)
        return [] if binary.startswith("python") and rest == expected else ["focused command mismatch"]
    if gate == "restarts":
        return restart_command_problems(binary, rest)
    if gate not in {"tests", "migration"}:
        return ["unknown gate command"]
    if not (binary.startswith("python") and rest[:2] == ["-m", "pytest"]):
        return ["test command is not pytest"]
    selected, junit_outputs = [], []
    value_options = {"-n", "--dist", "--durations"}
    index = 2
    while index < len(rest):
        value = rest[index]
        if value in value_options and index + 1 < len(rest):
            index += 2
            continue
        if value.startswith(("--junitxml=", "--junit-xml=")):
            junit_outputs.append(value.split("=", 1)[1])
        elif value.startswith("--basetemp=") or re.fullmatch(r"-[qv]+", value):
            pass
        elif "::" in value or not value.startswith("tests/") or value.startswith("-"):
            return ["required test gate uses an unapproved or partial selection"]
        else:
            selected.append(value.rstrip("/"))
        index += 1
    report = document["test_report" if gate == "tests" else "migration_report"]
    if len(junit_outputs) != 1 or not junit_outputs[0].endswith("/" + report["path"]):
        return ["pytest output path differs from the exact retained JUnit artifact"]
    if gate == "migration":
        return [] if selected == [MIGRATION_DIRECTORY] else ["migration command does not run the complete directory"]
    required = [
        path
        for path in document["sources"]
        if path.startswith("tests/")
        and path.endswith(".py")
        and Path(path).name.startswith("test_")
        and not path.startswith(MIGRATION_DIRECTORY + "/")
        and path != RESTART_TESTS
    ]
    if any(not any(path == item or path.startswith(item + "/") for item in selected) for path in required):
        return ["test command omits an owned test file"]
    return []


def restart_command_problems(binary: str, rest: list[str]) -> list[str]:
    if not binary.startswith("python") or len(rest) != 7 or rest[0] != "scripts/r2/run_m9b_recovery_gate.py":
        return ["restart command is not the pinned gate runner"]
    options = dict(zip(rest[1::2], rest[2::2], strict=True))
    if set(options) != {"--repo", "--artifact-dir", "--basetemp"}:
        return ["restart command uses unapproved options"]
    if options["--basetemp"] != options["--artifact-dir"].rstrip("/") + "/pytest-temp":
        return ["restart command does not own its pytest basetemp"]
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


def _summary_problems(log: bytes, passed: int, skipped: int) -> list[str]:
    summaries = re.findall(rb"(\d+) passed(?:, (\d+) skipped)?", log)
    if not summaries or int(summaries[-1][0]) != passed or int(summaries[-1][1] or 0) != skipped:
        return ["test log summary differs from recorded logical counts"]
    if re.search(rb"\d+ (failed|error|errors)\b", log):
        return ["test log reports failures or errors"]
    return []


def evidence_child_problems(view: RepoView, tested_head: str) -> list[str]:
    head = view.head()
    if head == tested_head:
        return []
    if view.parents(head) != [tested_head]:
        return ["evidence is not the sole child of the tested code HEAD"]
    stray = [
        path
        for path in view.changed(tested_head, head)
        if not (path in EVIDENCE_OUTPUTS or path.startswith(ARTIFACT_ROOT))
    ]
    return ["evidence child changes non-evidence paths: " + ", ".join(sorted(stray))] if stray else []


def verify_m9b_evidence(
    document: object,
    schema: object,
    view: RepoView,
    tested_head: str,
    *,
    gates: frozenset[str] = GATES,
    extra_faults: frozenset[str] = frozenset(),
) -> list[str]:
    """Every problem with the candidate document, sorted; an empty list is the only pass."""
    problems = verify_m8_evidence(document, schema, tested_head)
    if problems or not isinstance(document, dict):
        return problems
    try:
        bindings = repository_bindings(view, tested_head)
    except (*LOAD_ERRORS, ValueError) as error:
        return ["repository bindings are unavailable: " + type(error).__name__]
    problems.extend(
        f"immutable binding mismatch: {field}" for field, value in bindings.items() if document[field] != value
    )
    problems.extend(evidence_child_problems(view, tested_head))
    problems.extend(runtime_signing_problems(view, tested_head, bindings["sources"]))
    if document["runtime_signing_key_dependency"] is not False:
        problems.append("runtime signing key dependency is claimed")
    commands = document["commands"]
    names = [command["gate"] for command in commands]
    if frozenset(names) != gates or len(names) != len(set(names)):
        problems.append("required gates are missing, unknown or duplicated")
    artifacts = {item["path"]: item["sha256"] for item in document["artifacts"]}
    retained: dict[str, bytes] = {}
    for path, digest in artifacts.items():
        try:
            raw = view.artifact(path)
        except (OSError, ValueError):
            problems.append("retained artifact is absent: " + path)
            continue
        if _sha(raw) != digest:
            problems.append("retained artifact does not match its recorded hash: " + path)
        retained[path] = raw

    def read(ref: Mapping[str, str]) -> bytes:
        if artifacts.get(ref["path"]) != ref["sha256"] or ref["path"] not in retained:
            raise KeyError(ref["path"])
        return retained[ref["path"]]

    source_bytes = {path: view.blob(tested_head, path) for path in bindings["sources"] if path.startswith("tests/")}
    identities: dict[str, list[str]] = {}
    for command in commands:
        try:
            result = RecordedCommandResult.model_validate(loads_unique_json(read(command["result"])))
            log = read(command["log"])
        except (KeyError, ValueError):
            problems.append(f"{command['gate']}: machine result or log is not a retained artifact")
            continue
        problems.extend(
            f"{command['gate']}: {item}" for item in command_shape_problems(command["gate"], result.argv, document)
        )
        recorded = (
            command["gate"],
            command["tested_head"],
            command["command"],
            command["exit"],
            command["passed"],
            command["skipped"],
            command["log"],
        )
        actual = (
            result.gate,
            result.tested_head,
            shlex.join(result.argv),
            result.exit,
            result.passed,
            result.skipped,
            result.log.model_dump(),
        )
        if recorded != actual or result.tested_head != tested_head:
            problems.append(f"{command['gate']}: machine command result differs from recorded gate")
        if command["gate"] in {"tests", "migration"}:
            report = document["test_report" if command["gate"] == "tests" else "migration_report"]
            if result.test_report is None or result.test_report.model_dump() != report:
                problems.append(f"{command['gate']}: machine command result does not bind its exact JUnit artifact")
                continue
            if command["passed"] <= 0:
                problems.append(f"{command['gate']}: gate collected no passing tests")
            problems.extend(
                f"{command['gate']}: {item}" for item in _summary_problems(log, command["passed"], command["skipped"])
            )
            try:
                found, junit_problems = junit_identities(read(report), command["passed"])
            except (KeyError, ET.ParseError):
                problems.append(f"{command['gate']}: JUnit report is not a retained artifact")
                continue
            identities[command["gate"]] = found
            problems.extend(f"{command['gate']}: {item}" for item in junit_problems)
    executed = {identity.split("[", 1)[0] for gate in ("tests", "migration") for identity in identities.get(gate, [])}
    scoped = {"sources": [path for path in bindings["sources"] if path != RESTART_TESTS]}
    if identities.get("tests") and not expected_test_functions(
        {"scope_allowlist": scoped["sources"]}, source_bytes
    ).issubset(executed):
        problems.append("passing JUnit runs omit an owned test function")
    all_identities = [identity for gate in ("tests", "migration") for identity in identities.get(gate, [])]
    for category, anchors in FAULT_TESTS.items():
        claimed = document["fault_matrix"].get(category, {}).get("test_refs", [])
        expected = {identity for identity in all_identities if identity.split("[", 1)[0] in anchors}
        if not anchors.issubset(executed) or set(claimed) != expected or len(set(claimed)) != len(claimed):
            problems.append(f"fault category {category} does not bind its complete executed test inventory")
    if set(document["fault_matrix"]) - set(FAULT_TESTS) - extra_faults:
        problems.append("fault matrix names an unknown category")
    if document["full_backend"]["executed"] and not document["full_backend"].get("log"):
        problems.append("full backend is claimed without a retained log")
    for flag in ("production_activation_authorized", "provider_network_executed"):
        if document[flag] is not False:
            problems.append(f"{flag} must be false for a candidate")
    review = document["independent_review"]
    if review["budget"] != 1 or review["used"] != 0:
        problems.append("independent review budget is not the single unused pass")
    return sorted(set(problems))


def load_document(path: Path) -> object:
    return loads_unique_json(path.read_bytes())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        document = load_document(args.evidence)
        schema = json.loads((args.repo / SCHEMA).read_text(encoding="utf-8"))
    except (*LOAD_ERRORS, ValueError) as error:
        print("M9_REQUIRED_EVIDENCE_MISSING: " + type(error).__name__)
        return 1
    problems = verify_m9b_evidence(document, schema, GitRepoView(args.repo), args.tested_head)
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print("M9_B_EVIDENCE_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
