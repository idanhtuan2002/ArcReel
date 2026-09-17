from __future__ import annotations

from scripts.r2.verify_m5c_scope import evaluate


def test_impl_phase_accepts_allowlisted_paths_and_prefixes() -> None:
    paths = [
        "r2/contracts/narrative_plan.py",
        "r2/narrative_lifecycle/changeset_parser.py",
        "r2/narrative_lifecycle/evidence.py",
        "r2/contracts/narrative_lifecycle.py",
        "lib/db/models/narrative_lifecycle.py",
        "lib/db/repositories/narrative_lifecycle.py",
        "tests/integration/donor_parity/vendor/huohuo/workbench-server/src/common/novel/novel-change-record.ts",
        "docs/r2/evidence/R2_M5C_DONOR_BASELINE.json",
        "pyproject.toml",
    ]
    assert evaluate(paths, phase="impl") == []


def test_impl_phase_rejects_an_off_allowlist_path() -> None:
    problems = evaluate(["server/routers/tasks.py"], phase="impl")
    assert problems == ["unexpected implementation path: server/routers/tasks.py"]


def test_impl_phase_allows_only_the_m5c_1b_evidence_migration() -> None:
    assert evaluate(["alembic/versions/5c7c4a0e0001_add_narrative_lifecycle_evidence.py"], phase="impl") == []
    problems = evaluate(["alembic/versions/5c7c4a0e0002_add_narrative_decision_authority.py"], phase="impl")
    assert any("alembic/versions/" in p for p in problems)


def test_handoff_phase_accepts_either_checkpoint_review_doc() -> None:
    assert evaluate(["docs/r2/evidence/R2_M5C_1A_REVIEW.md"], phase="handoff") == []
    assert evaluate(["docs/r2/evidence/R2_M5C_1_REVIEW.md"], phase="handoff") == []


def test_handoff_phase_rejects_anything_else() -> None:
    problems = evaluate(["r2/contracts/narrative_plan.py"], phase="handoff")
    assert problems == ["unexpected post-verified path: r2/contracts/narrative_plan.py"]


def test_m5c2_impl_phase_accepts_the_decision_authority_paths() -> None:
    paths = [
        "r2/narrative_lifecycle/acceptance.py",
        "r2/narrative_lifecycle/authority_kernel.py",
        "lib/db/repositories/narrative_lifecycle.py",
        "alembic/versions/5c7c4a0e0002_add_narrative_decision_authority.py",
        "pyproject.toml",
    ]
    assert evaluate(paths, phase="impl", checkpoint="m5c2") == []


def test_m5c2_impl_phase_rejects_the_m5c1_only_evidence_migration() -> None:
    problems = evaluate(
        ["alembic/versions/5c7c4a0e0001_add_narrative_lifecycle_evidence.py"], phase="impl", checkpoint="m5c2"
    )
    assert any("alembic/versions/" in p for p in problems)


def test_m5c2_impl_phase_rejects_an_off_allowlist_path() -> None:
    problems = evaluate(["server/routers/tasks.py"], phase="impl", checkpoint="m5c2")
    assert problems == ["unexpected implementation path: server/routers/tasks.py"]


def test_m5c2_handoff_phase_accepts_only_its_own_review_doc() -> None:
    assert evaluate(["docs/r2/evidence/R2_M5C_2_REVIEW.md"], phase="handoff", checkpoint="m5c2") == []
    problems = evaluate(["docs/r2/evidence/R2_M5C_1_REVIEW.md"], phase="handoff", checkpoint="m5c2")
    assert problems == ["unexpected post-verified path: docs/r2/evidence/R2_M5C_1_REVIEW.md"]
