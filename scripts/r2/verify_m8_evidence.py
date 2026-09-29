"""The shared strict M8 evidence fold (plan Tasks A1.4 and A4).

An evidence document passes only when:

- it validates against its schema, which rejects unknown fields;
- it binds the expected tested HEAD;
- it lists at least one artifact;
- every recorded command exited 0;
- it records no required skip and no material unknown.

    uv run python scripts/r2/verify_m8_evidence.py <evidence.json> --schema <schema.json> \\
        --tested-head <sha>

The command form also checks that each listed artifact exists and still has its recorded
sha256. It exits 2 on any problem.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


def verify_m8_evidence(document: object, schema: object, expected_tested_head: str) -> list[str]:
    """Every problem with ``document``, sorted; an empty list is the only pass."""
    if not isinstance(schema, Mapping):
        return ["evidence schema is not an object"]
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    problems = [
        f"schema: {'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
        for error in validator.iter_errors(document)
    ]
    if not isinstance(document, Mapping):
        return sorted(problems)
    if document.get("tested_head") != expected_tested_head:
        problems.append(f"tested_head is {document.get('tested_head')!r}, expected {expected_tested_head!r}")
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        problems.append("no artifacts are recorded")
    commands = document.get("commands")
    for command in commands if isinstance(commands, list) else []:
        exit_status = command.get("exit") if isinstance(command, Mapping) else None
        if exit_status != 0:
            problems.append(f"command {command!r} did not exit 0")
    problems.extend(
        f"{key} is not empty: {document.get(key)!r}"
        for key in ("required_skips", "material_unknowns")
        if document.get(key)
    )
    return sorted(problems)


def artifact_problems(document: Mapping[str, object], repo: Path) -> list[str]:
    problems: list[str] = []
    artifacts = document.get("artifacts")
    for artifact in artifacts if isinstance(artifacts, list) else []:
        if not isinstance(artifact, Mapping):
            continue
        path = repo / str(artifact.get("path"))
        if not path.is_file():
            problems.append(f"artifact {artifact.get('path')} is missing")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != artifact.get("sha256"):
            problems.append(f"artifact {artifact.get('path')} no longer has its recorded sha256")
    return sorted(problems)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--repo", type=Path, default=Path())
    args = parser.parse_args(argv)
    document = json.loads(args.evidence.read_text(encoding="utf-8"))
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    problems = verify_m8_evidence(document, schema, args.tested_head)
    if isinstance(document, Mapping):
        problems += artifact_problems(document, args.repo.resolve())
    for problem in sorted(problems):
        print(problem)
    if problems:
        return 2
    print("M8_EVIDENCE_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
