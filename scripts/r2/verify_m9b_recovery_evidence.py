"""Verify candidate-only M9-B manual recovery V2 evidence over the complete M9-B gate inventory.

The recovery document is a superset of the M9-B acquisition candidate: every acquisition gate plus the real
parent-kill restart gate, its retained per-case records and the recovery-only claims (no E global closure, no
production activation). The acquisition evidence in the same tree must verify on its own and record the same gate
commands, so this extension cannot accept an incomplete M9-B packet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts.r2.run_m9b_recovery_gate import REQUIRED_TESTS as RUNNER_TESTS
from scripts.r2.verify_m9_prerequisites import LOAD_ERRORS, loads_unique_json
from scripts.r2.verify_m9b_evidence import (
    EVIDENCE,
    GATES,
    SCHEMA,
    GitRepoView,
    RecordedCommandResult,
    RepoView,
    junit_identities,
    summary_problems,
    verify_m9b_evidence,
)

RECOVERY_SCHEMA = "docs/r2/evidence/schemas/R2_M9_B_RECOVERY_V2.schema.json"
RESTART_INVENTORY = "tests/fixtures/r2/opportunity/manual_recovery_restarts.json"
RECOVERY_GATES = GATES | {"restarts"}
RESTART_FAULTS = frozenset(
    {
        "tests.integration.r2.opportunity.test_acquisition_v2_restarts::test_parent_kill_after_claim_reconstructs_original_material_without_repeating_fetch",
        "tests.integration.r2.opportunity.test_acquisition_v2_restarts::test_parent_kill_preserves_initial_admission_and_exact_terminal_replay",
        "tests.integration.r2.opportunity.test_acquisition_v2_restarts::test_parent_kill_private_erasure_reuses_original_spend_proof",
        "tests.integration.r2.opportunity.test_acquisition_v2_restarts::test_parent_kill_public_erasure_reuses_exact_receipt_before_sql_completion",
    }
)
_UID = {"application": 31002, "issuer": 31001}
# The worker export (tests/integration/r2/opportunity/test_acquisition_v2_restarts.py): tracked Python under these
# roots plus these files; every worker seal must be exactly this inventory of the tested tree.
WORKER_EXPORT_ROOTS = ("lib/", "r2/", "server/", "scripts/", "tests/fixtures/")
WORKER_EXPORT_FILES = frozenset(
    {
        "uv.lock",
        "pyproject.toml",
        "tests/fixtures/r2/opportunity/manual_import.json",
        "tests/fixtures/r2/opportunity/manual_recovery_restarts.json",
        "tests/integration/r2/opportunity/test_acquisition_v2_restarts.py",
    }
)
# Runtime sources every worker seal must name; a subset of the export inventory.
RUNTIME_SEALED = frozenset(
    {
        "r2/opportunity/acquisition_v2.py",
        "lib/db/repositories/opportunity_manual_admission.py",
        "server/services/m9_manual_publication.py",
        "server/services/opportunity_acquisition_v2.py",
    }
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def worker_export(tree: Mapping[str, str]) -> dict[str, str]:
    """The exact source inventory the restart worker export seals, taken from the tested tree."""
    return {
        path: digest
        for path, digest in tree.items()
        if (path.endswith(".py") and path.startswith(WORKER_EXPORT_ROOTS)) or path in WORKER_EXPORT_FILES
    }


def _record_problems(case: Mapping[str, Any], raw: Mapping[str, bytes], export: Mapping[str, str]) -> list[str]:
    """The runner's own per-case proof, re-derived: arrival and armed markers, kernel kill, fresh PIDs, source seal."""
    identity = case.get("case_id")
    uid = _UID.get(case.get("principal"))
    try:
        record = loads_unique_json(raw["record"])
        arrival = loads_unique_json(raw["arrival"])
        armed = loads_unique_json(raw["armed"])
    except (*LOAD_ERRORS, KeyError):
        return [f"restart record is not retained: {identity}"]
    pids = [record.get(key) for key in ("parent_pid", "killed_pid", "restarted_pid")]
    kernel = record.get("kernel") or {}
    seal = record.get("source_hashes") or {}
    proven = (
        record.get("schema") == "m9-manual-recovery-restart.v1"
        and record.get("case_id") == identity
        and record.get("worker_uid") == uid
        and all(record.get(key) is True for key in ("passed", "parent_killed", "reaped", "marker_fsynced"))
        and all(type(pid) is int and pid > 0 for pid in pids)
        and len(set(pids)) == 3
        and record.get("wait_exit_code") == 137
        and kernel.get("pid") == record.get("killed_pid")
        and kernel.get("uid") == uid
        and kernel.get("parent_sent_sigkill") is True
        and kernel.get("pidfd_pinned") is True
        and record.get("marker_sha256") == _sha(raw["arrival"])
        and record.get("armed_sha256") == _sha(raw["armed"])
        and arrival
        == {
            "schema": "m9-manual-recovery-arrival.v1",
            "case_id": identity,
            "boundary": case.get("boundary"),
            "pid": record.get("killed_pid"),
            "uid": uid,
        }
        and armed
        == {
            "schema": "m9-manual-recovery-armed.v1",
            "case_id": identity,
            "arrival_sha256": _sha(raw["arrival"]),
            "pid": record.get("killed_pid"),
        }
    )
    problems = [] if proven else [f"restart record does not prove a fresh-PID parent kill: {identity}"]
    if not RUNTIME_SEALED.issubset(seal) or seal != export:
        problems.append(f"restart worker source seal differs from the tested code: {identity}")
    return problems


def runner_argv(command: Sequence[str]) -> list[str]:
    """The exact pytest argv the pinned runner builds for a recorded runner command (`run_recovery_gate`)."""
    options = dict(zip(command[2::2], command[3::2], strict=False))
    artifact_dir = options.get("--artifact-dir", "")
    return [
        command[0],
        "-m",
        "pytest",
        *RUNNER_TESTS,
        "-q",
        "--basetemp=" + artifact_dir + "/pytest-temp",
        "--junitxml=" + artifact_dir + "/junit.xml",
    ]


def restart_problems(document: Mapping[str, Any], view: RepoView, tested_head: str) -> list[str]:
    """The restart gate ran the pinned runner on the tested code and proved every mandatory parent-kill case."""
    problems: list[str] = []
    artifacts = {item["path"]: item["sha256"] for item in document["artifacts"]}

    def read(ref: Mapping[str, str]) -> bytes:
        if artifacts.get(ref["path"]) != ref["sha256"]:
            raise KeyError(ref["path"])
        raw = view.artifact(ref["path"])
        if _sha(raw) != ref["sha256"]:
            raise ValueError(ref["path"])
        return raw

    restart = document["restart"]
    try:
        inventory = loads_unique_json(view.blob(tested_head, RESTART_INVENTORY))
        manifest = loads_unique_json(read(restart["manifest"]))
        command = next(item for item in document["commands"] if item["gate"] == "restarts")
        result = RecordedCommandResult.model_validate(loads_unique_json(read(command["result"])))
        junit = read(restart["report"])
        log = read(command["log"])
    except (*LOAD_ERRORS, KeyError, StopIteration, ValueError):
        return ["restart gate manifest, result, log or report is not a retained artifact"]
    cases = inventory.get("cases", [])
    ids = [case.get("case_id") for case in cases]
    if (inventory.get("schema"), inventory.get("seed")) != ("m9-manual-recovery-restarts.v1", 20261020):
        problems.append("restart inventory is not the pinned seed")
    if inventory.get("selected") != ids or inventory.get("unselected") != [] or not ids:
        problems.append("restart inventory omits or samples a mandatory case")
    if (restart["schema"], restart["seed"], restart["mandatory_cases"]) != (
        "m9-manual-recovery-restarts.v1",
        20261020,
        len(ids),
    ):
        problems.append("recorded restart identity differs from the tested inventory")
    expected = {
        "schema": "m9-manual-recovery-gate.v1",
        "status": "PASS",
        "exit_code": 0,
        "subprocess_exit_code": 0,
        "head": tested_head,
        "source_unchanged": True,
        "errors": [],
        "restart_cases": len(ids),
        "argv": runner_argv(result.argv),
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        problems.append("restart manifest does not record a clean PASS of every case at the tested HEAD")
    try:
        tree = view.tree_sha256(tested_head)
    except (*LOAD_ERRORS, OSError):
        return [*problems, "the tested code tree cannot be hashed"]
    manifest_hashes = manifest.get("source_hashes") or {}
    export = worker_export(tree)
    if manifest_hashes != tree:
        problems.append("restart manifest source seal differs from the tested code tree")
    if manifest.get("log_sha256") != command["log"]["sha256"]:
        problems.append("restart manifest log differs from the retained gate log")
    if result.test_report is None or result.test_report.model_dump() != restart["report"]:
        problems.append("restart result does not bind its exact JUnit artifact")
    problems.extend("restarts: " + item for item in summary_problems(log, command["passed"], command["skipped"]))
    identities, junit_problems = junit_identities(junit, command["passed"])
    problems.extend("restarts: " + item for item in junit_problems)
    if (manifest.get("junit") or {}) != {"tests": command["passed"], "failures": 0, "errors": 0, "skipped": 0}:
        problems.append("restart manifest JUnit count differs from the recorded gate")
    try:
        collected = view.collected(list(RUNNER_TESTS))
    except (OSError, ValueError, subprocess.CalledProcessError):
        collected = None
        problems.append("restarts: the runner tests cannot be collected from the tested code")
    if collected is not None and sorted(collected) != sorted(identities):
        problems.append("restarts: executed JUnit cases differ from the collected test inventory")
    executed = {identity.split("[", 1)[0] for identity in identities}
    claimed = document["fault_matrix"].get("restart", {}).get("test_refs", [])
    if not RESTART_FAULTS.issubset(executed) or set(claimed) != {
        identity for identity in identities if identity.split("[", 1)[0] in RESTART_FAULTS
    }:
        problems.append("fault category restart does not bind its complete executed test inventory")
    if set(restart["records"]) != set(ids):
        problems.append("restart records differ from the mandatory case inventory")
    killed: list[object] = []
    for case in cases:
        refs = restart["records"].get(case.get("case_id"), {})
        try:
            raw = {kind: read(refs[kind]) for kind in ("record", "arrival", "armed")}
        except (KeyError, ValueError, OSError, TypeError):
            problems.append(f"restart record is not retained: {case.get('case_id')}")
            continue
        problems.extend(_record_problems(case, raw, export))
        killed.append(loads_unique_json(raw["record"]).get("killed_pid"))
    if len(set(killed)) != len(killed):
        problems.append("restart cases reuse a killed process")
    return problems


def verify_recovery_evidence(repo: Path, evidence: Mapping[str, Any], *, view: RepoView | None = None) -> list[str]:
    """Every problem with the recovery candidate, sorted; an empty list is the only pass."""
    view = view or GitRepoView(repo)
    tested_head = evidence.get("tested_head")
    if not isinstance(tested_head, str):
        return ["tested_head is missing"]
    try:
        schema = json.loads(view.blob(tested_head, RECOVERY_SCHEMA))
        acquisition_schema = json.loads(view.blob(tested_head, SCHEMA))
        acquisition = loads_unique_json(view.evidence(EVIDENCE))
    except (*LOAD_ERRORS, ValueError):
        return ["recovery schema or the M9-B acquisition evidence is unavailable"]
    problems = verify_m9b_evidence(
        dict(evidence), schema, view, tested_head, gates=RECOVERY_GATES, extra_faults=frozenset({"restart"})
    )
    acquisition_problems = verify_m9b_evidence(acquisition, acquisition_schema, view, tested_head)
    problems.extend("acquisition evidence: " + item for item in acquisition_problems)
    if problems and any(item.startswith("schema:") for item in problems):
        return sorted(set(problems))
    shared = [command for command in evidence["commands"] if command["gate"] in GATES]
    if sorted(shared, key=lambda item: item["gate"]) != sorted(acquisition["commands"], key=lambda item: item["gate"]):
        problems.append("recovery and acquisition evidence record different M9-B gates")
    for flag in ("e_global_closure_accepted",):
        if evidence.get(flag) is not False:
            problems.append(f"{flag} must be false for a candidate")
    problems.extend(restart_problems(evidence, view, tested_head))
    return sorted(set(problems))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        document = loads_unique_json(args.evidence.read_bytes())
    except (*LOAD_ERRORS, ValueError) as error:
        print("M9_REQUIRED_EVIDENCE_MISSING: " + type(error).__name__)
        return 1
    problems = verify_recovery_evidence(args.repo, document)
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print("M9_B_RECOVERY_EVIDENCE_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
