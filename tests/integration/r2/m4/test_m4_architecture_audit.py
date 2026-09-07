"""D12 — the repository-scope audit sensor reports zero blocking violations."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[4]
_SCRIPT = _ROOT / "scripts" / "r2" / "audit_m4_architecture.py"
_M4_STARTING_HEAD = "863ab4993b3dce725fb5f12b5d2f2a74a79031a3"


@pytest.fixture
def report(tmp_path: Path) -> dict[str, object]:
    out = tmp_path / "audit.json"
    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--starting-head",
            _M4_STARTING_HEAD,
            "--output",
            str(out),
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def test_no_blocking_architecture_violations(report: dict[str, object]) -> None:
    assert report["blocking_violation_count"] == 0


def test_no_unapproved_host_runtime_change(report: dict[str, object]) -> None:
    assert report["unapproved_host_runtime_changes"] == []


def test_no_unapproved_db_migration(report: dict[str, object]) -> None:
    assert report["unapproved_db_migrations"] == []


def test_no_m5_scope_leakage(report: dict[str, object]) -> None:
    assert report["m5_scope_leakage"] == []


def test_report_pins_the_starting_head(report: dict[str, object]) -> None:
    assert report["starting_head"] == _M4_STARTING_HEAD
    assert report["final_head"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
