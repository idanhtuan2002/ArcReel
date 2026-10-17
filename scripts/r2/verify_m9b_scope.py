"""Read-only Git-bound release and disposable-target gate for M9-B."""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Mapping
from pathlib import Path

from scripts.r2.verify_m9_prerequisites import LOAD_ERRORS, GitPrerequisiteReader, loads_unique_json
from scripts.r2.verify_m9_scope import environment_problems

RELEASE_COMMIT = "5b7a4be9f4b083f1d00db8005b49d7ba664658b8"
RELEASE_PATH = "docs/r2/evidence/R2_M9_B_PACKET_RELEASE.json"
ACCEPTED_A = "04b1b92184a5d5b0643256be533332de6ed8b009"
DRAFT = "70e459d68615120bda3f73dc1cd67e31b4054635"
ACCEPTANCE_PATH = "docs/r2/evidence/R2_M9_A_IMPLEMENTATION_ACCEPTANCE.json"
READINESS_PATH = "docs/r2/evidence/R2_M9_B_READINESS.json"
MIGRATION_PATH = "alembic/versions/9b9c4a0e0001_add_m9_acquisition_observations.py"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def verify_m9b_scope(repo: Path, release: Mapping[str, object]) -> list[str]:
    """Recompute immutable release authority before allowing owned B work."""
    missing = "M9_REQUIRED_EVIDENCE_MISSING: "
    seam = "POST_M8_BASE_SEAM_CHANGED: "
    try:
        source = GitPrerequisiteReader(repo)
        head = source.head()
        raw = source.blob(RELEASE_COMMIT, RELEASE_PATH)
        pinned = loads_unique_json(raw)
        if dict(release) != pinned or (repo / RELEASE_PATH).read_bytes() != raw:
            return [missing + "release differs from the pinned Human-approved record"]
        if source.parents(RELEASE_COMMIT) != [DRAFT] or source.changed_paths(RELEASE_COMMIT) != {RELEASE_PATH}:
            return [missing + "release parent or changed-path ceremony differs"]
        if source.parents(DRAFT) != [ACCEPTED_A]:
            return [missing + "draft does not descend directly from accepted A"]
        if not source.is_ancestor(RELEASE_COMMIT, head):
            return [missing + "HEAD does not descend from the exact released packet"]
        errors: list[str] = []
        if source._run("branch", "--show-current").decode().strip() != pinned["implementation_branch"]:
            errors.append(missing + "worktree is not the released implementation branch")
        if source.dirty_paths():
            errors.append(missing + "worktree is dirty")
        artifacts = pinned["artifacts"]
        for path, digest in artifacts.items():
            blob = source.blob(RELEASE_COMMIT, path)
            if _sha(blob) != digest or (repo / path).read_bytes() != blob:
                errors.append(missing + f"frozen authority artifact differs: {path}")
        acceptance = loads_unique_json(source.blob(ACCEPTED_A, ACCEPTANCE_PATH))
        candidate = acceptance["accepted_candidate"]
        if (
            pinned["accepted_predecessor"] != ACCEPTED_A
            or acceptance["status"] != "M9_A_ACCEPTED"
            or acceptance["independent_review"]["verdict"] != "PASS_M9_A_FOUNDATION"
            or source.parents(ACCEPTED_A) != [candidate]
            or source.parents(candidate) != [acceptance["tested_head"]]
            or source.changed_paths(ACCEPTED_A) != set(acceptance["ceremony"]["exact_changed_paths"])
            or source.blob(head, ACCEPTANCE_PATH) != source.blob(ACCEPTED_A, ACCEPTANCE_PATH)
        ):
            errors.append(missing + "accepted A lineage or independent verdict differs")
        approval = pinned["approval"]
        if pinned["status"] != "M9_B_PACKET_RELEASED" or not (
            approval["plan_approved"] is True and approval["fixture_approved"] is True
        ):
            errors.append(missing + "Human plan/fixture approval is absent")
        creates, modifies = pinned["owned_create_paths"], pinned["owned_modify_paths"]
        allowed = set(creates) | set(modifies)
        changed = set(source._run("diff", "--name-only", f"{RELEASE_COMMIT}..{head}").decode().splitlines())
        if changed - allowed:
            errors.append(seam + "committed changes exceed released owned paths")
        existing = set(source._run("ls-tree", "-r", "--name-only", ACCEPTED_A).decode().splitlines())
        if existing & set(creates) or set(modifies) - existing:
            errors.append(seam + "owned path creation/modification preconditions differ")
        readiness = loads_unique_json(source.blob(RELEASE_COMMIT, READINESS_PATH))
        for path, digest in readiness["files"].items():
            if _sha(source.blob(RELEASE_COMMIT, path)) != digest:
                errors.append(seam + f"released A native source differs: {path}")
            if path not in allowed and (repo / path).read_bytes() != source.blob(RELEASE_COMMIT, path):
                errors.append(seam + f"frozen A source differs: {path}")
        heads, _ = source.migration_metadata(head)
        permitted = ("9b9c4a0e0001",) if MIGRATION_PATH in changed else ("9a9c4a0e0001",)
        if heads != permitted:
            errors.append("M9_SCHEMA_CHANGE_REQUIRED: migration head differs from the released linear chain")
        if MIGRATION_PATH in changed:
            # Parse metadata without importing or executing migration source.
            import ast

            tree = ast.parse(source.blob(head, MIGRATION_PATH))
            values = {
                target.id: ast.literal_eval(node.value)
                for node in tree.body
                if isinstance(node, ast.Assign)
                for target in node.targets
                if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}
            }
            if values != pinned["migration"]:
                errors.append("M9_SCHEMA_CHANGE_REQUIRED: migration predecessor or revision differs")
        errors.extend(missing + error for error in environment_problems())
        if source.head() != head or source.dirty_paths():
            errors.append(missing + "worktree changed or remained dirty during verification")
        return errors
    except (*LOAD_ERRORS, SyntaxError, AttributeError):
        return [missing + "required Git-bound release evidence is unavailable or malformed"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    args = parser.parse_args()
    try:
        errors = verify_m9b_scope(Path.cwd(), loads_unique_json(args.release.read_bytes()))
    except LOAD_ERRORS:
        errors = ["M9_REQUIRED_EVIDENCE_MISSING: release is unavailable or malformed"]
    for error in errors:
        print(error)
    if not errors:
        print("M9_B_SCOPE_OK")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
