"""Folding M8-B donor/port observations into parity rows (scripts/r2/m8b_parity_rows.py)."""

from __future__ import annotations

from r2.contracts.advanced_creative import ParityDisposition
from scripts.r2.m8b_parity_rows import HarnessRun, build_rows, compare_behavior

FIXTURES = {
    "cases": [
        {"id": "same", "behaviors": ["A"]},
        {"id": "fixed", "behaviors": ["B"]},
        {"id": "drift", "behaviors": ["C"]},
    ]
}
OBS = {"same": [{"s": 1}, {"s": 2}], "fixed": [{"s": 1}, {"s": 2}, {"s": 3}], "drift": [{"s": 1}]}
DONOR = {"same": [{"s": 1}, {"s": 2}], "fixed": [{"s": 1}, {"s": 9}, {"s": 9}], "drift": [{"s": 0}]}
CORRECTIONS = [{"harness": "graph", "case": "fixed", "from_step": 1, "behavior": "B", "description": "donor defect"}]


def _run(port_rerun: dict[str, list[object]] | None = None) -> HarnessRun:
    return HarnessRun(
        name="graph", fixtures=FIXTURES, donor=DONOR, port=OBS, port_rerun=port_rerun if port_rerun is not None else OBS
    )


def test_equal_observations_are_parity() -> None:
    assert compare_behavior("A", [_run()], CORRECTIONS) == (
        ParityDisposition.PARITY,
        ParityDisposition.PARITY,
        ["graph:same"],
    )


def test_a_difference_inside_a_declared_correction_is_improved() -> None:
    assert compare_behavior("B", [_run()], CORRECTIONS)[0] is ParityDisposition.IMPROVED


def test_a_difference_before_the_declared_step_is_unverified() -> None:
    corrections = [{**CORRECTIONS[0], "from_step": 2}]

    assert compare_behavior("B", [_run()], corrections)[0] is ParityDisposition.UNVERIFIED


def test_an_undeclared_difference_or_a_missing_fixture_is_unverified() -> None:
    assert compare_behavior("C", [_run()], CORRECTIONS)[0] is ParityDisposition.UNVERIFIED
    assert compare_behavior("Z", [_run()], CORRECTIONS) == (
        ParityDisposition.UNVERIFIED,
        ParityDisposition.UNVERIFIED,
        [],
    )


def test_a_port_rerun_that_differs_is_not_deterministic() -> None:
    rerun = {**OBS, "same": [{"s": 1}, {"s": 3}]}

    assert compare_behavior("A", [_run(rerun)], CORRECTIONS)[1] is ParityDisposition.UNVERIFIED


def test_rows_merge_measured_dimensions_and_record_intentional_differences() -> None:
    baseline = {
        "behaviors": [
            {"behavior_id": "A", "donor_tests": ["t-a"]},
            {"behavior_id": "B", "donor_tests": ["t-b"]},
        ]
    }
    dimensions = {
        "A": {"performance": "PARITY", "resources": "PARITY", "failure_safety": "PARITY", "observability": "PARITY"}
    }

    rows = build_rows(baseline, [_run()], CORRECTIONS, dimensions)

    assert [row.behavior_id for row in rows] == ["A", "B"]
    assert rows[0].performance is ParityDisposition.PARITY
    assert rows[0].intentional_difference is None
    assert rows[1].performance is ParityDisposition.UNVERIFIED
    assert rows[1].intentional_difference == "donor defect"
    assert rows[1].donor_test_refs == ("t-b",)
