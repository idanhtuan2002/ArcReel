"""Machine-checkable M7 prerequisite and evidence-baseline verifier.

The verifier must fail closed before any implementation code is trusted
unless every precondition below holds: the M6 handoff this worktree is rooted
on is present and formally accepted, the worktree is clean at the
materialization base, that base is the exact recorded M6-accepted head, the
Alembic head is exactly the one M7 requires with no stray heads, the complete
ordered Alembic revision graph still hashes to what the baseline recorded, and
every materialized planning document and verified legacy seam still hashes to
what the baseline recorded.

    uv run python scripts/r2/verify_m7_scope.py --check
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from r2.host_hardening.route_inventory import submit_route_inventory_problems

if TYPE_CHECKING:
    from alembic.script import ScriptDirectory

M6_HANDOFF_RELPATH = "docs/r2/evidence/R2_M6_IMPLEMENTATION_HANDOFF.json"
BASELINE_RELPATH = "docs/r2/evidence/R2_M7_BASELINE.json"
MATERIALIZATION_ANCHOR_RELPATH = "docs/superpowers/plans/2026-09-12-r2-m7-host-production-hardening.md"

# Prerequisite-gate failures stop with M7_PREREQUISITE_NOT_ACCEPTED (umbrella plan
# Global Constraints: "if M6 is not accepted, the tree is dirty, its evidence does
# not bind the exact HEAD, the migration head differs, or the ADR/spec/research
# hashes differ"). A legacy-seam mismatch is a distinct stop code: the accepted
# base itself changed under an approved document, not the M6 handoff.
PREREQUISITE_CHECK_NAMES = frozenset(
    {"m6_accepted", "clean_tree", "base_sha", "alembic_head", "revision_graph_digest", "documents"}
)
SEAM_CHANGED_CHECK_NAMES = frozenset({"legacy_seams"})
SUBMIT_ROUTE_CHECK_NAMES = frozenset({"submit_routes"})


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


# --- pure checks (unit-tested directly, no filesystem/git/alembic access) -----------


def check_clean_tree(dirty_paths: Iterable[str]) -> CheckResult:
    dirty = sorted(p for p in dirty_paths if p)
    if dirty:
        return CheckResult("clean_tree", False, f"dirty paths: {dirty}")
    return CheckResult("clean_tree", True, "working tree clean")


def check_base_sha(*, actual_base: str, expected_base: str) -> CheckResult:
    if actual_base != expected_base:
        return CheckResult("base_sha", False, f"worktree base is {actual_base!r}, expected {expected_base!r}")
    return CheckResult("base_sha", True, f"base matches the recorded {expected_base!r}")


def check_m6_accepted(*, status: str | None) -> CheckResult:
    if status != "ACCEPTED":
        return CheckResult(
            "m6_accepted",
            False,
            f"{M6_HANDOFF_RELPATH} status is {status!r}, expected 'ACCEPTED' -- M6 has not been accepted",
        )
    return CheckResult("m6_accepted", True, f"{M6_HANDOFF_RELPATH} status is 'ACCEPTED'")


def check_alembic_head(*, actual_heads: tuple[str, ...], expected_head: str) -> CheckResult:
    if actual_heads != (expected_head,):
        return CheckResult(
            "alembic_head",
            False,
            f"Alembic heads are {list(actual_heads)}, expected exactly [{expected_head!r}]",
        )
    return CheckResult("alembic_head", True, f"single Alembic head {expected_head!r}")


def check_revision_graph_digest(*, actual_digest: str, expected_digest: str) -> CheckResult:
    if actual_digest != expected_digest:
        return CheckResult(
            "revision_graph_digest",
            False,
            f"Alembic revision graph digest is {actual_digest!r}, expected {expected_digest!r} -- "
            "a revision edge was added, removed or altered since the baseline",
        )
    return CheckResult("revision_graph_digest", True, "revision graph digest matches the baseline")


def check_file_hashes(*, recorded: Mapping[str, str], actual: Mapping[str, str], label: str) -> CheckResult:
    missing = sorted(path for path in recorded if path not in actual)
    mismatched = sorted(path for path, digest in recorded.items() if path in actual and actual[path] != digest)
    problems = missing + mismatched
    if problems:
        return CheckResult(label, False, f"missing or mismatched {label}: {problems}")
    return CheckResult(label, True, f"{len(recorded)} {label} match the baseline")


def check_submit_route_inventory() -> CheckResult:
    problems = submit_route_inventory_problems()
    if problems:
        return CheckResult("submit_routes", False, "; ".join(problems))
    return CheckResult("submit_routes", True, "all paid asynchronous submit families are bound")


# --- real-world wiring ---------------------------------------------------------------


def _run(cmd: list[str], *, cwd: Path) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _git_dirty_paths(repo: Path) -> list[str]:
    out = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line[3:] for line in out.splitlines() if line.strip()]


def _materialization_commit(repo: Path) -> str:
    # The materialization commit adds the umbrella plan alongside every other
    # planning document; its parent is the exact M6-accepted head this worktree
    # is rooted on (mirrors verify_m6_scope.py's own doc_commit^ pattern).
    out = _run(["git", "log", "--format=%H", "--diff-filter=A", "--", MATERIALIZATION_ANCHOR_RELPATH], cwd=repo)
    lines = out.splitlines()
    if not lines:
        return ""
    return lines[-1]


def _worktree_base(repo: Path) -> str:
    materialization_commit = _materialization_commit(repo)
    return "" if not materialization_commit else _run(["git", "rev-parse", f"{materialization_commit}^"], cwd=repo)


def _m6_handoff_status(repo: Path, accepted_base: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{accepted_base}:{M6_HANDOFF_RELPATH}"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        return None
    data = json.loads(result.stdout)
    status = data.get("status")
    return status if isinstance(status, str) else None


def alembic_revision_graph_digest(script_dir: ScriptDirectory) -> str:
    """Hash of every ordered (revision, down_revision) pair in the complete graph."""
    pairs: list[dict[str, object]] = []
    for rev in script_dir.walk_revisions():
        down = rev.down_revision
        down_norm: object = down if down is None or isinstance(down, str) else sorted(down)
        pairs.append({"revision": rev.revision, "down_revision": down_norm})
    return _revision_pairs_digest(pairs)


def _revision_pairs_digest(pairs: list[dict[str, object]]) -> str:
    pairs.sort(key=lambda p: str(p["revision"]))
    canonical = json.dumps(pairs, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _git_blob(repo: Path, ref: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout


def _git_blob_hashes(repo: Path, ref: str, paths: Iterable[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in paths:
        try:
            hashes[path] = hashlib.sha256(_git_blob(repo, ref, path)).hexdigest()
        except subprocess.CalledProcessError:
            continue
    return hashes


def _literal_assignment(source: bytes, name: str) -> object:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return ast.literal_eval(node.value)
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise ValueError(f"missing {name!r} assignment")


def _alembic_revision_metadata_at_ref(repo: Path, ref: str) -> tuple[tuple[str, ...], str]:
    listed = _run(["git", "ls-tree", "-r", "--name-only", ref, "--", "alembic/versions"], cwd=repo)
    pairs: list[dict[str, object]] = []
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in listed.splitlines():
        if not path.endswith(".py") or path.endswith("/__init__.py"):
            continue
        source = _git_blob(repo, ref, path)
        revision = str(_literal_assignment(source, "revision"))
        raw_down = _literal_assignment(source, "down_revision")
        down_revisions = () if raw_down is None else (raw_down,) if isinstance(raw_down, str) else tuple(raw_down)
        down_norm: object = (
            None if not down_revisions else down_revisions[0] if len(down_revisions) == 1 else sorted(down_revisions)
        )
        pairs.append({"revision": revision, "down_revision": down_norm})
        revisions.add(revision)
        parents.update(str(parent) for parent in down_revisions)
    return tuple(sorted(revisions - parents)), _revision_pairs_digest(pairs)


def run_all_checks(*, repo: Path, baseline: Mapping[str, object]) -> list[CheckResult]:
    dirty = _git_dirty_paths(repo)
    materialization_commit = _materialization_commit(repo)
    actual_base = _worktree_base(repo)
    expected_base = str(baseline["m6_accepted_head"])

    m6_status = _m6_handoff_status(repo, expected_base)

    documents = dict(baseline["documents"])
    legacy_seams = dict(baseline["legacy_seams"])
    if actual_base:
        actual_heads, actual_digest = _alembic_revision_metadata_at_ref(repo, actual_base)
        actual_documents = _git_blob_hashes(repo, materialization_commit, documents)
        actual_seams = _git_blob_hashes(repo, actual_base, legacy_seams)
    else:
        actual_heads, actual_digest = (), ""
        actual_documents = {}
        actual_seams = {}

    return [
        check_m6_accepted(status=m6_status),
        check_clean_tree(dirty),
        check_base_sha(actual_base=actual_base, expected_base=expected_base),
        check_alembic_head(actual_heads=actual_heads, expected_head=str(baseline["alembic_required_head"])),
        check_revision_graph_digest(actual_digest=actual_digest, expected_digest=str(baseline["alembic_graph_digest"])),
        check_file_hashes(recorded=documents, actual=actual_documents, label="documents"),
        check_file_hashes(recorded=legacy_seams, actual=actual_seams, label="legacy_seams"),
        check_submit_route_inventory(),
    ]


def verify_m7_scope(repo: Path, baseline: Mapping[str, object]) -> list[str]:
    """Return every failing-check detail; an empty list means every check passed."""
    return [result.detail for result in run_all_checks(repo=repo, baseline=baseline) if not result.ok]


def _load_baseline(repo: Path) -> dict[str, object]:
    return json.loads((repo / BASELINE_RELPATH).read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--check", action="store_true", help="run the verifier and print PASS/FAIL per check")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    baseline = _load_baseline(repo)
    results = run_all_checks(repo=repo, baseline=baseline)

    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {result.name}: {result.detail}")

    failed_names = {r.name for r in results if not r.ok}
    if failed_names & PREREQUISITE_CHECK_NAMES:
        print("M7_PREREQUISITE_NOT_ACCEPTED", file=sys.stderr)
        return 2
    if failed_names & SEAM_CHANGED_CHECK_NAMES:
        print("M7_BASE_SEAM_CHANGED", file=sys.stderr)
        return 2
    if failed_names & SUBMIT_ROUTE_CHECK_NAMES:
        print("M7_SUBMIT_ROUTE_UNBOUND", file=sys.stderr)
        return 2
    return 1 if failed_names else 0


if __name__ == "__main__":
    raise SystemExit(main())
