"""M5C Narrative lifecycle: pure proposal-evidence helpers and hash domains.

This package holds only pure code. It imports no repository, unit of work, clock, random
source, provider, acceptance service, or Canon transaction service, and it never produces
a ``NarrativeChangeSet`` or Canon state — its output is proposal-only evidence and
content-addressed identities.
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
from .hashing import (
    EVIDENCE_SEMANTIC_FINGERPRINT_VERSION,
    PROSE_CONTENT_HASH_VERSION,
    compute_evidence_semantic_fingerprint,
    compute_prose_content_hash,
    normalize_prose,
)

__all__ = [
    "EVIDENCE_SEMANTIC_FINGERPRINT_VERSION",
    "PROSE_CONTENT_HASH_VERSION",
    "ContinuityIssue",
    "ContinuityReport",
    "ParsedChangeRecord",
    "canonicalize_change_record_headers",
    "compute_evidence_semantic_fingerprint",
    "compute_prose_content_hash",
    "is_structured_change_record_block",
    "merge_continuity_reports",
    "normalize_change_record_artifacts",
    "normalize_prose",
    "peel_orphaned_structured_from_prose",
    "run_hard_rule_checks",
    "split_prose_and_change_record",
    "split_structured_block_and_trailing_prose",
    "strip_length_adjust_instruction_echo",
]
