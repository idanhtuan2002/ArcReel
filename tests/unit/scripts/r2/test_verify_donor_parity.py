"""The donor parity verifier recomputes the surface digest and the verdict (plan Task A1.4)."""

from __future__ import annotations

from r2.advanced_creative.digests import digest_canonical
from scripts.r2.verify_donor_parity import surface_digest, verify_donor_parity

HEAD = "c" * 40
SURFACE = {"a.ts": "sha256:" + "a" * 64}
DIMENSIONS = (
    "functionality",
    "correctness",
    "determinism",
    "failure_safety",
    "data_integrity",
    "observability",
    "performance",
    "resources",
)


def _report(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "behavior_id": "b1",
        "donor_test_refs": ["t1"],
        "fixture_refs": ["f1"],
        "intentional_difference": None,
        "evidence_refs": ["e1"],
    }
    for dimension in DIMENSIONS:
        row[dimension] = "PARITY"
    digest = "sha256:" + "b" * 64
    report: dict[str, object] = {
        "contract_version": "1",
        "donor": {
            "repository_url": "https://example.invalid/donor",
            "commit_sha": "e" * 40,
            "selected_paths": ["a.ts"],
            "reachable_surface_digest": surface_digest(SURFACE),
            "runtime_identity": "node20",
            "behavior_inventory_digest": digest,
            "donor_test_inventory_digest": digest,
            "fixture_set_digest": digest,
        },
        "integrated_head": HEAD,
        "rows": [row],
        "commands": [],
        "required_skips": [],
        "material_unknowns": [],
        "reviewer": "codex",
        "verdict": "PASS",
    }
    return report | overrides


def test_a_consistent_report_passes() -> None:
    assert verify_donor_parity(_report(), HEAD, SURFACE) == []


def test_the_surface_digest_is_the_canonical_path_hash_map() -> None:
    assert surface_digest(SURFACE) == digest_canonical(SURFACE)


def test_a_drifted_selected_file_is_rejected() -> None:
    assert verify_donor_parity(_report(), HEAD, {"a.ts": "sha256:" + "c" * 64})


def test_a_missing_selected_file_is_rejected() -> None:
    assert verify_donor_parity(_report(), HEAD, {})


def test_a_pass_claim_the_rows_do_not_support_is_rejected() -> None:
    problems = verify_donor_parity(_report(rows=[]), HEAD, SURFACE)

    assert any("verdict" in problem for problem in problems)


def test_a_blocked_report_is_reported_even_when_it_says_blocked() -> None:
    assert verify_donor_parity(_report(rows=[], verdict="BLOCKED"), HEAD, SURFACE)


def test_an_invalid_report_is_rejected() -> None:
    assert verify_donor_parity(_report(verdict="MAYBE"), HEAD, SURFACE)
