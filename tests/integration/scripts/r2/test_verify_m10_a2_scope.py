"""A2 custody uses real accepted Git history and remains read-only on refusal."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[4]
GUARD = "scripts/r2/verify_m10_a2_scope.py"
ACCEPTANCE = "f3d9cf978"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "--no-optional-locks", "-c", "core.hooksPath=/dev/null", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def commit(repo: Path) -> None:
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "A2 scope fixture")


def snapshot(repo: Path) -> dict[str, str]:
    return {
        str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in repo.rglob("*") if p.is_file()
    }


@pytest.fixture
def a2_repo(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "clone", "--shared", "--no-checkout", "-q", str(SOURCE), str(repo)], check=True, capture_output=True
    )
    git(repo, "checkout", "--detach", "-q", ACCEPTANCE)
    ref = git(repo, "rev-parse", "HEAD")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / GUARD).write_bytes((SOURCE / GUARD).read_bytes())
    commit(repo)
    runner = tmp_path / "accepted-a2-guard.py"
    runner.write_bytes((repo / GUARD).read_bytes())
    return repo, runner, ref


def invoke(repo: Path, runner: Path, ref: str, **environment: str):
    return subprocess.run(
        [sys.executable, "-I", "-B", str(runner), "--repo", str(repo), "--acceptance-ref", ref],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, **environment, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def test_accepted_a2_scope_is_read_only_and_allows_unrelated_dirty_work(a2_repo) -> None:
    repo, runner, ref = a2_repo
    (repo / "unrelated-note.txt").write_text("preserve")
    before = snapshot(repo)
    result = invoke(repo, runner, ref)
    assert result.returncode == 0, result.stdout + result.stderr
    body = json.loads(result.stdout)
    assert body["status"] == "M10_A2_SCOPE_OK"
    assert body["stop_codes"] == []
    assert body["head"] == git(repo, "rev-parse", "HEAD")
    assert snapshot(repo) == before


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("wrong_acceptance", "M10_DESIGN_NOT_ACCEPTED"),
        ("missing_acceptance", "M10_DESIGN_NOT_ACCEPTED"),
        ("dirty_owned", "POST_M8_BASE_SEAM_CHANGED"),
        ("ignored_owned", "POST_M8_BASE_SEAM_CHANGED"),
        ("staged_dependency", "POST_M8_BASE_SEAM_CHANGED"),
        ("skip_worktree", "POST_M8_BASE_SEAM_CHANGED"),
        ("assume_unchanged", "POST_M8_BASE_SEAM_CHANGED"),
        ("baseline_bytes", "POST_M8_BASE_SEAM_CHANGED"),
        ("baseline_mode", "POST_M8_BASE_SEAM_CHANGED"),
        ("outside_scope", "POST_M8_BASE_SEAM_CHANGED"),
        ("migration", "M10_SCHEMA_CHANGE_REQUIRED"),
        ("dirty_migration", "M10_SCHEMA_CHANGE_REQUIRED"),
        ("hidden_migration", "M10_SCHEMA_CHANGE_REQUIRED"),
        ("forbidden_import", "M10_NETWORK_SIDE_EFFECT_FORBIDDEN"),
        ("async_implementation", "M10_NETWORK_SIDE_EFFECT_FORBIDDEN"),
        ("bootstrap_canary", "POST_M8_BASE_SEAM_CHANGED"),
        ("receipt_change", "POST_M8_BASE_SEAM_CHANGED"),
        ("review_change", "POST_M8_BASE_SEAM_CHANGED"),
    ],
)
def test_a2_refusal_preserves_repository_and_never_imports_candidate(a2_repo, case: str, code: str) -> None:
    repo, runner, ref = a2_repo
    if case == "wrong_acceptance":
        ref = git(repo, "rev-parse", "HEAD")
    elif case == "missing_acceptance":
        ref = "0" * 40
    elif case in {"dirty_owned", "skip_worktree", "assume_unchanged"}:
        if case != "dirty_owned":
            git(repo, "update-index", "--skip-worktree" if case == "skip_worktree" else "--assume-unchanged", GUARD)
        with (repo / GUARD).open("a") as stream:
            stream.write("\n# dirty guard\n")
    elif case == "ignored_owned":
        with (repo / ".git/info/exclude").open("a") as stream:
            stream.write("\nr2/quality/ports.py\n")
        (repo / "r2/quality/ports.py").write_text("must not execute")
    elif case == "staged_dependency":
        (repo / "r2/quality/digests.py").write_text("changed")
        git(repo, "add", "r2/quality/digests.py")
    elif case == "baseline_mode":
        git(repo, "update-index", "--chmod=+x", "r2/quality/digests.py")
        git(repo, "commit", "-qm", "changed mode")
    elif case == "hidden_migration":
        path = git(repo, "ls-files", "alembic/versions").splitlines()[0]
        git(repo, "update-index", "--assume-unchanged", path)
    else:
        path, content = {
            "baseline_bytes": ("r2/quality/digests.py", "changed"),
            "outside_scope": ("outside-m10.txt", "changed"),
            "migration": ("alembic/versions/m10_stray.py", "revision='stray'"),
            "dirty_migration": ("alembic/versions/m10_stray.py", "revision='stray'"),
            "forbidden_import": ("r2/quality/ports.py", "import socket\n"),
            "async_implementation": (
                "r2/quality/ports.py",
                "from typing import Protocol\nclass P(Protocol):\n    async def f(self): return 1\n",
            ),
            "bootstrap_canary": ("scripts/r2/verify_m10_bootstrap.py", "raise RuntimeError('SECRET_CANARY')\n"),
            "receipt_change": ("docs/r2/evidence/R2_M10_A2_DESIGN_ACCEPTANCE.json", "{}"),
            "review_change": ("docs/r2/evidence/m10-a2-reviews/a-5eda15b89.json", "{}"),
        }[case]
        (repo / path).write_text(content)
        if case not in {"dirty_migration", "bootstrap_canary"}:
            commit(repo)
    before = snapshot(repo)
    result = invoke(repo, runner, ref)
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["stop_codes"] == [code]
    assert "SECRET_CANARY" not in result.stdout + result.stderr
    assert snapshot(repo) == before


def test_a2_sanitizes_inherited_git_redirects(a2_repo, tmp_path: Path) -> None:
    repo, runner, ref = a2_repo
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    git(unrelated, "init", "-q")
    result = invoke(repo, runner, ref, GIT_DIR=str(unrelated / ".git"), GIT_WORK_TREE=str(unrelated))
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "M10_A2_SCOPE_OK"
