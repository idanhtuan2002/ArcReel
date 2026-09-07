import subprocess
from pathlib import Path

import pytest

from scripts.r2.verify_baseline import BaselineError, parse_baseline, verify_repository


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        text=True,
    ).strip()


def _init_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "R2 Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "r2-test@localhost"], check=True)
    (repo / "a.txt").write_text("baseline\n")
    subprocess.run(["git", "-C", str(repo), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "baseline"], check=True)
    baseline = _git(repo, "rev-parse", "HEAD")
    subprocess.run(["git", "-C", str(repo), "tag", "v0.29.0"], check=True)
    subprocess.run(["git", "-C", str(repo), "switch", "-q", "-c", "r2/main"], check=True)
    (repo / "r2.txt").write_text("r2\n")
    subprocess.run(["git", "-C", str(repo), "add", "r2.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "r2"], check=True)
    return repo, baseline


def test_parse_baseline_rejects_missing_key(tmp_path):
    p = tmp_path / "HOST_BASELINE.txt"
    p.write_text("tag=v0.29.0\n")
    with pytest.raises(BaselineError, match="missing baseline keys"):
        parse_baseline(p)


def test_descendant_head_is_valid(tmp_path):
    repo, baseline = _init_repo(tmp_path)
    cfg = {
        "upstream": "https://github.com/ArcReel/ArcReel.git",
        "tag": "v0.29.0",
        "sha": baseline,
        "branch": "r2/main",
    }
    verify_repository(repo, cfg, check_remote=False)


def test_wrong_pinned_sha_is_rejected(tmp_path):
    repo, _baseline = _init_repo(tmp_path)
    cfg = {
        "upstream": "https://github.com/ArcReel/ArcReel.git",
        "tag": "v0.29.0",
        "sha": "0" * 40,
        "branch": "r2/main",
    }
    with pytest.raises(BaselineError):
        verify_repository(repo, cfg, check_remote=False)


def test_wrong_branch_is_rejected(tmp_path):
    repo, baseline = _init_repo(tmp_path)
    cfg = {
        "upstream": "https://github.com/ArcReel/ArcReel.git",
        "tag": "v0.29.0",
        "sha": baseline,
        "branch": "wrong",
    }
    with pytest.raises(BaselineError, match="branch"):
        verify_repository(repo, cfg, check_remote=False)
