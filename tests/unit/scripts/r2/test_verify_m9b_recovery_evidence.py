"""Recovery V2 evidence must cover every M9-B gate plus the real parent-kill restart gate at one clean HEAD."""

import copy
import json
import shlex

import pytest

from scripts.r2 import verify_m9b_evidence as m9b
from scripts.r2 import verify_m9b_recovery_evidence as recovery
from tests.unit.scripts.r2.test_verify_m9b_evidence import ART, HEAD, PY, ROOT, _junit, candidate, sha

CASES = [
    {"case_id": "claim-after", "principal": "application", "boundary": "claim-committed", "mandatory": True},
    {"case_id": "issuer-publish", "principal": "issuer", "boundary": "published", "mandatory": True},
]


def _put(view, document, path, raw):
    view.artifacts[path] = raw
    ref = {"path": path, "sha256": sha(raw)}
    document["artifacts"] = [item for item in document["artifacts"] if item["path"] != path] + [ref]
    return ref


def recovery_candidate():
    view, acquisition = candidate()
    document = copy.deepcopy(acquisition)
    view.evidences[m9b.EVIDENCE] = json.dumps(acquisition).encode()
    document.update(status="M9_B_RECOVERY_V2_CANDIDATE", packet="M9-B-RECOVERY-V2", e_global_closure_accepted=False)
    view.blobs[recovery.RESTART_INVENTORY] = json.dumps(
        {
            "schema": "m9-manual-recovery-restarts.v1",
            "seed": 20261020,
            "cases": CASES,
            "selected": [case["case_id"] for case in CASES],
            "unselected": [],
        }
    ).encode()
    identities = sorted(recovery.RESTART_FAULTS)
    report = _put(view, document, ART + "restarts/junit.xml", _junit(identities))
    log = b"%d passed in 1800.0s\n" % len(identities)
    log_ref = _put(view, document, ART + "restarts/pytest.log", log)
    artifact_dir = "/repo/" + ART + "restarts"
    argv = [
        PY,
        "scripts/r2/run_m9b_recovery_gate.py",
        "--repo",
        "/repo",
        "--artifact-dir",
        artifact_dir,
        "--basetemp",
        artifact_dir + "/pytest-temp",
    ]
    result = {
        "schema_version": "m9.command-result.v1",
        "gate": "restarts",
        "tested_head": HEAD,
        "argv": argv,
        "exit": 0,
        "passed": len(identities),
        "skipped": 0,
        "log": log_ref,
        "test_report": report,
    }
    result_ref = _put(view, document, ART + "restarts.result.json", json.dumps(result).encode())
    document["commands"].append(
        {
            "gate": "restarts",
            "command": shlex.join(argv),
            "exit": 0,
            "tested_head": HEAD,
            "passed": len(identities),
            "skipped": 0,
            "log": log_ref,
            "result": result_ref,
        }
    )
    manifest = {
        "schema": "m9-manual-recovery-gate.v1",
        "status": "PASS",
        "exit_code": 0,
        "subprocess_exit_code": 0,
        "head": HEAD,
        "source_unchanged": True,
        "errors": [],
        "restart_cases": len(CASES),
        "log_sha256": log_ref["sha256"],
        "junit": {"tests": len(identities), "failures": 0, "errors": 0, "skipped": 0},
    }
    records = {}
    for index, case in enumerate(CASES):
        record = {
            "case_id": case["case_id"],
            "worker_uid": 31001 if case["principal"] == "issuer" else 31002,
            "parent_pid": 100 + index,
            "killed_pid": 200 + index,
            "restarted_pid": 300 + index,
            "passed": True,
            "parent_killed": True,
            "reaped": True,
            "marker_fsynced": True,
        }
        records[case["case_id"]] = _put(
            view, document, ART + f"restarts/{case['case_id']}.json", json.dumps(record).encode()
        )
    document["restart"] = {
        "schema": "m9-manual-recovery-restarts.v1",
        "seed": 20261020,
        "mandatory_cases": len(CASES),
        "manifest": _put(view, document, ART + "restarts/manifest.json", json.dumps(manifest).encode()),
        "report": report,
        "records": records,
    }
    document["fault_matrix"]["restart"] = {"test_refs": identities}
    view.blobs[recovery.RECOVERY_SCHEMA] = _schema("R2_M9_B_RECOVERY_V2.schema.json")
    view.blobs[m9b.SCHEMA] = _schema("R2_M9_B_ACQUISITION.schema.json")
    return view, document


def _schema(name):
    return (ROOT / "docs/r2/evidence/schemas" / name).read_bytes()


def verify(view, document):
    return recovery.verify_recovery_evidence(ROOT, document, view=view)


def test_the_complete_recovery_candidate_passes():
    view, document = recovery_candidate()
    assert verify(view, document) == []


def _record(view, document, case_id, **changes):
    ref = document["restart"]["records"][case_id]
    record = json.loads(view.artifacts[ref["path"]]) | changes
    document["restart"]["records"][case_id] = _put(view, document, ref["path"], json.dumps(record).encode())


def _manifest(view, document, **changes):
    ref = document["restart"]["manifest"]
    body = json.loads(view.artifacts[ref["path"]]) | changes
    document["restart"]["manifest"] = _put(view, document, ref["path"], json.dumps(body).encode())


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda v, d: d["commands"].pop(), "required gates are missing"),
        (lambda v, d: d.update(e_global_closure_accepted=True), "e_global_closure_accepted"),
        (lambda v, d: d["restart"].update(seed=1), "recorded restart identity"),
        (lambda v, d: d["restart"].update(mandatory_cases=1), "recorded restart identity"),
        (lambda v, d: d["restart"]["records"].pop("issuer-publish"), "restart record"),
        (lambda v, d: _record(v, d, "claim-after", killed_pid=100), "fresh-PID parent kill"),
        (lambda v, d: _record(v, d, "claim-after", worker_uid=0), "fresh-PID parent kill"),
        (lambda v, d: _record(v, d, "issuer-publish", reaped=False), "fresh-PID parent kill"),
        (lambda v, d: _record(v, d, "issuer-publish", killed_pid=200), "reuse a killed process"),
        (lambda v, d: _manifest(v, d, status="INTERRUPTED"), "clean PASS"),
        (lambda v, d: _manifest(v, d, head="f" * 40), "clean PASS"),
        (lambda v, d: _manifest(v, d, source_unchanged=False), "clean PASS"),
        (lambda v, d: _manifest(v, d, restart_cases=1), "clean PASS"),
        (lambda v, d: _manifest(v, d, log_sha256="0" * 64), "manifest log differs"),
        (lambda v, d: d["fault_matrix"]["restart"]["test_refs"].pop(), "fault category restart"),
        (lambda v, d: v.artifacts.pop(ART + "restarts/manifest.json"), "not a retained artifact"),
    ],
)
def test_incomplete_or_forged_restart_evidence_is_refused(mutate, expected):
    view, document = recovery_candidate()
    mutate(view, document)
    found = verify(view, document)
    assert any(expected in problem for problem in found), found


def test_sampled_or_reseeded_restart_inventory_is_refused():
    view, document = recovery_candidate()
    inventory = json.loads(view.blobs[recovery.RESTART_INVENTORY])
    inventory.update(selected=["claim-after"], unselected=["issuer-publish"])
    view.blobs[recovery.RESTART_INVENTORY] = json.dumps(inventory).encode()
    assert any("omits or samples" in problem for problem in verify(view, document))
    inventory.update(selected=[case["case_id"] for case in CASES], unselected=[], seed=7)
    view.blobs[recovery.RESTART_INVENTORY] = json.dumps(inventory).encode()
    assert any("pinned seed" in problem for problem in verify(view, document))


def test_an_incomplete_acquisition_packet_cannot_be_accepted_through_the_extension():
    view, document = recovery_candidate()
    acquisition = json.loads(view.evidences[m9b.EVIDENCE])
    acquisition["commands"] = [item for item in acquisition["commands"] if item["gate"] != "migration"]
    view.evidences[m9b.EVIDENCE] = json.dumps(acquisition).encode()
    found = verify(view, document)
    assert any(problem.startswith("acquisition evidence: required gates") for problem in found), found
    assert any("different M9-B gates" in problem for problem in found), found
    del view.evidences[m9b.EVIDENCE]
    assert verify(view, document) == ["recovery schema or the M9-B acquisition evidence is unavailable"]


def test_the_restart_gate_must_run_the_pinned_runner_with_its_owned_basetemp():
    assert m9b.restart_command_problems("python", ["scripts/r2/other.py"]) != []
    rest = ["scripts/r2/run_m9b_recovery_gate.py", "--repo", "/r", "--artifact-dir", "/a", "--basetemp", "/b"]
    assert m9b.restart_command_problems("python", rest) == ["restart command does not own its pytest basetemp"]
    rest[-1] = "/a/pytest-temp"
    assert m9b.restart_command_problems("python", rest) == []
