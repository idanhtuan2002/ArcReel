"""verify_upstream_candidate over real pinned Git repositories."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from r2.host_hardening.compatibility import CompatibilityError, parse_gate_log, verify_upstream_candidate
from tests.fixtures.r2.compatibility_reports import (
    EVIDENCE_PATH,
    REQUIRED_GATES,
    commit,
    digest,
    gate_log,
    git,
    recommit_evidence,
    upstream_report,
)


def _verify(report: dict[str, Any], host: Path, upstream: Path) -> str:
    return verify_upstream_candidate(report, host_repo=host, upstream_repo=upstream)


def test_a_complete_pinned_candidate_is_compatible(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path)
    assert _verify(report, host, upstream) == "COMPATIBLE"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda r: r.pop("source_tree_sha"), "source_tree_sha"),
        (lambda r: r.pop("dependency_files"), "dependency_files"),
        (lambda r: r["change_inventory"].clear(), "change_inventory"),
        (lambda r: r["change_inventory"][0].pop("disposition"), "disposition"),
        (lambda r: r["gates"]["migration"].update(status="FAIL"), "migration"),
        (lambda r: r["gates"]["golden_b"].update(required_skips=1), "golden_b"),
        (lambda r: r.pop("rollback_target_sha"), "rollback_target_sha"),
        (lambda r: r.update(evidence_sha="0" * 40), "evidence_sha"),
    ],
)
def test_incomplete_or_failed_evidence_is_incompatible(
    tmp_path: Path, change: Callable[[dict[str, Any]], object], reason: str
) -> None:
    report, host, upstream = upstream_report(tmp_path)
    change(report)
    with pytest.raises(CompatibilityError, match=reason):
        _verify(report, host, upstream)


def test_an_uninventoried_upstream_commit_is_rejected(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path)
    report["new_sha"] = commit(upstream, {"extra.txt": "extra"}, "extra")
    report["source_tree_sha"] = git(upstream, "rev-parse", f"{report['new_sha']}^{{tree}}")
    with pytest.raises(CompatibilityError, match="change_inventory"):
        _verify(report, host, upstream)


def test_a_diverged_old_upstream_pin_is_rejected(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path)
    git(upstream, "checkout", "-q", report["old_sha"])
    report["old_sha"] = commit(upstream, {"other.txt": "diverged"}, "diverged")
    with pytest.raises(CompatibilityError, match=r"old_sha.*merge_base_sha"):
        _verify(report, host, upstream)


def test_a_dirty_host_is_rejected(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path)
    (host / "untracked.txt").write_text("dirty")
    with pytest.raises(CompatibilityError, match="dirty"):
        _verify(report, host, upstream)


def test_a_code_change_after_the_candidate_is_rejected(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path)
    recommit_evidence(report, host, extra={"app.txt": "new code after the tested candidate"})
    with pytest.raises(CompatibilityError, match="non-evidence"):
        _verify(report, host, upstream)


def test_the_report_cannot_relabel_runtime_code_as_evidence(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path)
    report["evidence_sha"] = commit(host, {"candidate.txt": "untested code"}, "code")
    report["change_inventory"][0].update(evidence_path="candidate.txt", evidence_digest=digest("untested code"))
    with pytest.raises(CompatibilityError, match="evidence_path"):
        _verify(report, host, upstream)


def test_the_rollback_target_must_precede_the_candidate(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path)
    report["rollback_target_sha"] = report["host_sha"]
    with pytest.raises(CompatibilityError, match="rollback_target_sha"):
        _verify(report, host, upstream)


def test_a_dependency_checksum_must_match_the_pinned_source(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path)
    report["dependency_files"][0]["sha256"] = "sha256:" + "0" * 64
    with pytest.raises(CompatibilityError, match="dependency_files"):
        _verify(report, host, upstream)


def test_gate_and_disposition_digests_must_match_the_committed_manifest(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path)
    report["gates"]["migration"]["evidence_digest"] = "sha256:" + "0" * 64
    with pytest.raises(CompatibilityError, match=r"migration.*evidence_digest"):
        _verify(report, host, upstream)


def test_a_reported_disposition_must_match_the_committed_manifest(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path)
    recommit_evidence(report, host, changes={report["new_sha"]: "REJECTED"})
    with pytest.raises(CompatibilityError, match=r"change_inventory.*manifest"):
        _verify(report, host, upstream)


def test_gates_cannot_select_conflicting_manifests(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path)
    second = json.loads((host / EVIDENCE_PATH).read_text())
    second_text = json.dumps(second, sort_keys=True) + "\n"
    second_path = "docs/r2/evidence/other-gate-evidence.json"
    report["evidence_sha"] = commit(host, {second_path: second_text}, "second manifest")
    report["gates"]["migration"].update(evidence_path=second_path, evidence_digest=digest(second_text))
    with pytest.raises(CompatibilityError, match="single manifest"):
        _verify(report, host, upstream)


# --- integration proof (S1) -----------------------------------------------------------


def test_an_unchanged_commit_is_proven_by_its_patch_id(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path, disposition="UNCHANGED")
    assert _verify(report, host, upstream) == "COMPATIBLE"


def test_an_unchanged_claim_without_matching_content_is_rejected(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path, disposition="UNCHANGED")
    git(upstream, "checkout", "-q", report["old_sha"])
    other = commit(upstream, {"uv.lock": "other-lock\n"}, "other bump")
    report.update(new_sha=other, source_tree_sha=git(upstream, "rev-parse", f"{other}^{{tree}}"))
    report["dependency_files"][0]["sha256"] = digest("other-lock\n")
    report["change_inventory"][0]["commit_sha"] = other
    recommit_evidence(report, host, changes={other: "UNCHANGED"})
    with pytest.raises(CompatibilityError, match=r"UNCHANGED.*patch id"):
        _verify(report, host, upstream)


def test_an_adapted_claim_needs_a_host_commit_naming_it(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path, name_upstream=False)
    with pytest.raises(CompatibilityError, match=r"ADAPTED.*not named"):
        _verify(report, host, upstream)


def test_a_deferred_commit_must_be_absent_from_the_host(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path, disposition="DEFERRED")
    with pytest.raises(CompatibilityError, match=r"DEFERRED.*present"):
        _verify(report, host, upstream)


def test_a_merge_requires_the_upstream_head_in_the_host_history(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path)
    report["integration_method"] = "MERGE"
    with pytest.raises(CompatibilityError, match="MERGE requires new_sha"):
        _verify(report, host, upstream)


# --- runner-written gate logs (S3) ------------------------------------------------------


def test_a_manifest_pass_needs_the_committed_log_to_agree(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path)
    logs = {gate: gate_log(gate) for gate in REQUIRED_GATES}
    logs["golden_a"] = gate_log("golden_a", exit_code=1)
    recommit_evidence(report, host, logs=logs)
    with pytest.raises(CompatibilityError, match="golden_a log does not show the manifest command exiting 0"):
        _verify(report, host, upstream)


@pytest.mark.parametrize(
    "summary",
    ["", "0 passed in 0.01s", "10 passed, 1 failed in 2.00s", "3 passed, 2 errors in 1.00s"],
    ids=["no-tests", "zero-selected", "failure", "error"],
)
def test_a_test_gate_needs_a_non_empty_passing_run(tmp_path: Path, summary: str) -> None:
    report, host, upstream = upstream_report(tmp_path)
    logs = {gate: gate_log(gate) for gate in REQUIRED_GATES}
    logs["h1_h8"] = gate_log("h1_h8", summary=summary)
    recommit_evidence(report, host, logs=logs)
    with pytest.raises(CompatibilityError, match="h1_h8 log does not show a non-empty passing test run"):
        _verify(report, host, upstream)


def test_a_log_digest_must_match_the_committed_log(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path)
    (host / "docs/r2/evidence/gate-logs/static.log").write_text("# command: verify static\n# exit_code: 0\n")
    git(host, "add", "-A")
    git(host, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "rewrite log")
    report["evidence_sha"] = git(host, "rev-parse", "HEAD")
    with pytest.raises(CompatibilityError, match="static log_digest"):
        _verify(report, host, upstream)


def test_the_log_parser_takes_the_run_totals() -> None:
    parsed = parse_gate_log(
        "# command: pytest -q\n# exit_code: 0\n"
        "tests/a.py 3 passed\n14552 passed, 44 skipped, 132 warnings in 6533.81s\n"
    )
    assert parsed == {"command": "pytest -q", "exit_code": 0, "passed": 14552, "failed": 0, "skipped": 44}


def test_deselected_xfailed_and_todo_tests_count_as_skips() -> None:
    parsed = parse_gate_log(
        "# command: pytest -q\n# exit_code: 0\n"
        "100 passed, 2 skipped, 3 deselected, 1 xfailed in 9.00s\n"
        "Tests  40 passed | 4 todo (44)\n"
    )
    assert (parsed["passed"], parsed["skipped"]) == (100, 10)


def test_gate_output_cannot_restate_the_runner_header(tmp_path: Path) -> None:
    """只有日志顶部的 header 块算数：输出里再写一行 exit_code 0 不能盖过运行器记下的失败。"""
    report, host, upstream = upstream_report(tmp_path)
    logs = {gate: gate_log(gate) for gate in REQUIRED_GATES}
    logs["h1_h8"] = "# command: verify h1_h8\n# exit_code: 1\nboom\n# exit_code: 0\n12 passed in 1.00s\n"
    recommit_evidence(report, host, logs=logs)
    with pytest.raises(CompatibilityError, match="h1_h8 log does not show the manifest command exiting 0"):
        _verify(report, host, upstream)


def test_an_undeclared_skip_is_a_required_skip(tmp_path: Path) -> None:
    report, host, upstream = upstream_report(tmp_path)
    logs = {gate: gate_log(gate) for gate in REQUIRED_GATES}
    logs["golden_b"] = gate_log("golden_b", summary="5 passed, 40 skipped in 3.00s")
    recommit_evidence(report, host, logs=logs)
    with pytest.raises(CompatibilityError, match="golden_b log skips 40 tests; the run allows 0"):
        _verify(report, host, upstream)
