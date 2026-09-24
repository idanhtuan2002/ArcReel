from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from r2.host_hardening.compatibility import CompatibilityError, verify_provider_qualification
from r2.host_hardening.provider_capabilities import compute_entry_digest

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "r2" / "provider_capabilities" / "unqualified.json"
NOW = datetime(2026, 9, 24, tzinfo=UTC)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _report(tmp_path: Path) -> tuple[dict, Path, Path]:
    registry = tmp_path / "registry.json"
    registry.write_text(FIXTURE.read_text())
    entry = json.loads(registry.read_text())["profiles"][0]
    evidence_repo = tmp_path / "evidence"
    evidence_repo.mkdir()
    _git(evidence_repo, "init", "-q")
    (evidence_repo / "provider-result.json").write_text('{"kind":"offline-contract","passed":true}')
    _git(evidence_repo, "add", "provider-result.json")
    _git(evidence_repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "evidence")
    evidence_sha = _git(evidence_repo, "rev-parse", "HEAD")
    report = {
        "schema_version": 1,
        "profile_ref": entry["ref"],
        "profile_entry_digest": entry["entry_digest"],
        "provider_id": entry["provider_id"],
        "api_version": entry["api_version"],
        "adapter_version": entry["adapter_version"],
        "status": "OFFLINE_VERIFIED",
        "evidence_kind": "LOCAL_FIXTURE",
        "evidence_sha": evidence_sha,
        "evidence_path": "provider-result.json",
        "evidence_digest": "sha256:"
        + hashlib.sha256((evidence_repo / "provider-result.json").read_bytes()).hexdigest(),
        "recorded_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "required_skips": 0,
    }
    return report, registry, evidence_repo


def test_offline_fixture_can_only_prove_offline_status(tmp_path: Path) -> None:
    report, registry, evidence_repo = _report(tmp_path)
    assert (
        verify_provider_qualification(report, registry_path=registry, evidence_repo=evidence_repo, now=NOW)
        == "OFFLINE_VERIFIED"
    )
    with pytest.raises(CompatibilityError, match="QUALIFIED"):
        verify_provider_qualification(
            report, registry_path=registry, evidence_repo=evidence_repo, now=NOW, enable_production=True
        )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("profile_entry_digest", "sha256:" + "0" * 64, "profile_entry_digest"),
        ("api_version", "wrong-version", "api_version"),
        ("evidence_digest", "sha256:" + "0" * 64, "evidence_digest"),
        ("required_skips", 1, "required_skips"),
        ("status", "QUALIFIED", "LOCAL_FIXTURE"),
        ("expires_at", (NOW - timedelta(seconds=1)).isoformat(), "expired"),
    ],
)
def test_mismatched_or_mock_only_provider_report_is_rejected(
    tmp_path: Path, field: str, value: object, reason: str
) -> None:
    report, registry, evidence_repo = _report(tmp_path)
    report[field] = value
    with pytest.raises(CompatibilityError, match=reason):
        verify_provider_qualification(report, registry_path=registry, evidence_repo=evidence_repo, now=NOW)


def test_dirty_provider_evidence_repo_is_rejected(tmp_path: Path) -> None:
    report, registry, evidence_repo = _report(tmp_path)
    (evidence_repo / "untracked.txt").write_text("dirty")
    with pytest.raises(CompatibilityError, match="dirty"):
        verify_provider_qualification(report, registry_path=registry, evidence_repo=evidence_repo, now=NOW)


def test_expired_registry_entry_is_rejected_even_when_report_is_fresh(tmp_path: Path) -> None:
    report, registry, evidence_repo = _report(tmp_path)
    document = json.loads(registry.read_text())
    entry = document["profiles"][0]
    entry["evidence_expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
    entry["entry_digest"] = compute_entry_digest(entry)
    registry.write_text(json.dumps(document))
    report["profile_entry_digest"] = entry["entry_digest"]
    with pytest.raises(CompatibilityError, match=r"registry.*expired"):
        verify_provider_qualification(report, registry_path=registry, evidence_repo=evidence_repo, now=NOW)


def test_future_recorded_provider_evidence_is_rejected(tmp_path: Path) -> None:
    report, registry, evidence_repo = _report(tmp_path)
    report["recorded_at"] = (NOW + timedelta(minutes=1)).isoformat()
    with pytest.raises(CompatibilityError, match="recorded_at"):
        verify_provider_qualification(report, registry_path=registry, evidence_repo=evidence_repo, now=NOW)


def test_provider_cli_refuses_production_for_offline_evidence(tmp_path: Path) -> None:
    report, registry, evidence_repo = _report(tmp_path)
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report))
    script = Path(__file__).resolve().parents[4] / "scripts" / "r2" / "verify_provider_qualification.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
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
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[4])},
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["verdict"] == "REJECTED"
