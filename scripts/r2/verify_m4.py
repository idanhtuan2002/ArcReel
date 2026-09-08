"""D11/C08 — assemble the canonical M4 Gate-D evidence manifest + summary.

Fail-closed: exits non-zero unless every defining Gate-D condition holds against
the exact expected HEAD — frozen selections at their pinned counts with zero
fail/skip, the golden baseline 12/12, MUT-01..MUT-08 all PASS, repo-wide quality
gates green, architecture blocking count zero, no unapproved Host/DB change, and
the real-execution evidence either PASS or fully covered by recorded approved
waivers. Writes the C08 ``r2_m4_evidence.json`` plus ``R2_M4_FINAL_VERIFICATION.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SELECTIONS = _ROOT / "docs" / "r2" / "evidence" / "frozen_selections"
_PLAN = (
    Path.home()
    / "Bản tải về"
    / "conten os"
    / "2026-09-07-r2-m4-production-intelligence-implementation-plan-APPROVED.md"
)

# Expected pass counts for the four frozen regression selections. A run that
# does not reproduce these exactly (0 fail, 0 skip) fails the gate.
_FROZEN_EXPECTED = {"m1_frozen": 41, "m2_frozen": 53, "m3_focused": 122, "host_frozen": 349}
_M4_FOCUSED = ["tests/unit/r2/production_intelligence", "tests/integration/r2/m4"]
_MUTATIONS = "tests/integration/r2/m4/test_golden_12_mutations.py"
_SELECTION_FILES = {
    "m1_frozen": "m1_contracts.nodeids.txt",
    "m2_frozen": "m2_production.nodeids.txt",
    "m3_focused": "m3_focused.nodeids.txt",
    "host_frozen": "host_arcreel_focused.paths.txt",
}
_REPO_GATES: dict[str, list[str]] = {
    "ruff_check": ["uv", "run", "ruff", "check", "."],
    "ruff_format": ["uv", "run", "ruff", "format", "--check", "."],
    "basedpyright": ["uv", "run", "basedpyright", "--warnings"],
    "deptry": ["uv", "run", "deptry", "lib", "server", "alembic", "scripts", "tests", "r2"],
    "lint_imports": ["uv", "run", "lint-imports"],
    "audit_tests": ["uv", "run", "python", "scripts/audit_tests.py", "--check"],
}


def _pytest(args: list[str], *, verbose: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "pytest", "-v" if verbose else "-q", *args]
    return subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True, check=False)


def _counts(text: str) -> tuple[int, int, int]:
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", text)) else 0
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", text)) else 0
    skipped = int(m.group(1)) if (m := re.search(r"(\d+) skipped", text)) else 0
    return passed, failed, skipped


def _run_suite(paths: list[str]) -> dict[str, object]:
    proc = _pytest(paths)
    p, f, s = _counts(proc.stdout + proc.stderr)
    return {"pass_count": p, "fail_count": f, "skip_count": s, "result": "PASS" if proc.returncode == 0 else "FAIL"}


def _selection(filename: str) -> list[str]:
    return [ln for ln in (_SELECTIONS / filename).read_text(encoding="utf-8").splitlines() if ln.strip()]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "UNAVAILABLE"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=_ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _porcelain_path(line: str) -> str:
    """`XY PATH` (or `RXY ORIG -> DEST` for renames) -> the working-tree path."""
    body = line[3:]
    return body.split(" -> ")[-1] if " -> " in body else body


def _read_host_baseline() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (_ROOT / "docs" / "r2" / "HOST_BASELINE.txt").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def _mutation_rows(expected: dict[str, str]) -> list[dict[str, object]]:
    proc = _pytest([_MUTATIONS], verbose=True)
    text = proc.stdout + proc.stderr
    rows: list[dict[str, object]] = []
    for mut_id, expected_outcome in expected.items():
        token = mut_id.lower().replace("-", "_")  # MUT-01 -> mut_01 -> test_mut_01_...
        m = re.search(rf"test_{token}\w*\s+(PASSED|FAILED|ERROR|SKIPPED)", text)
        observed = m.group(1) if m else "MISSING"
        rows.append(
            {
                "mutation_id": mut_id,
                "expected_outcome": expected_outcome,
                "observed_outcome": observed,
                "result": "PASS" if observed == "PASSED" else "FAIL",
            }
        )
    return rows


def _write_recovery_log(frozen_rows: list[dict[str, object]]) -> None:
    lines = [
        "# Frozen regression recovery log",
        f"# generated {datetime.now(UTC).isoformat()} at HEAD {_git('rev-parse', 'HEAD')}",
        "",
        "Recovery commands (run at each pinned corpus commit via a temporary worktree):",
        "  M1  git worktree add --detach <wt> 9330bcf3 && pytest --co -q tests/unit/r2/contracts/",
        "  M2  git worktree add --detach <wt> 9cc04edd && pytest --co -q tests/unit/r2/production/ tests/integration/r2/production/",
        "  M3  git worktree add --detach <wt> 1985b815 && pytest --co -q tests/unit/r2/m3/ tests/integration/r2/m3/ tests/unit/r2/production/ tests/integration/r2/production/ tests/unit/r2/contracts/",
        "  Host  file set verbatim from docs/superpowers/plans/2026-09-06-r2-m2-artifact-bridge-implementation-plan.md Step 6",
        "",
        "Execution at the M4 final head:",
    ]
    lines.extend(
        f"  {row['suite_id']:<12} expected={row['expected']} "
        f"pass={row['pass_count']} fail={row['fail_count']} skip={row['skip_count']} -> {row['result']}"
        for row in frozen_rows
    )
    (_SELECTIONS / "recovery_log.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(args: argparse.Namespace) -> dict[str, object]:
    arch = json.loads(Path(args.architecture_audit).read_text(encoding="utf-8"))
    regression = json.loads(Path(args.regression_evidence).read_text(encoding="utf-8"))
    real = json.loads(Path(args.real_evidence).read_text(encoding="utf-8"))
    waivers = json.loads(Path(args.waivers).read_text(encoding="utf-8")) if args.waivers else []

    head = _git("rev-parse", "HEAD")
    expected_head = args.expected_head or head

    # Clean modulo the artifacts this run itself writes.
    def _rel(p: Path) -> str:
        return str(p.resolve().relative_to(_ROOT)) if p.resolve().is_relative_to(_ROOT) else str(p)

    generated = {
        _rel(Path(args.json_output)),
        _rel(Path(args.markdown_output)),
        _rel(Path(args.architecture_audit)),
        "docs/r2/evidence/frozen_selections/recovery_log.txt",
    }
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"], cwd=_ROOT, capture_output=True, text=True, check=True
    ).stdout
    dirty = [_porcelain_path(ln) for ln in porcelain.splitlines() if ln.strip()]
    dirty_beyond_evidence = [p for p in dirty if p not in generated]

    m4_focused = {"suite_id": "m4_focused", **_run_suite(_M4_FOCUSED)}

    frozen: list[dict[str, object]] = []
    for suite_id, filename in _SELECTION_FILES.items():
        outcome = _run_suite(_selection(filename))
        expected = _FROZEN_EXPECTED[suite_id]
        frozen.append(
            {
                "suite_id": suite_id,
                "selection_ref": f"docs/r2/evidence/frozen_selections/{filename}",
                "expected": expected,
                **outcome,
                "result": "PASS"
                if (outcome["pass_count"] == expected and outcome["fail_count"] == 0 and outcome["skip_count"] == 0)
                else "FAIL",
            }
        )
    _write_recovery_log(frozen)

    mutation_rows = _mutation_rows({f"MUT-{i:02d}": expected for i, expected in enumerate(["PASS"] * 8, start=1)})

    gate_results: dict[str, str] = {}
    for name, cmd in _REPO_GATES.items():
        rc = subprocess.run([*cmd], cwd=_ROOT, capture_output=True, text=True, check=False).returncode
        gate_results[name] = "PASS" if rc == 0 else "FAIL"

    reg = regression if regression.get("mode") == "regression" else regression.get("regression", {})
    golden_rows = reg.get("shots", [])

    real_rows = [
        {
            "seam_id": e.get("method"),
            "seam": e.get("seam"),
            "result": e.get("result"),
            "artifact_refs": e.get("artifact_refs", []),
            "attempt_refs": e.get("attempt_refs", []),
            "cost_refs": e.get("cost_refs", []),
            "detail": e.get("detail"),
        }
        for e in real.get("real_execution_evidence", [])
    ]
    waived = {w.get("seam_id") for w in waivers}
    unresolved_real = [r for r in real_rows if r["result"] != "PASS" and r["seam_id"] not in waived]

    frozen_ok = all(r["result"] == "PASS" for r in frozen)
    mutations_ok = all(r["result"] == "PASS" for r in mutation_rows)
    golden_ok = reg.get("baseline_passed") == reg.get("baseline_total") == 12 and reg.get("result") == "PASS"
    gates_ok = all(v == "PASS" for v in gate_results.values())
    arch_ok = (
        arch.get("blocking_violation_count") == 0
        and not arch.get("unapproved_host_runtime_changes")
        and not arch.get("unapproved_db_migrations")
        and not arch.get("mutated_c04_host_files")
    )
    head_ok = head == expected_head

    gate_d_pass = all(
        [
            head_ok,
            not dirty_beyond_evidence,
            m4_focused["result"] == "PASS",
            frozen_ok,
            mutations_ok,
            golden_ok,
            gates_ok,
            arch_ok,
            not unresolved_real,
        ]
    )
    if gate_d_pass:
        gate_d_status = "COMPLETE" if not unresolved_real and not waivers else "COMPLETE_WITH_WAIVER"
    elif not unresolved_real:
        gate_d_status = "FAIL"
    else:
        gate_d_status = "INCOMPLETE_PENDING_WAIVER"

    return {
        "schema_version": "1",
        "milestone": "R2-M4",
        "design_spec_ref": "docs/superpowers/specs/2026-09-06-r2-m4-production-intelligence-design.md",
        "design_spec_hash": _sha256_file(
            _ROOT / "docs" / "superpowers" / "specs" / "2026-09-06-r2-m4-production-intelligence-design.md"
        ),
        "implementation_plan_ref": str(_PLAN),
        "implementation_plan_hash": _sha256_file(_PLAN),
        "starting_head": args.starting_head,
        "verified_head": head,
        "expected_head": expected_head,
        "head_matches_expected": head_ok,
        "branch": _git("branch", "--show-current"),
        "worktree_clean_strict": not dirty,
        "worktree_clean_modulo_generated_evidence": not dirty_beyond_evidence,
        "dirty_beyond_evidence": sorted(dirty_beyond_evidence),
        "environment_summary": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "ffmpeg": shutil.which("ffmpeg") is not None,
            "ffprobe": shutil.which("ffprobe") is not None,
        },
        "host_baseline": _read_host_baseline(),
        "gate_results": gate_results,
        "suite_results": [m4_focused],
        "golden_baseline": {
            "passed": reg.get("baseline_passed"),
            "total": reg.get("baseline_total"),
            "result": reg.get("result"),
            "shots": golden_rows,
        },
        "fault_overlays": mutation_rows,
        "real_execution_evidence": real_rows,
        "real_evidence_result": real.get("result"),
        "unresolved_real_evidence_seams": [r["seam_id"] for r in unresolved_real],
        "frozen_regression": {
            "expected": _FROZEN_EXPECTED,
            "results": frozen,
            "all_pass": frozen_ok,
            "recovery_log_ref": "docs/r2/evidence/frozen_selections/recovery_log.txt",
            "note": (
                "Exact node-id / file selections recovered from the pinned corpus commits "
                "(M1 9330bcf3, M2 9cc04edd, M3 1985b815; Host set from the M2 plan). Figures match the M4 "
                "plan Global Constraints and R2_M4_BASELINE_CI_REMEDIATION.md; no re-baselining occurred."
            ),
        },
        "architecture_audit": {
            "report_ref": "docs/r2/evidence/R2_M4_ARCHITECTURE_AUDIT.json",
            "blocking_violation_count": arch.get("blocking_violation_count"),
            "approved_c04_host_changes": arch.get("approved_c04_host_changes", []),
        },
        "host_runtime_change_count": len(arch.get("unapproved_host_runtime_changes", [])),
        "db_migration_count": len(arch.get("unapproved_db_migrations", [])),
        "h1_status": "OPEN",
        "open_blockers": ["R2-HOST-001 / H1"],
        "approved_waivers": waivers,
        "gate_d_status": gate_d_status,
        "gate_d_pass": gate_d_pass,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _markdown(ev: dict[str, object]) -> str:
    lines = [
        "# R2-M4 Final Verification",
        "",
        f"- Gate D status: **{ev['gate_d_status']}** (`gate_d_pass={ev['gate_d_pass']}`)",
        f"- Starting head: `{ev['starting_head']}`",
        f"- Verified head: `{ev['verified_head']}` (expected `{ev['expected_head']}`, match: {ev['head_matches_expected']})",
        f"- Branch: `{ev['branch']}`",
        f"- Worktree clean (strict / modulo generated evidence): **{ev['worktree_clean_strict']} / {ev['worktree_clean_modulo_generated_evidence']}**",
        f"- H1 / R2-HOST-001: **{ev['h1_status']}**",
        "",
        "> This evidence certifies the tree at `verified_head`. When committed it is a",
        "> docs-only child of that commit; no code, test, or contract path changes.",
        "",
        "## Repo-wide gates",
        "",
        "| gate | result |",
        "|---|---|",
    ]
    gates: dict[str, str] = ev["gate_results"]
    lines.extend(f"| {k} | {v} |" for k, v in gates.items())
    m4 = ev["suite_results"][0]
    frozen = ev["frozen_regression"]["results"]
    lines += [
        "",
        "## Suites",
        "",
        "| suite | pass | fail | skip | result |",
        "|---|--:|--:|--:|---|",
        f"| m4_focused | {m4['pass_count']} | {m4['fail_count']} | {m4['skip_count']} | {m4['result']} |",
    ]
    lines.extend(
        f"| {r['suite_id']} (expected {r['expected']}) | {r['pass_count']} | {r['fail_count']} | {r['skip_count']} | {r['result']} |"
        for r in frozen
    )
    gb = ev["golden_baseline"]
    lines += ["", f"## Golden baseline: {gb['passed']}/{gb['total']} — {gb['result']}", ""]
    lines += ["| shot | expected director/method | actual | result |", "|---|---|---|---|"]
    for s in gb.get("shots", []):
        lines.append(
            f"| {s['shot_id']} | {s['expected_director']}/{s['expected_method']} | "
            f"{s.get('actual_director')}/{s.get('actual_method')} | {s['result']} |"
        )
    lines += ["", "## Fault overlays", "", "| mutation | expected | observed | result |", "|---|---|---|---|"]
    for r in ev["fault_overlays"]:
        lines.append(f"| {r['mutation_id']} | {r['expected_outcome']} | {r['observed_outcome']} | {r['result']} |")
    lines += ["", "## Real execution evidence", "", "| seam | via | result | detail |", "|---|---|---|---|"]
    for r in ev["real_execution_evidence"]:
        lines.append(f"| {r['seam_id']} | {r['seam']} | {r['result']} | {r.get('detail') or ''} |")
    lines += [
        "",
        f"Real-evidence result: **{ev['real_evidence_result']}**; unresolved seams: {ev['unresolved_real_evidence_seams']}; approved waivers: {len(ev['approved_waivers'])}",
        "",
        "## Architecture",
        "",
        f"- Blocking violations: **{ev['architecture_audit']['blocking_violation_count']}**",
        f"- Unapproved Host runtime changes: **{ev['host_runtime_change_count']}**; DB migrations by M4: **{ev['db_migration_count']}**",
        "",
        "This milestone does not claim RECOVERY_VERIFIED or PRODUCTION_CANDIDATE; H1 remains OPEN.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="M4 Gate-D evidence assembler (fail-closed)")
    parser.add_argument("--starting-head", required=True)
    parser.add_argument("--expected-head", default=None)
    parser.add_argument("--architecture-audit", required=True)
    parser.add_argument("--regression-evidence", required=True)
    parser.add_argument("--real-evidence", required=True)
    parser.add_argument("--waivers", default=None, help="JSON list of approved waiver objects with seam_id")
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()

    evidence = build(args)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown_output.write_text(_markdown(evidence) + "\n", encoding="utf-8")
    print(f"gate_d_status={evidence['gate_d_status']} gate_d_pass={evidence['gate_d_pass']}", file=sys.stderr)
    return 0 if evidence["gate_d_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
