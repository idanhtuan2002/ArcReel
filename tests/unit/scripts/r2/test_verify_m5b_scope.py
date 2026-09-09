from __future__ import annotations

from scripts.r2.verify_m5b_scope import RESERVED_MIGRATION, evaluate


def test_allowed_implementation_paths_pass() -> None:
    paths = [
        "r2/narrative/temporal.py",
        "r2/narrative_plan/service.py",
        "r2/narrative_context/compiler.py",
        "lib/db/models/narrative_plan.py",
        RESERVED_MIGRATION,
        "tests/integration/r2/test_m5b_acceptance.py",
        "docs/r2/evidence/R2_M5B_STARTING_STATE.json",
        "docs/research/2026-09-08-r2-m5b-author-draft-omniscient-gate.md",
        "docs/research/2026-09-08-r2-m5b-validate-scene-plan-commit-rules.md",
    ]
    assert evaluate(paths) == []


def test_an_out_of_scope_path_is_rejected() -> None:
    problems = evaluate(["r2/production/approval_service.py"])
    assert problems == ["unexpected implementation path: r2/production/approval_service.py"]


def test_a_non_reserved_migration_is_rejected() -> None:
    problems = evaluate([RESERVED_MIGRATION, "alembic/versions/9999_other.py"])
    assert any("exactly one changed alembic/versions/ file" in item for item in problems)


def test_wrong_single_migration_is_rejected() -> None:
    problems = evaluate(["alembic/versions/deadbeef_wrong.py"])
    assert any("is not the reserved" in item for item in problems)


def test_post_verified_range_accepts_only_the_final_verification_doc() -> None:
    assert evaluate([RESERVED_MIGRATION], ["docs/r2/evidence/R2_M5B_FINAL_VERIFICATION.md"]) == []
    problems = evaluate([RESERVED_MIGRATION], ["r2/narrative/temporal.py"])
    assert problems == ["unexpected post-verified path: r2/narrative/temporal.py"]
