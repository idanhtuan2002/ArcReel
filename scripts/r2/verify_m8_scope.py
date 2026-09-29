"""Machine-checkable M8 accepted baseline (plan Task A0, execution contract and amendments).

The verifier fails closed unless every prerequisite holds:

- **Branch and base.** The branch is the M8-A implementation branch, not the design branch.
  The recorded executor base is an ancestor of HEAD, and every change since it, committed or
  not, is inside the exact scope allowlist.
- **Alembic.** The executor base has exactly one Alembic head, the recorded one. Later M8
  migrations are in the scope allowlist.
- **M7 evidence and design artifacts.** They still hash to the recorded values. The
  acceptance names the recorded candidate HEAD with the recorded status.
- **Authority seams.** Each keeps its path, signature and source hash.
- **Donors.** Each is present at its pinned commit, with the selected files' recorded hashes.

    uv run python scripts/r2/verify_m8_scope.py docs/r2/evidence/R2_M8_BASELINE.json \\
        --donor DramaClaw=<clone> --donor OpenMontage=<clone>

It prints the sorted stop codes and details and exits 2 on any failure, or prints
``M8_BASELINE_OK`` and exits 0.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from scripts.r2.verify_m7_scope import _alembic_revision_metadata_at_ref

DESIGN_BRANCH = "design/r2-m5b-narrative-context"
SCHEMA_RELPATH = "docs/r2/evidence/schemas/R2_M8_BASELINE.schema.json"
ACCEPTANCE_RELPATH = "docs/r2/evidence/R2_M7_IMPLEMENTATION_ACCEPTANCE.json"

PREREQUISITE = "M8_PREREQUISITE_NOT_ACCEPTED"
SEAM_CHANGED = "M8_BASE_SEAM_CHANGED"
DONOR_DRIFT = "M8_DONOR_BASELINE_DRIFT"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MARKDOWN_STATUS = re.compile(r"\*\*Status:\*\*\s*`([A-Z0-9_]+)`")


@dataclass(frozen=True)
class ObservedSeam:
    path: str
    signature: str
    sha256: str


@dataclass(frozen=True)
class Observed:
    branch: str
    base_is_ancestor: bool
    changed_paths: tuple[str, ...]
    alembic_heads: tuple[str, ...]
    file_hashes: Mapping[str, str]
    evidence_status: Mapping[str, str | None]
    accepted_candidate_head: str | None
    seams: Mapping[str, ObservedSeam]
    donor_commits: Mapping[str, str | None]
    donor_files: Mapping[tuple[str, str], str] = field(default_factory=dict)


# --- pure evaluation -----------------------------------------------------------------


def schema_problems(baseline: object) -> list[str]:
    schema = json.loads((_REPO_ROOT / SCHEMA_RELPATH).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return sorted(
        f"{PREREQUISITE}: baseline schema: {'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
        for error in validator.iter_errors(baseline)
    )


def _prerequisite_problems(baseline: Mapping[str, object], observed: Observed) -> list[str]:
    problems: list[str] = []
    if observed.branch == DESIGN_BRANCH:
        problems.append(f"{PREREQUISITE}: running on the design branch {DESIGN_BRANCH}")
    elif observed.branch != baseline["branch"]:
        problems.append(f"{PREREQUISITE}: branch is {observed.branch!r}, expected {baseline['branch']!r}")
    if not observed.base_is_ancestor:
        problems.append(f"{PREREQUISITE}: executor base {baseline['base_head']} is not an ancestor of HEAD")
    allowlist = set(_strings(baseline["scope_allowlist"]))
    outside = sorted(path for path in observed.changed_paths if path not in allowlist)
    if outside:
        problems.append(f"{PREREQUISITE}: changes outside the scope allowlist: {outside}")
    expected_heads = tuple(_strings(baseline["alembic_heads"]))
    if observed.alembic_heads != expected_heads:
        problems.append(
            f"{PREREQUISITE}: Alembic heads are {list(observed.alembic_heads)}, expected {list(expected_heads)}"
        )
    for entry in _records(baseline["m7_evidence"]):
        path = str(entry["path"])
        if observed.file_hashes.get(path) != entry["sha256"]:
            problems.append(f"{PREREQUISITE}: M7 evidence {path} is missing or its hash drifted")
        elif observed.evidence_status.get(path) != entry["status"]:
            problems.append(
                f"{PREREQUISITE}: M7 evidence {path} status is {observed.evidence_status.get(path)!r}, "
                f"expected {entry['status']!r}"
            )
    if observed.accepted_candidate_head != baseline["accepted_m7_candidate_head"]:
        problems.append(
            f"{PREREQUISITE}: the acceptance names candidate {observed.accepted_candidate_head!r}, "
            f"expected {baseline['accepted_m7_candidate_head']!r}"
        )
    for entry in _records(baseline["design_artifacts"]):
        path = str(entry["path"])
        if observed.file_hashes.get(path) != entry["sha256"]:
            problems.append(f"{PREREQUISITE}: design artifact {path} is missing or its hash drifted")
    return problems


def _seam_problems(baseline: Mapping[str, object], observed: Observed) -> list[str]:
    problems: list[str] = []
    for entry in _records(baseline["seams"]):
        name = str(entry["qualified_name"])
        seam = observed.seams.get(name)
        if seam is None:
            problems.append(f"{SEAM_CHANGED}: seam {name} is missing")
            continue
        problems.extend(
            f"{SEAM_CHANGED}: seam {name} {key} drifted"
            for key in ("path", "signature", "sha256")
            if getattr(seam, key) != entry[key]
        )
    return problems


def _donor_problems(baseline: Mapping[str, object], observed: Observed) -> list[str]:
    problems: list[str] = []
    for donor in _records(baseline["donors"]):
        name = str(donor["name"])
        if observed.donor_commits.get(name) != donor["commit"]:
            problems.append(f"{DONOR_DRIFT}: donor {name} is not available at pinned commit {donor['commit']}")
            continue
        problems.extend(
            f"{DONOR_DRIFT}: donor {name} file {item['path']} is missing or its hash drifted"
            for item in _records(donor["files"])
            if observed.donor_files.get((name, str(item["path"]))) != item["sha256"]
        )
    return problems


def evaluate(baseline: Mapping[str, object], observed: Observed) -> list[str]:
    """Every failed prerequisite as ``STOP_CODE: detail``, sorted; empty means the base is accepted."""
    return sorted(
        _prerequisite_problems(baseline, observed)
        + _seam_problems(baseline, observed)
        + _donor_problems(baseline, observed)
    )


def _records(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _strings(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


# --- observation -----------------------------------------------------------------------


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _evidence_status(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        status = json.loads(text).get("status")
        return status if isinstance(status, str) else None
    match = _MARKDOWN_STATUS.search(text)
    return match.group(1) if match else None


def symbol_seam(repo: Path, qualified_name: str, path: str) -> ObservedSeam | None:
    """Locate ``module:Owner.member`` (or ``module:function``) in ``path`` and fingerprint its source."""
    source = (repo / path).read_text(encoding="utf-8")
    nodes: list[ast.AST] = list(ast.parse(source).body)
    node: ast.AST | None = None
    for part in qualified_name.split(":", 1)[1].split("."):
        node = next(
            (
                item
                for item in nodes
                if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == part
            ),
            None,
        )
        if node is None:
            return None
        nodes = list(getattr(node, "body", []))
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return None
    segment = ast.get_source_segment(source, node) or ""
    if isinstance(node, ast.ClassDef):
        signature = f"class {node.name}"
    else:
        returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
        signature = f"({ast.unparse(node.args)}){returns}"
    return ObservedSeam(path=path, signature=signature, sha256=_sha256(segment.encode("utf-8")))


def observe(repo: Path, baseline: Mapping[str, object], donors: Mapping[str, Path]) -> Observed:
    base = str(baseline["base_head"])
    ancestor = _git(repo, "merge-base", "--is-ancestor", base, "HEAD", check=False).returncode == 0
    committed = _git(repo, "diff", "--name-only", f"{base}..HEAD", check=False).stdout.split() if ancestor else []
    dirty = [
        line[3:]
        for line in _git(repo, "status", "--porcelain=v1", "--untracked-files=all").stdout.splitlines()
        if line.strip()
    ]
    heads, _digest = _alembic_revision_metadata_at_ref(repo, base) if ancestor else ((), "")
    tracked = [
        str(entry["path"]) for entry in _records(baseline["m7_evidence"]) + _records(baseline["design_artifacts"])
    ]
    file_hashes = {path: _sha256((repo / path).read_bytes()) for path in tracked if (repo / path).is_file()}
    evidence_status = {
        str(entry["path"]): _evidence_status(repo / str(entry["path"]))
        for entry in _records(baseline["m7_evidence"])
        if (repo / str(entry["path"])).is_file()
    }
    acceptance = repo / ACCEPTANCE_RELPATH
    accepted_head = (
        json.loads(acceptance.read_text(encoding="utf-8")).get("accepted_candidate_head")
        if acceptance.is_file()
        else None
    )
    seams = {}
    for entry in _records(baseline["seams"]):
        seam = (
            symbol_seam(repo, str(entry["qualified_name"]), str(entry["path"]))
            if (repo / str(entry["path"])).is_file()
            else None
        )
        if seam is not None:
            seams[str(entry["qualified_name"])] = seam
    donor_commits: dict[str, str | None] = {}
    donor_files: dict[tuple[str, str], str] = {}
    for donor in _records(baseline["donors"]):
        name, commit = str(donor["name"]), str(donor["commit"])
        clone = donors.get(name)
        present = (
            clone is not None and _git(clone, "cat-file", "-e", f"{commit}^{{commit}}", check=False).returncode == 0
        )
        donor_commits[name] = commit if present else None
        if not present or clone is None:
            continue
        for item in _records(donor["files"]):
            blob = subprocess.run(
                ["git", "show", f"{commit}:{item['path']}"], cwd=clone, capture_output=True, check=False
            )
            if blob.returncode == 0:
                donor_files[(name, str(item["path"]))] = _sha256(blob.stdout)
    return Observed(
        branch=_git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(),
        base_is_ancestor=ancestor,
        changed_paths=tuple(sorted(set(committed) | set(dirty))),
        alembic_heads=heads,
        file_hashes=file_hashes,
        evidence_status=evidence_status,
        accepted_candidate_head=accepted_head if isinstance(accepted_head, str) else None,
        seams=seams,
        donor_commits=donor_commits,
        donor_files=donor_files,
    )


def verify_m8_scope(repo: Path, baseline: Mapping[str, object], donors: Mapping[str, Path] | None = None) -> list[str]:
    """Every failed prerequisite, sorted; an empty list is the only pass."""
    problems = schema_problems(baseline)
    if problems:
        return problems
    return evaluate(baseline, observe(repo, baseline, donors or {}))


def _donor_arg(raw: str) -> tuple[str, Path]:
    name, sep, path = raw.partition("=")
    if not sep or not name or not path:
        raise argparse.ArgumentTypeError(f"expected NAME=PATH, got {raw!r}")
    return name, Path(path).expanduser()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("--repo", type=Path, default=Path())
    parser.add_argument("--donor", type=_donor_arg, action="append", default=[])
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    baseline = json.loads((repo / args.baseline).read_text(encoding="utf-8"))
    problems = verify_m8_scope(repo, baseline, dict(args.donor))
    for problem in problems:
        print(problem)
    if problems:
        return 2
    print("M8_BASELINE_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
