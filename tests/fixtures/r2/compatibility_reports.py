"""Git-backed fixtures for the offline upstream-compatibility and provider-evidence verifiers.

The upstream fixture builds two real repositories:

- **upstream:** ``uv.lock`` goes from ``old-lock`` to ``new-lock`` in one commit.
- **host:** starts from the same ``old-lock`` (the rollback target). It then carries that
  change in a candidate commit whose message names the upstream commit
  (``Upstream: <sha>``), so the change is ADAPTED by marker and UNCHANGED by patch id.
- **evidence commit:** on top of the candidate, it adds one manifest plus a runner-style
  log per required gate.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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
TEST_GATES = frozenset({"i18n", "frontend", "website", "h1_h8", "golden_a", "golden_b", "browser"})
EVIDENCE_PATH = "docs/r2/evidence/gate-evidence.json"
LOG_DIR = "docs/r2/evidence/gate-logs"
PROVIDER_FIXTURE = Path(__file__).resolve().parent / "provider_capabilities" / "unqualified.json"
NOW = datetime(2026, 9, 24, tzinfo=UTC)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def commit(repo: Path, files: dict[str, str], message: str) -> str:
    for name, content in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(content, encoding="utf-8")
        git(repo, "add", name)
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def gate_log(gate: str, *, exit_code: int = 0, summary: str | None = None) -> str:
    """A log as the gate runner writes it: a ``#`` header, then the command output."""
    if summary is None:
        summary = "12 passed in 1.00s" if gate in TEST_GATES else "All checks passed!"
    return f"# command: verify {gate}\n# exit_code: {exit_code}\n{summary}\n"


def evidence_files(host_sha: str, changes: dict[str, str], logs: dict[str, str]) -> tuple[dict[str, str], str]:
    """The evidence commit's files and the manifest digest."""
    results = {}
    files = {}
    for gate in REQUIRED_GATES:
        log_path = f"{LOG_DIR}/{gate}.log"
        files[log_path] = logs[gate]
        results[gate] = {
            "status": "PASS",
            "required_skips": 0,
            "exit_code": 0,
            "command": f"verify {gate}",
            "log_path": log_path,
            "log_digest": digest(logs[gate]),
        }
    manifest = {"schema_version": 1, "target_sha": host_sha, "changes": changes, "results": results}
    manifest_text = json.dumps(manifest, sort_keys=True)
    files[EVIDENCE_PATH] = manifest_text
    return files, digest(manifest_text)


def upstream_report(
    tmp_path: Path, *, disposition: str = "ADAPTED", name_upstream: bool = True
) -> tuple[dict[str, Any], Path, Path]:
    host = tmp_path / "host"
    upstream = tmp_path / "upstream"
    host.mkdir()
    upstream.mkdir()
    for repo in (host, upstream):
        git(repo, "init", "-q")
    old_sha = commit(upstream, {"uv.lock": "old-lock\n"}, "lock")
    new_sha = commit(upstream, {"uv.lock": "new-lock\n"}, "bump lock")
    git(upstream, "remote", "add", "origin", "https://example.invalid/upstream.git")
    rollback_sha = commit(host, {"uv.lock": "old-lock\n", "app.txt": "host\n"}, "host")
    message = f"fix: take the lock bump\n\nUpstream: {new_sha}\n" if name_upstream else "fix: take the lock bump"
    host_sha = commit(host, {"uv.lock": "new-lock\n"}, message)
    logs = {gate: gate_log(gate) for gate in REQUIRED_GATES}
    files, manifest_digest = evidence_files(host_sha, {new_sha: disposition}, logs)
    evidence_sha = commit(host, files, "evidence")
    report = {
        "schema_version": 1,
        "host_sha": host_sha,
        "evidence_sha": evidence_sha,
        "upstream_url": "https://example.invalid/upstream.git",
        "old_sha": old_sha,
        "new_sha": new_sha,
        "merge_base_sha": old_sha,
        "source_tree_sha": git(upstream, "rev-parse", f"{new_sha}^{{tree}}"),
        "integration_method": "CHERRY_PICK",
        "dependency_files": [{"path": "uv.lock", "sha256": digest("new-lock\n")}],
        "change_inventory": [
            {
                "commit_sha": new_sha,
                "disposition": disposition,
                "evidence_path": EVIDENCE_PATH,
                "evidence_digest": manifest_digest,
            }
        ],
        "rollback_target_sha": rollback_sha,
        "gates": {
            gate: {
                "status": "PASS",
                "evidence_sha": host_sha,
                "evidence_path": EVIDENCE_PATH,
                "evidence_digest": manifest_digest,
                "required_skips": 0,
            }
            for gate in REQUIRED_GATES
        },
    }
    return report, host, upstream


def recommit_evidence(
    report: dict[str, Any],
    host: Path,
    *,
    changes: dict[str, str] | None = None,
    logs: dict[str, str] | None = None,
    extra: dict[str, str] | None = None,
) -> None:
    """Commit replacement evidence on the host and point the report at it."""
    host_sha = report["host_sha"]
    changes = (
        changes if changes is not None else {i["commit_sha"]: i["disposition"] for i in report["change_inventory"]}
    )
    logs = logs if logs is not None else {gate: gate_log(gate) for gate in REQUIRED_GATES}
    files, manifest_digest = evidence_files(host_sha, changes, logs)
    files.update(extra or {})
    report["evidence_sha"] = commit(host, files, "evidence again")
    for item in report["change_inventory"]:
        item["evidence_digest"] = manifest_digest
    for gate in report["gates"].values():
        gate["evidence_digest"] = manifest_digest


def provider_evidence(entry: dict[str, Any], **overrides: Any) -> str:
    evidence = {
        "schema_version": 1,
        "profile_ref": entry["ref"],
        "profile_entry_digest": entry["entry_digest"],
        "evidence_kind": "LOCAL_FIXTURE",
        "result": "PASS",
        "required_skips": 0,
    }
    evidence.update(overrides)
    return json.dumps(evidence, sort_keys=True)


def provider_report(tmp_path: Path, **evidence_overrides: Any) -> tuple[dict[str, Any], Path, Path]:
    registry = tmp_path / "registry.json"
    registry.write_text(PROVIDER_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    entry = json.loads(registry.read_text(encoding="utf-8"))["profiles"][0]
    evidence_repo = tmp_path / "evidence"
    evidence_repo.mkdir()
    git(evidence_repo, "init", "-q")
    text = provider_evidence(entry, **evidence_overrides)
    evidence_sha = commit(evidence_repo, {"provider-result.json": text}, "evidence")
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
        "evidence_digest": digest(text),
        "recorded_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "required_skips": 0,
    }
    return report, registry, evidence_repo
