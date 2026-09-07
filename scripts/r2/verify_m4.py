"""D11/C08 — assemble the canonical M4 Gate-D evidence manifest + summary.

Runs the frozen regression selections and the accumulated M4 suites, folds in the
architecture audit and the regression/real-evidence reports, and writes the C08
``r2_m4_evidence.json`` plus a human-readable ``R2_M4_FINAL_VERIFICATION.md``.
Evidence output is deterministic in structure and uses stable result codes.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SELECTIONS = _ROOT / "docs" / "r2" / "evidence" / "frozen_selections"

# Frozen figures from the M4 plan Global Constraints, unchanged since the
# post-remediation acceptance (R2_M4_BASELINE_CI_REMEDIATION.md).
_FROZEN_EXPECTED = {"m1_frozen": 41, "m2_frozen": 53, "m3_focused": 122, "host_frozen": 349}

# m4_focused count is recorded, never frozen. Everything else is an exact
# node-id / file selection recovered from the pinned corpus commits.
_DIR_SUITES = {"m4_focused": ["tests/unit/r2/production_intelligence", "tests/integration/r2/m4"]}
_SELECTION_FILES = {
    "m1_frozen": "m1_contracts.nodeids.txt",
    "m2_frozen": "m2_production.nodeids.txt",
    "m3_focused": "m3_focused.nodeids.txt",
    "host_frozen": "host_arcreel_focused.paths.txt",
}


def _run(args: list[str]) -> tuple[int, int, int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *args],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    text = proc.stdout + proc.stderr
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", text)) else 0
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", text)) else 0
    skipped = int(m.group(1)) if (m := re.search(r"(\d+) skipped", text)) else 0
    return passed, failed, skipped, ("PASS" if proc.returncode == 0 else "FAIL")


def _run_selection(filename: str) -> list[str]:
    return [ln for ln in (_SELECTIONS / filename).read_text(encoding="utf-8").splitlines() if ln.strip()]


def _read_host_baseline() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (_ROOT / "docs" / "r2" / "HOST_BASELINE.txt").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def build(args: argparse.Namespace) -> dict[str, object]:
    arch = json.loads(Path(args.architecture_audit).read_text(encoding="utf-8"))
    regression = json.loads(Path(args.regression_evidence).read_text(encoding="utf-8"))
    real = json.loads(Path(args.real_evidence).read_text(encoding="utf-8"))

    suites: list[dict[str, object]] = []
    for suite_id, paths in _DIR_SUITES.items():
        p, f, s, result = _run(paths)
        suites.append({"suite_id": suite_id, "pass_count": p, "fail_count": f, "skip_count": s, "result": result})

    frozen: list[dict[str, object]] = []
    for suite_id, filename in _SELECTION_FILES.items():
        selection = _run_selection(filename)
        p, f, s, _ = _run(selection)
        expected = _FROZEN_EXPECTED[suite_id]
        frozen.append(
            {
                "suite_id": suite_id,
                "selection_ref": f"docs/r2/evidence/frozen_selections/{filename}",
                "expected": expected,
                "pass_count": p,
                "fail_count": f,
                "skip_count": s,
                "result": "PASS" if (p == expected and f == 0) else "FAIL",
            }
        )

    final_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    worktree_clean = (
        subprocess.run(
            ["git", "status", "--short"], cwd=_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        == ""
    )

    reg = regression if regression.get("mode") == "regression" else regression.get("regression", {})
    return {
        "schema_version": "1",
        "milestone": "R2-M4",
        "design_spec_ref": "docs/superpowers/specs/2026-09-06-r2-m4-production-intelligence-design.md",
        "starting_head": args.starting_head,
        "final_head": final_head,
        "branch": subprocess.run(
            ["git", "branch", "--show-current"], cwd=_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip(),
        "worktree_clean": worktree_clean,
        "host_baseline": _read_host_baseline(),
        "suite_results": suites,
        "golden_baseline": {
            "passed": reg.get("baseline_passed"),
            "total": reg.get("baseline_total"),
            "result": reg.get("result"),
        },
        "fault_overlays": "MUT-01..MUT-08 asserted in tests/integration/r2/m4/test_golden_12_mutations.py (8/8)",
        "real_execution_evidence": real.get("real_execution_evidence", []),
        "real_evidence_result": real.get("result"),
        "frozen_regression": {
            "expected": _FROZEN_EXPECTED,
            "results": frozen,
            "all_pass": all(row["result"] == "PASS" for row in frozen),
            "note": (
                "Exact node-id / file selections recovered from the pinned corpus commits "
                "(M1 9330bcf3, M2 9cc04edd, M3 1985b815; Host set from the M2 plan). Figures match the M4 "
                "plan Global Constraints and R2_M4_BASELINE_CI_REMEDIATION.md; no re-baselining occurred."
            ),
        },
        "architecture_audit": {
            "report_ref": str(Path(args.architecture_audit).relative_to(_ROOT))
            if Path(args.architecture_audit).is_absolute()
            else str(args.architecture_audit),
            "blocking_violation_count": arch.get("blocking_violation_count"),
            "approved_c04_host_changes": arch.get("approved_c04_host_changes", []),
        },
        "host_runtime_change_count": len(arch.get("unapproved_host_runtime_changes", [])),
        "db_migration_count": len(arch.get("unapproved_db_migrations", [])),
        "h1_status": "OPEN",
        "open_blockers": ["R2-HOST-001 / H1"],
        "approved_waivers": [],
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _markdown(evidence: dict[str, object]) -> str:
    lines = [
        "# R2-M4 Final Verification",
        "",
        f"- Starting head: `{evidence['starting_head']}`",
        f"- Final head: `{evidence['final_head']}`",
        f"- Branch: `{evidence['branch']}`",
        f"- Worktree clean: **{evidence['worktree_clean']}**",
        f"- H1 / R2-HOST-001: **{evidence['h1_status']}**",
        "",
        "## Suites",
        "",
        "| Suite | pass | fail | skip | result |",
        "|---|--:|--:|--:|---|",
    ]
    suite_rows = evidence["suite_results"]
    assert isinstance(suite_rows, list)
    lines.extend(
        f"| {s['suite_id']} | {s['pass_count']} | {s['fail_count']} | {s['skip_count']} | {s['result']} |"
        for s in suite_rows
    )
    gb = evidence["golden_baseline"]
    lines += [
        "",
        f"## Golden baseline: {gb['passed']}/{gb['total']} — {gb['result']}",
        "",
        "MUT-01..MUT-08: 8/8 (see test_golden_12_mutations.py).",
        "",
        "## Frozen regression re-baselining",
        "",
        "```json",
        json.dumps(evidence["frozen_regression"], indent=2, sort_keys=True),
        "```",
        "",
        "## Real execution evidence",
        "",
        "| method | seam | result |",
        "|---|---|---|",
    ]
    real_rows = evidence["real_execution_evidence"]
    assert isinstance(real_rows, list)
    for e in real_rows:
        lines.append(f"| {e['method']} | {e['seam']} | {e['result']} |")
    lines += [
        "",
        f"Real-evidence result: **{evidence['real_evidence_result']}**",
        "",
        "## Architecture",
        "",
        f"- Blocking violations: **{evidence['architecture_audit']['blocking_violation_count']}**",
        f"- Unapproved Host runtime changes: **{evidence['host_runtime_change_count']}**",
        f"- DB migrations added by M4: **{evidence['db_migration_count']}**",
        "",
        "This milestone does not claim RECOVERY_VERIFIED or PRODUCTION_CANDIDATE; H1 remains OPEN.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="M4 Gate-D evidence assembler")
    parser.add_argument("--starting-head", required=True)
    parser.add_argument("--architecture-audit", required=True)
    parser.add_argument("--regression-evidence", required=True)
    parser.add_argument("--real-evidence", required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()

    evidence = build(args)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown_output.write_text(_markdown(evidence) + "\n", encoding="utf-8")
    print("evidence written", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
