"""M5C Narrative lifecycle: pure helpers, hash domains, evidence ports, and the
append-only ``NarrativeLifecycleEvidenceService``.

Nothing here imports a concrete repository, session, ORM row, clock, random source,
provider, acceptance service, or Canon transaction service. The evidence service depends
only on the structural ports in ``ports.py``; the SQLAlchemy adapters live under
``lib.db``. This package never mutates a Narrative head.
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
from .coverage import (
    ConflictSubject,
    coverage_contains,
    effect_keys_collide,
    minimal_conflict_subject,
    normalize_effect_keys,
    normalize_source_spans,
    spans_overlap,
)
from .evidence import ExtractionAdmissionCommand, NarrativeLifecycleEvidenceService
from .hashing import (
    DECISION_CANONICAL_IDENTITY_HASH_VERSION,
    EVIDENCE_SEMANTIC_FINGERPRINT_VERSION,
    PROSE_CONTENT_HASH_VERSION,
    compute_decision_canonical_identity_hash,
    compute_evidence_semantic_fingerprint,
    compute_prose_content_hash,
    normalize_prose,
)
from .ports import (
    NarrativeLifecycleEvidenceRepositoryPort,
    NarrativeLifecycleUnitOfWork,
    NarrativeLifecycleUnitOfWorkFactory,
    NarrativeShowrunnerAuthorityPort,
)

__all__ = [
    "DECISION_CANONICAL_IDENTITY_HASH_VERSION",
    "EVIDENCE_SEMANTIC_FINGERPRINT_VERSION",
    "PROSE_CONTENT_HASH_VERSION",
    "ConflictSubject",
    "ContinuityIssue",
    "ContinuityReport",
    "ExtractionAdmissionCommand",
    "NarrativeLifecycleEvidenceRepositoryPort",
    "NarrativeLifecycleEvidenceService",
    "NarrativeLifecycleUnitOfWork",
    "NarrativeLifecycleUnitOfWorkFactory",
    "NarrativeShowrunnerAuthorityPort",
    "ParsedChangeRecord",
    "canonicalize_change_record_headers",
    "compute_decision_canonical_identity_hash",
    "compute_evidence_semantic_fingerprint",
    "compute_prose_content_hash",
    "coverage_contains",
    "effect_keys_collide",
    "is_structured_change_record_block",
    "merge_continuity_reports",
    "minimal_conflict_subject",
    "normalize_change_record_artifacts",
    "normalize_effect_keys",
    "normalize_prose",
    "normalize_source_spans",
    "peel_orphaned_structured_from_prose",
    "run_hard_rule_checks",
    "spans_overlap",
    "split_prose_and_change_record",
    "split_structured_block_and_trailing_prose",
    "strip_length_adjust_instruction_echo",
]
