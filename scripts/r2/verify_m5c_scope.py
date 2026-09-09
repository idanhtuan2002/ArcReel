"""Machine-checkable M5C-1A implementation / handoff scope allowlist.

Fail-closed: any changed path (``git diff --name-only base...head``) outside the
allowlist exits non-zero. The M5C-1A implementation range must touch **no**
``alembic/versions/`` file (migrations land in M5C-1B onward). The evidence-only
handoff range may touch exactly ``docs/r2/evidence/R2_M5C_1A_REVIEW.md``.

    uv run python scripts/r2/verify_m5c_scope.py --base <sha> --head <sha> --phase impl
    uv run python scripts/r2/verify_m5c_scope.py --base <sha> --head <sha> --phase handoff
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Iterable

# Directory prefixes owned wholesale by M5C-1A.
ALLOWED_PREFIXES: tuple[str, ...] = (
    "tests/integration/donor_parity/",
    "docs/r2/evidence/R2_M5C_",
)

HANDOFF_ONLY_ALLOWLIST: frozenset[str] = frozenset({"docs/r2/evidence/R2_M5C_1A_REVIEW.md"})

IMPLEMENTATION_ALLOWLIST: frozenset[str] = HANDOFF_ONLY_ALLOWLIST | frozenset(
    {
        # approved documents materialised at the M5C base
        "docs/adr/0076-narrative-lifecycle-evidence-and-acceptance-authority.md",
        "docs/research/2026-09-09-r2-m5c-persistence-state-machine-validation.md",
        "docs/superpowers/plans/2026-09-09-r2-m5c-narrative-lifecycle.md",
        "docs/superpowers/specs/2026-09-09-r2-m5c-narrative-lifecycle-design.md",
        # tooling / fitness
        "pyproject.toml",
        "uv.lock",
        "scripts/r2/verify_m5c_scope.py",
        # v2 contracts + selectors
        "r2/contracts/__init__.py",
        "r2/contracts/narrative_plan.py",
        # F9 relationship / thread / R9 / R10
        "r2/narrative/__init__.py",
        "r2/narrative/errors.py",
        "r2/narrative/relationship_facts.py",
        "r2/narrative/validation.py",
        "r2/narrative_plan/__init__.py",
        "r2/narrative_plan/hashing.py",
        "r2/narrative_plan/schema_upgrade.py",
        "r2/narrative_plan/service.py",
        "r2/narrative_plan/validation.py",
        # scene-side omniscient gate
        "r2/narrative_context/__init__.py",
        "r2/narrative_context/compiler.py",
        "r2/narrative_context/errors.py",
        "r2/narrative_context/ports.py",
        # donor ports (pure)
        "r2/narrative_lifecycle/__init__.py",
        "r2/narrative_lifecycle/changeset_parser.py",
        "r2/narrative_lifecycle/continuity_rules.py",
        # tests
        "tests/unit/r2/contracts/test_narrative_plan_v2.py",
        "tests/unit/r2/narrative/test_relationship_facts.py",
        "tests/unit/r2/narrative/test_validation_f9.py",
        "tests/unit/r2/narrative_context/test_compiler.py",
        "tests/unit/r2/narrative_context/test_omniscient_gate.py",
        "tests/unit/r2/narrative_plan/_helpers.py",
        "tests/unit/r2/narrative_plan/test_hashing_v2.py",
        "tests/unit/r2/narrative_plan/test_schema_upgrade_scene.py",
        "tests/unit/r2/narrative_plan/test_thread_lifecycle.py",
        "tests/unit/r2/test_m5c_architecture_boundaries.py",
        "tests/unit/scripts/r2/test_verify_m5c_scope.py",
        "tests/integration/r2/test_m5b_acceptance.py",
    }
)


def _git_diff_names(base: str, head: str) -> list[str]:
    output = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in output.stdout.splitlines() if line.strip()]


def _allowed(path: str, *, allowlist: frozenset[str], prefixes: tuple[str, ...]) -> bool:
    return path in allowlist or any(path.startswith(prefix) for prefix in prefixes)


def unexpected_paths(paths: Iterable[str], *, allowlist: frozenset[str], prefixes: tuple[str, ...]) -> list[str]:
    return sorted(p for p in paths if p and not _allowed(p, allowlist=allowlist, prefixes=prefixes))


def migration_violations(paths: Iterable[str]) -> list[str]:
    migrations = sorted(p for p in paths if p.startswith("alembic/versions/"))
    return [f"M5C-1A must touch no alembic/versions/ file, found {migrations}"] if migrations else []


def evaluate(paths: Iterable[str], *, phase: str) -> list[str]:
    changed = list(paths)
    if phase == "handoff":
        return [
            f"unexpected post-verified path: {item}"
            for item in unexpected_paths(changed, allowlist=HANDOFF_ONLY_ALLOWLIST, prefixes=())
        ]
    problems = [
        f"unexpected implementation path: {item}"
        for item in unexpected_paths(changed, allowlist=IMPLEMENTATION_ALLOWLIST, prefixes=ALLOWED_PREFIXES)
    ]
    problems += migration_violations(changed)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--phase", required=True, choices=("impl", "handoff"))
    args = parser.parse_args()

    problems = evaluate(_git_diff_names(args.base, args.head), phase=args.phase)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
