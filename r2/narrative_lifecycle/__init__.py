"""M5C Narrative lifecycle: pure helpers, hash domains, evidence ports, the
append-only ``NarrativeLifecycleEvidenceService``, and the internal decision-authority
kernel.

Nothing here imports a concrete repository, session, ORM row, random source, provider,
or Canon transaction service — every adapter lives under ``lib.db`` and every dependency
is a structural port from ``ports.py``. ``authority_kernel.py`` and ``acceptance.py`` are
the two modules that read the wall clock (decision ``stored_at`` / lineage ``created_at``
audit metadata) and mutate a Narrative head or create a conflict-resolution lineage;
every other module in this package is read-only / append-only evidence.
"""

from .acceptance import NarrativeAcceptanceService
from .authority_kernel import ApplicabilityCheck, AuthorityKernel, GenesisPreparation
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
    CONFLICT_SUBJECT_FINGERPRINT_VERSION,
    DECISION_CANONICAL_IDENTITY_HASH_VERSION,
    EVIDENCE_SEMANTIC_FINGERPRINT_VERSION,
    EXTRACTION_INPUT_FINGERPRINT_VERSION,
    PROSE_CONTENT_HASH_VERSION,
    compute_conflict_subject_fingerprint,
    compute_decision_canonical_identity_hash,
    compute_evidence_semantic_fingerprint,
    compute_extraction_input_fingerprint,
    compute_prose_content_hash,
    normalize_prose,
)
from .integrity import NarrativeLifecycleIntegrityChecker
from .ports import (
    NarrativeAuthorityRepositoryPort,
    NarrativeLifecycleEvidenceRepositoryPort,
    NarrativeLifecycleRepositoryPort,
    NarrativeLifecycleUnitOfWork,
    NarrativeLifecycleUnitOfWorkFactory,
    NarrativeShowrunnerAuthorityPort,
)

__all__ = [
    "CONFLICT_SUBJECT_FINGERPRINT_VERSION",
    "DECISION_CANONICAL_IDENTITY_HASH_VERSION",
    "EVIDENCE_SEMANTIC_FINGERPRINT_VERSION",
    "EXTRACTION_INPUT_FINGERPRINT_VERSION",
    "PROSE_CONTENT_HASH_VERSION",
    "ApplicabilityCheck",
    "AuthorityKernel",
    "ConflictSubject",
    "ContinuityIssue",
    "ContinuityReport",
    "ExtractionAdmissionCommand",
    "GenesisPreparation",
    "NarrativeAcceptanceService",
    "NarrativeAuthorityRepositoryPort",
    "NarrativeLifecycleEvidenceRepositoryPort",
    "NarrativeLifecycleEvidenceService",
    "NarrativeLifecycleIntegrityChecker",
    "NarrativeLifecycleRepositoryPort",
    "NarrativeLifecycleUnitOfWork",
    "NarrativeLifecycleUnitOfWorkFactory",
    "NarrativeShowrunnerAuthorityPort",
    "ParsedChangeRecord",
    "canonicalize_change_record_headers",
    "compute_conflict_subject_fingerprint",
    "compute_decision_canonical_identity_hash",
    "compute_evidence_semantic_fingerprint",
    "compute_extraction_input_fingerprint",
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
