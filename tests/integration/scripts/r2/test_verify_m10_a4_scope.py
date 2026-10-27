"""Real Git A4 custody refuses tampering without executing candidate modules."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.integration.scripts.r2.test_verify_m10_a2_scope import commit, git, snapshot

SOURCE = Path(__file__).resolve().parents[4]
ACCEPTANCE = "cf9f2f2c76d1eea46dd9f0b69db744c0d3f97327"
GUARD = "scripts/r2/verify_m10_a4_scope.py"


@pytest.fixture
def a4_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "clone", "--shared", "--no-checkout", "-q", str(SOURCE), str(repo)],
        check=True,
        capture_output=True,
    )
    git(repo, "checkout", "--detach", "-q", ACCEPTANCE)
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    path = SOURCE / GUARD
    assert path.exists(), "A4 guard is missing; no safe source admission"
    (repo / GUARD).write_bytes(path.read_bytes())
    commit(repo)
    runner = tmp_path / "trusted-guard.py"
    runner.write_bytes(path.read_bytes())
    return repo, runner


def invoke(repo: Path, runner: Path, *extra: str):
    return subprocess.run(
        [sys.executable, "-I", "-B", str(runner), "--repo", str(repo), *extra],
        capture_output=True,
        text=True,
        timeout=45,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def test_scope_uses_real_head_preserves_unrelated_work_and_claims_no_runtime(a4_repo) -> None:
    repo, runner = a4_repo
    (repo / "unrelated.txt").write_text("preserve")
    before = snapshot(repo)
    result = invoke(repo, runner)
    assert result.returncode == 0, result.stdout + result.stderr
    body = json.loads(result.stdout)
    assert body["status"] == "M10_A4_SCOPE_OK"
    assert body["head"] == git(repo, "rev-parse", "HEAD")
    assert body["runtime_accepted"] is False
    assert snapshot(repo) == before


@pytest.mark.parametrize(
    "case",
    [
        "dirty_contract",
        "staged_contract",
        "committed_contract",
        "hidden_contract",
        "skip_contract",
        "extra_migration",
        "registry_effect",
        "old_capability",
        "shadow_module",
        "candidate_initializer",
        "dirty_guard",
        "dirty_config",
        "extra_committed_scope",
        "wrong_acceptance",
        "missing_history",
        "changed_compatibility",
    ],
)
def test_tampering_refuses_without_candidate_execution_or_repository_mutation(a4_repo, case: str) -> None:
    repo, runner = a4_repo
    extra = ()
    if case == "wrong_acceptance":
        extra = ("--acceptance-ref", "0" * 40)
    elif case == "missing_history":
        git(repo, "checkout", "--orphan", "unrelated")
        git(repo, "rm", "-rf", ".")
        (repo / "unrelated.txt").write_text("unrelated")
        commit(repo)
    else:
        path = {
            "extra_migration": "alembic/versions/stray.py",
            "registry_effect": "lib/db/models/__init__.py",
            "old_capability": "r2/provider_capabilities/registry.json",
            "shadow_module": "server/services/quality_probes/__init__.py",
            "candidate_initializer": "r2/quality/__init__.py",
            "dirty_guard": GUARD,
            "dirty_config": "pyproject.toml",
            "extra_committed_scope": "outside-m10.txt",
            "changed_compatibility": "tests/integration/lib/db/migrations/test_65f53650f3a8_quality_profile_publication.py",
        }.get(case, "r2/contracts/quality.py")
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a") as stream:
            stream.write("\nraise RuntimeError('CANARY_SECRET')\n")
        if case == "hidden_contract":
            git(repo, "update-index", "--assume-unchanged", path)
        elif case == "skip_contract":
            git(repo, "update-index", "--skip-worktree", path)
        elif case == "staged_contract":
            git(repo, "add", path)
        elif case not in {"dirty_guard", "dirty_config"}:
            commit(repo)
    before = snapshot(repo)
    result = invoke(repo, runner, *extra)
    assert result.returncode == 1, result.stdout + result.stderr
    body = json.loads(result.stdout)
    assert body["stop_codes"]
    assert body["runtime_accepted"] is False
    assert "CANARY_SECRET" not in result.stdout + result.stderr
    assert snapshot(repo) == before
