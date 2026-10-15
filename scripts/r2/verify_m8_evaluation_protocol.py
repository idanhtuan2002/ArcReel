"""Verify the M8-F evaluation pre-registration (plan F1).

The protocol passes only when:

- it validates against its schema, which rejects unknown fields and any exclusion;
- every corpus source file still has its recorded sha256;
- both M6 profile cohorts are registered, each once.

With ``--results``, a results document must also bind the protocol's sha256 as
``protocol_digest``, and the commit that first added the results must descend from the commit
that first added the protocol, so results cannot predate their registration.

    uv run python scripts/r2/verify_m8_evaluation_protocol.py [--results <results.json>]

Every problem is reported as ``M8_EVALUATION_NOT_PREREGISTERED`` and exits 2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

STOP_CODE = "M8_EVALUATION_NOT_PREREGISTERED"
PROTOCOL = Path("docs/r2/evidence/R2_M8_EVALUATION_PROTOCOL_V3.json")
SCHEMA = Path("docs/r2/evidence/schemas/R2_M8_EVALUATION_PROTOCOL.schema.json")
COHORT_IDS = {"WESTERN_GENERIC", "CN_SHORT_DRAMA_SHUANGWEN"}


def protocol_problems(protocol: object, schema: object, repo: Path) -> list[str]:
    """Every problem with ``protocol``, sorted; an empty list is the only pass."""
    if not isinstance(schema, Mapping):
        return ["protocol schema is not an object"]
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    problems = [
        f"schema: {'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
        for error in validator.iter_errors(protocol)
    ]
    if not isinstance(protocol, Mapping):
        return sorted(problems)
    corpus = protocol.get("corpus")
    sources = corpus.get("sources") if isinstance(corpus, Mapping) else None
    for source in sources if isinstance(sources, list) else []:
        if not isinstance(source, Mapping):
            continue
        path = repo / str(source.get("path"))
        if not path.is_file():
            problems.append(f"corpus source {source.get('path')} is missing")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != source.get("sha256"):
            problems.append(f"corpus source {source.get('path')} changed after registration")
    cohorts = protocol.get("cohorts")
    ids = (
        [item.get("creative_profile_id") for item in cohorts if isinstance(item, Mapping)]
        if isinstance(cohorts, list)
        else []
    )
    if sorted(ids) != sorted(COHORT_IDS):
        problems.append(f"cohorts must be exactly {sorted(COHORT_IDS)}, found {ids}")
    return sorted(problems)


def _first_commit(repo: Path, path: Path) -> str | None:
    result = subprocess.run(
        ["git", "log", "--diff-filter=A", "--format=%H", "--", str(path)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    commits = result.stdout.split()
    return commits[-1] if result.returncode == 0 and commits else None


def results_problems(
    results: object, protocol_bytes: bytes, repo: Path, results_path: Path, protocol_path: Path = PROTOCOL
) -> list[str]:
    """Results must bind this protocol and must have been committed after it."""
    problems: list[str] = []
    digest = "sha256:" + hashlib.sha256(protocol_bytes).hexdigest()
    if not isinstance(results, Mapping) or results.get("protocol_digest") != digest:
        problems.append("results do not bind the registered protocol digest")
    protocol_commit = _first_commit(repo, protocol_path)
    results_commit = _first_commit(repo, results_path)
    if protocol_commit is None:
        problems.append("the protocol is not committed")
    elif results_commit is not None:
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", protocol_commit, results_commit], cwd=repo, check=False
        )
        if ancestor.returncode != 0 or protocol_commit == results_commit:
            problems.append("results were committed before or together with the protocol")
    return sorted(problems)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=Path())
    parser.add_argument("--results", type=Path)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    args = parser.parse_args(argv)
    repo: Path = args.repo
    protocol_bytes = (repo / args.protocol).read_bytes()
    problems = protocol_problems(
        json.loads(protocol_bytes), json.loads((repo / SCHEMA).read_text(encoding="utf-8")), repo
    )
    if args.results is not None:
        results = json.loads((repo / args.results).read_text(encoding="utf-8"))
        problems += results_problems(results, protocol_bytes, repo, args.results, args.protocol)
    for problem in problems:
        print(f"{STOP_CODE}: {problem}", file=sys.stderr)
    if problems:
        return 2
    print("M8_EVALUATION_PREREGISTERED_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
