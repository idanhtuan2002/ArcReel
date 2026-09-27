from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.fixtures.r2.compatibility_reports import NOW, provider_report

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_the_cli_refuses_production_for_offline_evidence(tmp_path: Path) -> None:
    report, registry, evidence_repo = provider_report(tmp_path)
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report))
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "r2" / "verify_provider_qualification.py"),
            "--report",
            str(report_path),
            "--registry",
            str(registry),
            "--evidence-repo",
            str(evidence_repo),
            "--now",
            NOW.isoformat(),
            "--enable-production",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["verdict"] == "REJECTED"
