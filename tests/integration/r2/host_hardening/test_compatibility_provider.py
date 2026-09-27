"""verify_provider_qualification over a real pinned evidence repository."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from r2.host_hardening.compatibility import CompatibilityError, verify_provider_qualification
from r2.host_hardening.provider_capabilities import compute_entry_digest
from tests.fixtures.r2.compatibility_reports import NOW, provider_report


def _verify(report: dict, registry: Path, evidence_repo: Path, **kwargs) -> str:
    return verify_provider_qualification(report, registry_path=registry, evidence_repo=evidence_repo, now=NOW, **kwargs)


def test_offline_fixture_evidence_proves_only_offline_status(tmp_path: Path) -> None:
    report, registry, evidence_repo = provider_report(tmp_path)
    assert _verify(report, registry, evidence_repo) == "OFFLINE_VERIFIED"
    with pytest.raises(CompatibilityError, match="QUALIFIED"):
        _verify(report, registry, evidence_repo, enable_production=True)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("profile_entry_digest", "sha256:" + "0" * 64, "profile_entry_digest"),
        ("api_version", "wrong-version", "api_version"),
        ("evidence_digest", "sha256:" + "0" * 64, "evidence_digest"),
        ("required_skips", 1, "required_skips"),
        ("status", "QUALIFIED", "LOCAL_FIXTURE"),
        ("expires_at", (NOW - timedelta(seconds=1)).isoformat(), "expired"),
        ("recorded_at", (NOW + timedelta(minutes=1)).isoformat(), "recorded_at"),
    ],
)
def test_a_mismatched_or_mock_only_report_is_rejected(tmp_path: Path, field: str, value: object, reason: str) -> None:
    report, registry, evidence_repo = provider_report(tmp_path)
    report[field] = value
    with pytest.raises(CompatibilityError, match=reason):
        _verify(report, registry, evidence_repo)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"result": "FAIL"}, "passing run"),
        ({"required_skips": 2}, "passing run"),
        ({"profile_ref": "other@host-video-v1"}, "profile_ref"),
        ({"evidence_kind": "SANDBOX_CALL"}, "evidence_kind"),
        ({"schema_version": 2}, "schema_version"),
    ],
)
def test_the_committed_evidence_content_must_record_this_passing_run(
    tmp_path: Path, overrides: dict, reason: str
) -> None:
    """Pinned bytes are not enough: evidence that records a failure or another profile is refused."""
    report, registry, evidence_repo = provider_report(tmp_path, **overrides)
    with pytest.raises(CompatibilityError, match=reason):
        _verify(report, registry, evidence_repo)


def test_a_dirty_evidence_repo_is_rejected(tmp_path: Path) -> None:
    report, registry, evidence_repo = provider_report(tmp_path)
    (evidence_repo / "untracked.txt").write_text("dirty")
    with pytest.raises(CompatibilityError, match="dirty"):
        _verify(report, registry, evidence_repo)


def test_an_expired_registry_entry_is_rejected_even_when_the_report_is_fresh(tmp_path: Path) -> None:
    report, registry, evidence_repo = provider_report(tmp_path)
    document = json.loads(registry.read_text())
    entry = document["profiles"][0]
    entry["evidence_expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
    entry["entry_digest"] = compute_entry_digest(entry)
    registry.write_text(json.dumps(document))
    report["profile_entry_digest"] = entry["entry_digest"]
    with pytest.raises(CompatibilityError, match=r"registry.*expired"):
        _verify(report, registry, evidence_repo)
