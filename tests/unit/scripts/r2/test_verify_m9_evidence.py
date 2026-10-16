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
        }
        for gate in gates
    ]
    proof = {"status": "PASS", "command_gate": "tests", "test_refs": ["test_exact_replay"]}
    return {
        "schema_version": "1",
        "status": "M9_A_CANDIDATE",
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

    from scripts.r2.verify_m9_evidence import recorded_log_problems

    document, _ = evidence()
    path = tmp_path / "test.log"
    path.write_text("1 passed in 0.5s\n")
    artifact = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    document["artifacts"] = [artifact]
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
