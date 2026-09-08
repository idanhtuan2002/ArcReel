"""Machine-checkable M5A scope allowlist for the implementation and evidence diffs.

Fail-closed: any changed path outside the mode's allowlist exits non-zero. The
implementation mode additionally requires exactly one changed file under
``alembic/versions/`` and that its path is the reserved M5A migration.

    uv run python scripts/r2/verify_m5a_scope.py --base <sha> --head <sha> --mode implementation
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Iterable

RESERVED_MIGRATION = "alembic/versions/5a7c4a0e0001_add_canon_authority.py"

IMPLEMENTATION_ALLOWLIST: frozenset[str] = frozenset(
    {
        "CONTEXT.md",
        "docs/adr/0075-canon-authority-append-only-deltas.md",
        "docs/superpowers/specs/2026-09-07-r2-m5a-canon-authority-and-transactions-design.md",
        "docs/superpowers/plans/2026-09-07-r2-m5a-canon-authority-and-transactions.md",
        "docs/r2/evidence/R2_M5A_STARTING_STATE.json",
        "r2/contracts/narrative.py",
        "r2/contracts/__init__.py",
        "r2/narrative/__init__.py",
        "r2/narrative/errors.py",
        "r2/narrative/hashing.py",
        "r2/narrative/canon_state.py",
        "r2/narrative/validation.py",
        "r2/narrative/ports.py",
        "r2/narrative/canon_resolver.py",
        "r2/narrative/canon_resolution.py",
        "r2/narrative/canon_transaction.py",
        "r2/narrative/integrity.py",
        "lib/db/models/canon.py",
        "lib/db/models/__init__.py",
        "lib/db/repositories/canon_repo.py",
        "lib/db/canon_uow.py",
        RESERVED_MIGRATION,
        "tests/unit/r2/contracts/test_narrative.py",
        "tests/unit/r2/narrative/test_hashing.py",
        "tests/unit/r2/narrative/test_canon_state.py",
        "tests/unit/r2/narrative/test_validation.py",
        "tests/unit/r2/narrative/test_canon_architecture_boundaries.py",
        "tests/unit/lib/db/models/test_canon.py",
        "tests/unit/scripts/r2/test_verify_m5a_scope.py",
        "tests/integration/lib/db/migrations/test_alembic_canon_authority.py",
        "tests/integration/lib/db/repositories/test_canon_repo.py",
        # Shared Canon authority seeding helpers for the 5 narrative integration
        # test files (keeps identical fixtures out of >=3 files per audit_tests).
        "tests/integration/r2/narrative/_canon_authority.py",
        "tests/integration/r2/narrative/test_canon_resolver.py",
        "tests/integration/r2/narrative/test_canon_resolution.py",
        "tests/integration/r2/narrative/test_canon_transaction.py",
        "tests/integration/r2/narrative/test_canon_concurrency.py",
        "tests/integration/r2/narrative/test_canon_integrity.py",
        "scripts/r2/verify_m5a_scope.py",
        "pyproject.toml",
        # Retired at M4 closure: the M4 PR-scope tripwire (``_M5_MARKERS`` pre-registered
        # r2/narrative etc. to keep M5 code out of the M4 PR) structurally cannot pass on
        # an M5 branch. The permanent M4 fitness sensors stay in
        # tests/unit/r2/production_intelligence/test_architecture_boundaries.py.
        "scripts/r2/audit_m4_architecture.py",
        "tests/integration/r2/m4/test_m4_architecture_audit.py",
    }
)

HANDOFF_ALLOWLIST: frozenset[str] = frozenset({"docs/r2/evidence/R2_M5A_FINAL_VERIFICATION.md"})


def _allowlist_for(mode: str) -> frozenset[str]:
    if mode == "implementation":
        return IMPLEMENTATION_ALLOWLIST
    if mode == "handoff":
        return HANDOFF_ALLOWLIST
    raise ValueError(f"unknown mode {mode!r}")


def unexpected_paths(paths: Iterable[str], *, mode: str) -> list[str]:
    allowlist = _allowlist_for(mode)
    return sorted(path for path in paths if path and path not in allowlist)


def migration_violations(paths: Iterable[str], *, mode: str) -> list[str]:
    if mode != "implementation":
        return []
    migration_paths = sorted(path for path in paths if path.startswith("alembic/versions/"))
    problems: list[str] = []
    if len(migration_paths) != 1:
        problems.append(f"expected exactly one changed alembic/versions/ file, found {migration_paths}")
    elif migration_paths[0] != RESERVED_MIGRATION:
        problems.append(f"changed migration {migration_paths[0]!r} is not the reserved {RESERVED_MIGRATION!r}")
    return problems


def evaluate(paths: Iterable[str], *, mode: str) -> list[str]:
    paths = list(paths)
    return [
        *(f"unexpected path: {item}" for item in unexpected_paths(paths, mode=mode)),
        *migration_violations(paths, mode=mode),
    ]


def _git_diff_names(base: str, head: str) -> list[str]:
    output = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in output.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--mode", required=True, choices=("implementation", "handoff"))
    args = parser.parse_args(argv)

    paths = _git_diff_names(args.base, args.head)
    problems = evaluate(paths, mode=args.mode)
    if problems:
        print(f"M5A scope check FAILED ({args.mode}):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"M5A scope check passed ({args.mode}): {len(paths)} changed path(s) within the allowlist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
