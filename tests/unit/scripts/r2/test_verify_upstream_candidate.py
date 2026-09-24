from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from r2.host_hardening.compatibility import CompatibilityError, verify_upstream_candidate

REQUIRED_GATES = (
    "migration",
    "static",
    "type",
    "imports",
    "dependencies",
    "i18n",
    "frontend",
    "website",
    "h1_h8",
    "golden_a",
    "golden_b",
    "browser",
)
EVIDENCE_PATH = "docs/r2/evidence/gate-evidence.txt"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _commit(repo: Path, name: str, content: str) -> str:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(content)
    _git(repo, "add", name)
    _git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


def _report(tmp_path: Path) -> tuple[dict, Path, Path]:
    host = tmp_path / "host"
    upstream = tmp_path / "upstream"
    host.mkdir()
    upstream.mkdir()
    for repo in (host, upstream):
        _git(repo, "init", "-q")
    rollback_sha = _commit(host, "app.txt", "host")
    host_sha = _commit(host, "candidate.txt", "candidate code")
    evidence_sha = _commit(host, EVIDENCE_PATH, "verified evidence")
    evidence_digest = "sha256:" + hashlib.sha256(b"verified evidence").hexdigest()
    old_sha = _commit(upstream, "uv.lock", "old-lock")
    new_sha = _commit(upstream, "uv.lock", "new-lock")
    _git(upstream, "remote", "add", "origin", "https://example.invalid/upstream.git")
    report = {
        "schema_version": 1,
        "host_sha": host_sha,
        "evidence_sha": evidence_sha,
        "upstream_url": "https://example.invalid/upstream.git",
        "old_sha": old_sha,
        "new_sha": new_sha,
        "merge_base_sha": old_sha,
        "source_tree_sha": _git(upstream, "rev-parse", f"{new_sha}^{{tree}}"),
        "integration_method": "MERGE",
        "dependency_files": [{"path": "uv.lock", "sha256": "sha256:" + hashlib.sha256(b"new-lock").hexdigest()}],
        "change_inventory": [
            {
                "commit_sha": new_sha,
                "disposition": "ADAPTED",
                "evidence_path": EVIDENCE_PATH,
                "evidence_digest": evidence_digest,
            }
        ],
        "rollback_target_sha": rollback_sha,
        "gates": {
            gate: {
                "status": "PASS",
                "evidence_sha": host_sha,
                "evidence_path": EVIDENCE_PATH,
                "evidence_digest": evidence_digest,
                "required_skips": 0,
            }
            for gate in REQUIRED_GATES
        },
    }
    return report, host, upstream


def test_complete_pinned_candidate_is_compatible(tmp_path: Path) -> None:
    report, host, upstream = _report(tmp_path)
    assert verify_upstream_candidate(report, host_repo=host, upstream_repo=upstream) == "COMPATIBLE"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda r: r.pop("source_tree_sha"), "source_tree_sha"),
        (lambda r: r.pop("dependency_files"), "dependency_files"),
        (lambda r: r["change_inventory"].clear(), "change_inventory"),
        (lambda r: r["change_inventory"][0].pop("disposition"), "disposition"),
        (lambda r: r["gates"]["migration"].update(status="FAIL"), "migration"),
        (lambda r: r["gates"]["golden_b"].update(required_skips=1), "golden_b"),
        (lambda r: r.pop("rollback_target_sha"), "rollback_target_sha"),
        (lambda r: r.update(evidence_sha="0" * 40), "evidence_sha"),
    ],
)
def test_incomplete_or_failed_evidence_is_incompatible(
    tmp_path: Path, change: Callable[[dict[str, Any]], object], reason: str
) -> None:
    report, host, upstream = _report(tmp_path)
    change(report)
    with pytest.raises(CompatibilityError, match=reason):
        verify_upstream_candidate(report, host_repo=host, upstream_repo=upstream)


def test_uninventoried_upstream_commit_is_rejected(tmp_path: Path) -> None:
    report, host, upstream = _report(tmp_path)
    report["new_sha"] = _commit(upstream, "extra.txt", "extra")
    report["source_tree_sha"] = _git(upstream, "rev-parse", f"{report['new_sha']}^{{tree}}")
    with pytest.raises(CompatibilityError, match="change_inventory"):
        verify_upstream_candidate(report, host_repo=host, upstream_repo=upstream)


def test_diverged_old_upstream_pin_is_rejected(tmp_path: Path) -> None:
    report, host, upstream = _report(tmp_path)
    original_old_sha = report["old_sha"]
    _git(upstream, "checkout", "-q", original_old_sha)
    report["old_sha"] = _commit(upstream, "other.txt", "diverged")
    with pytest.raises(CompatibilityError, match=r"old_sha.*merge_base_sha"):
        verify_upstream_candidate(report, host_repo=host, upstream_repo=upstream)


def test_dirty_host_is_rejected(tmp_path: Path) -> None:
    report, host, upstream = _report(tmp_path)
    (host / "untracked.txt").write_text("dirty")
    with pytest.raises(CompatibilityError, match="dirty"):
        verify_upstream_candidate(report, host_repo=host, upstream_repo=upstream)


def test_code_change_after_candidate_sha_is_rejected(tmp_path: Path) -> None:
    report, host, upstream = _report(tmp_path)
    report["evidence_sha"] = _commit(host, "app.txt", "new code after tested candidate")
    with pytest.raises(CompatibilityError, match="non-evidence"):
        verify_upstream_candidate(report, host_repo=host, upstream_repo=upstream)


def test_code_rename_into_evidence_path_is_rejected(tmp_path: Path) -> None:
    report, host, upstream = _report(tmp_path)
    _git(host, "checkout", "-q", report["host_sha"])
    (host / EVIDENCE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (host / "candidate.txt").rename(host / EVIDENCE_PATH)
    _git(host, "add", "-A")
    _git(host, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "rename code")
    report["evidence_sha"] = _git(host, "rev-parse", "HEAD")
    renamed_digest = "sha256:" + hashlib.sha256(b"candidate code").hexdigest()
    report["change_inventory"][0]["evidence_digest"] = renamed_digest
    for gate in report["gates"].values():
        gate["evidence_digest"] = renamed_digest
    with pytest.raises(CompatibilityError, match="non-evidence"):
        verify_upstream_candidate(report, host_repo=host, upstream_repo=upstream)


def test_report_cannot_relabel_runtime_code_as_evidence(tmp_path: Path) -> None:
    report, host, upstream = _report(tmp_path)
    report["evidence_sha"] = _commit(host, "candidate.txt", "untested code")
    code_digest = "sha256:" + hashlib.sha256(b"untested code").hexdigest()
    report["change_inventory"][0].update(evidence_path="candidate.txt", evidence_digest=code_digest)
    with pytest.raises(CompatibilityError, match="evidence_path"):
        verify_upstream_candidate(report, host_repo=host, upstream_repo=upstream)


def test_rollback_target_must_precede_candidate(tmp_path: Path) -> None:
    report, host, upstream = _report(tmp_path)
    report["rollback_target_sha"] = report["host_sha"]
    with pytest.raises(CompatibilityError, match="rollback_target_sha"):
        verify_upstream_candidate(report, host_repo=host, upstream_repo=upstream)


def test_dependency_checksum_must_match_pinned_source(tmp_path: Path) -> None:
    report, host, upstream = _report(tmp_path)
    report["dependency_files"][0]["sha256"] = "sha256:" + "0" * 64
    with pytest.raises(CompatibilityError, match="dependency_files"):
        verify_upstream_candidate(report, host_repo=host, upstream_repo=upstream)


def test_gate_evidence_digest_must_match_committed_artifact(tmp_path: Path) -> None:
    report, host, upstream = _report(tmp_path)
    report["gates"]["migration"]["evidence_digest"] = "sha256:" + "0" * 64
    with pytest.raises(CompatibilityError, match=r"migration.*evidence_digest"):
        verify_upstream_candidate(report, host_repo=host, upstream_repo=upstream)


def test_change_disposition_evidence_must_match_committed_artifact(tmp_path: Path) -> None:
    report, host, upstream = _report(tmp_path)
    report["change_inventory"][0]["evidence_digest"] = "sha256:" + "0" * 64
    with pytest.raises(CompatibilityError, match=r"change_inventory.*evidence_digest"):
        verify_upstream_candidate(report, host_repo=host, upstream_repo=upstream)


def test_upstream_cli_emits_machine_readable_verdict(tmp_path: Path) -> None:
    report, host, upstream = _report(tmp_path)
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report))
    script = Path(__file__).resolve().parents[4] / "scripts" / "r2" / "verify_upstream_candidate.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--report",
            str(report_path),
            "--host-repo",
            str(host),
            "--upstream-repo",
            str(upstream),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[4])},
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["verdict"] == "COMPATIBLE"
