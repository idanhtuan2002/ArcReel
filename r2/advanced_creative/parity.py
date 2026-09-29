"""The donor parity fold (spec §4 ``DonorParityReport``, §11).

``PASS`` needs at least one row, the exact integrated HEAD, no required skip or material
unknown, and every dimension of every row ``PARITY`` or ``IMPROVED``. A row may instead be
wholly ``EXCLUDED`` with a reason: that is a behavior outside the selected reachable surface.
A row that is partly excluded is exercised yet unmeasured in some dimension, which is a
reachable exclusion, and it blocks. The report's own verdict is never trusted.
"""

from __future__ import annotations

from r2.contracts.advanced_creative import BehaviorParityRow, DonorParityReport, ParityDisposition, ParityVerdict

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
_PASSING = frozenset({ParityDisposition.PARITY, ParityDisposition.IMPROVED})


def _row_passes(row: BehaviorParityRow) -> bool:
    dispositions = [getattr(row, dimension) for dimension in DIMENSIONS]
    if all(disposition is ParityDisposition.EXCLUDED for disposition in dispositions):
        return bool(row.intentional_difference and row.intentional_difference.strip())
    return all(disposition in _PASSING for disposition in dispositions)


def evaluate_parity(report: DonorParityReport, current_head: str) -> ParityVerdict:
    measured = [row for row in report.rows if getattr(row, DIMENSIONS[0]) is not ParityDisposition.EXCLUDED]
    if (
        not measured
        or report.integrated_head != current_head
        or report.required_skips
        or report.material_unknowns
        or not all(_row_passes(row) for row in report.rows)
    ):
        return ParityVerdict.BLOCKED
    return ParityVerdict.PASS


__all__ = ["DIMENSIONS", "evaluate_parity"]
