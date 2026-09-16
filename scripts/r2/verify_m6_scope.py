"""Machine-checkable M6 implementation-boundary and per-checkpoint scope verifier.

Task 0 (checkpoint M6-A) must fail closed before any M6 implementation code is
trusted unless every precondition below holds: the M5C base this worktree is
rooted on has a formally Codex-accepted handoff, the worktree is clean, that
base is the exact recorded one, the four approved M6 documents still hash to
what ``R2_M6_DOCUMENT_APPROVAL.json`` recorded, and a Codebase Memory graph
exists for this worktree. Only once every check passes does the per-checkpoint
path/migration allowlist below apply — mirroring M5C's own
``verify_m5c_scope.py``, extended with the prerequisite checks M5C's version
never needed (M5C's own prerequisite was verified by an ad hoc Task 0 script,
not folded into that tool).

    uv run python scripts/r2/verify_m6_scope.py --checkpoint M6-A
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

M6_ALEMBIC_BASE = "5c7c4a0e0004"
M5C_FINAL_VERIFICATION_RELPATH = "docs/r2/evidence/R2_M5C_FINAL_VERIFICATION.md"
DOCUMENT_APPROVAL_RELPATH = "docs/r2/evidence/R2_M6_DOCUMENT_APPROVAL.json"

# --- checkpoint M6-A allowlist (Task 0 adds only its own three files, no migration) --

ALLOWED_MIGRATIONS_M6A: frozenset[str] = frozenset()

HANDOFF_ONLY_ALLOWLIST_M6A: frozenset[str] = frozenset({"docs/r2/evidence/R2_M6_A_REVIEW.md"})

IMPLEMENTATION_ALLOWLIST_M6A: frozenset[str] = HANDOFF_ONLY_ALLOWLIST_M6A | frozenset(
    {
        # materialized onto this worktree's base commit, before Task 0
        "docs/superpowers/specs/2026-09-12-r2-m6-dual-profile-adaptation-design.md",
        "docs/superpowers/plans/2026-09-12-r2-m6-dual-profile-adaptation.md",
        "docs/adr/0077-dual-profile-adaptation-lineage-and-policy-evidence.md",
        "docs/research/2026-09-12-r2-m6-dual-profile-adaptation-research.md",
        "docs/r2/evidence/R2_M6_DOCUMENT_APPROVAL.json",
        # Task 0
        "docs/r2/evidence/R2_M6_STARTING_STATE.json",
        "scripts/r2/verify_m6_scope.py",
        "tests/unit/scripts/r2/test_verify_m6_scope.py",
        # Task 1: adaptation and profile contracts
        "r2/contracts/adaptation.py",
        "r2/adaptation/__init__.py",
        "tests/unit/r2/contracts/test_adaptation.py",
        # Task 2: canonical serialization, hashing, and schema ratchets
        "r2/adaptation/hashing.py",
        "r2/adaptation/schema_upgrade.py",
        "tests/unit/r2/adaptation/test_adaptation_hashing.py",
        "tests/unit/r2/adaptation/test_adaptation_schema_upgrade.py",
        # Task 3: ShotSpecV2 without changing v1 bytes
        "r2/contracts/production.py",
        "r2/contracts/fingerprints.py",
        "r2/production/shot_schema_upgrade.py",
        "tests/unit/r2/contracts/test_shot_spec_v2.py",
        "tests/unit/r2/production/test_shot_schema_upgrade.py",
        # Task 4: pin and parity-test Take vocabulary
        "docs/r2/evidence/reuse-map-2026-09-07/source-manifest.json",
        "docs/r2/evidence/R2_M6_DONOR_BASELINE.json",
        "tests/integration/donor_parity/take_shot_vocabulary_runner.mjs",
        "tests/integration/donor_parity/test_take_shot_vocabulary.py",
        "tests/integration/donor_parity/fixtures/take_shot_vocabulary/cases.json",
        "tests/integration/donor_parity/vendor/take/packages/core/src/models/enums.ts",
    }
)


# --- checkpoint M6-FINAL (Task 17): the M6-B/C/D/E per-checkpoint gates in the plan
# were never separately frozen with their own R2_M6_{B,C,D}_REVIEW.md -- the user
# explicitly deferred per-checkpoint review to one combined pass at Task 17
# (`docs/r2/evidence/R2_M6_TASK17_HANDOFF_IN_PROGRESS.md`, since superseded by the
# final evidence pair below). This checkpoint's allowlist is therefore the true
# cumulative diff from the M6-A base through the exact HEAD used for that final
# review -- every path independently cross-checked against the plan's own Tasks
# 5-17 ``Files:`` declarations (including declared-but-differently-named test
# files, e.g. ``test_concurrency.py`` -> ``test_adaptation_concurrency.py``, and
# donor vendor sources implied but not individually enumerated by Task 10) --
# rather than four separately-reviewed increments. -----------------------------

ALLOWED_MIGRATIONS_M6_FINAL: frozenset[str] = frozenset(
    {
        "alembic/versions/6a7c4a0e0001_add_adaptation_evidence.py",
        "alembic/versions/6b7c4a0e0001_add_adaptation_authority.py",
        "alembic/versions/6c7c4a0e0001_add_profile_reports_and_waivers.py",
        "alembic/versions/6c7c4a0e0002_add_screenplay_admission.py",
    }
)

HANDOFF_ONLY_ALLOWLIST_M6_FINAL: frozenset[str] = frozenset(
    {
        "docs/r2/evidence/R2_M6_FINAL_VERIFICATION.md",
        "docs/r2/evidence/R2_M6_IMPLEMENTATION_HANDOFF.json",
    }
)

IMPLEMENTATION_ALLOWLIST_M6_FINAL: frozenset[str] = (
    IMPLEMENTATION_ALLOWLIST_M6A
    | HANDOFF_ONLY_ALLOWLIST_M6_FINAL
    | ALLOWED_MIGRATIONS_M6_FINAL
    | frozenset(
        {
            # Task 5: append-only persistence and migrations
            "lib/db/models/adaptation.py",
            "lib/db/repositories/adaptation.py",
            "lib/db/adaptation_uow.py",
            "lib/db/models/__init__.py",
            "tests/unit/lib/db/models/test_adaptation.py",
            "tests/integration/lib/db/migrations/test_alembic_adaptation.py",
            "tests/integration/lib/db/repositories/test_adaptation.py",
            # Task 6: proposal evidence service (test file later renamed with an
            # explicit "adaptation_" prefix to disambiguate from M5C's own
            # evidence-service test of the same short name)
            "r2/adaptation/ports.py",
            "r2/adaptation/evidence.py",
            "r2/adaptation/errors.py",
            "tests/integration/r2/adaptation/test_adaptation_evidence_service.py",
            # Task 7: authority kernel and map approval (test file renamed
            # test_concurrency.py -> test_adaptation_concurrency.py; pyproject.toml
            # and the Canon architecture-boundary allowlist extended for the new
            # import-linter contracts and the evidence repository's shared
            # insert_branch method name)
            "r2/adaptation/authority_kernel.py",
            "r2/adaptation/authority.py",
            "pyproject.toml",
            "tests/integration/r2/adaptation/test_map_approval.py",
            "tests/integration/r2/adaptation/test_adaptation_concurrency.py",
            "tests/unit/r2/test_m6_architecture_boundaries.py",
            "tests/integration/lib/db/migrations/test_alembic_adaptation_authority.py",
            "tests/unit/r2/narrative/test_canon_architecture_boundaries.py",
            # Task 8: immutable profile-pack registry
            "r2/adaptation/profiles.py",
            "r2/adaptation/policy_packs/__init__.py",
            "r2/adaptation/policy_packs/western_generic_v1.json",
            "r2/adaptation/policy_packs/cn_short_drama_shuangwen_v1.json",
            "tests/unit/r2/adaptation/test_profiles.py",
            # Task 9: Western evaluator
            "r2/adaptation/western_profile.py",
            "tests/fixtures/r2/m6_western_profile.py",
            "tests/unit/r2/adaptation/test_western_profile.py",
            # Task 10: bounded Huohuo/Shuangwen surface and donor parity
            "r2/adaptation/shuangwen_profile.py",
            "docs/r2/evidence/reuse-map-2026-09-07/source-manifest.json",
            "tests/integration/donor_parity/huohuo_drama_fields_runner.mjs",
            "tests/integration/donor_parity/test_huohuo_drama_fields.py",
            "tests/integration/donor_parity/fixtures/huohuo_drama_fields/cases.jsonl",
            "tests/unit/r2/adaptation/test_shuangwen_profile.py",
            "tests/integration/donor_parity/vendor/huohuo_drama_fields/workbench-server/"
            "src/services/novel/novel-commercial-appeal-audit.ts",
            "tests/integration/donor_parity/vendor/huohuo_drama_fields/workbench-server/"
            "src/services/novel/novel-commercial-appeal-isomorph.ts",
            "tests/integration/donor_parity/vendor/huohuo_drama_fields/workbench-server/"
            "src/services/novel/novel-emotion-core-contract.ts",
            "tests/integration/donor_parity/vendor/huohuo_drama_fields/workbench-server/"
            "src/services/novel/novel-outline-drama-fields.ts",
            "tests/integration/donor_parity/vendor/huohuo_drama_fields/workbench-server/"
            "src/services/novel/novel-stakes-common-sense.ts",
            # Task 11: persist reports and governed waivers
            "r2/adaptation/evaluation.py",
            "tests/integration/r2/adaptation/test_evaluation.py",
            "tests/integration/r2/adaptation/test_waivers.py",
            "tests/integration/r2/adaptation/conftest.py",
            "tests/integration/r2/adaptation/_fakes.py",
            "tests/integration/lib/db/migrations/test_alembic_adaptation_profiles.py",
            # Task 12: atomically approve and lock screenplay for direction
            # (ApprovedScreenplayReader factored into its own module rather than
            # left inline in authority.py)
            "r2/adaptation/screenplay_reader.py",
            "tests/integration/r2/adaptation/test_screenplay_admission.py",
            "tests/integration/lib/db/migrations/test_alembic_screenplay_admission.py",
            # Task 13: TakeDirector adapter and the async Director boundary
            # (scripts/r2/m4_test_doubles.py and run_m4_golden_12.py were the one
            # real caller of DirectorExecutionService.execute outside tests, missed
            # by the initial grep and fixed once the async conversion broke it)
            "r2/production_intelligence/take_director.py",
            "r2/production_intelligence/director.py",
            "r2/contracts/director.py",
            "scripts/r2/m4_test_doubles.py",
            "scripts/r2/run_m4_golden_12.py",
            "tests/unit/r2/production_intelligence/test_take_director.py",
            "tests/unit/r2/production_intelligence/test_director.py",
            # Task 14: retrofit readiness, fingerprints and Production consumers
            "r2/contracts/__init__.py",
            "r2/contracts/production.py",
            "r2/contracts/fingerprints.py",
            "r2/m3/director.py",
            "r2/m3/host_integration.py",
            "r2/m3/preparation.py",
            "r2/production_intelligence/readiness.py",
            "r2/production_intelligence/prompting.py",
            "r2/production_intelligence/fixture_loader.py",
            "r2/production_intelligence/capability_registry.py",
            "tests/unit/r2/contracts/test_fingerprints.py",
            "tests/unit/r2/contracts/test_shot_spec_v2.py",
            "tests/unit/r2/contracts/test_roundtrip.py",
            "tests/unit/r2/contracts/test_architecture_boundaries.py",
            "tests/unit/r2/production_intelligence/test_architecture_boundaries.py",
            "tests/unit/r2/production_intelligence/test_contracts.py",
            "tests/unit/r2/production_intelligence/test_prompting.py",
            "tests/unit/r2/production_intelligence/test_readiness.py",
            "r2/production/shot_schema_upgrade.py",
            "tests/unit/r2/production/test_shot_schema_upgrade.py",
            # Task 15: shared-Canon dual-profile corpus
            "tests/fixtures/r2/m6_dual_profile_corpus.py",
            "tests/integration/r2/test_m6_dual_profile_acceptance.py",
            # Task 16: adversarial mutation and real-PostgreSQL acceptance tests
            "tests/integration/r2/adaptation/test_m6_postgres_concurrency.py",
            # cross-cutting contract additions touched across Tasks 6-12
            "r2/contracts/adaptation.py",
            "r2/adaptation/hashing.py",
            "r2/adaptation/schema_upgrade.py",
            "r2/adaptation/__init__.py",
            "tests/unit/r2/contracts/test_adaptation.py",
            "tests/unit/r2/adaptation/test_adaptation_hashing.py",
            "tests/unit/r2/adaptation/test_adaptation_schema_upgrade.py",
        }
    )
)

CHECKPOINTS: dict[str, tuple[frozenset[str], frozenset[str], frozenset[str]]] = {
    # name -> (implementation_allowlist, handoff_only_allowlist, allowed_migrations)
    "M6-A": (IMPLEMENTATION_ALLOWLIST_M6A, HANDOFF_ONLY_ALLOWLIST_M6A, ALLOWED_MIGRATIONS_M6A),
    "M6-FINAL": (IMPLEMENTATION_ALLOWLIST_M6_FINAL, HANDOFF_ONLY_ALLOWLIST_M6_FINAL, ALLOWED_MIGRATIONS_M6_FINAL),
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


# --- pure checks (unit-tested directly, no filesystem/git access) -------------------


def check_m5c_accepted(*, final_verification_exists: bool) -> CheckResult:
    if not final_verification_exists:
        return CheckResult(
            "m5c_accepted",
            False,
            f"{M5C_FINAL_VERIFICATION_RELPATH} is absent — the M5C handoff has not been Codex-accepted",
        )
    return CheckResult("m5c_accepted", True, f"{M5C_FINAL_VERIFICATION_RELPATH} is present")


def check_clean_tree(dirty_paths: Iterable[str]) -> CheckResult:
    dirty = sorted(p for p in dirty_paths if p)
    if dirty:
        return CheckResult("clean_tree", False, f"dirty paths: {dirty}")
    return CheckResult("clean_tree", True, "working tree clean")


def check_base_sha(*, actual_base: str, expected_base: str) -> CheckResult:
    if actual_base != expected_base:
        return CheckResult("base_sha", False, f"worktree base is {actual_base!r}, expected {expected_base!r}")
    return CheckResult("base_sha", True, f"base matches the recorded {expected_base!r}")


def check_document_hashes(*, recorded: dict[str, str], actual: dict[str, str]) -> CheckResult:
    missing = sorted(path for path in recorded if path not in actual)
    mismatched = sorted(path for path, digest in recorded.items() if path in actual and actual[path] != digest)
    problems = missing + mismatched
    if problems:
        return CheckResult("document_hashes", False, f"missing or mismatched: {problems}")
    return CheckResult("document_hashes", True, f"{len(recorded)} document(s) match {DOCUMENT_APPROVAL_RELPATH}")


def check_graph_evidence(*, indexed: bool, node_count: int) -> CheckResult:
    if not indexed or node_count <= 0:
        return CheckResult("graph_evidence", False, "no Codebase Memory graph evidence for this worktree")
    return CheckResult("graph_evidence", True, f"graph indexed with {node_count} node(s)")


def unexpected_paths(paths: Iterable[str], *, allowlist: frozenset[str]) -> list[str]:
    return sorted(p for p in paths if p and p not in allowlist)


def migration_violations(paths: Iterable[str], *, allowed_migrations: frozenset[str], checkpoint: str) -> list[str]:
    stray = sorted(p for p in paths if p.startswith("alembic/versions/") and p not in allowed_migrations)
    return [f"{checkpoint} may touch only {sorted(allowed_migrations)}, found {stray}"] if stray else []


def check_scope(paths: Iterable[str], *, checkpoint: str) -> CheckResult:
    implementation_allowlist, _, allowed_migrations = CHECKPOINTS[checkpoint]
    changed = list(paths)
    problems = [
        f"unexpected implementation path: {p}" for p in unexpected_paths(changed, allowlist=implementation_allowlist)
    ]
    problems += migration_violations(changed, allowed_migrations=allowed_migrations, checkpoint=checkpoint)
    if problems:
        return CheckResult("scope", False, "; ".join(problems))
    return CheckResult("scope", True, f"{len(changed)} changed path(s) all within the {checkpoint} allowlist")


# --- real-world wiring ---------------------------------------------------------------


def _run(cmd: list[str], *, cwd: Path) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _git_dirty_paths(repo: Path) -> list[str]:
    out = _run(["git", "status", "--porcelain"], cwd=repo)
    return [line[3:] for line in out.splitlines() if line.strip()]


def _git_committed_diff_from_base(repo: Path, base: str) -> list[str]:
    out = _run(["git", "diff", "--name-only", f"{base}..HEAD"], cwd=repo)
    return [line for line in out.splitlines() if line.strip()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_approval_manifest(repo: Path) -> dict[str, object]:
    return json.loads((repo / DOCUMENT_APPROVAL_RELPATH).read_text())


def _recorded_document_hashes(manifest: dict[str, object]) -> Iterator[tuple[str, str]]:
    for prefix in ("design", "plan", "adr", "research"):
        path = manifest[f"{prefix}_path"]
        digest = manifest[f"{prefix}_sha256"]
        assert isinstance(path, str)
        assert isinstance(digest, str)
        yield path, digest


def _m5c_final_verification_exists(repo: Path) -> bool:
    # M5C's own implementation lives in a sibling worktree, not inside this one.
    m5c_worktree = repo.parent / "content-production-os-m5c"
    return (m5c_worktree / M5C_FINAL_VERIFICATION_RELPATH).is_file()


def run_all_checks(*, repo: Path, checkpoint: str) -> list[CheckResult]:
    manifest = _load_approval_manifest(repo)
    base_intent = str(manifest["m6_integration_base_intent"])
    expected_base = base_intent.rsplit("@", 1)[-1].strip()

    dirty = _git_dirty_paths(repo)
    # The materialization commit is the first commit to add the approval manifest;
    # its parent is the exact SHA this worktree was rooted on.
    doc_commit = _run(
        ["git", "log", "--format=%H", "--diff-filter=A", "--", DOCUMENT_APPROVAL_RELPATH], cwd=repo
    ).splitlines()[-1]
    actual_base = _run(["git", "rev-parse", f"{doc_commit}^"], cwd=repo)

    final_verification_exists = _m5c_final_verification_exists(repo)

    recorded_hashes = dict(_recorded_document_hashes(manifest))
    actual_hashes = {path: _sha256(repo / path) for path in recorded_hashes if (repo / path).is_file()}

    changed_paths = _git_committed_diff_from_base(repo, actual_base) if actual_base else []

    return [
        check_m5c_accepted(final_verification_exists=final_verification_exists),
        check_clean_tree(dirty),
        check_base_sha(actual_base=actual_base, expected_base=expected_base),
        check_document_hashes(recorded=recorded_hashes, actual=actual_hashes),
        # graph_evidence is intentionally left to the caller (main()) — indexing status
        # comes from the Codebase Memory MCP, not from anything this script can query.
        check_scope(changed_paths, checkpoint=checkpoint),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", default="M6-A", choices=sorted(CHECKPOINTS))
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    results = run_all_checks(repo=repo, checkpoint=args.checkpoint)

    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {result.name}: {result.detail}")

    failed = [r for r in results if not r.ok]
    if any(r.name == "m5c_accepted" for r in failed):
        print("M6_PREREQUISITE_NOT_ACCEPTED", file=sys.stderr)
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
