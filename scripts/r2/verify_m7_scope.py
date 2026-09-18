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
import hashlib
import json
import subprocess
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alembic.script import ScriptDirectory

M6_WORKTREE_DIRNAME = "content-production-os-m6"
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


# --- real-world wiring ---------------------------------------------------------------


def _run(cmd: list[str], *, cwd: Path) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _git_dirty_paths(repo: Path) -> list[str]:
    out = _run(["git", "status", "--porcelain"], cwd=repo)
    return [line[3:] for line in out.splitlines() if line.strip()]


def _worktree_base(repo: Path) -> str:
    # The materialization commit adds the umbrella plan alongside every other
    # planning document; its parent is the exact M6-accepted head this worktree
    # is rooted on (mirrors verify_m6_scope.py's own doc_commit^ pattern).
    out = _run(["git", "log", "--format=%H", "--diff-filter=A", "--", MATERIALIZATION_ANCHOR_RELPATH], cwd=repo)
    lines = out.splitlines()
    if not lines:
        return ""
    materialization_commit = lines[-1]
    return _run(["git", "rev-parse", f"{materialization_commit}^"], cwd=repo)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _m6_handoff_status(repo: Path) -> str | None:
    handoff = repo.parent / M6_WORKTREE_DIRNAME / M6_HANDOFF_RELPATH
    if not handoff.is_file():
        return None
    data = json.loads(handoff.read_text())
    status = data.get("status")
    return status if isinstance(status, str) else None


def _alembic_script_directory(repo: Path) -> ScriptDirectory:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config()
    cfg.set_main_option("script_location", str(repo / "alembic"))
    return ScriptDirectory.from_config(cfg)


def alembic_revision_graph_digest(script_dir: ScriptDirectory) -> str:
    """Hash of every ordered (revision, down_revision) pair in the complete graph."""
    pairs: list[dict[str, object]] = []
    for rev in script_dir.walk_revisions():
        down = rev.down_revision
        down_norm: object = down if down is None or isinstance(down, str) else sorted(down)
        pairs.append({"revision": rev.revision, "down_revision": down_norm})
    pairs.sort(key=lambda p: str(p["revision"]))
    canonical = json.dumps(pairs, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_all_checks(*, repo: Path, baseline: Mapping[str, object]) -> list[CheckResult]:
    dirty = _git_dirty_paths(repo)
    actual_base = _worktree_base(repo)
    expected_base = str(baseline["m6_accepted_head"])

    m6_status = _m6_handoff_status(repo)

    script_dir = _alembic_script_directory(repo)
    actual_heads = tuple(sorted(script_dir.get_heads()))
    actual_digest = alembic_revision_graph_digest(script_dir)

    documents = dict(baseline["documents"])
    legacy_seams = dict(baseline["legacy_seams"])
    actual_documents = {path: _sha256(repo / path) for path in documents if (repo / path).is_file()}
    actual_seams = {path: _sha256(repo / path) for path in legacy_seams if (repo / path).is_file()}

    return [
        check_m6_accepted(status=m6_status),
        check_clean_tree(dirty),
        check_base_sha(actual_base=actual_base, expected_base=expected_base),
        check_alembic_head(actual_heads=actual_heads, expected_head=str(baseline["alembic_required_head"])),
        check_revision_graph_digest(actual_digest=actual_digest, expected_digest=str(baseline["alembic_graph_digest"])),
        check_file_hashes(recorded=documents, actual=actual_documents, label="documents"),
        check_file_hashes(recorded=legacy_seams, actual=actual_seams, label="legacy_seams"),
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
    return 1 if failed_names else 0


if __name__ == "__main__":
    raise SystemExit(main())
