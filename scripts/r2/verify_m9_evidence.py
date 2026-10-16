"""Verify candidate-only M9-A proof against immutable code and retained log bytes.

This fold proves recorded gates and lineage, never independent approval or release.
Run with evidence.json --tested-head <clean-code-sha>; the evidence may be staged
on that code HEAD or committed as its sole schema/evidence child.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts.r2.verify_m8_evidence import artifact_problems, verify_m8_evidence
from scripts.r2.verify_m9_prerequisites import LOAD_ERRORS, GitPrerequisiteReader, loads_unique_json
from scripts.r2.verify_m9_scope import BASE, BASELINE, BRANCH, SEAMS

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


def recorded_log_problems(document: dict[str, Any], repo: Path) -> list[str]:
    problems = artifact_problems(document, repo)
    for command in document["commands"]:
        if command["gate"] != "tests":
            continue
        path = repo / command["log"]["path"]
        if not path.is_file():
            continue
        log = path.read_text(encoding="utf-8")
        summaries = re.findall(r"(\d+) passed(?:, (\d+) skipped)?", log)
        if (
            not summaries
            or int(summaries[-1][0]) != command["passed"]
            or int(summaries[-1][1] or 0) != command["skipped"]
        ):
            problems.append("test log summary differs from recorded logical counts")
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
            problems.extend(recorded_log_problems(document, repo))
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
