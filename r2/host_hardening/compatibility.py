"""Offline, fail-closed M7-E compatibility checks over pinned Git and evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from functools import cache
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

from r2.host_hardening.provider_capabilities import ProviderCapabilityError, load_capability_profile

UPSTREAM_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "r2" / "schemas" / "m7-upstream-candidate.schema.json"
)
PROVIDER_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "r2" / "schemas" / "m7-provider-qualification.schema.json"
)

REQUIRED_GATES = frozenset(
    {
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
    }
)


class CompatibilityError(ValueError):
    """The report cannot establish compatibility at its exact evidence SHA."""


@cache
def _upstream_validator() -> Draft202012Validator:
    schema = json.loads(UPSTREAM_SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@cache
def _provider_validator() -> Draft202012Validator:
    schema = json.loads(PROVIDER_SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if result.returncode:
        raise CompatibilityError(f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def _git_bytes(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if result.returncode:
        raise CompatibilityError(f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def _exact_commit(repo: Path, sha: str, field: str) -> None:
    if _git(repo, "rev-parse", f"{sha}^{{commit}}") != sha:
        raise CompatibilityError(f"{field} is not an exact pinned commit")


def _committed_evidence_digest(repo: Path, sha: str, path: str, label: str) -> str:
    pure_path = PurePosixPath(path)
    if pure_path.is_absolute() or ".." in pure_path.parts or path.startswith(":"):
        raise CompatibilityError(f"{label} evidence_path is unsafe")
    return "sha256:" + hashlib.sha256(_git_bytes(repo, "show", f"{sha}:{path}")).hexdigest()


def verify_upstream_candidate(report: dict[str, Any], *, host_repo: Path, upstream_repo: Path) -> str:
    """Verify local source/checksum pins and all required evidence, without changing either repo.

    Source and evidence checksums pin committed bytes. This offline check does
    not assert that the artifacts were independently reviewed or a provider called.
    """
    errors = sorted(_upstream_validator().iter_errors(report), key=lambda error: str(error.path))
    if errors:
        error = errors[0]
        raise CompatibilityError(f"{list(error.path)}: {error.message}")

    host_sha = report["host_sha"]
    evidence_sha = report["evidence_sha"]
    if _git(host_repo, "status", "--porcelain=v1"):
        raise CompatibilityError("host worktree is dirty")
    if _git(host_repo, "rev-parse", "HEAD") != evidence_sha:
        raise CompatibilityError("evidence_sha does not equal current HEAD")
    _exact_commit(host_repo, host_sha, "host_sha")
    if host_sha == evidence_sha:
        raise CompatibilityError("evidence_sha must follow the candidate host_sha")
    evidence_ancestor = subprocess.run(
        ["git", "-C", str(host_repo), "merge-base", "--is-ancestor", host_sha, evidence_sha],
        capture_output=True,
    )
    if evidence_ancestor.returncode:
        raise CompatibilityError("host_sha is not an ancestor of evidence_sha")
    evidence_paths = {item["evidence_path"] for item in report["change_inventory"]}
    evidence_paths.update(gate["evidence_path"] for gate in report["gates"].values())
    changed_paths = set(
        _git(host_repo, "diff", "--no-renames", "--name-only", host_sha, evidence_sha, "--").splitlines()
    )
    if not changed_paths or not changed_paths <= evidence_paths:
        raise CompatibilityError(f"non-evidence changes after host_sha: {sorted(changed_paths - evidence_paths)}")
    if report["rollback_target_sha"] == host_sha:
        raise CompatibilityError("rollback_target_sha must precede host_sha")
    _exact_commit(host_repo, report["rollback_target_sha"], "rollback_target_sha")
    ancestor = subprocess.run(
        ["git", "-C", str(host_repo), "merge-base", "--is-ancestor", report["rollback_target_sha"], host_sha],
        capture_output=True,
    )
    if ancestor.returncode:
        raise CompatibilityError("rollback_target_sha is not an ancestor of host_sha")

    old_sha = report["old_sha"]
    new_sha = report["new_sha"]
    _exact_commit(upstream_repo, old_sha, "old_sha")
    _exact_commit(upstream_repo, new_sha, "new_sha")
    if _git(upstream_repo, "remote", "get-url", "origin") != report["upstream_url"]:
        raise CompatibilityError("upstream_url does not match origin")
    if _git(upstream_repo, "merge-base", old_sha, new_sha) != report["merge_base_sha"]:
        raise CompatibilityError("merge_base_sha does not match the pinned range")
    if old_sha != report["merge_base_sha"]:
        raise CompatibilityError("old_sha must equal merge_base_sha for a complete forward change inventory")
    if _git(upstream_repo, "rev-parse", f"{new_sha}^{{tree}}") != report["source_tree_sha"]:
        raise CompatibilityError("source_tree_sha checksum does not match new_sha")

    expected_commits = _git(upstream_repo, "rev-list", "--reverse", f"{old_sha}..{new_sha}").splitlines()
    inventoried_commits = [item["commit_sha"] for item in report["change_inventory"]]
    if inventoried_commits != expected_commits:
        raise CompatibilityError("change_inventory does not cover the exact ordered upstream range")
    for item in report["change_inventory"]:
        actual = _committed_evidence_digest(host_repo, evidence_sha, item["evidence_path"], "change_inventory")
        if actual != item["evidence_digest"]:
            raise CompatibilityError("change_inventory evidence_digest does not match committed artifact")

    dependency_paths: set[str] = set()
    for item in report["dependency_files"]:
        path = item["path"]
        pure_path = PurePosixPath(path)
        if pure_path.is_absolute() or ".." in pure_path.parts or path in dependency_paths:
            raise CompatibilityError("dependency_files contains an unsafe or duplicate path")
        dependency_paths.add(path)
        actual = "sha256:" + hashlib.sha256(_git_bytes(upstream_repo, "show", f"{new_sha}:{path}")).hexdigest()
        if actual != item["sha256"]:
            raise CompatibilityError(f"dependency_files checksum mismatch for {path!r}")

    gates = report["gates"]
    if set(gates) != set(REQUIRED_GATES):
        raise CompatibilityError(f"gates inventory mismatch: missing {sorted(REQUIRED_GATES - set(gates))}")
    for gate_name, gate in gates.items():
        if gate["status"] != "PASS" or gate["evidence_sha"] != host_sha or gate["required_skips"]:
            raise CompatibilityError(f"{gate_name} gate lacks fresh complete PASS evidence")
        actual = _committed_evidence_digest(host_repo, evidence_sha, gate["evidence_path"], gate_name)
        if actual != gate["evidence_digest"]:
            raise CompatibilityError(f"{gate_name} evidence_digest does not match committed artifact")
    return "COMPATIBLE"


def verify_provider_qualification(
    report: dict[str, Any],
    *,
    registry_path: Path,
    evidence_repo: Path,
    now: datetime,
    enable_production: bool = False,
) -> str:
    """Verify an exact profile against pinned, offline evidence.

    E1 can prove only local fixture results. Sandbox and paid-provider claims
    require an independently trusted attestation mechanism in the later M7-E
    operational packet; a self-described report cannot grant QUALIFIED status.
    """
    errors = sorted(_provider_validator().iter_errors(report), key=lambda error: str(error.path))
    if errors:
        error = errors[0]
        raise CompatibilityError(f"{list(error.path)}: {error.message}")
    if now.tzinfo is None or now.utcoffset() is None:
        raise CompatibilityError("now must be timezone aware")

    ref = report["profile_ref"]
    try:
        profile = load_capability_profile(ref, registry_path=registry_path)
    except ProviderCapabilityError as exc:
        raise CompatibilityError(f"profile_ref cannot resolve to a valid profile: {exc}") from exc
    raw_registry = json.loads(registry_path.read_text())
    entry = next(item for item in raw_registry["profiles"] if item["ref"] == ref)
    if entry["entry_digest"] != report["profile_entry_digest"]:
        raise CompatibilityError("profile_entry_digest does not match the exact registry entry")
    if entry["evidence_expires_at"] is not None:
        registry_expiry = datetime.fromisoformat(entry["evidence_expires_at"])
        if registry_expiry.tzinfo is None or registry_expiry.utcoffset() is None or registry_expiry <= now:
            raise CompatibilityError("registry capability evidence is expired")
    for field in ("provider_id", "api_version", "adapter_version"):
        if getattr(profile, field) != report[field]:
            raise CompatibilityError(f"{field} does not match the exact capability profile")

    recorded = datetime.fromisoformat(report["recorded_at"])
    expires = datetime.fromisoformat(report["expires_at"])
    if any(value.tzinfo is None or value.utcoffset() is None for value in (recorded, expires)):
        raise CompatibilityError("evidence timestamps must be timezone aware")
    if recorded > now:
        raise CompatibilityError("recorded_at is in the future")
    if expires <= now.astimezone(UTC) or expires <= recorded:
        raise CompatibilityError("provider evidence is expired or has an invalid expiry")
    if report["required_skips"]:
        raise CompatibilityError("required_skips must be zero")
    if _git(evidence_repo, "status", "--porcelain=v1"):
        raise CompatibilityError("provider evidence worktree is dirty")
    evidence_sha = report["evidence_sha"]
    if _git(evidence_repo, "rev-parse", "HEAD") != evidence_sha:
        raise CompatibilityError("evidence_sha does not match current HEAD")
    actual = _committed_evidence_digest(evidence_repo, evidence_sha, report["evidence_path"], "provider")
    if actual != report["evidence_digest"]:
        raise CompatibilityError("evidence_digest does not match the committed provider artifact")

    status = report["status"]
    if status in {"QUALIFIED", "SANDBOX_VERIFIED"}:
        raise CompatibilityError(
            f"{report['evidence_kind']} cannot establish {status} without trusted external attestation"
        )
    if status == "OFFLINE_VERIFIED" and report["evidence_kind"] != "LOCAL_FIXTURE":
        raise CompatibilityError("OFFLINE_VERIFIED requires LOCAL_FIXTURE evidence")
    if enable_production:
        raise CompatibilityError("production route requires QUALIFIED exact-version evidence")
    return status
