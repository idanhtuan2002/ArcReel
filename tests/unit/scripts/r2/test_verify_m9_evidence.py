"""M9 foundation evidence must bind complete successful gates to one code HEAD."""

import copy
import json
from pathlib import Path

import pytest

from scripts.r2.verify_m9_evidence import verify_m9_evidence

ROOT = Path(__file__).resolve().parents[4]
HEAD = "a" * 40
PARENT = "b" * 40
H = "c" * 64


def evidence():
    gates = [
        "ruff",
        "format",
        "types",
        "imports",
        "dependencies",
        "tests",
        "audit",
        "diff",
        "scope",
        "migration",
        "parity",
    ]
    artifact = {"path": "/tmp/m9-fixture.log", "sha256": H}
    bindings = {
        "tested_parent": PARENT,
        "branch": "impl/r2-m9a-opportunity-foundation",
        "baseline_sha256": H,
        "documents": {"spec.md": H},
        "contracts": {"r2/contracts/opportunity.py": H},
        "seams": {"r2/contracts/advanced_creative.py": H},
        "migration": {
            "path": "alembic/versions/foundation.py",
            "sha256": H,
            "head": "9a9c4a0e0001",
            "predecessor": "918c4a0e0001",
        },
        "scope_allowlist": ["r2/contracts/opportunity.py"],
        "donor_inventory": [{"name": "fixture", "commit": "d" * 40, "files": {"donor.py": H}}],
    }
    commands = [
        {
            "gate": gate,
            "command": gate,
            "exit": 0,
            "tested_head": HEAD,
            "passed": 1 if gate == "tests" else 0,
            "skipped": 0,
            "log": artifact,
            "result": artifact,
        }
        for gate in gates
    ]
    proof = {"status": "PASS", "command_gate": "tests", "test_refs": ["test_exact_replay"]}
    return {
        "schema_version": "1",
        "status": "M9_A_CANDIDATE",
        "packet": "M9-A",
        "parity_scope": "RUNTIME_PARITY",
        "donor_runtime_executed": True,
        "runtime_parity_claimed": True,
        "runtime_ports": ["fixture"],
        "sponsor_amendment": None,
        "tested_head": HEAD,
        **bindings,
        "commands": commands,
        "fault_matrix": {
            name: copy.deepcopy(proof)
            for name in ("replay", "scope", "custody", "rollback", "integrity", "concurrency", "architecture")
        },
        "required_skips": [],
        "material_unknowns": [],
        "graph_coverage": {
            "project": "r2-m9a",
            "generation": "2026-10-16T00:00:00Z",
            "signal": "best_effort",
            "paths": ["r2/contracts/opportunity.py"],
            "source_fallback": ["r2/contracts/opportunity.py"],
            "artifact": artifact,
        },
        "artifacts": [artifact],
        "test_report": artifact,
        "migration_report": artifact,
        "parity_reports": [artifact],
        "independent_review": {"status": "PENDING", "approval_claimed": False},
        "created_at": "2026-10-16T00:00:00Z",
    }, bindings


def verify(document, bindings):
    schema = json.loads((ROOT / "docs/r2/evidence/schemas/R2_M9_A_FOUNDATION.schema.json").read_text())
    return verify_m9_evidence(document, schema, HEAD, bindings)


def test_complete_candidate_does_not_claim_independent_acceptance():
    document, bindings = evidence()
    assert verify(document, bindings) == []


@pytest.mark.parametrize("field", list(evidence()[0]))
def test_every_top_level_evidence_field_is_required(field):
    document, bindings = evidence()
    del document[field]
    assert verify(document, bindings)


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "pass",
        "independent",
        "head",
        "parent",
        "branch",
        "binding",
        "skip",
        "unknown",
        "failed",
        "zero_tests",
        "missing_gate",
        "duplicate_gate",
        "stale_command",
        "unhashed_log",
        "unlisted_log",
        "missing_fault",
        "false_fault",
        "unknown_fault_gate",
        "uncovered_source",
    ],
)
def test_refuses_false_or_incomplete_proof(mutation):
    document, bindings = evidence()
    if mutation == "extra":
        document["unknown"] = True
    elif mutation == "pass":
        document["status"] = "PASS"
    elif mutation == "independent":
        document["independent_review"]["approval_claimed"] = True
    elif mutation == "head":
        document["tested_head"] = PARENT
    elif mutation in {"parent", "branch", "binding"}:
        field = {"parent": "tested_parent", "branch": "branch", "binding": "contracts"}[mutation]
        document[field] = "wrong"
    elif mutation == "skip":
        document["required_skips"] = ["custody"]
    elif mutation == "unknown":
        document["material_unknowns"] = ["concurrency"]
    elif mutation == "failed":
        document["commands"][0]["exit"] = 1
    elif mutation == "zero_tests":
        document["commands"][5]["passed"] = 0
    elif mutation == "missing_gate":
        document["commands"].pop()
    elif mutation == "duplicate_gate":
        document["commands"].append(document["commands"][0])
    elif mutation == "stale_command":
        document["commands"][0]["tested_head"] = PARENT
    elif mutation == "unhashed_log":
        document["commands"][0]["log"]["sha256"] = "wrong"
    elif mutation == "unlisted_log":
        document["artifacts"] = [{"path": "other", "sha256": H}]
    elif mutation == "missing_fault":
        del document["fault_matrix"]["concurrency"]
    elif mutation == "false_fault":
        document["fault_matrix"]["custody"]["status"] = "PASS_BUT_SKIPPED"
    elif mutation == "unknown_fault_gate":
        document["fault_matrix"]["custody"]["command_gate"] = "missing"
    else:
        document["graph_coverage"]["paths"] = ["unrelated.py"]
    assert verify(document, bindings)


@pytest.mark.parametrize("field", list(evidence()[1]))
def test_each_immutable_binding_is_recomputed(field):
    document, bindings = evidence()
    bindings[field] = "changed"
    assert verify(document, bindings)


def test_retained_log_bytes_and_logical_counts_are_checked(tmp_path):
    import hashlib

    from scripts.r2.verify_m9_evidence import command_log_problems as recorded_log_problems

    document, _ = evidence()
    path = tmp_path / "test.log"
    path.write_text("1 passed in 0.5s\n")
    artifact = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    document["artifacts"] = [artifact]
    document["commands"][9]["passed"] = 1
    for command in document["commands"]:
        command["log"] = artifact
    assert recorded_log_problems(document, tmp_path) == []
    document["commands"][5]["passed"] = 2
    assert recorded_log_problems(document, tmp_path)
    document["commands"][5]["passed"] = 1
    path.write_text("0 passed\n")
    assert any("sha256" in problem for problem in recorded_log_problems(document, tmp_path))
    path.unlink()
    assert any("missing" in problem for problem in recorded_log_problems(document, tmp_path))


def test_matching_pytest_count_does_not_prove_unexecuted_faults_or_arbitrary_graph_bytes(tmp_path):
    import hashlib

    from scripts.r2.verify_m9_evidence import recorded_log_problems

    document, _ = evidence()
    log = tmp_path / "unrelated.log"
    log.write_text("1 passed in 0.1s\n")
    artifact = {"path": str(log), "sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
    document["artifacts"] = [artifact]
    document["graph_coverage"]["artifact"] = artifact
    for command in document["commands"]:
        command["log"] = artifact
    assert recorded_log_problems(document, tmp_path)


def physical_proof_fixture(tmp_path):
    import hashlib
    import shlex
    import xml.etree.ElementTree as ET

    from scripts.r2.verify_m9_evidence import CONTRACT, FAULT_TESTS, MIGRATION_CASES, MIGRATION_TEST_PATH

    document, _ = evidence()
    document["artifacts"] = []

    def artifact(name, raw):
        path = tmp_path / name
        path.write_bytes(raw)
        ref = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
        document["artifacts"].append(ref)
        return ref

    def junit(identities):
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite")
        for identity in sorted(identities):
            module, name = identity.split("::")
            ET.SubElement(suite, "testcase", classname=module, name=name)
        return ET.tostring(root)

    identities = {"tests.test_profile_fixture::test_exact_replay", *MIGRATION_CASES}
    for anchors in FAULT_TESTS.values():
        identities.update(anchors)
    document["test_report"] = artifact("tests.xml", junit(identities))
    document["migration_report"] = artifact("migration.xml", junit(MIGRATION_CASES))
    document["parity_reports"] = [artifact("donor-report.json", b"{}")]
    for category, anchors in FAULT_TESTS.items():
        document["fault_matrix"][category]["test_refs"] = sorted(anchors)
    logs = {
        "tests": artifact("tests.log", f"{len(identities)} passed in 0.1s\n".encode()),
        "migration": artifact("migration.log", b"2 passed in 0.1s\n"),
        "other": artifact("gate.log", b"gate completed\n"),
    }
    recipes = {
        "ruff": ["ruff", "check", "."],
        "format": ["ruff", "format", "--check", "."],
        "types": ["basedpyright", "--warnings"],
        "imports": ["lint-imports"],
        "dependencies": ["deptry", "lib", "server", "alembic", "scripts", "tests", "r2"],
        "tests": ["python", "-m", "pytest", "tests", "--junitxml=" + document["test_report"]["path"]],
        "migration": [
            "python",
            "-m",
            "pytest",
            MIGRATION_TEST_PATH,
            "--junitxml=" + document["migration_report"]["path"],
        ],
        "audit": ["python", "scripts/audit_tests.py", "--check"],
        "diff": ["git", "diff", "--check"],
        "scope": ["python", "scripts/r2/verify_m9_scope.py", CONTRACT],
        "parity": [
            "python",
            "scripts/r2/verify_m9_parity.py",
            document["parity_reports"][0]["path"],
            "--head",
            HEAD,
            "--donor-clone",
            str(tmp_path / "OpenMontage.git"),
        ],
    }
    for command in document["commands"]:
        gate = command["gate"]
        command["log"] = logs.get(gate, logs["other"])
        command["passed"] = len(identities) if gate == "tests" else 2 if gate == "migration" else 0
        argv = recipes[gate]
        command["command"] = shlex.join(argv)
        report = (
            document["test_report"]
            if gate == "tests"
            else document["migration_report"]
            if gate == "migration"
            else None
        )
        result = {
            "schema_version": "m9.command-result.v1",
            "gate": gate,
            "tested_head": HEAD,
            "argv": argv,
            "exit": 0,
            "passed": command["passed"],
            "skipped": 0,
            "log": command["log"],
            "test_report": report,
        }
        command["result"] = artifact(gate + "-result.json", json.dumps(result).encode())
    source = {"r2/contracts/opportunity.py": b"immutable contract source"}
    for identity in sorted(identities):
        module, name = identity.split("::")
        path = module.replace(".", "/") + ".py"
        source[path] = source.get(path, b"") + f"def {name}(): pass\n".encode()
    document["scope_allowlist"] = sorted(source)
    document["graph_coverage"]["paths"] = sorted(source)
    rows = [
        {"path": path, "status": "no_recorded_issue", "freshness": "metadata_match", "coverage": []}
        for path in sorted(source)
    ]
    rows[0].update(status="excluded", freshness="not_tracked", coverage=[{"kind": "not_indexed_dir"}])
    snapshot = {
        "project": "r2-m9a",
        "signal": "best_effort",
        "tested_head": HEAD,
        "indexed_at": document["graph_coverage"]["generation"],
        "metadata": {
            "generation": document["graph_coverage"]["generation"],
            "generation_matches": True,
            "recording_status": "complete",
        },
        "paths": rows,
        "source_fallback_reads": {
            "r2/contracts/opportunity.py": hashlib.sha256(source["r2/contracts/opportunity.py"]).hexdigest()
        },
    }
    document["graph_coverage"]["artifact"] = artifact("graph.json", json.dumps(snapshot).encode())
    return document, source


def replace_physical_artifact(reference, mutate):
    import hashlib

    path = Path(reference["path"])
    raw = path.read_bytes()
    path.write_bytes(mutate(raw))
    reference["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


def test_physical_fault_and_graph_proofs_are_parsed_and_bound_to_tested_code(tmp_path):
    from scripts.r2.verify_m9_evidence import recorded_log_problems

    document, source = physical_proof_fixture(tmp_path)
    assert recorded_log_problems(document, tmp_path, source) == []


@pytest.mark.parametrize(
    "mutation",
    [
        "unexecuted_fault",
        "failed_case",
        "skipped_case",
        "wrong_count",
        "duplicate_case",
        "graph_project",
        "graph_generation",
        "graph_head",
        "graph_missing_path",
        "graph_missing_fallback",
        "graph_changed_source",
        "graph_pending",
        "graph_unrecorded_gap",
        "result_head",
        "result_exit",
        "result_argv",
        "result_count",
    ],
)
def test_rejects_semantically_fabricated_proof_even_after_hashes_are_updated(tmp_path, mutation):
    from scripts.r2.verify_m9_evidence import recorded_log_problems

    document, source = physical_proof_fixture(tmp_path)
    if mutation == "unexecuted_fault":
        document["fault_matrix"]["custody"]["test_refs"] = ["tests.never::test_executed"]
    elif mutation in {"failed_case", "skipped_case", "duplicate_case"}:

        def change_junit(raw):
            if mutation == "duplicate_case":
                return raw.replace(
                    b"</testsuite>", b'<testcase classname="tests.profile" name="test_exact_replay"/></testsuite>'
                )
            tag = b"failure" if mutation == "failed_case" else b"skipped"
            return raw.replace(b"/>", b"><" + tag + b"/></testcase>", 1)

        replace_physical_artifact(document["test_report"], change_junit)
    elif mutation == "wrong_count":
        document["commands"][5]["passed"] = 2
    elif mutation.startswith("graph_"):

        def change_graph(raw):
            snapshot = json.loads(raw)
            if mutation == "graph_project":
                snapshot["project"] = "foreign"
            elif mutation == "graph_generation":
                snapshot["metadata"]["generation"] = "2025-01-01T00:00:00Z"
            elif mutation == "graph_head":
                snapshot["tested_head"] = PARENT
            elif mutation == "graph_missing_path":
                snapshot["paths"] = []
            elif mutation == "graph_missing_fallback":
                snapshot["source_fallback_reads"] = {}
            elif mutation == "graph_changed_source":
                snapshot["source_fallback_reads"]["r2/contracts/opportunity.py"] = H
            elif mutation == "graph_pending":
                snapshot["metadata"]["recording_status"] = "pending"
            else:
                snapshot["paths"][0].update(status="no_recorded_issue", freshness="metadata_match")
                document["graph_coverage"]["source_fallback"] = []
                snapshot["source_fallback_reads"] = {}
            return json.dumps(snapshot).encode()

        replace_physical_artifact(document["graph_coverage"]["artifact"], change_graph)
    else:

        def change_result(raw):
            result = json.loads(raw)
            if mutation == "result_head":
                result["tested_head"] = PARENT
            elif mutation == "result_exit":
                result["exit"] = 1
            elif mutation == "result_argv":
                result["argv"] = ["unrelated-command"]
            else:
                result["passed"] = 0
            return json.dumps(result).encode()

        replace_physical_artifact(document["commands"][5]["result"], change_result)
    assert recorded_log_problems(document, tmp_path, source)


def test_foundation_parity_gate_folds_real_report_artifacts_instead_of_a_named_log(tmp_path):
    from scripts.r2.verify_m9_evidence import recorded_parity_problems

    document, _ = physical_proof_fixture(tmp_path)
    assert recorded_parity_problems(document, tmp_path, tmp_path)


@pytest.mark.parametrize(
    ("gate", "argv"),
    [
        ("ruff", ("true",)),
        ("types", ("echo", "0 errors")),
        ("tests", ("python", "-m", "pytest", "tests", "-k", "one_case")),
        ("tests", ("pytest", "tests/unrelated")),
        ("tests", ("pytest", "tests", "--keyword", "one_case")),
        ("tests", ("pytest", "/tmp/unrelated.py")),
    ],
)
def test_gate_names_cannot_relabel_unrelated_commands_or_partial_tests(gate, argv):
    from scripts.r2.verify_m9_evidence import command_shape_problems

    document, _ = evidence()
    document["scope_allowlist"] = ["tests/test_profile_fixture.py"]
    assert command_shape_problems(gate, argv, document)


def test_owned_test_functions_are_derived_from_immutable_source_not_declared_refs(tmp_path):
    from scripts.r2.verify_m9_evidence import recorded_log_problems

    document, source = physical_proof_fixture(tmp_path)
    source["tests/test_profile_fixture.py"] += b"def test_other_case(): pass\n"
    assert any("omits an owned test function" in item for item in recorded_log_problems(document, tmp_path, source))


def test_foundation_parity_gate_recomputes_the_pair_from_retained_output_bytes(tmp_path, monkeypatch):
    import hashlib

    from scripts.r2 import verify_m9_evidence as verifier
    from tests.unit.scripts.r2.test_verify_m9_parity import execution_fixture, install_fixture_harness, report_fixture

    document, _ = evidence()
    body, hashes = report_fixture()
    for name, raw in execution_fixture(body).items():
        (tmp_path / name).write_bytes(raw)
    report = tmp_path / "donor-report.json"
    report.write_text(json.dumps(body))
    document["donor_inventory"] = [{"name": "OpenMontage", "commit": body["donor"]["commit_sha"], "files": hashes}]
    document["parity_reports"] = [{"path": str(report), "sha256": hashlib.sha256(report.read_bytes()).hexdigest()}]
    monkeypatch.setattr(verifier, "clone_file_hashes", lambda *_: hashes)
    install_fixture_harness(body, monkeypatch)
    assert verifier.recorded_parity_problems(document, tmp_path, tmp_path) == []
    (tmp_path / "r2.json").write_bytes(b"unrelated bytes")
    assert verifier.recorded_parity_problems(document, tmp_path, tmp_path)


@pytest.mark.parametrize("gate", ["scope", "migration", "parity"])
def test_focused_gate_cannot_be_relabelled_from_true(gate):
    from scripts.r2.verify_m9_evidence import command_shape_problems

    document, _ = evidence()
    assert command_shape_problems(gate, ("true",), document)


def test_pytest_output_path_must_be_the_bound_junit_artifact():
    from scripts.r2.verify_m9_evidence import command_shape_problems

    document, _ = evidence()
    document["test_report"] = {"path": "/tmp/expected.xml", "sha256": H}
    assert command_shape_problems("tests", ("pytest", "tests", "--junitxml=/tmp/unrelated.xml"), document)


def test_one_passing_test_cannot_be_reused_as_every_fault_category(tmp_path):
    from scripts.r2.verify_m9_evidence import recorded_log_problems

    document, source = physical_proof_fixture(tmp_path)
    for proof in document["fault_matrix"].values():
        proof["test_refs"] = ["tests.test_profile_fixture::test_exact_replay"]
    assert recorded_log_problems(document, tmp_path, source)


def test_command_result_must_bind_the_exact_junit_reference(tmp_path):
    from scripts.r2.verify_m9_evidence import recorded_log_problems

    document, source = physical_proof_fixture(tmp_path)

    def change(raw):
        result = json.loads(raw)
        result["test_report"] = document["migration_report"]
        return json.dumps(result).encode()

    replace_physical_artifact(document["commands"][5]["result"], change)
    assert any("exact JUnit" in problem for problem in recorded_log_problems(document, tmp_path, source))


def test_an_unrelated_junit_with_identical_cases_cannot_replace_the_command_output(tmp_path):
    import hashlib

    from scripts.r2.verify_m9_evidence import recorded_log_problems

    document, source = physical_proof_fixture(tmp_path)
    path = tmp_path / "unrelated.xml"
    path.write_bytes(Path(document["test_report"]["path"]).read_bytes())
    ref = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    document["test_report"] = ref
    document["artifacts"].append(ref)
    assert any("output path differs" in problem for problem in recorded_log_problems(document, tmp_path, source))


def test_migration_wrapper_cannot_omit_a_step_check_even_with_matching_counts(tmp_path):
    import xml.etree.ElementTree as ET

    from scripts.r2.verify_m9_evidence import recorded_log_problems

    document, source = physical_proof_fixture(tmp_path)
    command = next(item for item in document["commands"] if item["gate"] == "migration")

    def remove_case(raw):
        root = ET.fromstring(raw)
        suite = root.find("testsuite")
        assert suite is not None
        suite.remove(next(iter(suite)))
        return ET.tostring(root)

    replace_physical_artifact(document["migration_report"], remove_case)
    replace_physical_artifact(command["log"], lambda _: b"1 passed in 0.1s\n")
    command["passed"] = 1

    def change_result(raw):
        result = json.loads(raw)
        result.update(passed=1, log=command["log"], test_report=document["migration_report"])
        return json.dumps(result).encode()

    replace_physical_artifact(command["result"], change_result)
    assert any("round-trip/head check" in problem for problem in recorded_log_problems(document, tmp_path, source))


@pytest.mark.parametrize("mutation", ["packet", "runtime", "claim", "ports", "approval", "reports"])
def test_foundation_candidate_cannot_broaden_the_approved_exception(mutation):
    from scripts.r2.verify_m9_scope import AMENDMENT, AMENDMENT_COMMIT

    document, bindings = evidence()
    document.update(
        {
            "parity_scope": "FOUNDATION_INVENTORY_VERIFIED",
            "donor_runtime_executed": False,
            "runtime_parity_claimed": False,
            "runtime_ports": [],
            "sponsor_amendment": {"path": AMENDMENT, "sha256": H, "commit": AMENDMENT_COMMIT},
        }
    )
    assert verify(document, bindings) == []
    if mutation == "packet":
        document["packet"] = "M9-B"
    elif mutation == "runtime":
        document["donor_runtime_executed"] = True
    elif mutation == "claim":
        document["runtime_parity_claimed"] = True
    elif mutation == "ports":
        document["runtime_ports"] = ["research"]
    elif mutation == "approval":
        document["sponsor_amendment"] = None
    else:
        document["parity_reports"] *= 2
    assert verify(document, bindings)
