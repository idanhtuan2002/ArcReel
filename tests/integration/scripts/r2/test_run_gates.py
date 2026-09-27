from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from r2.host_hardening.compatibility import parse_gate_log
from scripts.r2 import run_gates
from tests.fixtures.r2.compatibility_reports import commit, git


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    commit(repo, {"app.txt": "code\n"}, "code")
    return repo


def test_the_runner_writes_logs_the_verifier_can_re_read(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    config = tmp_path / "gates.json"
    config.write_text(
        json.dumps(
            {
                "h1_h8": f"{sys.executable} -c \"print('7 passed in 0.10s')\"",
                "static": f'{sys.executable} -c "import sys; sys.exit(3)"',
            }
        )
    )
    monkeypatch.chdir(repo)

    exit_code = run_gates.main(["--config", str(config), "--out", "evidence/run-1"])

    manifest = json.loads((repo / "evidence/run-1/manifest.json").read_text())
    assert exit_code == 1
    assert manifest["target_sha"] == git(repo, "rev-parse", "HEAD")
    passing = parse_gate_log((repo / manifest["results"]["h1_h8"]["log_path"]).read_text())
    failing = parse_gate_log((repo / manifest["results"]["static"]["log_path"]).read_text())
    assert (passing["exit_code"], passing["passed"], manifest["results"]["h1_h8"]["status"]) == (0, 7, "PASS")
    assert (failing["exit_code"], manifest["results"]["static"]["status"]) == (3, "FAIL")


def test_the_runner_refuses_a_dirty_tree(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    (repo / "untracked.txt").write_text("dirty")
    config = tmp_path / "gates.json"
    config.write_text(json.dumps({"static": "true"}))
    monkeypatch.chdir(repo)

    assert run_gates.main(["--config", str(config), "--out", "evidence/run-1"]) == 2
    assert not (repo / "evidence").exists()
    assert subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
