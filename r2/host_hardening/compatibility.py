"""Offline, fail-closed upstream-compatibility and provider-evidence checks over pinned Git evidence."""

from __future__ import annotations

import hashlib
import json
import re
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


_UPSTREAM_MARKER_RE = re.compile(r"^Upstream:\s*([0-9a-f]{7,40})\s*$", re.MULTILINE)
_CHERRY_PICK_MARKER_RE = re.compile(r"\(cherry picked from commit ([0-9a-f]{40})\)")


def _stable_patch_id(repo: Path, sha: str) -> str | None:
    """``git patch-id --stable`` of one commit; ``None`` for a commit with no diff (e.g. a merge)."""
    diff = _git_bytes(repo, "show", "--no-color", "--format=", sha)
    if not diff.strip():
        return None
    result = subprocess.run(["git", "-C", str(repo), "patch-id", "--stable"], input=diff, capture_output=True)
    if result.returncode:
        raise CompatibilityError(f"git patch-id failed for {sha}")
    output = result.stdout.decode().split()
    return output[0] if output else None


def _host_integration_index(repo: Path, rollback_sha: str, host_sha: str) -> tuple[set[str], set[str]]:
    """Patch ids and upstream markers of the host commits in ``rollback_sha..host_sha``."""
    patch_ids: set[str] = set()
    markers: set[str] = set()
    for sha in _git(repo, "rev-list", f"{rollback_sha}..{host_sha}").splitlines():
        patch_id = _stable_patch_id(repo, sha)
        if patch_id is not None:
            patch_ids.add(patch_id)
        message = _git(repo, "log", "-1", "--format=%B", sha)
        markers.update(_CHERRY_PICK_MARKER_RE.findall(message))
        markers.update(_UPSTREAM_MARKER_RE.findall(message))
    return patch_ids, markers


def _marked(commit_sha: str, markers: set[str]) -> bool:
    return any(commit_sha.startswith(marker) for marker in markers)


def _verify_integration(report: dict[str, Any], *, host_repo: Path, upstream_repo: Path) -> None:
    """Prove that each disposition is what the host range actually contains.

    - ``MERGE``: ``new_sha`` is in the host history, so every inventoried commit is integrated;
      ``DEFERRED`` and ``REJECTED`` are therefore impossible.
    - ``CHERRY_PICK`` / ``REBASE`` / ``PATCH``: an ``UNCHANGED`` commit has a host commit in
      ``rollback_target_sha..host_sha`` with the same stable patch id; an ``ADAPTED`` commit has a
      host commit whose message names it (``(cherry picked from commit <sha>)`` or
      ``Upstream: <sha>``); a ``DEFERRED`` or ``REJECTED`` commit has neither.

    Equal stable patch ids are a content-equivalence observation (git-patch-id), not provenance;
    the markers and the pinned upstream range supply the rest.
    """
    host_sha = report["host_sha"]
    method = report["integration_method"]
    if method == "MERGE":
        merged = subprocess.run(
            ["git", "-C", str(host_repo), "merge-base", "--is-ancestor", report["new_sha"], host_sha],
            capture_output=True,
        )
        if merged.returncode:
            raise CompatibilityError("integration_method MERGE requires new_sha in the host history")
        excluded = [
            item["commit_sha"] for item in report["change_inventory"] if item["disposition"] in {"DEFERRED", "REJECTED"}
        ]
        if excluded:
            raise CompatibilityError(f"a MERGE cannot leave commits out: {excluded[0]}")
        return

    patch_ids, markers = _host_integration_index(host_repo, report["rollback_target_sha"], host_sha)
    for item in report["change_inventory"]:
        commit_sha = item["commit_sha"]
        disposition = item["disposition"]
        in_host_by_content = (_stable_patch_id(upstream_repo, commit_sha) or "") in patch_ids
        in_host_by_marker = _marked(commit_sha, markers)
        if disposition == "UNCHANGED" and not in_host_by_content:
            raise CompatibilityError(f"UNCHANGED commit {commit_sha} has no host commit with the same patch id")
        if disposition == "ADAPTED" and not in_host_by_marker:
            raise CompatibilityError(f"ADAPTED commit {commit_sha} is not named by any host commit")
        if disposition in {"DEFERRED", "REJECTED"} and (in_host_by_content or in_host_by_marker):
            raise CompatibilityError(f"{disposition} commit {commit_sha} is present in the host range")


#: Gates whose log must show a non-empty passing test run, not only a zero exit code.
TEST_GATES = frozenset({"i18n", "frontend", "website", "h1_h8", "golden_a", "golden_b", "browser"})

_LOG_HEADER_RE = re.compile(r"^# (command|exit_code|tool_versions): (.*)$", re.MULTILINE)
_PASSED_RE = re.compile(r"\b(\d+) passed\b")
_FAILED_RE = re.compile(r"\b(\d+) (failed|errors?)\b")
_SKIPPED_RE = re.compile(r"\b(\d+) skipped\b")


def parse_gate_log(text: str) -> dict[str, Any]:
    """Read a runner-written gate log: the ``# command`` / ``# exit_code`` header and test counts.

    Counts come from pytest and vitest summary lines (``N passed``, ``N failed``, ``N error(s)``,
    ``N skipped``); the largest figure of each kind is taken, so a per-file line cannot hide the
    run total.
    """
    header = dict(_LOG_HEADER_RE.findall(text))
    exit_code = header.get("exit_code")
    return {
        "command": header.get("command", ""),
        "exit_code": int(exit_code) if exit_code is not None and exit_code.lstrip("-").isdigit() else None,
        "passed": max((int(n) for n in _PASSED_RE.findall(text)), default=0),
        "failed": max((int(n) for n, _kind in _FAILED_RE.findall(text)), default=0),
        "skipped": max((int(n) for n in _SKIPPED_RE.findall(text)), default=0),
    }


def _verify_gate_log(repo: Path, evidence_sha: str, gate_name: str, result: dict[str, Any]) -> None:
    """The manifest's PASS claim must be backed by the committed log the gate runner wrote."""
    log_path = result.get("log_path")
    log_digest = result.get("log_digest")
    if not isinstance(log_path, str) or not isinstance(log_digest, str):
        raise CompatibilityError(f"{gate_name} manifest names no committed gate log")
    if _committed_evidence_digest(repo, evidence_sha, log_path, gate_name) != log_digest:
        raise CompatibilityError(f"{gate_name} log_digest does not match the committed gate log")
    parsed = parse_gate_log(_git_bytes(repo, "show", f"{evidence_sha}:{log_path}").decode(errors="replace"))
    if parsed["exit_code"] != 0 or parsed["command"] != result.get("command"):
        raise CompatibilityError(f"{gate_name} log does not show the manifest command exiting 0")
    if gate_name in TEST_GATES and (parsed["passed"] == 0 or parsed["failed"] != 0):
        raise CompatibilityError(f"{gate_name} log does not show a non-empty passing test run")


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
    manifest_refs = {(item["evidence_path"], item["evidence_digest"]) for item in report["change_inventory"]}
    manifest_refs.update((gate["evidence_path"], gate["evidence_digest"]) for gate in report["gates"].values())
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
    _verify_integration(report, host_repo=host_repo, upstream_repo=upstream_repo)

    manifests: dict[str, dict[str, Any]] = {}

    def committed_manifest(path: str, label: str) -> dict[str, Any]:
        if path not in manifests:
            try:
                data = json.loads(_git_bytes(host_repo, "show", f"{evidence_sha}:{path}"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise CompatibilityError(f"{label} manifest is not valid JSON") from exc
            if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("target_sha") != host_sha:
                raise CompatibilityError(f"{label} manifest does not bind the candidate host_sha")
            manifests[path] = data
        return manifests[path]

    for item in report["change_inventory"]:
        actual = _committed_evidence_digest(host_repo, evidence_sha, item["evidence_path"], "change_inventory")
        if actual != item["evidence_digest"]:
            raise CompatibilityError("change_inventory evidence_digest does not match committed artifact")
        manifest = committed_manifest(item["evidence_path"], "change_inventory")
        if manifest.get("changes") != {
            entry["commit_sha"]: entry["disposition"] for entry in report["change_inventory"]
        }:
            raise CompatibilityError("change_inventory does not match committed manifest")

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
        manifest = committed_manifest(gate["evidence_path"], gate_name)
        results = manifest.get("results")
        if not isinstance(results, dict) or set(results) != set(REQUIRED_GATES):
            raise CompatibilityError(f"{gate_name} manifest has an incomplete gate inventory")
        result = results.get(gate_name)
        if (
            not isinstance(result, dict)
            or result.get("status") != "PASS"
            or result.get("required_skips") != 0
            or result.get("exit_code") != 0
            or not isinstance(result.get("command"), str)
            or not result["command"]
        ):
            raise CompatibilityError(f"{gate_name} manifest does not prove a completed PASS gate")
        _verify_gate_log(host_repo, evidence_sha, gate_name, result)
    if len(manifest_refs) != 1:
        raise CompatibilityError("all gates and dispositions must bind one single manifest")
    # After host_sha only evidence may change: the single manifest and the gate logs it names.
    evidence_paths = {path for path, _digest in manifest_refs}
    for manifest in manifests.values():
        evidence_paths.update(
            result["log_path"]
            for result in manifest["results"].values()
            if isinstance(result, dict) and isinstance(result.get("log_path"), str)
        )
    changed_paths = set(
        _git(host_repo, "diff", "--no-renames", "--name-only", host_sha, evidence_sha, "--").splitlines()
    )
    if not changed_paths or not changed_paths <= evidence_paths:
        raise CompatibilityError(f"non-evidence changes after host_sha: {sorted(changed_paths - evidence_paths)}")
    return "COMPATIBLE"


def _verify_provider_evidence_content(report: dict[str, Any], *, evidence_repo: Path, evidence_sha: str) -> None:
    """The committed evidence must itself report a passing run of this exact profile.

    Byte pinning alone lets a report point at evidence whose contents record a failure or a
    different profile; the evidence JSON has to agree with the report on the profile, its
    entry digest and the evidence kind, and record ``result: "PASS"`` with no required skip.
    """
    try:
        evidence = json.loads(_git_bytes(evidence_repo, "show", f"{evidence_sha}:{report['evidence_path']}"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise CompatibilityError("provider evidence is not valid JSON") from exc
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1:
        raise CompatibilityError("provider evidence has no schema_version 1 envelope")
    for field in ("profile_ref", "profile_entry_digest", "evidence_kind"):
        if evidence.get(field) != report[field]:
            raise CompatibilityError(f"provider evidence {field} does not match the report")
    if evidence.get("result") != "PASS" or evidence.get("required_skips") != 0:
        raise CompatibilityError("provider evidence does not record a passing run without required skips")


def verify_provider_qualification(
    report: dict[str, Any],
    *,
    registry_path: Path,
    evidence_repo: Path,
    now: datetime,
    enable_production: bool = False,
) -> str:
    """Verify an exact profile against pinned, offline evidence.

    Offline evidence can prove only local fixture results. A self-described report
    cannot grant SANDBOX_VERIFIED or QUALIFIED status; those come from a live route
    qualification recorded under operator attestation.
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
    _verify_provider_evidence_content(report, evidence_repo=evidence_repo, evidence_sha=evidence_sha)

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
