"""M9 exact-pin, same-fixture parity over the existing M8 report vocabulary."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import Field, ValidationError

from r2.advanced_creative.digests import digest_canonical
from r2.advanced_creative.parity import DIMENSIONS, evaluate_parity
from r2.contracts.advanced_creative import DonorParityReport, M8ContractModel, ParityDisposition, ParityVerdict

# Selected surfaces are fixed by the accepted M9 baseline, never caller-selected.
PINNED_SURFACES = {
    "08e2151fa02de28a5d6a312b3d575692bf147ad7": (
        "skills/pipelines/explainer/research-director.md",
        "schemas/artifacts/research_brief.schema.json",
        "schemas/artifacts/decision_log.schema.json",
    ),
    "e4b5a2173ca03d365aad565a89fcc43159b44f9b": (
        "pipeline/src/research.py",
        "pipeline/src/creative.py",
        "pipeline/src/kalinga.py",
        "pipeline/src/daily.py",
        "channels/history-shorts/channel.yaml",
    ),
    "f104b853b3563e124d9cde25f9331d323fb483b9": ("workbench-server/src/services/novel/novel-outline-drama-fields.ts",),
}


PINNED_REPOSITORIES = {
    "08e2151fa02de28a5d6a312b3d575692bf147ad7": "https://github.com/calesthio/OpenMontage",
    "e4b5a2173ca03d365aad565a89fcc43159b44f9b": "https://github.com/desaultkhan/Kalinga-Shorts-Factory",
    "f104b853b3563e124d9cde25f9331d323fb483b9": "https://github.com/appolloqin/huohuo-drama",
}


class DimensionMeasurement(M8ContractModel):
    dimension: str
    comparison: Literal["EQUAL", "LOWER_IS_BETTER", "HIGHER_IS_BETTER"]
    donor: str | int | Decimal | bool
    r2: str | int | Decimal | bool


class FixtureComparison(M8ContractModel):
    evidence_ref: str = Field(min_length=1)
    behavior_id: str = Field(min_length=1)
    fixture_ref: str = Field(min_length=1)
    donor_commit: str
    integrated_head: str
    donor_exit_code: int
    r2_exit_code: int
    applicable: bool
    dimensions: tuple[DimensionMeasurement, ...]


class DonorInventory(M8ContractModel):
    kind: Literal["INVENTORY"]
    behavior_ids: tuple[str, ...]
    donor_test_refs: tuple[str, ...]
    fixture_refs: tuple[str, ...]


def _disposition(measurement: DimensionMeasurement) -> ParityDisposition | None:
    if measurement.comparison == "EQUAL":
        return ParityDisposition.PARITY if measurement.donor == measurement.r2 else None
    try:
        donor, r2 = Decimal(str(measurement.donor)), Decimal(str(measurement.r2))
    except InvalidOperation:
        return None
    if not donor.is_finite() or not r2.is_finite():
        return None
    if donor == r2:
        return ParityDisposition.PARITY
    if (measurement.comparison == "LOWER_IS_BETTER" and r2 < donor) or (
        measurement.comparison == "HIGHER_IS_BETTER" and r2 > donor
    ):
        return ParityDisposition.IMPROVED
    return None


def evaluate_m9_parity(report: DonorParityReport, integrated_head: str) -> ParityVerdict:
    """A declaration never substitutes for a complete paired measurement inventory."""
    if evaluate_parity(report, integrated_head) is not ParityVerdict.PASS:
        return ParityVerdict.BLOCKED
    selected = PINNED_SURFACES.get(report.donor.commit_sha)
    if (
        selected is None
        or sorted(report.donor.selected_paths) != sorted(selected)
        or report.donor.repository_url != PINNED_REPOSITORIES.get(report.donor.commit_sha)
    ):
        return ParityVerdict.BLOCKED
    if len({row.behavior_id for row in report.rows}) != len(report.rows):
        return ParityVerdict.BLOCKED
    try:
        documents = [command.model_dump() for command in report.commands]
        inventories = [
            DonorInventory.model_validate(document) for document in documents if document.get("kind") == "INVENTORY"
        ]
        comparisons = tuple(
            FixtureComparison.model_validate(document) for document in documents if document.get("kind") != "INVENTORY"
        )
    except ValidationError:
        return ParityVerdict.BLOCKED
    if len(inventories) != 1:
        return ParityVerdict.BLOCKED
    inventory = inventories[0]
    bindings = (
        (inventory.behavior_ids, {row.behavior_id for row in report.rows}, report.donor.behavior_inventory_digest),
        (
            inventory.donor_test_refs,
            {ref for row in report.rows for ref in row.donor_test_refs},
            report.donor.donor_test_inventory_digest,
        ),
        (
            inventory.fixture_refs,
            {ref for row in report.rows for ref in row.fixture_refs},
            report.donor.fixture_set_digest,
        ),
    )
    if any(
        len(set(values)) != len(values) or set(values) != expected or digest_canonical(sorted(values)) != digest
        for values, expected, digest in bindings
    ):
        return ParityVerdict.BLOCKED
    if len({comparison.evidence_ref for comparison in comparisons}) != len(comparisons):
        return ParityVerdict.BLOCKED
    known_behaviors = {row.behavior_id for row in report.rows}
    if any(comparison.behavior_id not in known_behaviors for comparison in comparisons):
        return ParityVerdict.BLOCKED
    for row in report.rows:
        matches = [comparison for comparison in comparisons if comparison.behavior_id == row.behavior_id]
        excluded = all(getattr(row, dimension) is ParityDisposition.EXCLUDED for dimension in DIMENSIONS)
        if excluded:
            if not (row.intentional_difference or "").startswith(("SCOPE:", "AUTHORITY:")) or any(
                comparison.applicable for comparison in matches
            ):
                return ParityVerdict.BLOCKED
            continue
        if not row.fixture_refs or not row.donor_test_refs or not row.evidence_refs or not matches:
            return ParityVerdict.BLOCKED
        if set(row.fixture_refs) != {comparison.fixture_ref for comparison in matches} or set(row.evidence_refs) != {
            comparison.evidence_ref for comparison in matches
        }:
            return ParityVerdict.BLOCKED
        defect = (row.intentional_difference or "").startswith("DONOR_DEFECT:")
        for comparison in matches:
            if (
                not comparison.applicable
                or comparison.donor_commit != report.donor.commit_sha
                or comparison.integrated_head != integrated_head
                or comparison.r2_exit_code != 0
            ):
                return ParityVerdict.BLOCKED
            if (comparison.donor_exit_code != 0) != defect:
                return ParityVerdict.BLOCKED
            if len(comparison.dimensions) != len(DIMENSIONS) or {
                value.dimension for value in comparison.dimensions
            } != set(DIMENSIONS):
                return ParityVerdict.BLOCKED
            if any(_disposition(value) is not getattr(row, value.dimension) for value in comparison.dimensions):
                return ParityVerdict.BLOCKED
    return ParityVerdict.PASS
