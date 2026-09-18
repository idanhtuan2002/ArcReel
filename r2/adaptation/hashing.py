"""Versioned canonical hash domains for M6 dual-profile adaptation evidence.

Each hash domain is versioned independently of the artifact's own content
``schema_version`` selector (plan Task 2: "distinct versioned hash domains...
without sharing hash domain labels") so a hash algorithm change never collides
with a content schema change. Every hash covers every semantic field of its
artifact except: the artifact's own server-assigned identity field (an
``AdaptationMapV2`` submitted twice with byte-identical content is the same
content regardless of which ``adaptation_map_id``/``version`` it landed under),
``created_at``/``created_by`` audit metadata, and the hash field itself.
"""

from __future__ import annotations

import hashlib

from r2.contracts import canonical_json_bytes, ensure_json_value
from r2.contracts.adaptation import (
    AdaptationDecisionAuthorization,
    AdaptationMapV2,
    AdaptationProfileRef,
    MapApprovalCommand,
    ProfileEvaluationReport,
    ProfileWaiverCommand,
    ScreenplayAdmissionCommand,
    ScreenplayArtifactV2,
    ShuangwenAnalysis,
    WesternDramaAnalysis,
)

ADAPTATION_MAP_HASH_VERSION = "r2-m6-adaptation-map-hash-v1"
SCREENPLAY_ARTIFACT_HASH_VERSION = "r2-m6-screenplay-artifact-hash-v1"
WESTERN_ANALYSIS_HASH_VERSION = "r2-m6-western-analysis-hash-v1"
SHUANGWEN_ANALYSIS_HASH_VERSION = "r2-m6-shuangwen-analysis-hash-v1"
PROFILE_EVALUATION_REPORT_HASH_VERSION = "r2-m6-profile-evaluation-report-hash-v1"
DECISION_IDENTITY_HASH_VERSION = "r2-m6-decision-identity-hash-v1"
COMMAND_IDENTITY_HASH_VERSION = "r2-m6-command-identity-hash-v1"

AdaptationEvidenceArtifact = AdaptationMapV2 | ScreenplayArtifactV2 | WesternDramaAnalysis | ShuangwenAnalysis
AdaptationDecisionCommand = MapApprovalCommand | ProfileWaiverCommand | ScreenplayAdmissionCommand


def canonical_adaptation_bytes(payload: object) -> bytes:
    """The one canonical-JSON encoding every M6 adaptation hash is computed over:
    sorted keys, no whitespace, stable under dictionary insertion order."""
    return canonical_json_bytes(ensure_json_value(payload))


def _sha256_hex(payload: object) -> str:
    return hashlib.sha256(canonical_adaptation_bytes(payload)).hexdigest()


def compute_adaptation_hash(artifact: AdaptationEvidenceArtifact) -> str:
    """Selector-dispatched content hash for an adaptation evidence artifact.

    Dispatch is on the artifact's exact type, not a discriminator field, because
    ``AdaptationMapV2``, ``ScreenplayArtifactV2``, ``WesternDramaAnalysis`` and
    ``ShuangwenAnalysis`` have no shared discriminator — each is a distinct,
    independently versioned schema.
    """
    if isinstance(artifact, AdaptationMapV2):
        payload = {
            "schema": ADAPTATION_MAP_HASH_VERSION,
            "content_schema_version": artifact.schema_version,
            "adaptation_branch_ref": artifact.adaptation_branch_ref.model_dump(mode="json"),
            "entries": [entry.model_dump(mode="json") for entry in artifact.entries],
            "profile_analysis_refs": [ref.model_dump(mode="json") for ref in artifact.profile_analysis_refs],
        }
        return "sha256:" + _sha256_hex(payload)
    if isinstance(artifact, ScreenplayArtifactV2):
        payload = {
            "schema": SCREENPLAY_ARTIFACT_HASH_VERSION,
            "content_schema_version": artifact.schema_version,
            "adaptation_branch_ref": artifact.adaptation_branch_ref.model_dump(mode="json"),
            "content_basis": artifact.content_basis.model_dump(mode="json"),
            "scenes": [scene.model_dump(mode="json") for scene in artifact.scenes],
            "characters": artifact.characters,
            "source_mapping_refs": artifact.source_mapping_refs,
            "approval_status": artifact.approval_status.value,
            "locked_for_direction": artifact.locked_for_direction,
            "adaptation_map_ref": artifact.adaptation_map_ref.model_dump(mode="json"),
            "profile_analysis_refs": [ref.model_dump(mode="json") for ref in artifact.profile_analysis_refs],
        }
        return "sha256:" + _sha256_hex(payload)
    if isinstance(artifact, WesternDramaAnalysis):
        payload = {
            "schema": WESTERN_ANALYSIS_HASH_VERSION,
            "content_schema_version": artifact.schema_version,
            "format_findings": [finding.model_dump(mode="json") for finding in artifact.format_findings],
            "rubric_observations": artifact.rubric_observations,
            "evidence_locations": artifact.evidence_locations,
        }
        return "sha256:" + _sha256_hex(payload)
    payload = {
        "schema": SHUANGWEN_ANALYSIS_HASH_VERSION,
        "content_schema_version": artifact.schema_version,
        "chapter_start": artifact.chapter_start,
        "chapter_end": artifact.chapter_end,
        "hen_evidence": artifact.hen_evidence,
        "shuang_evidence": artifact.shuang_evidence,
        "ji_evidence": artifact.ji_evidence,
        "pan_evidence": artifact.pan_evidence,
        "shuang_type": artifact.shuang_type.value if artifact.shuang_type is not None else None,
        "findings": [finding.model_dump(mode="json") for finding in artifact.findings],
    }
    return "sha256:" + _sha256_hex(payload)


def compute_profile_evaluation_report_digest(report: ProfileEvaluationReport) -> str:
    """Content-address a ``ProfileEvaluationReport`` over the exact artifact hash it
    evaluated, the profile it evaluated against, the evaluator version, the sidecar
    it produced, and its ordered findings. Excludes ``created_at`` and the report's
    own ``report_digest``."""
    payload = {
        "schema": PROFILE_EVALUATION_REPORT_HASH_VERSION,
        "content_schema_version": report.schema_version,
        "artifact_hash": report.artifact_hash,
        "profile_ref": report.profile_ref.model_dump(mode="json"),
        "evaluator_version": report.evaluator_version,
        "sidecar_ref": report.sidecar_ref.model_dump(mode="json"),
        "sidecar_digest": report.sidecar_digest,
        "findings": [finding.model_dump(mode="json") for finding in report.findings],
    }
    return "sha256:" + _sha256_hex(payload)


def compute_profile_sidecar_id(artifact_id: str, profile_ref: AdaptationProfileRef) -> str:
    """Return the deterministic sidecar identity for one exact artifact identity
    namespace and profile. The artifact version remains the sidecar ref's version."""
    return f"{artifact_id}:{profile_ref.profile_id.value}"


def compute_decision_identity_hash(
    command: AdaptationDecisionCommand, authorization: AdaptationDecisionAuthorization
) -> str:
    """Content-address one Human decision command together with its original
    authorization evidence — the same command replayed with the same authorization
    always identifies the same decision, independent of ``decision_digest`` or
    ``sequence``, neither of which this function receives."""
    payload = {
        "schema": DECISION_IDENTITY_HASH_VERSION,
        "command": command.model_dump(mode="json"),
        "authorization": authorization.model_dump(mode="json"),
    }
    return "adi:" + _sha256_hex(payload)


def compute_command_identity_hash(command: AdaptationDecisionCommand) -> str:
    """Content-address one decision command alone, with no authorization — the value
    ``AdaptationShowrunnerAuthorityPort.authorize`` binds its minted authorization to
    (plan Task 7). Distinct from ``compute_decision_identity_hash``, which additionally
    covers the authorization and so cannot exist before one is minted; this hash is
    computed first, from the command alone, precisely so the authority port can prove
    the authorization it mints is bound to this exact command content before either
    exists as a stored decision."""
    payload = {"schema": COMMAND_IDENTITY_HASH_VERSION, "command": command.model_dump(mode="json")}
    return "cid:" + _sha256_hex(payload)


__all__ = [
    "ADAPTATION_MAP_HASH_VERSION",
    "COMMAND_IDENTITY_HASH_VERSION",
    "DECISION_IDENTITY_HASH_VERSION",
    "PROFILE_EVALUATION_REPORT_HASH_VERSION",
    "SCREENPLAY_ARTIFACT_HASH_VERSION",
    "SHUANGWEN_ANALYSIS_HASH_VERSION",
    "WESTERN_ANALYSIS_HASH_VERSION",
    "canonical_adaptation_bytes",
    "compute_adaptation_hash",
    "compute_command_identity_hash",
    "compute_decision_identity_hash",
    "compute_profile_evaluation_report_digest",
    "compute_profile_sidecar_id",
]
