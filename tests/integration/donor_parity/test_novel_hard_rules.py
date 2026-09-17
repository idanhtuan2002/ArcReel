from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from r2.narrative_lifecycle import continuity_rules as port
from tests.integration.donor_parity._harness import load_jsonl, run_node_runner

_REPO_ROOT = Path(__file__).parents[3]
_CASES = "tests/integration/donor_parity/fixtures/novel_hard_rules/cases.jsonl"


def test_novel_baseline_manifest_matches_the_pinned_source() -> None:
    manifest = json.loads((_REPO_ROOT / "docs/r2/evidence/R2_M5C_DONOR_BASELINE.json").read_text())
    entry = manifest["ports"]["novel_studio_hard_rules"]
    assert entry["revision"] == "9b690ae2e2f6921f9bd2782b42cef53c1662ad3b"
    assert entry["source_sha256"] == "7756c4093b52e11e3f591c58af1719887428fd5e437f4ade0828533ac3663954"
    vendored = _REPO_ROOT / "tests/integration/donor_parity/vendor" / entry["vendored_path"]
    assert hashlib.sha256(vendored.read_bytes()).hexdigest() == entry["source_sha256"]


def _issue_dict(issue: port.ContinuityIssue) -> dict[str, str]:
    return dataclasses.asdict(issue)


def _model_report(raw: dict) -> port.ContinuityReport:
    return port.ContinuityReport(
        passed=raw["pass"],
        issues=tuple(port.ContinuityIssue(**item) for item in raw["issues"]),
    )


def _py_results(case_input: dict) -> dict[str, object]:
    hard = port.run_hard_rule_checks(case_input["contextPack"], case_input["draftText"])
    merged = port.merge_continuity_reports(_model_report(case_input["modelReport"]), hard)
    return {
        "hard_issues": [_issue_dict(issue) for issue in hard],
        "merged": {"pass": merged.passed, "issues": [_issue_dict(issue) for issue in merged.issues]},
    }


def _node_results(row: dict) -> dict[str, object]:
    return {"hard_issues": row["hard_issues"], "merged": row["merged"]}


@pytest.fixture(scope="session")
def novel_node_baseline(donor_node_env) -> dict[str, dict]:
    return run_node_runner(donor_node_env, "novel_hard_rules_runner.mjs", _CASES)


@pytest.mark.parametrize("case", load_jsonl(_CASES), ids=lambda case: case["id"])
def test_python_port_matches_node_baseline(case: dict, novel_node_baseline: dict[str, dict]) -> None:
    assert _py_results(case["input"]) == _node_results(novel_node_baseline[case["id"]])
