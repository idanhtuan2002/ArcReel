"""The donor parity fold (spec §4 DonorParityReport, §11)."""

from __future__ import annotations

import pytest

from r2.advanced_creative.parity import evaluate_parity
from r2.contracts.advanced_creative import (
    BehaviorParityRow,
    DonorParityReport,
    DonorSurfaceRef,
    ParityDisposition,
    ParityVerdict,
)

HEAD = "c" * 40
DIGEST = "sha256:" + "a" * 64
DIMENSIONS = (
    "functionality",
    "correctness",
    "determinism",
    "failure_safety",
    "data_integrity",
    "observability",
    "performance",
    "resources",
)


def _row(**overrides: object) -> BehaviorParityRow:
    fields: dict[str, object] = {
        "behavior_id": "b1",
        "donor_test_refs": ("t1",),
        "fixture_refs": ("f1",),
        "intentional_difference": None,
        "evidence_refs": ("e1",),
    }
    for dimension in DIMENSIONS:
        fields[dimension] = ParityDisposition.PARITY
    return BehaviorParityRow(**(fields | overrides))


def _report(**overrides: object) -> DonorParityReport:
    fields: dict[str, object] = {
        "contract_version": "1",
        "donor": DonorSurfaceRef(
            repository_url="https://example.invalid/donor",
            commit_sha="e" * 40,
            selected_paths=("a.ts",),
            reachable_surface_digest=DIGEST,
            runtime_identity="node20",
            behavior_inventory_digest=DIGEST,
            donor_test_inventory_digest=DIGEST,
            fixture_set_digest=DIGEST,
        ),
        "integrated_head": HEAD,
        "rows": (_row(),),
        "commands": (),
        "required_skips": (),
        "material_unknowns": (),
        "reviewer": "codex",
        "verdict": ParityVerdict.PASS,
    }
    return DonorParityReport(**(fields | overrides))


def test_a_complete_report_at_the_current_head_passes() -> None:
    assert evaluate_parity(_report(), HEAD) is ParityVerdict.PASS


def test_improved_counts_as_passing() -> None:
    assert evaluate_parity(_report(rows=(_row(performance=ParityDisposition.IMPROVED),)), HEAD) is ParityVerdict.PASS


def test_empty_rows_block() -> None:
    assert evaluate_parity(_report(rows=()), HEAD) is ParityVerdict.BLOCKED


def test_head_drift_blocks() -> None:
    assert evaluate_parity(_report(), "d" * 40) is ParityVerdict.BLOCKED


def test_a_required_skip_blocks() -> None:
    assert evaluate_parity(_report(required_skips=("browser",)), HEAD) is ParityVerdict.BLOCKED


def test_a_material_unknown_blocks() -> None:
    assert evaluate_parity(_report(material_unknowns=("timing",)), HEAD) is ParityVerdict.BLOCKED


def test_a_wholly_excluded_row_with_a_reason_passes() -> None:
    excluded = _row(
        behavior_id="b2",
        intentional_difference="outside the selected surface",
        **dict.fromkeys(DIMENSIONS, ParityDisposition.EXCLUDED),
    )

    assert evaluate_parity(_report(rows=(_row(), excluded)), HEAD) is ParityVerdict.PASS


def test_an_excluded_row_without_a_reason_blocks() -> None:
    excluded = _row(**dict.fromkeys(DIMENSIONS, ParityDisposition.EXCLUDED))

    assert evaluate_parity(_report(rows=(_row(behavior_id="b0"), excluded)), HEAD) is ParityVerdict.BLOCKED


def test_a_reachable_exclusion_blocks() -> None:
    # The behavior is exercised (functionality PARITY) yet one of its dimensions is excluded.
    partial = _row(intentional_difference="not measured", resources=ParityDisposition.EXCLUDED)

    assert evaluate_parity(_report(rows=(partial,)), HEAD) is ParityVerdict.BLOCKED


@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_each_unverified_dimension_blocks(dimension: str) -> None:
    row = _row(**{dimension: ParityDisposition.UNVERIFIED})

    assert evaluate_parity(_report(rows=(row,)), HEAD) is ParityVerdict.BLOCKED


def test_the_reported_verdict_is_not_trusted() -> None:
    blocked = _report(rows=(), verdict=ParityVerdict.PASS)

    assert evaluate_parity(blocked, HEAD) is ParityVerdict.BLOCKED
