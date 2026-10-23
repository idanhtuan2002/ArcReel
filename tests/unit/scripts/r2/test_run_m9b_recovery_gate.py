"""Recovery qualification refuses incomplete process and restart evidence."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest

INVENTORY = Path("tests/fixtures/r2/opportunity/manual_recovery_restarts.json")


def gate_module():
    return importlib.import_module("scripts.r2.run_m9b_recovery_gate")


@pytest.fixture
def subject(tmp_path):
    module = gate_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in module.REQUIRED_SOURCE_PATHS:
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("synthetic source\n")
    (repo / INVENTORY).write_bytes(INVENTORY.read_bytes())
    output = tmp_path / "artifacts ; literal $value"
    state = module.SourceState(head="a" * 40, paths=module.REQUIRED_SOURCE_PATHS)
    calls = []

    def execute(argv, cwd, log, environment):
        calls.append((argv, cwd, dict(environment)))
        log.write("synthetic external pytest execution\n")
        junit = Path(next(v.split("=", 1)[1] for v in argv if v.startswith("--junitxml=")))
        junit.write_text(
            '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">'
            '<testcase name="synthetic-external-result"/></testsuite></testsuites>'
        )
        inventory = json.loads((repo / INVENTORY).read_text())
        evidence = Path(environment["ARCREEL_M9_RECOVERY_ARTIFACT_DIR"]) / "restarts"
        evidence.mkdir()
        for index, case in enumerate(inventory["cases"]):
            uid = 31001 if case["principal"] == "issuer" else 31002
            killed = 10000 + index * 2
            restarted = killed + 1
            marker = {
                "schema": "m9-manual-recovery-arrival.v1",
                "case_id": case["case_id"],
                "boundary": case["boundary"],
                "pid": killed,
                "uid": uid,
            }
            raw = json.dumps(marker, sort_keys=True).encode()
            (evidence / (case["case_id"] + ".arrival.json")).write_bytes(raw)
            armed = json.dumps(
                {
                    "schema": "m9-manual-recovery-armed.v1",
                    "case_id": case["case_id"],
                    "arrival_sha256": hashlib.sha256(raw).hexdigest(),
                    "pid": killed,
                },
                sort_keys=True,
            ).encode()
            (evidence / (case["case_id"] + ".armed.json")).write_bytes(armed)
            record = {
                "case_id": case["case_id"],
                "passed": True,
                "parent_pid": 9000,
                "killed_pid": killed,
                "restarted_pid": restarted,
                "worker_uid": uid,
                "parent_killed": True,
                "reaped": True,
                "marker_fsynced": True,
                "marker_sha256": hashlib.sha256(raw).hexdigest(),
                "armed_sha256": hashlib.sha256(armed).hexdigest(),
            }
            (evidence / (case["case_id"] + ".json")).write_text(json.dumps(record))
        return 0

    return module, repo, output, state, execute, calls


def run(subject, executor=None, source=None):
    module, repo, output, state, execute, _ = subject
    return module.run_recovery_gate(
        repo=repo,
        artifact_dir=output,
        basetemp=output / "pytest-temp",
        python=Path("/synthetic/python"),
        execute=execute if executor is None else executor,
        source_state=(lambda _: state) if source is None else source,
    )


def test_gate_requires_consistent_junit_restarts_and_source_before_pass(subject):
    result = run(subject)
    module, repo, output, _, _, calls = subject
    assert result["status"] == "PASS"
    assert result["exit_code"] == 0
    assert result["source_unchanged"]
    assert result["junit"]["tests"] == 1
    assert result["restart_cases"] == len(json.loads(INVENTORY.read_text())["selected"])
    argv, cwd, environment = calls[0]
    assert isinstance(argv, tuple)
    assert argv[:3] == ("/synthetic/python", "-m", "pytest")
    assert cwd == repo
    assert "--basetemp=" + str(output / "pytest-temp") in argv
    assert all(name in argv for name in module.REQUIRED_TESTS)
    assert environment["ARCREEL_M9_RECOVERY_ARTIFACT_DIR"] == str(output)
    persisted = json.loads((output / "manifest.json").read_text())
    assert persisted == result
    assert (output / ".m9b-recovery-owner.json").is_file()


@pytest.mark.parametrize(
    "fault",
    [
        "nonzero",
        "zero-collected",
        "missing-junit",
        "failed-test",
        "skipped-test",
        "summary-mismatch",
        "empty-log",
        "missing-restart",
        "reused-pid",
        "unreaped",
        "wrong-uid",
        "bad-marker",
        "missing-armed",
        "forged-armed",
    ],
)
def test_gate_never_passes_incomplete_or_failed_external_evidence(subject, fault):
    _, _, output, _, execute, _ = subject

    def broken(argv, cwd, log, environment):
        exit_code = execute(argv, cwd, log, environment)
        junit = output / "junit.xml"
        if fault == "nonzero":
            return 1
        if fault == "zero-collected":
            junit.write_text('<testsuites><testsuite tests="0" failures="0" errors="0" skipped="0"/></testsuites>')
        elif fault == "missing-junit":
            junit.unlink()
        elif fault == "failed-test":
            junit.write_text(
                '<testsuite tests="1" failures="1" errors="0" skipped="0"><testcase><failure/></testcase></testsuite>'
            )
        elif fault == "skipped-test":
            junit.write_text(
                '<testsuite tests="1" failures="0" errors="0" skipped="1"><testcase><skipped/></testcase></testsuite>'
            )
        elif fault == "summary-mismatch":
            junit.write_text('<testsuite tests="2" failures="0" errors="0" skipped="0"><testcase/></testsuite>')
        elif fault == "empty-log":
            log.seek(0)
            log.truncate()
        else:
            evidence = next(
                p for p in (output / "restarts").glob("*.json") if not p.name.endswith((".arrival.json", ".armed.json"))
            )
            if fault == "missing-restart":
                evidence.unlink()
            else:
                record = json.loads(evidence.read_text())
                if fault == "reused-pid":
                    record["restarted_pid"] = record["killed_pid"]
                elif fault == "unreaped":
                    record["reaped"] = False
                elif fault == "wrong-uid":
                    record["worker_uid"] = 0
                elif fault == "bad-marker":
                    record["marker_sha256"] = "0" * 64
                elif fault == "missing-armed":
                    evidence.with_name(evidence.stem + ".armed.json").unlink()
                elif fault == "forged-armed":
                    armed_path = evidence.with_name(evidence.stem + ".armed.json")
                    armed = json.loads(armed_path.read_text())
                    armed["arrival_sha256"] = "0" * 64
                    armed_raw = json.dumps(armed).encode()
                    armed_path.write_bytes(armed_raw)
                    record["armed_sha256"] = hashlib.sha256(armed_raw).hexdigest()
                evidence.write_text(json.dumps(record))
        return exit_code

    result = run(subject, broken)
    assert result["status"] == "FAIL"
    assert result["exit_code"] != 0
    assert result["errors"]
    assert json.loads((output / "manifest.json").read_text())["status"] == "FAIL"


def test_interrupted_runner_preserves_failure_manifest(subject):
    def interrupt(argv, cwd, log, environment):
        log.write("external process interrupted\n")
        raise KeyboardInterrupt

    result = run(subject, interrupt)
    assert result["status"] == "INTERRUPTED"
    assert result["exit_code"] == 130
    assert result["errors"]


def test_source_change_during_tests_invalidates_successful_execution(subject):
    module, repo, _, state, execute, _ = subject

    def changed(argv, cwd, log, environment):
        code = execute(argv, cwd, log, environment)
        (repo / module.REQUIRED_SOURCE_PATHS[0]).write_text("changed while running\n")
        return code

    result = run(subject, changed, source=lambda _: state)
    assert result["status"] == "FAIL"
    assert result["source_unchanged"] is False


def test_unrelated_basetemp_is_refused_without_touching_existing_work(subject, tmp_path):
    module, repo, output, state, execute, calls = subject
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    sentinel = unrelated / "keep"
    sentinel.write_text("existing user work")
    with pytest.raises(ValueError, match="basetemp"):
        module.run_recovery_gate(
            repo=repo, artifact_dir=output, basetemp=unrelated, execute=execute, source_state=lambda _: state
        )
    assert sentinel.read_text() == "existing user work"
    assert not output.exists()
    assert not calls


@pytest.mark.parametrize("shape", ["existing-output", "symlink-parent"])
def test_unowned_output_is_refused_before_execution(subject, tmp_path, shape):
    module, repo, output, state, execute, calls = subject
    if shape == "existing-output":
        output.mkdir()
        (output / "keep").write_text("existing evidence")
    else:
        link = tmp_path / "linked"
        link.symlink_to(tmp_path, target_is_directory=True)
        output = link / "new-output"
    with pytest.raises(ValueError, match=r"artifact directory|symlink"):
        module.run_recovery_gate(
            repo=repo,
            artifact_dir=output,
            basetemp=output / "pytest-temp",
            execute=execute,
            source_state=lambda _: state,
        )
    assert not calls
    if shape == "existing-output":
        assert (output / "keep").read_text() == "existing evidence"


def test_duplicate_inventory_keys_cannot_replace_selected_authority(subject):
    _, repo, output, _, _, calls = subject
    target = repo / INVENTORY
    target.write_text('{"seed":0,' + target.read_text()[1:])
    with pytest.raises(ValueError, match="duplicate"):
        run(subject)
    assert not output.exists()
    assert not calls


def test_duplicate_arrival_keys_cannot_be_hidden_by_a_recomputed_hash(subject):
    _, _, output, _, execute, _ = subject

    def duplicate(argv, cwd, log, environment):
        code = execute(argv, cwd, log, environment)
        marker = next((output / "restarts").glob("*.arrival.json"))
        raw = b'{"pid":1,' + marker.read_bytes()[1:]
        marker.write_bytes(raw)
        evidence = marker.with_name(marker.name.removesuffix(".arrival.json") + ".json")
        record = json.loads(evidence.read_text())
        record["marker_sha256"] = hashlib.sha256(raw).hexdigest()
        evidence.write_text(json.dumps(record))
        return code

    result = run(subject, duplicate)
    assert result["status"] == "FAIL"
