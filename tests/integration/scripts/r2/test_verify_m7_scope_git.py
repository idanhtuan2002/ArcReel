"""verify_m7_scope checks that drive real git repositories (the pinned-base read and the live repo)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.r2.verify_m7_scope import BASELINE_RELPATH, M6_HANDOFF_RELPATH, _m6_handoff_status, verify_m7_scope


def test_m6_handoff_is_read_from_pinned_base_in_nested_worktree(tmp_path: Path) -> None:
    repo = tmp_path / ".worktrees" / "m7"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    handoff = repo / M6_HANDOFF_RELPATH
    handoff.parent.mkdir(parents=True)
    handoff.write_text(json.dumps({"status": "ACCEPTED"}))
    subprocess.run(["git", "-C", str(repo), "add", M6_HANDOFF_RELPATH], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "handoff",
        ],
        check=True,
    )
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert _m6_handoff_status(repo, sha) == "ACCEPTED"


def test_verify_m7_scope_passes_against_the_real_baseline_and_repo() -> None:
    repo = Path(__file__).resolve().parents[4]
    baseline = json.loads((repo / BASELINE_RELPATH).read_text())
    assert verify_m7_scope(repo, baseline) == []
