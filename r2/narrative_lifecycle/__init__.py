"""M5C Narrative lifecycle: pure donor-derived proposal-evidence helpers.

This package holds only pure transformation code. It imports no repository, unit of
work, clock, random source, provider, acceptance service, or Canon transaction service,
and it never produces a ``NarrativeChangeSet`` or Canon state — its output is
proposal-only evidence.
"""

from .changeset_parser import (
    ParsedChangeRecord,
    canonicalize_change_record_headers,
    is_structured_change_record_block,
    normalize_change_record_artifacts,
    peel_orphaned_structured_from_prose,
    split_prose_and_change_record,
    split_structured_block_and_trailing_prose,
    strip_length_adjust_instruction_echo,
)
from .continuity_rules import (
    ContinuityIssue,
    ContinuityReport,
    merge_continuity_reports,
    run_hard_rule_checks,
)

__all__ = [
    "ContinuityIssue",
    "ContinuityReport",
    "ParsedChangeRecord",
    "canonicalize_change_record_headers",
    "is_structured_change_record_block",
    "merge_continuity_reports",
    "normalize_change_record_artifacts",
    "peel_orphaned_structured_from_prose",
    "run_hard_rule_checks",
    "split_prose_and_change_record",
    "split_structured_block_and_trailing_prose",
    "strip_length_adjust_instruction_echo",
]
