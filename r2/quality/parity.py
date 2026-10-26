"""Validate bound HEADs, then reuse the accepted M8 eight-dimension parity fold."""

from __future__ import annotations

import re

from r2.advanced_creative.parity import evaluate_parity
from r2.contracts.advanced_creative import DonorParityReport, ParityVerdict


def _bound_head(value: object) -> bool:
    return type(value) is str and re.fullmatch("[0-9a-f]{40}", value) is not None and value != "0" * 40


def evaluate_quality_parity(report: DonorParityReport, current_head: str) -> ParityVerdict:
    """A pure fold proves neither real Git currentness nor donor evidence provenance."""
    try:
        if not _bound_head(current_head) or not _bound_head(report.integrated_head):
            return ParityVerdict.BLOCKED
        validated = DonorParityReport.model_validate(report.model_dump(mode="python", warnings=False))
        return evaluate_parity(validated, current_head)
    except (ValueError, TypeError, AttributeError):
        return ParityVerdict.BLOCKED
