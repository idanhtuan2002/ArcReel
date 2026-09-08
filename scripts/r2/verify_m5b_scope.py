"""Machine-checkable M5B implementation/evidence scope allowlist.

Fail-closed: any changed path (``git diff --name-only base...head``) outside the
allowlist exits non-zero. The implementation range additionally requires exactly one
changed ``alembic/versions/`` file and that it is the reserved M5B migration.

    uv run python scripts/r2/verify_m5b_scope.py --base <sha> --verified-head <sha> [--handoff-head <sha>]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Iterable

RESERVED_MIGRATION = "alembic/versions/5b7c4a0e0001_add_narrative_plans.py"

DOC_ALLOWLIST: frozenset[str] = frozenset(
    {
        "docs/superpowers/specs/2026-09-08-r2-m5b-epistemic-plan-context-design.md",
        "docs/superpowers/plans/2026-09-08-r2-m5b-epistemic-plan-context.md",
        "docs/r2/evidence/R2_M5B_DOCUMENT_APPROVAL.json",
        "docs/r2/evidence/R2_M5B_STARTING_STATE.json",
        "docs/r2/evidence/R2_M5B_1_REVIEW.md",
        "docs/r2/evidence/R2_M5B_2_REVIEW.md",
        "docs/r2/evidence/R2_M5B_3_REVIEW.md",
        "docs/research/2026-09-08-r2-m5b-reuse-and-boundary-research.md",
    }
)

IMPLEMENTATION_ALLOWLIST: frozenset[str] = DOC_ALLOWLIST | frozenset(
    {
        "pyproject.toml",
        RESERVED_MIGRATION,
        "r2/contracts/__init__.py",
        "r2/contracts/narrative.py",
        "r2/contracts/narrative_plan.py",
        "r2/contracts/narrative_context.py",
        "r2/narrative/__init__.py",
        "r2/narrative/errors.py",
        "r2/narrative/hashing.py",
        "r2/narrative/schema_upgrade.py",
        "r2/narrative/canon_state.py",
        "r2/narrative/temporal.py",
        "r2/narrative/epistemic.py",
        "r2/narrative/validation.py",
        "r2/narrative/canon_transaction.py",
        "r2/narrative/canon_resolver.py",
        "r2/narrative/integrity.py",
        "r2/narrative_plan/__init__.py",
        "r2/narrative_plan/errors.py",
        "r2/narrative_plan/hashing.py",
        "r2/narrative_plan/validation.py",
        "r2/narrative_plan/integrity.py",
        "r2/narrative_plan/ports.py",
        "r2/narrative_plan/service.py",
        "r2/narrative_context/__init__.py",
        "r2/narrative_context/errors.py",
        "r2/narrative_context/ports.py",
        "r2/narrative_context/compiler.py",
        "lib/db/models/__init__.py",
        "lib/db/models/narrative_plan.py",
        "lib/db/repositories/narrative_plan.py",
        "lib/db/narrative_plan_uow.py",
        "scripts/r2/verify_m5b_scope.py",
        "tests/fixtures/r2/__init__.py",
        "tests/fixtures/r2/m5b_narrative_corpus.py",
        "tests/unit/r2/contracts/test_narrative_v2.py",
        "tests/unit/r2/contracts/test_narrative_plan.py",
        "tests/unit/r2/contracts/test_narrative_context.py",
        "tests/unit/r2/narrative/test_schema_upgrade.py",
        "tests/unit/r2/narrative/test_hashing.py",
        "tests/unit/r2/narrative/test_canon_state.py",
        "tests/unit/r2/narrative/test_temporal.py",
        "tests/unit/r2/narrative/test_epistemic.py",
        "tests/unit/r2/narrative/test_validation.py",
        "tests/unit/r2/narrative/test_validation_m5b.py",
        "tests/unit/r2/narrative/test_canon_architecture_boundaries.py",
        "tests/unit/r2/narrative_plan/_helpers.py",
        "tests/unit/r2/narrative_plan/test_plan_hashing.py",
        "tests/unit/r2/narrative_plan/test_plan_validation.py",
        "tests/unit/r2/narrative_context/test_compiler.py",
        "tests/unit/r2/test_m5b_architecture_boundaries.py",
        "tests/unit/lib/db/models/test_narrative_plan.py",
        "tests/unit/scripts/r2/test_verify_m5b_scope.py",
        "tests/integration/r2/narrative/test_canon_v2_replay.py",
        "tests/integration/r2/narrative_plan/test_integrity.py",
        "tests/integration/r2/narrative_plan/test_service.py",
        "tests/integration/r2/narrative_plan/test_concurrency.py",
        "tests/integration/r2/test_m5b_acceptance.py",
        "tests/integration/lib/db/migrations/test_alembic_narrative_plan.py",
        "tests/integration/lib/db/repositories/test_narrative_plan.py",
    }
)

FINAL_ONLY_ALLOWLIST: frozenset[str] = frozenset({"docs/r2/evidence/R2_M5B_FINAL_VERIFICATION.md"})


def _git_diff_names(base: str, head: str) -> list[str]:
    output = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in output.stdout.splitlines() if line.strip()]


def unexpected_paths(paths: Iterable[str], *, allowlist: frozenset[str]) -> list[str]:
    return sorted(path for path in paths if path and path not in allowlist)


def migration_violations(paths: Iterable[str]) -> list[str]:
    migrations = sorted(path for path in paths if path.startswith("alembic/versions/"))
    if not migrations:
        return []
    problems: list[str] = []
    if len(migrations) != 1:
        problems.append(f"expected exactly one changed alembic/versions/ file, found {migrations}")
    elif migrations[0] != RESERVED_MIGRATION:
        problems.append(f"changed migration {migrations[0]!r} is not the reserved {RESERVED_MIGRATION!r}")
    return problems


def evaluate(implementation_paths: Iterable[str], final_paths: Iterable[str] | None = None) -> list[str]:
    impl = list(implementation_paths)
    problems = [
        f"unexpected implementation path: {item}" for item in unexpected_paths(impl, allowlist=IMPLEMENTATION_ALLOWLIST)
    ]
    problems += migration_violations(impl)
    if final_paths is not None:
        problems += [
            f"unexpected post-verified path: {item}"
            for item in unexpected_paths(final_paths, allowlist=FINAL_ONLY_ALLOWLIST)
        ]
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--verified-head", required=True)
    parser.add_argument("--handoff-head")
    args = parser.parse_args()

    impl = _git_diff_names(args.base, args.verified_head)
    final = _git_diff_names(args.verified_head, args.handoff_head) if args.handoff_head else None
    problems = evaluate(impl, final)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
