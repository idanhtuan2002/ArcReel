"""The M10 parity adapter preserves the M8 fold while rejecting unbound HEADs."""

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
from r2.quality.parity import evaluate_quality_parity

HEAD = "c" * 40
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


def row(**changes: object) -> BehaviorParityRow:
    return BehaviorParityRow.model_validate(
        {
            "behavior_id": "behavior",
            "donor_test_refs": ("test",),
            "fixture_refs": ("fixture",),
            "evidence_refs": ("evidence",),
            "intentional_difference": None,
            **dict.fromkeys(DIMENSIONS, ParityDisposition.PARITY),
            **changes,
        }
    )


def report(**changes: object) -> DonorParityReport:
    digest = "sha256:" + "a" * 64
    return DonorParityReport.model_validate(
        {
            "contract_version": "1",
            "donor": DonorSurfaceRef(
                repository_url="https://example.invalid/donor",
                commit_sha="e" * 40,
                selected_paths=("a.ts",),
                reachable_surface_digest=digest,
                runtime_identity="node20",
                behavior_inventory_digest=digest,
                donor_test_inventory_digest=digest,
                fixture_set_digest=digest,
            ),
            "integrated_head": HEAD,
            "rows": (row(),),
            "commands": (),
            "required_skips": (),
            "material_unknowns": (),
            "reviewer": "reviewer",
            "verdict": ParityVerdict.PASS,
            **changes,
        }
    )


@pytest.mark.parametrize("dimension", DIMENSIONS)
@pytest.mark.parametrize("disposition", list(ParityDisposition))
def test_every_dimension_delegates_the_same_fixture_to_accepted_m8(
    dimension: str, disposition: ParityDisposition
) -> None:
    fixture = report(rows=(row(**{dimension: disposition}),))
    assert evaluate_quality_parity(fixture, HEAD) is evaluate_parity(fixture, HEAD)


@pytest.mark.parametrize(
    "changes",
    [
        {"rows": ()},
        {"required_skips": ("skip",)},
        {"material_unknowns": ("unknown",)},
        {"integrated_head": "d" * 40},
        {"verdict": ParityVerdict.BLOCKED},
    ],
)
def test_report_claims_and_missing_evidence_follow_m8(changes: dict[str, object]) -> None:
    fixture = report(**changes)
    assert evaluate_quality_parity(fixture, HEAD) is evaluate_parity(fixture, HEAD)


def test_excluded_only_and_mixed_reports_preserve_real_measurement_requirement() -> None:
    excluded = row(
        behavior_id="excluded",
        intentional_difference="out of scope",
        **dict.fromkeys(DIMENSIONS, ParityDisposition.EXCLUDED),
    )
    assert evaluate_quality_parity(report(rows=(excluded,)), HEAD) is ParityVerdict.BLOCKED
    assert evaluate_quality_parity(report(rows=(row(), excluded)), HEAD) is ParityVerdict.PASS
    assert (
        evaluate_quality_parity(report(rows=(row(resources=ParityDisposition.EXCLUDED),)), HEAD)
        is ParityVerdict.BLOCKED
    )


@pytest.mark.parametrize("head", ["", "0" * 40, "A" * 40, "a" * 39, "a" * 41, "z" * 40, " " + HEAD, None, 1])
def test_unbound_or_noncanonical_heads_block_even_if_they_match(head: object) -> None:
    fixture = report().model_copy(update={"integrated_head": head})
    assert evaluate_quality_parity(fixture, head) is ParityVerdict.BLOCKED


@pytest.mark.parametrize(
    "changes",
    [
        {"rows": None},
        {"rows": ({"functionality": "PARITY"},)},
        {"required_skips": 1},
        {"contract_version": "CANARY_SECRET"},
    ],
)
def test_bypassed_invalid_models_block_without_leaking(changes: dict[str, object]) -> None:
    assert evaluate_quality_parity(report().model_copy(update=changes), HEAD) is ParityVerdict.BLOCKED
