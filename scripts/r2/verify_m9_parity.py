"""Verify M9 exact-pin same-fixture parity, using the accepted M8 donor-byte verifier."""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import ValidationError

from r2.contracts.advanced_creative import DonorParityReport, ParityVerdict
from r2.opportunity.parity import evaluate_m9_parity
from scripts.r2.verify_donor_parity import clone_file_hashes, verify_donor_parity
from scripts.r2.verify_m9_design_acceptance import loads_unique_json


def verify_m9_parity(document: object, integrated_head: str, file_hashes: Mapping[str, str]) -> list[str]:
    problems = verify_donor_parity(document, integrated_head, file_hashes)
    try:
        report = DonorParityReport.model_validate(document)
    except ValidationError:
        return problems
    if evaluate_m9_parity(report, integrated_head) is not ParityVerdict.PASS:
        problems.append("M9_DONOR_PARITY_INCOMPLETE: selected source or paired fixture measurements do not pass")
    return sorted(set(problems))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--head", required=True)
    parser.add_argument("--donor-clone", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        document = loads_unique_json(args.report.read_bytes())
        report = DonorParityReport.model_validate(document)
        os.environ["GIT_NO_LAZY_FETCH"] = "1"
        hashes = clone_file_hashes(args.donor_clone, report.donor.commit_sha, report.donor.selected_paths)
        problems = verify_m9_parity(document, args.head, hashes)
    except (ValueError, OSError):
        problems = ["M9_DONOR_PARITY_INCOMPLETE: report or selected local donor is unavailable"]
    for problem in problems:
        print(problem)
    if problems:
        return 2
    print("M9_DONOR_PARITY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
