"""Versioned canonical hash domains for the M5C Narrative lifecycle.

``compute_prose_content_hash`` reuses the frozen M5B prose normalization so a draft or
revision hash and an accepted-source hash agree on identical prose bytes. The semantic
fingerprint is a separate domain over artifact kind, opaque id, stable scope, exact
bases, provenance, and schema versions. Neither hash selects an artifact or grants
authority.
"""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import UTC
from typing import TYPE_CHECKING

from r2.contracts import canonical_json_bytes, ensure_json_value

if TYPE_CHECKING:
    from r2.contracts.narrative import CanonCommitApproval
    from r2.contracts.narrative_lifecycle import (
        CompilationAttempt,
        ConflictSubject,
        DraftCandidate,
        NarrativeDecisionAuthorization,
        NarrativeDecisionCommand,
        NarrativeHandoffAdmission,
        NarrativeRevision,
    )

PROSE_CONTENT_HASH_VERSION = "r2-m5c-prose-content-v1"
EVIDENCE_SEMANTIC_FINGERPRINT_VERSION = "r2-m5c-evidence-fingerprint-v1"
DECISION_CANONICAL_IDENTITY_HASH_VERSION = "r2-m5c-decision-identity-v1"
CONFLICT_SUBJECT_FINGERPRINT_VERSION = "r2-m5c-conflict-subject-fingerprint-v1"
EXTRACTION_INPUT_FINGERPRINT_VERSION = "r2-m5c-extraction-input-fingerprint-v1"
COMPILATION_INPUT_FINGERPRINT_VERSION = "r2-m5c-compilation-input-fingerprint-v1"
CANON_APPROVAL_BINDING_FINGERPRINT_VERSION = "r2-m5c-canon-approval-binding-v1"
HANDOFF_ADMISSION_IDENTITY_HASH_VERSION = "r2-m5c-handoff-admission-identity-v1"


def normalize_prose(prose: str) -> str:
    """The frozen M5B prose normalization: NFC, then CRLF / CR collapse to LF.

    Byte-identical to the normalization inside
    ``r2.contracts.narrative_context.compute_source_content_hash``; the two are locked
    together by a regression test.
    """
    return unicodedata.normalize("NFC", prose).replace("\r\n", "\n").replace("\r", "\n")


def compute_prose_content_hash(prose: str) -> str:
    """``sha256`` over the normalized UTF-8 prose bytes. Proves prose bytes only."""
    return "pch:" + hashlib.sha256(normalize_prose(prose).encode("utf-8")).hexdigest()


def compute_evidence_semantic_fingerprint(artifact: DraftCandidate | NarrativeRevision) -> str:
    """Content-address a draft candidate or narrative revision over its kind, opaque id,
    stable scope, exact bases, and provenance. Equal prose under different bindings has a
    different fingerprint."""
    from r2.contracts.narrative_lifecycle import DraftCandidate

    if isinstance(artifact, DraftCandidate):
        artifact_kind = "draft_candidate"
        artifact_id = artifact.candidate_id
        lineage: dict[str, object] = {"base_candidate_id": None, "predecessor_revision_id": None}
    else:
        artifact_kind = "narrative_revision"
        artifact_id = artifact.revision_id
        lineage = {
            "base_candidate_id": artifact.base_candidate_id,
            "predecessor_revision_id": artifact.predecessor_revision_id,
        }
    payload = {
        "schema": EVIDENCE_SEMANTIC_FINGERPRINT_VERSION,
        "artifact_kind": artifact_kind,
        "artifact_id": artifact_id,
        "work_scope": artifact.work_scope.model_dump(mode="json"),
        "base_canon_version_id": artifact.base_canon_version_id,
        "plan_version": artifact.plan_version,
        "scene_contract_version": artifact.scene_contract_version,
        "context_pack_id": artifact.context_pack_id,
        "content_hash": artifact.content_hash,
        "provenance": artifact.provenance.model_dump(mode="json"),
        "lineage": lineage,
    }
    return "esf:" + hashlib.sha256(canonical_json_bytes(ensure_json_value(payload))).hexdigest()


def compute_decision_canonical_identity_hash(
    command: NarrativeDecisionCommand, authorization: NarrativeDecisionAuthorization
) -> str:
    """Content-address one Human decision command together with its original
    authorization evidence. Covers decision family, action, stable subject key,
    selected evidence IDs, both expected predecessors, exact Canon/Plan/Scene/Context
    bindings, actor identity, and (for a conflict resolution) conflict coverage, chosen
    resolution, and referenced resolution decisions — plus the exact original
    ``NarrativeDecisionAuthorization``, including its ``authenticated_at`` receipt time.

    Excludes a command's own ``retry_authentication``: fresh
    ``NarrativeDecisionRetryAuthentication`` proves only that the same actor is currently
    authenticated and is never part of decision identity. Also excludes any server-
    assigned ``stored_at`` audit metadata, which this function never receives — it is
    recorded after identity is established and is never compared as identity.
    """
    payload = {
        "schema": DECISION_CANONICAL_IDENTITY_HASH_VERSION,
        "command": command.model_dump(mode="json", exclude={"retry_authentication"}),
        "authorization": authorization.model_dump(mode="json"),
    }
    return "dci:" + hashlib.sha256(canonical_json_bytes(ensure_json_value(payload))).hexdigest()


def compute_conflict_subject_fingerprint(subject: ConflictSubject) -> str:
    """Content-address the minimal canonical conflict subject: the same accepted
    revision plus the same canonical span coverage and effect-key subjects always
    produces the same fingerprint, regardless of which competing change sets or opaque
    lineage ID a caller proposed."""
    payload = {"schema": CONFLICT_SUBJECT_FINGERPRINT_VERSION, "subject": subject.model_dump(mode="json")}
    return "csf:" + hashlib.sha256(canonical_json_bytes(ensure_json_value(payload))).hexdigest()


def compute_extraction_input_fingerprint(
    *,
    revision_content_hash: str,
    extractor_kind: str,
    extractor_version: str,
    policy_ref: str,
    policy_version: str,
) -> str:
    """Content-address the exact inputs an admitted extraction attempt commits to: the
    revision's own content hash plus the extractor/policy identity. Proves determinism
    of inputs only — it says nothing about the extraction's output."""
    payload = {
        "schema": EXTRACTION_INPUT_FINGERPRINT_VERSION,
        "revision_content_hash": revision_content_hash,
        "extractor_kind": extractor_kind,
        "extractor_version": extractor_version,
        "policy_ref": policy_ref,
        "policy_version": policy_version,
    }
    return "if:" + hashlib.sha256(canonical_json_bytes(ensure_json_value(payload))).hexdigest()


def compute_compilation_input_fingerprint(attempt: CompilationAttempt) -> str:
    """Content-address the exact semantic inputs a compilation attempt commits to: the
    accepted revision, its exact bases, every selected change set paired with the review
    decision that selected it, every named conflict resolution, and the exact heads
    observed as currently effective at admission — plus the creative-policy and
    compiler-version identity.

    Excludes the attempt's own opaque ``attempt_id`` / ``generation``, its
    ``requested_canon_delta_id`` (output identity, not input), and all admission/delta
    workflow metadata (``admitted_at`` / ``admitted_by``, ``delta_created_at`` /
    ``delta_created_by``) — none of these change what the compiler is asked to compile.
    """
    payload = {
        "schema": COMPILATION_INPUT_FINGERPRINT_VERSION,
        "work_scope": attempt.work_scope.model_dump(mode="json"),
        "revision_id": attempt.revision_id,
        "revision_acceptance_decision_id": attempt.revision_acceptance_decision_id,
        "selected_change_sets": [item.model_dump(mode="json") for item in attempt.selected_change_sets],
        "conflict_resolution_decision_ids": list(attempt.conflict_resolution_decision_ids),
        "observed_effective_heads": [item.model_dump(mode="json") for item in attempt.observed_effective_heads],
        "base_canon_version_id": attempt.base_canon_version_id,
        "plan_version": attempt.plan_version,
        "scene_contract_version": attempt.scene_contract_version,
        "context_pack_id": attempt.context_pack_id,
        "creative_policy_ref": attempt.creative_policy_ref,
        "creative_policy_version": attempt.creative_policy_version,
        "compiler_version": attempt.compiler_version,
    }
    return "cif:" + hashlib.sha256(canonical_json_bytes(ensure_json_value(payload))).hexdigest()


def compute_canon_approval_binding_fingerprint(approval: CanonCommitApproval) -> str:
    """Content-address every existing M5A ``CanonCommitApproval`` field: ``approval_ref``,
    ``canon_delta_id``, ``payload_hash`` and its algorithm/version, ``content_schema_version``,
    ``project_name``, ``user_id``, ``approved_by``, ``approved_at``, and ``status``.

    ``approved_at`` is normalized to an aware-UTC ISO-8601 string so a change of even one
    second changes the fingerprint; changing the hash algorithm or schema version changes
    the payload (and so the fingerprint) because both are covered fields, never silently
    ignored — a stale binding fails closed rather than matching by coincidence.
    """
    payload = {
        "schema": CANON_APPROVAL_BINDING_FINGERPRINT_VERSION,
        "approval_ref": approval.approval_ref,
        "canon_delta_id": approval.canon_delta_id,
        "payload_hash": approval.payload_hash,
        "payload_hash_algorithm": approval.payload_hash_algorithm,
        "payload_hash_version": approval.payload_hash_version,
        "content_schema_version": approval.content_schema_version,
        "project_name": approval.project_name,
        "user_id": approval.user_id,
        "approved_by": approval.approved_by,
        "approved_at": approval.approved_at.astimezone(UTC).isoformat(),
        "status": approval.status,
    }
    return "cab:" + hashlib.sha256(canonical_json_bytes(ensure_json_value(payload))).hexdigest()


def compute_handoff_admission_identity_hash(admission: NarrativeHandoffAdmission) -> str:
    """Content-address one atomic M5A handoff admission: its opaque id and scope, the
    exact compilation attempt/generation/result it admits, the delta id and payload hash,
    the complete inline M5A approval together with its binding fingerprint and that
    fingerprint's algorithm/version, every named revision/review/resolution decision, the
    exact heads observed as currently effective at the admission instant, the Canon base,
    and the admitting actor.

    Excludes only ``admitted_at`` (server-assigned audit metadata, exactly as
    ``compute_decision_canonical_identity_hash`` excludes ``stored_at``) and the
    ``canonical_identity_hash`` field this function produces. Changing the fingerprint
    algorithm or version therefore changes the identity hash too: a stale binding fails
    closed rather than matching by coincidence.
    """
    payload = {
        "schema": HANDOFF_ADMISSION_IDENTITY_HASH_VERSION,
        "admission": admission.model_dump(mode="json", exclude={"admitted_at", "canonical_identity_hash"}),
    }
    return "hai:" + hashlib.sha256(canonical_json_bytes(ensure_json_value(payload))).hexdigest()
