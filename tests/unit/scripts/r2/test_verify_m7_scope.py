from __future__ import annotations

from pathlib import Path

from scripts.r2.verify_m7_scope import (
    BASELINE_RELPATH,
    check_alembic_head,
    check_base_sha,
    check_clean_tree,
    check_file_hashes,
    check_m6_accepted,
    check_revision_graph_digest,
    check_submit_route_inventory,
    verify_m7_scope,
)


def test_submit_route_inventory_reports_unbound_symbols(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.r2.verify_m7_scope.submit_route_inventory_problems",
        lambda: ["M7_SUBMIT_ROUTE_UNBOUND:lib.example:Backend.submit"],
    )
    result = check_submit_route_inventory()
    assert result.ok is False
    assert result.detail == "M7_SUBMIT_ROUTE_UNBOUND:lib.example:Backend.submit"


def test_clean_tree_fails_on_a_dirty_checkpoint() -> None:
    result = check_clean_tree(["r2/host_hardening/somefile.py"])
    assert result.ok is False
    assert "r2/host_hardening/somefile.py" in result.detail


def test_clean_tree_passes_when_nothing_is_dirty() -> None:
    assert check_clean_tree([]).ok is True


def test_base_sha_fails_on_a_wrong_ancestor() -> None:
    result = check_base_sha(actual_base="deadbeef", expected_base="814761e3")
    assert result.ok is False
    assert "deadbeef" in result.detail
    assert "814761e3" in result.detail


def test_base_sha_passes_when_it_matches() -> None:
    assert check_base_sha(actual_base="814761e3", expected_base="814761e3").ok is True


def test_m6_accepted_fails_when_status_is_missing() -> None:
    result = check_m6_accepted(status=None)
    assert result.ok is False
    assert "ACCEPTED" in result.detail


def test_m6_accepted_fails_when_status_is_still_pending_review() -> None:
    result = check_m6_accepted(status="PENDING_REVIEW")
    assert result.ok is False
    assert "PENDING_REVIEW" in result.detail


def test_m6_accepted_passes_when_status_is_accepted() -> None:
    assert check_m6_accepted(status="ACCEPTED").ok is True


def test_alembic_head_fails_on_multiple_heads() -> None:
    result = check_alembic_head(actual_heads=("6c7c4a0e0002", "7a7c4a0e0001"), expected_head="6c7c4a0e0002")
    assert result.ok is False
    assert "6c7c4a0e0002" in result.detail
    assert "7a7c4a0e0001" in result.detail


def test_alembic_head_fails_on_the_wrong_single_head() -> None:
    result = check_alembic_head(actual_heads=("deadbeef0001",), expected_head="6c7c4a0e0002")
    assert result.ok is False


def test_alembic_head_passes_on_the_expected_single_head() -> None:
    assert check_alembic_head(actual_heads=("6c7c4a0e0002",), expected_head="6c7c4a0e0002").ok is True


def test_revision_graph_digest_fails_on_an_altered_edge() -> None:
    result = check_revision_graph_digest(actual_digest="sha256:aaa", expected_digest="sha256:bbb")
    assert result.ok is False
    assert "sha256:aaa" in result.detail
    assert "sha256:bbb" in result.detail


def test_revision_graph_digest_passes_when_unchanged() -> None:
    assert check_revision_graph_digest(actual_digest="sha256:aaa", expected_digest="sha256:aaa").ok is True


def test_file_hashes_fails_on_a_mismatch() -> None:
    result = check_file_hashes(
        recorded={"docs/a.md": "aaa", "docs/b.md": "bbb"},
        actual={"docs/a.md": "aaa", "docs/b.md": "changed"},
        label="documents",
    )
    assert result.ok is False
    assert "docs/b.md" in result.detail


def test_file_hashes_fails_when_a_recorded_file_is_missing() -> None:
    result = check_file_hashes(recorded={"r2/production/approval_service.py": "aaa"}, actual={}, label="legacy_seams")
    assert result.ok is False
    assert "r2/production/approval_service.py" in result.detail


def test_file_hashes_passes_when_everything_matches() -> None:
    recorded = {"docs/a.md": "aaa", "docs/b.md": "bbb"}
    assert check_file_hashes(recorded=recorded, actual=dict(recorded), label="documents").ok is True


def test_verify_m7_scope_passes_against_the_real_baseline_and_repo() -> None:
    import json

    repo = Path(__file__).resolve().parents[4]
    baseline = json.loads((repo / BASELINE_RELPATH).read_text())
    assert verify_m7_scope(repo, baseline) == []
