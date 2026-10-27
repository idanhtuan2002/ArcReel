"""A3-P source custody uses real accepted history without executing product code."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.integration.scripts.r2.test_verify_m10_a2_scope import commit, git, snapshot

SOURCE = Path(__file__).resolve().parents[4]
ACCEPTANCE = "c7a86813bd7a45f119262dc7acdfe9803967e181"
DESIGN = "2e69816123c32ba057bfbed7d5e55344b3daa7d2"
GUARD = "scripts/r2/verify_m10_a3_scope.py"


@pytest.fixture
def a3_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "clone", "--shared", "--no-checkout", "-q", str(SOURCE), str(repo)], check=True, capture_output=True
    )
    git(repo, "checkout", "--detach", "-q", ACCEPTANCE)
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / GUARD).write_bytes((SOURCE / GUARD).read_bytes())
    commit(repo)
    runner = tmp_path / "committed-a3-guard.py"
    runner.write_bytes((repo / GUARD).read_bytes())
    return repo, runner


def invoke(repo: Path, runner: Path, *, ref: str = ACCEPTANCE, **environment: str):
    return subprocess.run(
        [sys.executable, "-I", "-B", str(runner), "--repo", str(repo), "--acceptance-ref", ref],
        capture_output=True,
        text=True,
        timeout=45,
        env={**os.environ, **environment, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def test_real_a3_p_scope_pass_preserves_unrelated_dirty_work_and_ignored_caches(a3_repo) -> None:
    repo, runner = a3_repo
    (repo / "unrelated.txt").write_text("preserve")
    cache = repo / "alembic/versions/__pycache__/fixture.cpython-313.pyc"
    cache.parent.mkdir(exist_ok=True)
    cache.write_bytes(b"cache")
    before = snapshot(repo)
    result = invoke(repo, runner)
    assert result.returncode == 0, result.stdout + result.stderr
    body = json.loads(result.stdout)
    assert body["status"] == "M10_A3_P_SCOPE_OK"
    assert body["original_a3_fully_accepted"] is False
    assert body["readiness_runtime_accepted"] is False
    assert body["stop_codes"] == []
    assert snapshot(repo) == before


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("wrong_ref", "M10_DESIGN_NOT_ACCEPTED"),
        ("missing_ref", "M10_DESIGN_NOT_ACCEPTED"),
        ("dirty_guard", "POST_M8_BASE_SEAM_CHANGED"),
        ("hidden_guard", "POST_M8_BASE_SEAM_CHANGED"),
        ("skip_guard", "POST_M8_BASE_SEAM_CHANGED"),
        ("ignored_source", "POST_M8_BASE_SEAM_CHANGED"),
        ("staged_baseline", "POST_M8_BASE_SEAM_CHANGED"),
        ("committed_baseline", "POST_M8_BASE_SEAM_CHANGED"),
        ("baseline_mode", "POST_M8_BASE_SEAM_CHANGED"),
        ("registry_effect", "POST_M8_BASE_SEAM_CHANGED"),
        ("extra_scope", "POST_M8_BASE_SEAM_CHANGED"),
        ("extra_migration", "M10_SCHEMA_CHANGE_REQUIRED"),
        ("dirty_migration", "M10_SCHEMA_CHANGE_REQUIRED"),
        ("changed_migration", "M10_SCHEMA_CHANGE_REQUIRED"),
        ("wrong_migration", "M10_SCHEMA_CHANGE_REQUIRED"),
        ("forbidden_import", "M10_NETWORK_SIDE_EFFECT_FORBIDDEN"),
        ("legacy_auth", "M10_NETWORK_SIDE_EFFECT_FORBIDDEN"),
        ("acceptance_changed", "POST_M8_BASE_SEAM_CHANGED"),
        ("review_changed", "POST_M8_BASE_SEAM_CHANGED"),
        ("bootstrap_canary", "POST_M8_BASE_SEAM_CHANGED"),
        ("shadow_package", "POST_M8_BASE_SEAM_CHANGED"),
        ("parent_initializer", "POST_M8_BASE_SEAM_CHANGED"),
    ],
)
def test_refusal_preserves_repository_and_does_not_execute_candidate(a3_repo, case: str, code: str) -> None:
    repo, runner = a3_repo
    ref = ACCEPTANCE
    if case == "wrong_ref":
        ref = DESIGN
    elif case == "missing_ref":
        ref = "0" * 40
    elif case in {"dirty_guard", "hidden_guard", "skip_guard"}:
        if case != "dirty_guard":
            git(repo, "update-index", "--assume-unchanged" if case == "hidden_guard" else "--skip-worktree", GUARD)
        with (repo / GUARD).open("a") as stream:
            stream.write("\n# dirty\n")
    elif case == "baseline_mode":
        git(repo, "update-index", "--chmod=+x", "r2/quality/errors.py")
        git(repo, "commit", "-qm", "changed mode")
    else:
        path, content = {
            "ignored_source": ("r2/quality/profiles.py", "raise RuntimeError('CANARY_SECRET')"),
            "staged_baseline": ("r2/quality/errors.py", "changed"),
            "committed_baseline": ("r2/quality/errors.py", "changed"),
            "registry_effect": ("lib/db/models/__init__.py", "print('CANARY_SECRET')"),
            "extra_scope": ("outside-m10.txt", "outside"),
            "extra_migration": ("alembic/versions/stray.py", "revision='stray'\ndown_revision='918c4a0e0001'"),
            "dirty_migration": ("alembic/versions/stray.py", "revision='stray'\ndown_revision='918c4a0e0001'"),
            "changed_migration": (
                "alembic/versions/918c4a0e0001_bind_format_review_packets_to_grants.py",
                "revision='918c4a0e0001'\ndown_revision=None",
            ),
            "wrong_migration": (
                "alembic/versions/65f53650f3a8_quality_profile_publication.py",
                "revision='wrong'\ndown_revision='918c4a0e0001'",
            ),
            "forbidden_import": ("r2/quality/profiles.py", "import socket\n"),
            "legacy_auth": (
                "server/services/quality_profile_custodian.py",
                "from server.auth import get_current_user\n",
            ),
            "acceptance_changed": ("docs/r2/evidence/R2_M10_A3_DESIGN_ACCEPTANCE.json", "{}"),
            "review_changed": ("docs/r2/evidence/m10-a3-reviews/a-2e6981612.json", "{}"),
            "bootstrap_canary": ("scripts/r2/verify_m10_bootstrap.py", "raise RuntimeError('CANARY_SECRET')"),
            "shadow_package": (
                "server/services/quality_profile_custodian/__init__.py",
                "raise RuntimeError('CANARY_SECRET')",
            ),
            "parent_initializer": ("lib/db/__init__.py", "raise RuntimeError('CANARY_SECRET')"),
        }[case]
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(content)
        if case == "ignored_source":
            with (repo / ".git/info/exclude").open("a") as stream:
                stream.write("\nr2/quality/profiles.py\n")
        elif case == "staged_baseline":
            git(repo, "add", path)
        elif case not in {"dirty_migration", "bootstrap_canary", "shadow_package", "parent_initializer"}:
            commit(repo)
    before = snapshot(repo)
    result = invoke(repo, runner, ref=ref)
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["stop_codes"] == [code]
    assert "CANARY_SECRET" not in result.stdout + result.stderr
    assert snapshot(repo) == before


def test_exact_owned_migration_skeleton_is_scope_only_not_completion(a3_repo) -> None:
    repo, runner = a3_repo
    path = repo / "alembic/versions/65f53650f3a8_quality_profile_publication.py"
    path.write_text(
        "revision='65f53650f3a8'\ndown_revision='918c4a0e0001'\ndef upgrade(): pass\ndef downgrade(): pass\n"
    )
    commit(repo)
    result = invoke(repo, runner)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["original_a3_fully_accepted"] is False


def test_inherited_git_redirect_cannot_change_scope(a3_repo, tmp_path: Path) -> None:
    repo, runner = a3_repo
    outside = tmp_path / "outside"
    outside.mkdir()
    git(outside, "init", "-q")
    result = invoke(repo, runner, GIT_DIR=str(outside / ".git"), GIT_WORK_TREE=str(outside))
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "M10_A3_P_SCOPE_OK"


def test_missing_accepted_git_objects_refuse_without_writes(a3_repo, tmp_path: Path) -> None:
    _, runner = a3_repo
    repo = tmp_path / "empty-history"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / GUARD).parent.mkdir(parents=True)
    (repo / GUARD).write_bytes(runner.read_bytes())
    commit(repo)
    before = snapshot(repo)
    result = invoke(repo, runner)
    assert result.returncode == 2
    assert json.loads(result.stdout)["stop_codes"] == ["M10_PREREQUISITE_NOT_ACCEPTED"]
    assert snapshot(repo) == before


def test_preacceptance_branch_cannot_reuse_valid_receipt_object(a3_repo) -> None:
    repo, runner = a3_repo
    git(repo, "checkout", "--detach", "-q", DESIGN)
    (repo / GUARD).write_bytes(runner.read_bytes())
    commit(repo)
    before = snapshot(repo)
    result = invoke(repo, runner)
    assert result.returncode == 2
    assert json.loads(result.stdout)["stop_codes"] == ["M10_DESIGN_NOT_ACCEPTED"]
    assert snapshot(repo) == before
