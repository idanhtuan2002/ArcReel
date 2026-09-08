"""Acceptance and rejection cases for the M5A scope allowlist checker."""

from __future__ import annotations

import pytest

from scripts.r2.verify_m5a_scope import (
    RESERVED_MIGRATION,
    evaluate,
    migration_violations,
    unexpected_paths,
)

_HAPPY_IMPLEMENTATION = [
    "r2/narrative/canon_transaction.py",
    "lib/db/repositories/canon_repo.py",
    "tests/integration/r2/narrative/_canon_authority.py",
    "tests/integration/r2/narrative/test_canon_concurrency.py",
    "scripts/r2/audit_m4_architecture.py",
    "tests/integration/r2/m4/test_m4_architecture_audit.py",
    RESERVED_MIGRATION,
    "pyproject.toml",
]


def test_implementation_allowlist_accepts_the_expected_surface() -> None:
    assert evaluate(_HAPPY_IMPLEMENTATION, mode="implementation") == []


@pytest.mark.parametrize(
    "forbidden",
    [
        "r2/canvas/board.py",
        "r2/providers/openai.py",
        "server/main.py",
        "docs/superpowers/plans/2026-09-08-r2-m5b-epistemic-plan-context-design.md",
        "docs/r2/evidence/some_other_report.md",
    ],
)
def test_implementation_allowlist_rejects_out_of_scope_paths(forbidden: str) -> None:
    problems = evaluate([*_HAPPY_IMPLEMENTATION, forbidden], mode="implementation")
    assert any(forbidden in problem for problem in problems)


def test_a_second_migration_stops_the_gate() -> None:
    changed = [*_HAPPY_IMPLEMENTATION, "alembic/versions/9999_add_something_else.py"]
    problems = evaluate(changed, mode="implementation")
    assert any("alembic/versions" in problem for problem in problems)


def test_the_wrong_reserved_migration_stops_the_gate() -> None:
    changed = ["alembic/versions/deadbeef_add_canon.py", "pyproject.toml"]
    assert migration_violations(changed, mode="implementation")


def test_a_missing_migration_stops_the_implementation_gate() -> None:
    assert migration_violations(["pyproject.toml"], mode="implementation")


def test_handoff_mode_permits_only_the_final_verification_document() -> None:
    assert evaluate(["docs/r2/evidence/R2_M5A_FINAL_VERIFICATION.md"], mode="handoff") == []
    assert unexpected_paths(["r2/narrative/canon_transaction.py"], mode="handoff") == [
        "r2/narrative/canon_transaction.py"
    ]


def test_handoff_mode_ignores_the_migration_rule() -> None:
    assert migration_violations([RESERVED_MIGRATION], mode="handoff") == []


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown mode"):
        unexpected_paths(["pyproject.toml"], mode="nonsense")
