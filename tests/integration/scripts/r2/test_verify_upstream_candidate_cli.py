from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.fixtures.r2.compatibility_reports import upstream_report

REPO_ROOT = Path(__file__).resolve().parents[4]


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "r2" / "verify_upstream_candidate.py"), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )


def test_a_compatible_report_exits_zero_with_a_machine_readable_verdict(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path)
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report))
    result = _cli("--report", str(report_path), "--host-repo", str(host), "--upstream-repo", str(upstream))
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"verdict": "COMPATIBLE"}


def test_an_incompatible_report_exits_two_with_its_reason(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path, disposition="DEFERRED")
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report))
    result = _cli("--report", str(report_path), "--host-repo", str(host), "--upstream-repo", str(upstream))
    assert result.returncode == 2
    verdict = json.loads(result.stdout)
    assert verdict["verdict"] == "INCOMPATIBLE"
    assert "DEFERRED" in verdict["reason"]
