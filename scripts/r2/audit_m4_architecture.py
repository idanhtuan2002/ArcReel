"""M4-D12 — executable architecture fitness: git-diff repository-scope sensor.

Development/verification tooling only. Nothing at runtime imports this. It reports
whether the change scope since ``--starting-head`` stayed inside the approved M4
surface: R2 code plus tests plus tooling config, with C04 as the only approved
Host runtime/DB extension (and that extension is already in the pinned base).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# C04 is the only approved Host runtime/DB extension. On the pinned M4 baseline it
# is already merged, so any of these paths appearing in the diff is reported
# separately (approved) rather than as a blocking violation.
_APPROVED_C04_HOST_PATHS = frozenset(
    {
        "lib/artifact_manifest.py",
        "lib/budget_reservation.py",
        "lib/db/models/__init__.py",
        "lib/db/models/budget_reservation.py",
        "lib/db/repositories/__init__.py",
        "lib/db/repositories/budget_reservation_repo.py",
        "server/services/budget_reservation_events.py",
        "server/services/budget_reservation_service.py",
        "server/services/paid_submission_guard.py",
        "alembic/versions/c04b7d93e5a1_add_budget_reservations.py",
    }
)

_APPROVED_R2_PACKAGES = ("r2/contracts/", "r2/production/", "r2/production_intelligence/", "r2/m3/")
_M5_MARKERS = ("r2/canon", "r2/narrative", "r2/adaptation", "r2/m5", "r2/epistemic")


def _changed_paths(starting_head: str) -> list[tuple[str, str]]:
    out = subprocess.run(
        ["git", "diff", "--name-status", f"{starting_head}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            rows.append((parts[0], parts[-1]))
    return rows


def _is_host_runtime(path: str) -> bool:
    return (path.startswith(("lib/", "server/")) and not path.startswith(("tests/",))) and not path.endswith(
        ("_test.py",)
    )


def audit(starting_head: str) -> dict[str, object]:
    changed = _changed_paths(starting_head)
    approved_c04: list[str] = []
    unapproved_host: list[str] = []
    unapproved_migrations: list[str] = []
    m5_leakage: list[str] = []

    for status, path in changed:
        if path in _APPROVED_C04_HOST_PATHS:
            approved_c04.append(path)
            continue
        if path.startswith("alembic/versions/") and status == "A":
            unapproved_migrations.append(path)
            continue
        if _is_host_runtime(path):
            unapproved_host.append(path)
            continue
        if any(marker in path for marker in _M5_MARKERS):
            m5_leakage.append(path)
            continue
        if path.startswith("r2/") and not path.startswith(_APPROVED_R2_PACKAGES) and not path.startswith("r2/__"):
            m5_leakage.append(path)

    final_head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()

    blocking = len(unapproved_host) + len(unapproved_migrations) + len(m5_leakage)
    return {
        "schema_version": "1",
        "starting_head": starting_head,
        "final_head": final_head,
        "approved_c04_host_changes": sorted(approved_c04),
        "unapproved_host_runtime_changes": sorted(unapproved_host),
        "unapproved_db_migrations": sorted(unapproved_migrations),
        "m5_scope_leakage": sorted(m5_leakage),
        "blocking_violation_count": blocking,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="M4 architecture repository-scope audit")
    parser.add_argument("--starting-head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = audit(args.starting_head)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for key in ("unapproved_host_runtime_changes", "unapproved_db_migrations", "m5_scope_leakage"):
        offenders = report[key]
        assert isinstance(offenders, list)
        for path in offenders:
            print(f"BLOCKING [{key}]: {path}", file=sys.stderr)
    return 1 if report["blocking_violation_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
