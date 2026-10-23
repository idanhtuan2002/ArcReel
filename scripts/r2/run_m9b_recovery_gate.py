"""Run the offline recovery tests and retain source-bound, fail-closed evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO
from uuid import uuid4

from lib.json_io import atomic_write_bytes
from r2.advanced_creative.digests import canonical_json_bytes
from scripts.r2.verify_m9_design_acceptance import loads_unique_json

INVENTORY = "tests/fixtures/r2/opportunity/manual_recovery_restarts.json"
REQUIRED_TESTS = (
    "tests/unit/scripts/r2/test_run_m9b_recovery_gate.py",
    "tests/integration/r2/opportunity/test_acquisition_v2_restarts.py",
)
REQUIRED_SOURCE_PATHS = (
    "scripts/r2/run_m9b_recovery_gate.py",
    INVENTORY,
    "tests/fixtures/r2/opportunity/manual_recovery_worker.py",
    *REQUIRED_TESTS,
    "r2/opportunity/acquisition_v2.py",
    "lib/db/repositories/opportunity_manual_admission.py",
    "server/services/m9_manual_publication.py",
    "server/services/opportunity_acquisition_v2.py",
    "tests/fixtures/r2/opportunity/manual_admission_custodian.py",
)


@dataclass(frozen=True)
class SourceState:
    head: str
    paths: tuple[str, ...]


Executor = Callable[[tuple[str, ...], Path, TextIO, Mapping[str, str]], int]


def read_source_state(repo: Path) -> SourceState:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=repo).decode().split("\0")
    return SourceState(head, tuple(sorted(set(filter(None, tracked)) | set(REQUIRED_SOURCE_PATHS))))


def execute_tests(argv: tuple[str, ...], cwd: Path, log: TextIO, environment: Mapping[str, str]) -> int:
    with subprocess.Popen(
        argv, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, env=dict(environment), start_new_session=True
    ) as child:
        try:
            return child.wait()
        except BaseException:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            raise


def _no_symlinks(path: Path) -> Path:
    if ".." in path.parts:
        raise ValueError("parent traversal is not an owned output path")
    path = path.absolute()
    if any(component.is_symlink() for component in (*path.parents, path)):
        raise ValueError("symlink ancestry is not an owned output path")
    return path


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _snapshot(repo: Path, state: SourceState) -> dict[str, str]:
    if re.fullmatch(r"[0-9a-f]{40}", state.head) is None or not set(REQUIRED_SOURCE_PATHS).issubset(state.paths):
        raise ValueError("source identity or required paths missing")
    result = {}
    for name in state.paths:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("source path is outside the repository")
        target = repo / relative
        if target.is_symlink():
            if any(parent.is_symlink() for parent in target.parents if parent != repo.parent):
                raise ValueError("source symlink ancestry refused")
            result[name] = _hash(os.readlink(target).encode())
        else:
            result[name] = _hash(_no_symlinks(target).read_bytes())
    return result


def _write(path: Path, body: Mapping[str, object]) -> None:
    atomic_write_bytes(path, canonical_json_bytes(dict(body)))
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _inventory(repo: Path) -> list[dict[str, object]]:
    raw = (repo / INVENTORY).read_bytes()
    if len(raw) > 1_048_576:
        raise ValueError("restart inventory exceeds bound")
    body = loads_unique_json(raw)
    cases = body.get("cases")
    if (
        (body.get("schema"), body.get("seed")) != ("m9-manual-recovery-restarts.v1", 20261020)
        or not isinstance(cases, list)
        or not cases
    ):
        raise ValueError("restart inventory identity missing")
    ids = []
    for case in cases:
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("case_id"), str)
            or re.fullmatch(r"[a-z0-9-]+", case["case_id"]) is None
            or case.get("principal") not in ("application", "issuer")
            or not isinstance(case.get("boundary"), str)
            or not case["boundary"]
            or case.get("mandatory") is not True
        ):
            raise ValueError("restart case identity or mandatory selection missing")
        ids.append(case["case_id"])
    if len(ids) != len(set(ids)) or body.get("selected") != ids or body.get("unselected") != []:
        raise ValueError("initial-release restart cases cannot be omitted")
    return cases


def _junit(path: Path) -> dict[str, int]:
    raw = path.read_bytes()
    if not raw or len(raw) > 16_777_216 or b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ValueError("JUnit output is absent or invalid")
    root = ET.fromstring(raw)
    suites = [s for s in root.iter("testsuite") if not list(s.iterfind("testsuite"))]
    counts = {
        key: sum(int(s.attrib.get(key, "0")) for s in suites) for key in ("tests", "failures", "errors", "skipped")
    }
    cases = list(root.iter("testcase"))
    if (
        not suites
        or counts["tests"] <= 0
        or counts["tests"] != len(cases)
        or any(counts[k] for k in ("failures", "errors", "skipped"))
        or any(list(case.iter(tag)) for case in cases for tag in ("failure", "error", "skipped"))
    ):
        raise ValueError("JUnit requires nonzero consistent collection and no failures/errors/skips")
    return counts


def _restarts(artifact_dir: Path, cases: list[dict[str, object]]) -> int:
    for case in cases:
        identity = str(case["case_id"])
        evidence = artifact_dir / "restarts" / (identity + ".json")
        marker_path = artifact_dir / "restarts" / (identity + ".arrival.json")
        record = loads_unique_json(_no_symlinks(evidence).read_bytes())
        marker_raw = _no_symlinks(marker_path).read_bytes()
        marker = loads_unique_json(marker_raw)
        uid = 31001 if case["principal"] == "issuer" else 31002
        pids = [record.get(key) for key in ("parent_pid", "killed_pid", "restarted_pid")]
        if (
            any(type(pid) is not int or pid <= 0 for pid in pids)
            or len(set(pids)) != 3
            or record.get("case_id") != identity
            or record.get("worker_uid") != uid
            or any(record.get(key) is not True for key in ("passed", "parent_killed", "reaped", "marker_fsynced"))
            or record.get("marker_sha256") != _hash(marker_raw)
            or marker
            != {
                "schema": "m9-manual-recovery-arrival.v1",
                "case_id": identity,
                "boundary": case["boundary"],
                "pid": record["killed_pid"],
                "uid": uid,
            }
        ):
            raise ValueError("restart evidence does not prove the selected parent-kill/fresh-PID boundary: " + identity)
    return len(cases)


def run_recovery_gate(
    *,
    repo: Path,
    artifact_dir: Path,
    basetemp: Path,
    python: Path = Path(sys.executable),
    execute: Executor = execute_tests,
    source_state: Callable[[Path], SourceState] = read_source_state,
) -> dict[str, object]:
    repo = _no_symlinks(repo)
    artifact_dir = _no_symlinks(artifact_dir)
    basetemp = _no_symlinks(basetemp)
    if basetemp != artifact_dir / "pytest-temp":
        raise ValueError("basetemp must be the exact new owned artifact child pytest-temp")
    if artifact_dir.exists() or not artifact_dir.parent.is_dir():
        raise ValueError("artifact directory must be new beneath an existing parent")
    before = source_state(repo)
    hashes = _snapshot(repo, before)
    cases = _inventory(repo)
    artifact_dir.mkdir(mode=0o700)
    owner = uuid4().hex
    _write(artifact_dir / ".m9b-recovery-owner.json", {"owner": owner, "repo": str(repo), "head": before.head})
    argv = (
        str(python),
        "-m",
        "pytest",
        *REQUIRED_TESTS,
        "-q",
        "--basetemp=" + str(basetemp),
        "--junitxml=" + str(artifact_dir / "junit.xml"),
    )
    report: dict[str, object] = {
        "schema": "m9-manual-recovery-gate.v1",
        "status": "RUNNING",
        "exit_code": None,
        "head": before.head,
        "source_hashes": hashes,
        "source_unchanged": False,
        "owner": owner,
        "argv": list(argv),
        "errors": [],
    }
    manifest = artifact_dir / "manifest.json"
    _write(manifest, report)
    errors = []
    interrupted = False
    exit_code = 1
    log_path = artifact_dir / "pytest.log"
    try:
        with log_path.open("x+") as log:
            exit_code = execute(argv, repo, log, {**os.environ, "ARCREEL_M9_RECOVERY_ARTIFACT_DIR": str(artifact_dir)})
            log.flush()
            os.fsync(log.fileno())
        if type(exit_code) is not int or exit_code != 0:
            errors.append("external pytest returned nonzero")
        if not log_path.stat().st_size:
            errors.append("external pytest log is empty")
        report["junit"] = _junit(artifact_dir / "junit.xml")
        report["restart_cases"] = _restarts(artifact_dir, cases)
    except KeyboardInterrupt:
        interrupted = True
        errors.append("external execution interrupted")
    except Exception as error:
        errors.append(type(error).__name__ + ": " + str(error))
    try:
        after = source_state(repo)
        report["source_unchanged"] = before == after and hashes == _snapshot(repo, after)
        if not report["source_unchanged"]:
            errors.append("source identity or bytes changed during execution")
    except Exception as error:
        errors.append("source revalidation failed: " + type(error).__name__)
    report.update(
        status="INTERRUPTED" if interrupted else "FAIL" if errors else "PASS",
        exit_code=130 if interrupted else 1 if errors else 0,
        subprocess_exit_code=exit_code,
        errors=errors,
    )
    if log_path.exists():
        report["log_sha256"] = _hash(log_path.read_bytes())
    _write(manifest, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--basetemp", required=True, type=Path)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    args = parser.parse_args(argv)
    try:
        report = run_recovery_gate(
            repo=args.repo, artifact_dir=args.artifact_dir, basetemp=args.basetemp, python=args.python
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "FAIL", "error": type(error).__name__ + ": " + str(error)}))
        return 2
    print(json.dumps({"status": report["status"], "manifest": str(args.artifact_dir / "manifest.json")}))
    return int(str(report["exit_code"]))


if __name__ == "__main__":
    raise SystemExit(main())
