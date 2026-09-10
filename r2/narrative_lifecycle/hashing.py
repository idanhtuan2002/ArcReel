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
from typing import TYPE_CHECKING

from r2.contracts import canonical_json_bytes, ensure_json_value

if TYPE_CHECKING:
    from r2.contracts.narrative_lifecycle import DraftCandidate, NarrativeRevision

PROSE_CONTENT_HASH_VERSION = "r2-m5c-prose-content-v1"
EVIDENCE_SEMANTIC_FINGERPRINT_VERSION = "r2-m5c-evidence-fingerprint-v1"


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
