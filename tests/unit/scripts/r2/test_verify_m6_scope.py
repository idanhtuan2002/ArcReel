from __future__ import annotations

from scripts.r2.verify_m6_scope import (
    check_base_sha,
    check_clean_tree,
    check_document_hashes,
    check_graph_evidence,
    check_m5c_accepted,
    check_scope,
)


def test_m5c_accepted_fails_closed_when_final_verification_is_absent() -> None:
    result = check_m5c_accepted(final_verification_exists=False)
    assert result.ok is False
    assert "R2_M5C_FINAL_VERIFICATION.md" in result.detail


def test_m5c_accepted_passes_when_final_verification_is_present() -> None:
    result = check_m5c_accepted(final_verification_exists=True)
    assert result.ok is True


def test_clean_tree_fails_on_a_dirty_checkpoint() -> None:
    result = check_clean_tree(["r2/adaptation/somefile.py"])
    assert result.ok is False
    assert "r2/adaptation/somefile.py" in result.detail


def test_clean_tree_passes_when_nothing_is_dirty() -> None:
    assert check_clean_tree([]).ok is True


def test_base_sha_fails_on_a_wrong_base() -> None:
    result = check_base_sha(actual_base="deadbeef", expected_base="8b1959e7")
    assert result.ok is False
    assert "deadbeef" in result.detail
    assert "8b1959e7" in result.detail


def test_base_sha_passes_when_it_matches() -> None:
    assert check_base_sha(actual_base="8b1959e7", expected_base="8b1959e7").ok is True


def test_document_hashes_fails_on_a_mismatch() -> None:
    result = check_document_hashes(
        recorded={"docs/a.md": "aaa", "docs/b.md": "bbb"},
        actual={"docs/a.md": "aaa", "docs/b.md": "changed"},
    )
    assert result.ok is False
    assert "docs/b.md" in result.detail


def test_document_hashes_fails_when_a_recorded_document_is_missing() -> None:
    result = check_document_hashes(recorded={"docs/a.md": "aaa"}, actual={})
    assert result.ok is False
    assert "docs/a.md" in result.detail


def test_document_hashes_passes_when_everything_matches() -> None:
    recorded = {"docs/a.md": "aaa", "docs/b.md": "bbb"}
    assert check_document_hashes(recorded=recorded, actual=dict(recorded)).ok is True


def test_graph_evidence_fails_when_not_indexed() -> None:
    assert check_graph_evidence(indexed=False, node_count=0).ok is False
    assert check_graph_evidence(indexed=True, node_count=0).ok is False


def test_graph_evidence_passes_when_indexed_with_nodes() -> None:
    assert check_graph_evidence(indexed=True, node_count=100).ok is True


def test_scope_accepts_the_m6a_allowlisted_paths() -> None:
    paths = [
        "docs/r2/evidence/R2_M6_STARTING_STATE.json",
        "scripts/r2/verify_m6_scope.py",
        "tests/unit/scripts/r2/test_verify_m6_scope.py",
    ]
    assert check_scope(paths, checkpoint="M6-A").ok is True


def test_scope_rejects_an_off_allowlist_path() -> None:
    result = check_scope(["r2/adaptation/service.py"], checkpoint="M6-A")
    assert result.ok is False
    assert "r2/adaptation/service.py" in result.detail


def test_scope_rejects_any_migration_since_m6a_adds_none() -> None:
    result = check_scope(["alembic/versions/7a7c4a0e0001_x.py"], checkpoint="M6-A")
    assert result.ok is False
    assert "alembic/versions/" in result.detail
