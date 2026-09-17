from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.contracts.narrative import CanonCommitApproval
from r2.contracts.narrative_context import compute_source_content_hash
from r2.contracts.narrative_lifecycle import (
    DraftCandidate,
    NarrativeDecisionAuthorization,
    NarrativeDecisionRetryAuthentication,
    NarrativeRevision,
    NarrativeWorkScope,
    RevisionAcceptanceCommand,
)
from r2.contracts.provenance import Provenance
from r2.narrative_lifecycle.hashing import (
    CANON_APPROVAL_BINDING_FINGERPRINT_VERSION,
    DECISION_CANONICAL_IDENTITY_HASH_VERSION,
    EVIDENCE_SEMANTIC_FINGERPRINT_VERSION,
    PROSE_CONTENT_HASH_VERSION,
    compute_canon_approval_binding_fingerprint,
    compute_decision_canonical_identity_hash,
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
    assert CANON_APPROVAL_BINDING_FINGERPRINT_VERSION == "r2-m5c-canon-approval-binding-v1"


def _approval(**overrides: object) -> CanonCommitApproval:
    base: dict[str, object] = {
        "approval_ref": "approval-1",
        "canon_delta_id": "delta-1",
        "payload_hash": "sha256:deadbeef",
        "payload_hash_algorithm": "sha256",
        "payload_hash_version": "r2-canon-delta-v1",
        "content_schema_version": "r2-canon-schema-v1",
        "project_name": "proj",
        "user_id": "u-1",
        "approved_by": "showrunner-1",
        "approved_at": NOW,
        "status": "APPROVED",
    }
    return CanonCommitApproval(**(base | overrides))


def test_canon_approval_binding_fingerprint_prefix_and_determinism() -> None:
    fp = compute_canon_approval_binding_fingerprint(_approval())
    assert fp.startswith("cab:")
    assert fp == compute_canon_approval_binding_fingerprint(_approval())


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


def _authorization(**overrides: object) -> NarrativeDecisionAuthorization:
    base: dict[str, object] = {
        "authorization_ref": "auth-1",
        "user_id": "u-1",
        "project_name": "proj",
        "actor_id": "human:1",
        "authority_role": "HUMAN_SHOWRUNNER",
        "decision_family": "REVISION_ACCEPTANCE",
        "action": "ACCEPT",
        "decision_id": "dec-1",
        "stable_subject_fingerprint": "ssf:1",
        "decision_command_fingerprint": "dcf:1",
        "authenticated_at": NOW,
        "authenticated_via": "session:abc",
    }
    return NarrativeDecisionAuthorization(**(base | overrides))


def _retry_authentication(**overrides: object) -> NarrativeDecisionRetryAuthentication:
    base: dict[str, object] = {
        "retry_authentication_ref": "retry-1",
        "user_id": "u-1",
        "project_name": "proj",
        "actor_id": "human:1",
        "authority_role": "HUMAN_SHOWRUNNER",
        "decision_id": "dec-1",
        "authenticated_at": NOW,
        "authenticated_via": "session:xyz",
    }
    return NarrativeDecisionRetryAuthentication(**(base | overrides))


def _revision_command(
    *, actor_id: str = "human:1", canon_version_id: str = "cv-1", **overrides: object
) -> RevisionAcceptanceCommand:
    base: dict[str, object] = {
        "decision_id": "dec-1",
        "action": "ACCEPT",
        "work_scope": SCOPE,
        "selected_revision_id": "rev-1",
        "expected_latest_decision_id": None,
        "expected_effective_decision_id": None,
        "base_canon_version_id": canon_version_id,
        "plan_version": 1,
        "scene_contract_version": 1,
        "context_pack_id": "ctx-1",
        "actor_id": actor_id,
    }
    return RevisionAcceptanceCommand(**(base | overrides))


def test_decision_identity_hash_domain_version_is_pinned() -> None:
    assert DECISION_CANONICAL_IDENTITY_HASH_VERSION == "r2-m5c-decision-identity-v1"


def test_decision_identity_hash_prefix_and_determinism() -> None:
    h = compute_decision_canonical_identity_hash(_revision_command(), _authorization())
    assert h.startswith("dci:")
    assert h == compute_decision_canonical_identity_hash(_revision_command(), _authorization())


def test_retry_authentication_is_not_part_of_decision_identity() -> None:
    cmd, auth = _revision_command(), _authorization()
    h1 = compute_decision_canonical_identity_hash(cmd, auth)
    h2 = compute_decision_canonical_identity_hash(
        cmd.model_copy(update={"retry_authentication": _retry_authentication()}), auth
    )
    assert h1 == h2


def test_changed_actor_or_basis_is_a_different_identity() -> None:
    base = compute_decision_canonical_identity_hash(_revision_command(), _authorization())
    assert base != compute_decision_canonical_identity_hash(
        _revision_command(actor_id="other"), _authorization(actor_id="other")
    )
    assert base != compute_decision_canonical_identity_hash(
        _revision_command(canon_version_id="cv-2"), _authorization()
    )


def test_original_authorization_receipt_time_is_part_of_decision_identity() -> None:
    later = _authorization(authenticated_at=NOW.replace(hour=13))
    assert compute_decision_canonical_identity_hash(_revision_command(), _authorization()) != (
        compute_decision_canonical_identity_hash(_revision_command(), later)
    )
