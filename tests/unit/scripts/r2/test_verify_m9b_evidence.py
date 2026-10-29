"""M9-B candidate evidence must bind complete successful gates and retained artifacts to one clean code HEAD."""

import copy
import hashlib
import json
import shlex
from pathlib import Path

import pytest

from scripts.r2 import verify_m9b_evidence as m9b
from scripts.r2.verify_m9b_evidence import verify_m9b_evidence

ROOT = Path(__file__).resolve().parents[4]
HEAD = "a" * 40
PARENT = "b" * 40
CHILD = "c" * 40
ART = m9b.ARTIFACT_ROOT
PY = "/venv/bin/python"
RUNTIME = "r2/opportunity/acquisition_v2.py"
UNIT = "tests/unit/scripts/r2/test_fixture_only.py"
MIGRATION = "tests/integration/lib/db/migrations/test_fixture_migration.py"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _modules() -> dict[str, list[str]]:
    modules: dict[str, list[str]] = {}
    for anchors in m9b.FAULT_TESTS.values():
        for anchor in anchors:
            module, function = anchor.split("::")
            modules.setdefault(module.replace(".", "/") + ".py", []).append(function)
    modules[UNIT] = ["test_unit_fixture"]
    modules[MIGRATION] = ["test_migration_fixture"]
    for path in m9b.REQUIRED_REGRESSIONS:
        modules.setdefault(path, ["test_regression_fixture"])
    return modules


def _junit(identities: list[str]) -> bytes:
    cases = "".join(
        f'<testcase classname="{identity.split("::")[0]}" name="{identity.split("::")[1]}" time="0.1"/>'
        for identity in identities
    )
    return f'<?xml version="1.0"?><testsuites><testsuite tests="{len(identities)}">{cases}</testsuite></testsuites>'.encode()


class FakeView:
    """Fixed repository and artifact bytes standing in for Git and the retained artifact directory."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.artifacts: dict[str, bytes] = {}
        self.evidences: dict[str, bytes] = {}
        self.current = HEAD
        self.child_changes: set[str] = set()
        self.inventory: list[str] = []

    def blob(self, ref: str, path: str) -> bytes:
        if ref != HEAD:
            raise KeyError(ref)
        return self.blobs[path]

    def parents(self, ref: str) -> list[str]:
        return {HEAD: [PARENT], CHILD: [HEAD]}.get(ref, [])

    def head(self) -> str:
        return self.current

    def changed(self, base: str, head: str) -> set[str]:
        assert (base, head) == (HEAD, self.current)
        return self.child_changes

    def artifact(self, path: str) -> bytes:
        if not path.startswith(ART):
            raise ValueError(path)
        if path not in self.artifacts:
            raise FileNotFoundError(path)
        return self.artifacts[path]

    def evidence(self, path: str) -> bytes:
        return self.evidences[path]

    def tree_sha256(self, ref: str) -> dict[str, str]:
        assert ref == HEAD
        return {path: sha(raw) for path, raw in self.blobs.items()}

    def collected(self, paths) -> list[str]:
        modules = [path.removesuffix(".py").replace("/", ".") for path in paths]
        return [
            identity
            for identity in self.inventory
            if any(identity.split("::")[0] == module or identity.startswith(module + ".") for module in modules)
        ]


def schema(name: str) -> dict:
    return json.loads((ROOT / "docs/r2/evidence/schemas" / name).read_text(encoding="utf-8"))


def candidate() -> tuple[FakeView, dict]:
    view = FakeView()
    modules = _modules()
    for path, functions in modules.items():
        view.blobs[path] = "".join(f"def {name}():\n    pass\n\n\n" for name in functions).encode()
    view.blobs[RUNTIME] = b"from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey\n"
    owned = sorted({*modules, RUNTIME} - set(m9b.REQUIRED_REGRESSIONS))
    view.blobs[m9b.ORIGINAL_RELEASE] = json.dumps({"owned_create_paths": owned[:3], "owned_modify_paths": []}).encode()
    view.blobs[m9b.RECOVERY_RELEASE] = json.dumps(
        {"owned_create_paths": owned[3:], "owned_modify_paths": [], "inherited_unimplemented_create_paths": []}
    ).encode()
    tests = [path for path in modules if not path.startswith(m9b.MIGRATION_DIRECTORY)]
    unit_ids = [path.removesuffix(".py").replace("/", ".") + "::" + name for path in tests for name in modules[path]]
    migration_ids = [MIGRATION.removesuffix(".py").replace("/", ".") + "::test_migration_fixture"]
    view.inventory = [*unit_ids, *migration_ids]
    test_report = {"path": ART + "tests.junit.xml", "sha256": ""}
    migration_report = {"path": ART + "migration.junit.xml", "sha256": ""}
    reports = {"tests": (_junit(unit_ids), test_report), "migration": (_junit(migration_ids), migration_report)}
    for raw, ref in reports.values():
        view.artifacts[ref["path"]] = raw
        ref["sha256"] = sha(raw)
    argv = {
        "ruff": ["/venv/bin/ruff", "check", "."],
        "format": ["/venv/bin/ruff", "format", "--check", "."],
        "types": ["/venv/bin/basedpyright", "--warnings"],
        "imports": ["/venv/bin/lint-imports"],
        "dependencies": ["/venv/bin/deptry", "lib", "server", "alembic", "scripts", "tests", "r2"],
        "audit": [PY, "scripts/audit_tests.py", "--check"],
        "diff": ["git", "diff", "--check"],
        "scope": [PY, *m9b.SCOPE_COMMAND],
        "tests": [PY, "-m", "pytest", *tests, "-n", "4", "-q", "--junitxml=/repo/" + test_report["path"]],
        "migration": [
            PY,
            "-m",
            "pytest",
            m9b.MIGRATION_DIRECTORY,
            "-q",
            "--junitxml=/repo/" + migration_report["path"],
        ],
    }
    commands = []
    for gate, args in argv.items():
        passed = {"tests": len(unit_ids), "migration": 1}.get(gate, 0)
        log = f"{passed} passed in 1.0s\n".encode() if gate in reports else b"ok\n"
        log_ref = {"path": ART + gate + ".log", "sha256": sha(log)}
        view.artifacts[log_ref["path"]] = log
        result = {
            "schema_version": "m9.command-result.v1",
            "gate": gate,
            "tested_head": HEAD,
            "argv": args,
            "exit": 0,
            "passed": passed,
            "skipped": 0,
            "log": log_ref,
            "test_report": reports[gate][1] if gate in reports else None,
        }
        raw = json.dumps(result).encode()
        result_ref = {"path": ART + gate + ".result.json", "sha256": sha(raw)}
        view.artifacts[result_ref["path"]] = raw
        commands.append(
            {
                "gate": gate,
                "command": shlex.join(args),
                "exit": 0,
                "tested_head": HEAD,
                "passed": passed,
                "skipped": 0,
                "log": log_ref,
                "result": result_ref,
            }
        )
    document = {
        "schema_version": "1",
        "status": "M9_B_CANDIDATE",
        "packet": "M9-B",
        "tested_head": HEAD,
        "tested_parent": PARENT,
        "branch": m9b.BRANCH,
        "releases": {path: sha(view.blobs[path]) for path in (m9b.ORIGINAL_RELEASE, m9b.RECOVERY_RELEASE)},
        "sources": {path: sha(view.blobs[path]) for path in owned},
        "commands": commands,
        "test_report": test_report,
        "migration_report": migration_report,
        "fault_matrix": {category: {"test_refs": sorted(anchors)} for category, anchors in m9b.FAULT_TESTS.items()},
        "full_backend": {"executed": False, "reason": "sponsor rule: related tests only"},
        "runtime_signing_key_dependency": False,
        "production_activation_authorized": False,
        "provider_network_executed": False,
        "independent_review": {"budget": 1, "used": 0},
        "graph_coverage": {"method": "direct-read fallback", "paths": owned},
        "required_skips": [],
        "material_unknowns": [],
        "artifacts": [{"path": path, "sha256": sha(raw)} for path, raw in sorted(view.artifacts.items())],
        "limits": [],
        "created_at": "2026-10-29T12:00:00Z",
    }
    return view, document


def problems(view, document):
    return verify_m9b_evidence(document, schema("R2_M9_B_ACQUISITION.schema.json"), view, HEAD)


def test_the_complete_fixture_candidate_passes():
    view, document = candidate()
    assert problems(view, document) == []


def _retain(view, document, path, raw):
    view.artifacts[path] = raw
    for item in document["artifacts"]:
        if item["path"] == path:
            item["sha256"] = sha(raw)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda v, d: d.update(extra=True), "schema:"),
        (lambda v, d: d.pop("fault_matrix"), "schema:"),
        (lambda v, d: d.update(tested_head=CHILD), "tested_head"),
        (lambda v, d: d.update(tested_parent=CHILD), "immutable binding mismatch: tested_parent"),
        (lambda v, d: d["sources"].update({RUNTIME: "0" * 64}), "immutable binding mismatch: sources"),
        (lambda v, d: d["sources"].pop(UNIT), "immutable binding mismatch: sources"),
        (lambda v, d: d["releases"].update({m9b.ORIGINAL_RELEASE: "0" * 64}), "immutable binding mismatch: releases"),
        (lambda v, d: d["commands"].pop(), "required gates are missing"),
        (lambda v, d: d["commands"].append(copy.deepcopy(d["commands"][0])), "required gates are missing"),
        (lambda v, d: d["commands"][0].update(exit=1), "did not exit 0"),
        (lambda v, d: d["commands"][8].update(passed=99), "machine command result differs"),
        (lambda v, d: d["commands"][8].update(command="pytest tests"), "machine command result differs"),
        (lambda v, d: v.artifacts.update({ART + "tests.log": b"tampered"}), "does not match its recorded hash"),
        (lambda v, d: v.artifacts.pop(ART + "ruff.result.json"), "retained artifact is absent"),
        (lambda v, d: d.update(required_skips=["x"]), "required_skips is not empty"),
        (lambda v, d: d.update(material_unknowns=["x"]), "material_unknowns is not empty"),
        (lambda v, d: d.update(production_activation_authorized=True), "production_activation_authorized"),
        (lambda v, d: d.update(provider_network_executed=True), "provider_network_executed"),
        (lambda v, d: d.update(runtime_signing_key_dependency=True), "runtime signing key dependency is claimed"),
        (lambda v, d: d["independent_review"].update(used=1), "independent review budget"),
        (lambda v, d: d["independent_review"].update(budget=2), "independent review budget"),
        (lambda v, d: d["fault_matrix"]["replay"]["test_refs"].pop(), "fault category replay"),
        (lambda v, d: d["fault_matrix"].update(invented={"test_refs": ["x"]}), "unknown category"),
        (lambda v, d: d["full_backend"].update(executed=True), "full backend is claimed"),
    ],
)
def test_tampered_or_incomplete_evidence_is_refused(mutate, expected):
    view, document = candidate()
    mutate(view, document)
    found = problems(view, document)
    assert any(expected in problem for problem in found), found


def _forge_log(view, document, gate, raw):
    """Rewrite one gate's log and every hash that binds it, as a forger with write access would."""
    command = next(item for item in document["commands"] if item["gate"] == gate)
    _retain(view, document, command["log"]["path"], raw)
    command["log"]["sha256"] = sha(raw)
    result = json.loads(view.artifacts[command["result"]["path"]])
    result["log"]["sha256"] = sha(raw)
    forged = json.dumps(result).encode()
    _retain(view, document, command["result"]["path"], forged)
    command["result"]["sha256"] = sha(forged)


def test_fake_junit_and_log_counts_are_refused_even_when_rehashed():
    view, document = candidate()
    _retain(view, document, ART + "tests.junit.xml", _junit(["tests.unit.fake::test_other"]))
    document["test_report"]["sha256"] = sha(view.artifacts[ART + "tests.junit.xml"])
    found = problems(view, document)
    assert any("JUnit" in problem or "result does not bind" in problem for problem in found), found
    view, document = candidate()
    _forge_log(view, document, "tests", b"3 passed, 1 failed in 1.0s\n")
    found = problems(view, document)
    assert any("test log" in problem for problem in found), found
    view, document = candidate()
    _forge_log(view, document, "migration", b"no summary\n")
    found = problems(view, document)
    assert any("migration: test log summary differs" in problem for problem in found), found


def test_a_failed_junit_case_is_refused():
    view, document = candidate()
    raw = view.artifacts[ART + "migration.junit.xml"].replace(b' time="0.1"/>', b' time="0.1"><failure/></testcase>')
    _retain(view, document, ART + "migration.junit.xml", raw)
    document["migration_report"]["sha256"] = sha(raw)
    found = problems(view, document)
    assert found, found


@pytest.mark.parametrize(
    ("gate", "argv", "expected"),
    [
        (
            "tests",
            [PY, "-m", "pytest", UNIT, "--junitxml=/repo/" + ART + "tests.junit.xml"],
            "omits an owned test file",
        ),
        ("tests", [PY, "-m", "pytest", UNIT + "::test_unit_fixture"], "partial selection"),
        (
            "migration",
            [PY, "-m", "pytest", MIGRATION, "--junitxml=/repo/" + ART + "migration.junit.xml"],
            "complete directory",
        ),
        ("scope", [PY, "scripts/r2/verify_m9b_scope.py"], "focused command mismatch"),
        ("ruff", ["/venv/bin/ruff", "check", "scripts"], "does not execute its declared gate"),
    ],
)
def test_gate_commands_must_run_the_complete_declared_gate(gate, argv, expected):
    _, document = candidate()
    found = m9b.command_shape_problems(gate, tuple(argv), document)
    assert any(expected in problem for problem in found), found


def test_a_runtime_signing_key_import_is_refused():
    view, document = candidate()
    view.blobs[RUNTIME] = b"from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey\n"
    document["sources"][RUNTIME] = sha(view.blobs[RUNTIME])
    found = problems(view, document)
    assert any("private signing key" in problem for problem in found), found


def test_the_evidence_may_only_be_the_sole_evidence_child_of_the_tested_head():
    view, document = candidate()
    view.current = CHILD
    view.child_changes = {m9b.EVIDENCE, ART + "tests.log"}
    assert problems(view, document) == []
    view.child_changes = {m9b.EVIDENCE, RUNTIME}
    assert any("non-evidence paths" in problem for problem in problems(view, document))
    view.current = "d" * 40
    assert any("sole child" in problem for problem in problems(view, document))


def test_an_owned_test_function_missing_from_the_run_is_refused():
    view, document = candidate()
    view.blobs[UNIT] += b"def test_never_ran():\n    pass\n"
    document["sources"][UNIT] = sha(view.blobs[UNIT])
    found = problems(view, document)
    assert any("omit an owned test function" in problem for problem in found), found


def test_the_repository_schema_files_are_strict_and_parse():
    for name in ("R2_M9_B_ACQUISITION.schema.json", "R2_M9_B_RECOVERY_V2.schema.json"):
        body = schema(name)
        assert body["additionalProperties"] is False
        assert set(body["required"]) == set(body["properties"])


def test_a_required_original_b_regression_must_run_in_the_tests_gate():
    _, document = candidate()
    command = next(item for item in document["commands"] if item["gate"] == "tests")
    argv = [part for part in shlex.split(command["command"]) if part != "tests/unit/r2/learning/test_adapters.py"]
    found = m9b.command_shape_problems("tests", tuple(argv), document)
    assert found == ["test command omits an owned test file"]


def test_executed_cases_must_equal_the_collected_inventory_of_the_selected_paths():
    view, document = candidate()
    view.inventory.append("tests.unit.scripts.r2.test_fixture_only::test_unit_fixture[extra-parameter]")
    found = problems(view, document)
    assert any("tests: executed JUnit cases differ from the collected test inventory" in item for item in found), found


def test_selected_paths_ignore_options_and_their_values():
    argv = (PY, "-m", "pytest", "tests/a.py", "-n", "4", "--dist", "loadfile", "-q", "--junitxml=/x", "tests/b/")
    assert m9b.selected_paths(argv) == ["tests/a.py", "tests/b"]
    assert (
        m9b.junit_identity("tests/a/test_b.py::Outer::Inner::test_x[p-1]") == "tests.a.test_b.Outer.Inner::test_x[p-1]"
    )
