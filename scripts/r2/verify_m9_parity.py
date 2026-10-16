"""Verify M9 exact-pin same-fixture parity, using the accepted M8 donor-byte verifier."""

from __future__ import annotations

import argparse
import hashlib
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from pydantic import Field, ValidationError

from r2.contracts.advanced_creative import DonorParityReport, M8ContractModel, ParityVerdict
from r2.opportunity.parity import FixtureComparison, evaluate_m9_parity
from scripts.r2.verify_donor_parity import clone_file_hashes, verify_donor_parity
from scripts.r2.verify_m9_design_acceptance import loads_unique_json


def verify_m9_parity(
    document: object,
    integrated_head: str,
    file_hashes: Mapping[str, str],
    evidence_bytes: Mapping[str, bytes] | None = None,
) -> list[str]:
    problems = verify_donor_parity(document, integrated_head, file_hashes)
    try:
        report = DonorParityReport.model_validate(document)
    except ValidationError:
        return problems
    if evaluate_m9_parity(report, integrated_head) is not ParityVerdict.PASS:
        problems.append("M9_DONOR_PARITY_INCOMPLETE: selected source or paired fixture measurements do not pass")
    if not problems:
        problems.extend(measurement_problems(report, evidence_bytes or {}, integrated_head))
    return sorted(set(problems))


class ArtifactReference(M8ContractModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RecordedRuntime(M8ContractModel):
    argv: tuple[str, ...] = Field(min_length=1)
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    exit_code: int
    stdout: ArtifactReference


class FixtureExecutionRecord(M8ContractModel):
    schema_version: Literal["m9.fixture-execution.v1"]
    behavior_id: str
    fixture_ref: str
    fixture: ArtifactReference
    donor: RecordedRuntime
    r2: RecordedRuntime


class RecordedMeasurementOutput(M8ContractModel):
    behavior_id: str
    fixture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dimensions: dict[str, str | int | bool]


class ExecutedRuntime(M8ContractModel):
    argv: tuple[str, ...] = Field(min_length=1)
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    exit_code: int
    stdout: bytes


class ExecutedPair(M8ContractModel):
    donor: ExecutedRuntime
    r2: ExecutedRuntime


# Foundation has no qualified donor runtime port or registered execution harness.
# A retained declaration cannot register or select executable code.
REGISTERED_FIXTURE_HARNESSES: Mapping[tuple[str, str], Callable[[str, bytes], ExecutedPair]] = MappingProxyType({})


def verified_artifact_bytes(reference: ArtifactReference, evidence: Mapping[str, bytes]) -> bytes:
    raw = evidence[reference.path]
    if hashlib.sha256(raw).hexdigest() != reference.sha256:
        raise ValueError("retained artifact hash mismatch")
    return raw


def measurement_problems(report: DonorParityReport, evidence: Mapping[str, bytes], integrated_head: str) -> list[str]:
    problems = []
    for command in report.commands:
        document = command.model_dump()
        if document.get("kind") == "INVENTORY":
            continue
        try:
            comparison = FixtureComparison.model_validate(document)
            if not comparison.applicable:
                continue
            record = FixtureExecutionRecord.model_validate(loads_unique_json(evidence[comparison.evidence_ref]))
            if (
                record.behavior_id,
                record.fixture_ref,
                record.donor.source_commit,
                record.r2.source_commit,
                record.donor.exit_code,
                record.r2.exit_code,
            ) != (
                comparison.behavior_id,
                comparison.fixture_ref,
                comparison.donor_commit,
                comparison.integrated_head,
                comparison.donor_exit_code,
                comparison.r2_exit_code,
            ):
                raise ValueError("paired execution identity mismatch")
            fixture = verified_artifact_bytes(record.fixture, evidence)
            harness = REGISTERED_FIXTURE_HARNESSES.get((report.donor.commit_sha, comparison.behavior_id))
            if harness is None:
                raise ValueError("no pinned offline fixture harness is registered")
            observed = harness(integrated_head, fixture)
            for side, runtime in (("donor", record.donor), ("r2", record.r2)):
                raw_output = verified_artifact_bytes(runtime.stdout, evidence)
                executed = getattr(observed, side)
                if (executed.argv, executed.source_commit, executed.exit_code, executed.stdout) != (
                    runtime.argv,
                    runtime.source_commit,
                    runtime.exit_code,
                    raw_output,
                ):
                    raise ValueError("fresh pinned harness execution differs from retained record")
                output = RecordedMeasurementOutput.model_validate(loads_unique_json(raw_output))
                expected = {row.dimension: getattr(row, side) for row in comparison.dimensions}
                if (output.behavior_id, output.fixture_sha256, output.dimensions) != (
                    comparison.behavior_id,
                    record.fixture.sha256,
                    expected,
                ):
                    raise ValueError("paired retained measurements differ from report")
        except (KeyError, ValueError, OSError, TypeError):
            problems.append(
                "M9_DONOR_PARITY_INCOMPLETE: registered execution or paired fixture/output evidence is absent or invalid"
            )
    return sorted(set(problems))


def retained_evidence(report: DonorParityReport, root: Path) -> dict[str, bytes]:
    evidence = {}
    root = root.resolve()

    def read(ref: str) -> bytes:
        if ref in evidence:
            return evidence[ref]
        path = (root / ref).resolve()
        if not path.is_relative_to(root):
            raise ValueError("parity artifact leaves the declared evidence root")
        raw = path.read_bytes()
        evidence[ref] = raw
        return raw

    for command in report.commands:
        document = command.model_dump()
        if document.get("kind") == "INVENTORY":
            continue
        comparison = FixtureComparison.model_validate(document)
        if comparison.applicable:
            record = FixtureExecutionRecord.model_validate(loads_unique_json(read(comparison.evidence_ref)))
            for ref in (record.fixture, record.donor.stdout, record.r2.stdout):
                read(ref.path)
    return evidence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--head", required=True)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--donor-clone", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        document = loads_unique_json(args.report.read_bytes())
        report = DonorParityReport.model_validate(document)
        os.environ["GIT_NO_LAZY_FETCH"] = "1"
        hashes = clone_file_hashes(args.donor_clone, report.donor.commit_sha, report.donor.selected_paths)
        problems = verify_m9_parity(
            document, args.head, hashes, retained_evidence(report, args.evidence_root or args.report.parent)
        )
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
