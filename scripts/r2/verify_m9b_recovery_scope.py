"""Read-only Git-bound additive release gate for M9-B manual recovery V2."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path

from scripts.r2.verify_m9_prerequisites import LOAD_ERRORS, GitPrerequisiteReader, loads_unique_json
from scripts.r2.verify_m9_scope import environment_problems

AMENDMENT = "3964da7a705ca9c555b7515c6cc7b73531224244"
AMENDMENT_PATH = "docs/r2/evidence/R2_M9_B_RECOVERY_V2_RELEASE.json"
BASELINE = "4c4861e9ae6fe74ca6828d676791ae203252e139"
ORIGINAL_RELEASE = "5b7a4be9f4b083f1d00db8005b49d7ba664658b8"
ORIGINAL_PATH = "docs/r2/evidence/R2_M9_B_PACKET_RELEASE.json"
ACCEPTED_A = "04b1b92184a5d5b0643256be533332de6ed8b009"
DRAFT = "70e459d68615120bda3f73dc1cd67e31b4054635"
ACCEPTANCE_PATH = "docs/r2/evidence/R2_M9_A_IMPLEMENTATION_ACCEPTANCE.json"
READINESS_PATH = "docs/r2/evidence/R2_M9_B_READINESS.json"
MIGRATION_PATH = "alembic/versions/9b9c4a0e0002_add_m9_manual_admission.py"


def _json(value: Mapping[str, object]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _paths(source: GitPrerequisiteReader, *args: str) -> set[str]:
    return set(source._run(*args).decode().splitlines())


def verify_m9b_recovery_scope(
    repo: Path,
    amendment: Mapping[str, object],
    *,
    environment_check: Callable[[], list[str]] | None = None,
) -> list[str]:
    """Validate both immutable release ceremonies before admitting owned changes."""
    missing = "M9_REQUIRED_EVIDENCE_MISSING: "
    seam = "POST_M8_BASE_SEAM_CHANGED: "
    try:
        source = GitPrerequisiteReader(repo)
        head = source.head()
        raw = source.blob(AMENDMENT, AMENDMENT_PATH)
        pinned = loads_unique_json(raw)
        original_raw = source.blob(ORIGINAL_RELEASE, ORIGINAL_PATH)
        original = loads_unique_json(original_raw)
        if _json(amendment) != _json(pinned) or (repo / AMENDMENT_PATH).read_bytes() != raw:
            return [missing + "amendment differs from the pinned Human-approved record"]
        if (
            source.parents(AMENDMENT) != [BASELINE]
            or source.changed_paths(AMENDMENT) != set(pinned["artifacts"]) | {AMENDMENT_PATH}
            or not source.is_ancestor(AMENDMENT, head)
            or not source.is_ancestor(ORIGINAL_RELEASE, BASELINE)
            or pinned["baseline"] != BASELINE
            or pinned["original_release"] != ORIGINAL_RELEASE
            or pinned["accepted_predecessor"] != ACCEPTED_A
        ):
            return [missing + "amendment lineage or four-artifact ceremony differs"]
        if (
            source.parents(ORIGINAL_RELEASE) != [DRAFT]
            or source.changed_paths(ORIGINAL_RELEASE) != {ORIGINAL_PATH}
            or source.parents(DRAFT) != [ACCEPTED_A]
            or original["accepted_predecessor"] != ACCEPTED_A
            or original["status"] != "M9_B_PACKET_RELEASED"
            or original["approval"]["plan_approved"] is not True
            or original["approval"]["fixture_approved"] is not True
            or pinned["status"] != "M9_B_RECOVERY_V2_RELEASED"
            or pinned["approval"]["spec_approved"] is not True
            or pinned["approval"]["plan_approved"] is not True
            or pinned["production_activation_authorized"] is not False
            or pinned["private_key_in_runtime"] is not False
        ):
            return [missing + "original or additive approval authority differs"]
        errors: list[str] = []
        branch = source._run("branch", "--show-current").decode().strip()
        if branch != pinned["implementation_branch"] or branch != original["implementation_branch"]:
            errors.append(missing + "worktree is not the released implementation branch")
        if source.dirty_paths():
            errors.append(missing + "worktree is dirty")
        frozen = {
            ORIGINAL_PATH: original_raw,
            **{p: source.blob(ORIGINAL_RELEASE, p) for p in original["artifacts"]},
            **{p: source.blob(AMENDMENT, p) for p in pinned["artifacts"]},
            **{p: source.blob(BASELINE, p) for p in pinned["frozen_baseline_paths"]},
        }
        for record, ref in ((original, ORIGINAL_RELEASE), (pinned, AMENDMENT)):
            for path, digest in record["artifacts"].items():
                if hashlib.sha256(source.blob(ref, path)).hexdigest() != digest:
                    errors.append(missing + f"released artifact hash differs: {path}")
        acceptance = loads_unique_json(source.blob(ACCEPTED_A, ACCEPTANCE_PATH))
        candidate = acceptance["accepted_candidate"]
        if (
            acceptance["status"] != "M9_A_ACCEPTED"
            or acceptance["independent_review"]["verdict"] != "PASS_M9_A_FOUNDATION"
            or source.parents(ACCEPTED_A) != [candidate]
            or source.parents(candidate) != [acceptance["tested_head"]]
            or source.changed_paths(ACCEPTED_A) != set(acceptance["ceremony"]["exact_changed_paths"])
        ):
            errors.append(missing + "accepted A lineage or independent verdict differs")
        old_allowed = set(original["owned_create_paths"]) | set(original["owned_modify_paths"])
        allowed = old_allowed | set(pinned["owned_create_paths"]) | set(pinned["owned_modify_paths"])
        old_changed = _paths(source, "diff", "--name-only", f"{ORIGINAL_RELEASE}..{BASELINE}")
        changed = _paths(source, "diff", "--name-only", f"{ORIGINAL_RELEASE}..{head}")
        if old_changed - old_allowed or changed - allowed:
            errors.append(seam + "committed changes exceed the original and additive owned paths")
        for record, ref in ((original, ACCEPTED_A), (pinned, BASELINE)):
            existing = _paths(source, "ls-tree", "-r", "--name-only", ref)
            creates, modifies = set(record["owned_create_paths"]), set(record["owned_modify_paths"])
            if existing & creates or modifies - existing or creates & modifies:
                errors.append(seam + "owned creation/modification preconditions differ")
        if _paths(source, "diff", "--name-only", "--diff-filter=D", f"{BASELINE}..{head}"):
            errors.append(seam + "the amendment does not authorize path deletion")
        readiness = loads_unique_json(source.blob(ORIGINAL_RELEASE, READINESS_PATH))
        for path, digest in readiness["files"].items():
            blob = source.blob(ORIGINAL_RELEASE, path)
            if hashlib.sha256(blob).hexdigest() != digest:
                errors.append(seam + f"released A native source differs: {path}")
            if path not in old_allowed:
                frozen[path] = blob
        for path, blob in frozen.items():
            if source.blob(head, path) != blob or (repo / path).read_bytes() != blob:
                errors.append(seam + f"frozen authority or source differs: {path}")
        heads, _ = source.migration_metadata(head)
        new_migration = MIGRATION_PATH in changed
        if heads != (("9b9c4a0e0002",) if new_migration else ("9b9c4a0e0001",)):
            errors.append("M9_SCHEMA_CHANGE_REQUIRED: migration head differs from the additive linear chain")
        if new_migration:
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
        errors.extend(missing + error for error in (environment_check or environment_problems)())
        if source.head() != head or source.dirty_paths():
            errors.append(missing + "worktree changed or remained dirty during verification")
        return errors
    except (*LOAD_ERRORS, SyntaxError, AttributeError):
        return [missing + "required Git-bound recovery release evidence is unavailable or malformed"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("amendment", type=Path)
    args = parser.parse_args()
    try:
        errors = verify_m9b_recovery_scope(Path.cwd(), loads_unique_json(args.amendment.read_bytes()))
    except LOAD_ERRORS:
        errors = ["M9_REQUIRED_EVIDENCE_MISSING: recovery amendment is unavailable or malformed"]
    for error in errors:
        print(error)
    if not errors:
        print("M9_B_RECOVERY_SCOPE_OK")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
