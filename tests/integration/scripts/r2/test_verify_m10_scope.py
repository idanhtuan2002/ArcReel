"""The A0 guard consumes actual accepted history without executing mutable bootstrap code."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[4]
ACCEPTANCE = "cf18b9f6156ed9e6337c40708e217a73271027fa"
CANDIDATE = "97e03c2ccee778e2797940f245fca9900fbf7a8e"
GUARD = "scripts/r2/verify_m10_scope.py"


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
    git(repo, "commit", "-qm", "scope fixture")


def snapshot(repo: Path) -> dict[str, str]:
    return {
        str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in repo.rglob("*") if p.is_file()
    }


@pytest.fixture
def scope_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "clone", "--shared", "--no-checkout", "--quiet", str(SOURCE), str(repo)],
        check=True,
        capture_output=True,
    )
    git(repo, "checkout", "--detach", "-q", ACCEPTANCE)
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / GUARD).write_bytes((SOURCE / GUARD).read_bytes())
    commit(repo)
    runner = tmp_path / "committed-scope.py"
    runner.write_bytes(subprocess.check_output(["git", "show", f"HEAD:{GUARD}"], cwd=repo))
    return repo, runner


def invoke(repo: Path, runner: Path, *, ref: str = ACCEPTANCE, environment: dict[str, str] | None = None):
    return subprocess.run(
        [sys.executable, "-I", "-B", str(runner), "--repo", str(repo), "--acceptance-ref", ref],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, **(environment or {}), "PYTHONDONTWRITEBYTECODE": "1"},
    )


def test_actual_bounded_acceptance_allows_only_read_only_contract_scope(scope_repo) -> None:
    repo, runner = scope_repo
    before = snapshot(repo)
    result = invoke(repo, runner)
    assert result.returncode == 0, result.stdout + result.stderr
    body = json.loads(result.stdout)
    assert body["status"] == "M10_CONTRACT_SCOPE_OK"
    assert body["stop_codes"] == []
    assert body["acceptance_ref"] == ACCEPTANCE
    assert body["head"] == git(repo, "rev-parse", "HEAD")
    assert snapshot(repo) == before


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("wrong_acceptance", "M10_DESIGN_NOT_ACCEPTED"),
        ("dirty_owned", "M10_OWNED_PATH_DIRTY"),
        ("ignored_owned", "M10_OWNED_PATH_DIRTY"),
        ("skip_worktree", "M10_OWNED_PATH_DIRTY"),
        ("assume_unchanged", "M10_OWNED_PATH_DIRTY"),
        ("staged_dependency", "M10_OWNED_PATH_DIRTY"),
        ("committed_dependency", "M10_SCHEMA_FREEZE_FAILED"),
        ("outside_scope", "M10_SCOPE_EXPANSION_REQUIRED"),
        ("migration", "M10_MIGRATION_BOUNDARY_INVALID"),
        ("authority_import", "M10_SCOPE_EXPANSION_REQUIRED"),
        ("top_level_effect", "M10_SCOPE_EXPANSION_REQUIRED"),
        ("bootstrap_canary", "M10_SCHEMA_FREEZE_FAILED"),
    ],
)
def test_refused_scope_is_read_only_and_does_not_execute_candidate_modules(scope_repo, case: str, code: str) -> None:
    repo, runner = scope_repo
    marker = repo / "must-not-exist"
    ref = ACCEPTANCE
    if case == "wrong_acceptance":
        ref = CANDIDATE
    elif case in {"dirty_owned", "skip_worktree", "assume_unchanged"}:
        if case != "dirty_owned":
            git(repo, "update-index", "--skip-worktree" if case == "skip_worktree" else "--assume-unchanged", GUARD)
        with (repo / GUARD).open("a") as stream:
            stream.write("\n# dirty owned guard\n")
    elif case == "ignored_owned":
        with (repo / ".git/info/exclude").open("a") as stream:
            stream.write("\nr2/contracts/quality.py\n")
        (repo / "r2/contracts/quality.py").write_text("class Quality: pass\n")
    elif case == "staged_dependency":
        path = "r2/artifact_identity.py"
        with (repo / path).open("a") as stream:
            stream.write("\n# changed pure dependency\n")
        git(repo, "add", path)
    elif case == "committed_dependency":
        with (repo / "r2/artifact_identity.py").open("a") as stream:
            stream.write("\n# changed committed source pin\n")
        commit(repo)
    elif case == "bootstrap_canary":
        path = repo / "scripts/r2/verify_m10_bootstrap.py"
        path.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n" + path.read_text())
    else:
        path, content = {
            "outside_scope": ("outside-m10.txt", "outside"),
            "migration": ("alembic/versions/m10_stray.py", 'revision="m10_stray"\ndown_revision="918c4a0e0001"\n'),
            "authority_import": ("r2/contracts/quality.py", "from r2.production import authority\n"),
            "top_level_effect": (
                "r2/contracts/quality.py",
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
            ),
        }[case]
        (repo / path).write_text(content)
        commit(repo)
    before = snapshot(repo)
    result = invoke(repo, runner, ref=ref)
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["stop_codes"] == [code]
    assert not marker.exists()
    assert snapshot(repo) == before


def test_inherited_git_environment_cannot_redirect_scope_evidence(scope_repo, tmp_path: Path) -> None:
    repo, runner = scope_repo
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    git(unrelated, "init", "-q")
    before = snapshot(repo)
    result = invoke(repo, runner, environment={"GIT_DIR": str(unrelated / ".git"), "GIT_WORK_TREE": str(unrelated)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "M10_CONTRACT_SCOPE_OK"
    assert snapshot(repo) == before


def test_unrelated_history_cannot_reuse_a_valid_acceptance_object(scope_repo) -> None:
    repo, runner = scope_repo
    git(repo, "checkout", "--detach", "-q", CANDIDATE)
    (repo / GUARD).write_bytes(runner.read_bytes())
    commit(repo)
    before = snapshot(repo)
    result = invoke(repo, runner)
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["stop_codes"] == ["M10_SCHEMA_FREEZE_FAILED"]
    assert snapshot(repo) == before


def test_repository_without_accepted_objects_is_refused_read_only(scope_repo, tmp_path: Path) -> None:
    _, runner = scope_repo
    repo = tmp_path / "without-acceptance"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / GUARD).parent.mkdir(parents=True)
    (repo / GUARD).write_bytes(runner.read_bytes())
    commit(repo)
    before = snapshot(repo)
    result = invoke(repo, runner)
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["stop_codes"] == ["M10_REQUIRED_EVIDENCE_MISSING"]
    assert snapshot(repo) == before
