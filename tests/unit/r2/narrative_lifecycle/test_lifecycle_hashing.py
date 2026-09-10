from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.contracts.narrative_context import compute_source_content_hash
from r2.contracts.narrative_lifecycle import (
    DraftCandidate,
    NarrativeRevision,
    NarrativeWorkScope,
)
from r2.contracts.provenance import Provenance
from r2.narrative_lifecycle.hashing import (
    EVIDENCE_SEMANTIC_FINGERPRINT_VERSION,
    PROSE_CONTENT_HASH_VERSION,
    compute_evidence_semantic_fingerprint,
    compute_prose_content_hash,
    normalize_prose,
)

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
SCOPE = NarrativeWorkScope(
    user_id="u-1",
    project_name="proj",
    plan_id="plan-1",
    scene_contract_id="scene-1",
    canon_branch_id="branch-1",
)


def _provenance() -> Provenance:
    return Provenance(created_by="HUMAN", created_at=NOW)


def _revision(*, base_canon_version_id: str = "cv-1", context_pack_id: str = "ctx-1") -> NarrativeRevision:
    prose = "Hello world.\n"
    return NarrativeRevision(
        revision_id="rev-1",
        work_scope=SCOPE,
        base_candidate_id="cand-1",
        predecessor_revision_id=None,
        base_canon_version_id=base_canon_version_id,
        plan_version=3,
        scene_contract_version=2,
        context_pack_id=context_pack_id,
        normalized_content=prose,
        content_hash=compute_prose_content_hash(prose),
        review_refs=[],
        provenance=_provenance(),
        created_at=NOW,
        created_by="human:anhtuan",
        semantic_fingerprint="esf:placeholder",
    )


def _draft(*, base_canon_version_id: str = "cv-1") -> DraftCandidate:
    prose = "Hello world.\n"
    return DraftCandidate(
        candidate_id="cand-1",
        work_scope=SCOPE,
        base_canon_version_id=base_canon_version_id,
        plan_version=3,
        scene_contract_version=2,
        context_pack_id="ctx-1",
        normalized_content=prose,
        content_hash=compute_prose_content_hash(prose),
        writer_kind="HUMAN",
        writer_version="n/a",
        provenance=_provenance(),
        created_at=NOW,
        created_by="human:anhtuan",
        semantic_fingerprint="esf:placeholder",
    )


def test_hash_domain_versions_are_pinned() -> None:
    assert PROSE_CONTENT_HASH_VERSION == "r2-m5c-prose-content-v1"
    assert EVIDENCE_SEMANTIC_FINGERPRINT_VERSION == "r2-m5c-evidence-fingerprint-v1"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a\r\nb\rc\n", "a\nb\nc\n"),
        ("café", "café"),
        ("plain", "plain"),
    ],
)
def test_normalize_prose_applies_nfc_then_collapses_newlines(raw: str, expected: str) -> None:
    assert normalize_prose(raw) == expected
    assert normalize_prose(normalize_prose(raw)) == normalize_prose(raw)  # idempotent


def test_prose_content_hash_prefix_and_determinism() -> None:
    a = compute_prose_content_hash("line one\r\nline two")
    b = compute_prose_content_hash("line one\nline two")
    assert a.startswith("pch:")
    assert a == b  # CRLF and LF normalize to the same bytes


@pytest.mark.parametrize(
    "prose",
    ["café vs café", "mixed\r\nendings\rhere\n", "ascii only"],
)
def test_prose_content_hash_reuses_the_frozen_m5b_normalized_bytes(prose: str) -> None:
    assert compute_prose_content_hash(prose).removeprefix("pch:") == compute_source_content_hash(prose).removeprefix(
        "nsc:"
    )


def test_equal_prose_under_different_bases_has_distinct_semantic_fingerprint() -> None:
    a = _revision(base_canon_version_id="cv-1")
    b = _revision(base_canon_version_id="cv-2")
    assert a.content_hash == b.content_hash
    assert compute_evidence_semantic_fingerprint(a) != compute_evidence_semantic_fingerprint(b)


def test_semantic_fingerprint_prefix_and_determinism() -> None:
    fp = compute_evidence_semantic_fingerprint(_revision())
    assert fp.startswith("esf:")
    assert fp == compute_evidence_semantic_fingerprint(_revision())


def test_semantic_fingerprint_covers_bindings_and_artifact_kind() -> None:
    assert compute_evidence_semantic_fingerprint(_revision(context_pack_id="ctx-1")) != (
        compute_evidence_semantic_fingerprint(_revision(context_pack_id="ctx-2"))
    )
    # Same opaque id and bytes, different artifact kind -> different fingerprint.
    assert compute_evidence_semantic_fingerprint(_draft()) != compute_evidence_semantic_fingerprint(_revision())
