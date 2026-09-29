"""Recompute a donor parity report's surface digest and verdict (spec §11, plan Task A1.4).

The report's own verdict is never trusted. The reachable surface digest is recomputed from
the donor clone at the pinned commit, as the canonical digest of ``{path: sha256}`` over the
selected paths. The verdict is recomputed with ``evaluate_parity`` at the integrated HEAD. A
report passes only when it is valid, its surface matches, and the recomputed verdict is
``PASS`` and equals the reported one.

    uv run python scripts/r2/verify_donor_parity.py <report.json> --head <sha> --donor-clone <path>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import ValidationError

from r2.advanced_creative.digests import digest_canonical
from r2.advanced_creative.parity import evaluate_parity
from r2.contracts.advanced_creative import DonorParityReport, ParityVerdict


def surface_digest(file_hashes: Mapping[str, str]) -> str:
    return digest_canonical(dict(file_hashes))


def verify_donor_parity(report_document: object, current_head: str, file_hashes: Mapping[str, str]) -> list[str]:
    """Every problem with the report, sorted; an empty list is the only pass."""
    try:
        report = DonorParityReport.model_validate(report_document)
    except ValidationError as exc:
        return [f"report is invalid: {exc.error_count()} validation error(s)"]
    problems: list[str] = []
    missing = sorted(set(report.donor.selected_paths) - set(file_hashes))
    if missing:
        problems.append(f"selected paths are missing from the donor clone: {missing}")
    selected = {path: file_hashes[path] for path in report.donor.selected_paths if path in file_hashes}
    if not missing and surface_digest(selected) != report.donor.reachable_surface_digest:
        problems.append("reachable_surface_digest does not match the donor clone at the pinned commit")
    recomputed = evaluate_parity(report, current_head)
    if recomputed is not ParityVerdict.PASS:
        problems.append(f"recomputed verdict is {recomputed.value}")
    if recomputed is not report.verdict:
        problems.append(f"reported verdict {report.verdict.value} differs from the recomputed {recomputed.value}")
    return sorted(problems)


def clone_file_hashes(clone: Path, commit: str, paths: Sequence[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in paths:
        blob = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=clone, capture_output=True, check=False)
        if blob.returncode == 0:
            hashes[path] = "sha256:" + hashlib.sha256(blob.stdout).hexdigest()
    return hashes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", type=Path)
    parser.add_argument("--head", required=True)
    parser.add_argument("--donor-clone", type=Path, required=True)
    args = parser.parse_args(argv)
    document = json.loads(args.report.read_text(encoding="utf-8"))
    donor = document.get("donor", {}) if isinstance(document, dict) else {}
    hashes = clone_file_hashes(
        args.donor_clone, str(donor.get("commit_sha", "")), list(donor.get("selected_paths", []))
    )
    problems = verify_donor_parity(document, args.head, hashes)
    for problem in problems:
        print(problem)
    if problems:
        return 2
    print("M8_DONOR_PARITY_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
