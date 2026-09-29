"""The M8 accepted-baseline verifier fails closed on every prerequisite drift (plan Task A0)."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from scripts.r2.verify_m8_scope import Observed, ObservedSeam, evaluate, schema_problems

_SHA = "a" * 64
_OTHER = "b" * 64

BASELINE: dict[str, object] = {
    "schema_version": 1,
    "base_head": "c" * 40,
    "accepted_m7_candidate_head": "d" * 40,
    "branch": "impl/r2-m8a-exploration-promotion",
    "alembic_heads": ["c9e1f4a2b701"],
    "m7_evidence": [
        {
            "path": "docs/r2/evidence/R2_M7_IMPLEMENTATION_ACCEPTANCE.json",
            "sha256": _SHA,
            "status": "M7_IMPLEMENTATION_ACCEPTED",
        }
    ],
    "design_artifacts": [{"path": "docs/adr/0079-m8.md", "sha256": _SHA}],
    "seams": [
        {
            "qualified_name": "r2.host_hardening.promotion:AtomicPromotionService.promote",
            "path": "r2/host_hardening/promotion.py",
            "signature": "(self, *, user_id: str)",
            "sha256": _SHA,
        }
    ],
    "donors": [
        {
            "name": "DramaClaw",
            "url": "https://github.com/dramaclaw/dramaclaw",
            "commit": "e" * 40,
            "files": [{"path": "frontend/src/stores/canvasStore.ts", "sha256": _SHA}],
        }
    ],
    "scope_allowlist": ["r2/advanced_creative/__init__.py"],
    "graph": {"project": "r2-m8a", "generation": "2026-09-29T00:00:00Z", "coverage": "indexed_no_recorded_gap"},
    "created_at": "2026-09-29T00:00:00Z",
}

OBSERVED = Observed(
    branch="impl/r2-m8a-exploration-promotion",
    base_is_ancestor=True,
    changed_paths=(),
    alembic_heads=("c9e1f4a2b701",),
    file_hashes={"docs/r2/evidence/R2_M7_IMPLEMENTATION_ACCEPTANCE.json": _SHA, "docs/adr/0079-m8.md": _SHA},
    evidence_status={"docs/r2/evidence/R2_M7_IMPLEMENTATION_ACCEPTANCE.json": "M7_IMPLEMENTATION_ACCEPTED"},
    accepted_candidate_head="d" * 40,
    seams={
        "r2.host_hardening.promotion:AtomicPromotionService.promote": ObservedSeam(
            path="r2/host_hardening/promotion.py", signature="(self, *, user_id: str)", sha256=_SHA
        )
    },
    donor_commits={"DramaClaw": "e" * 40},
    donor_files={("DramaClaw", "frontend/src/stores/canvasStore.ts"): _SHA},
)


def _codes(problems: list[str]) -> set[str]:
    return {problem.split(":", 1)[0] for problem in problems}


def test_accepts_exact_clean_base() -> None:
    assert evaluate(BASELINE, OBSERVED) == []
    assert schema_problems(BASELINE) == []


def test_accepts_changes_inside_the_scope_allowlist() -> None:
    assert evaluate(BASELINE, replace(OBSERVED, changed_paths=("r2/advanced_creative/__init__.py",))) == []


def test_a_directory_entry_allows_every_path_below_it_only() -> None:
    baseline = {**BASELINE, "scope_allowlist": ["frontend/src/features/creative-canvas/"]}

    inside = evaluate(baseline, replace(OBSERVED, changed_paths=("frontend/src/features/creative-canvas/ui/Page.tsx",)))
    sibling = evaluate(baseline, replace(OBSERVED, changed_paths=("frontend/src/features/creative-canvas-old/x.ts",)))

    assert inside == []
    assert _codes(sibling) == {"M8_PREREQUISITE_NOT_ACCEPTED"}


def test_rejects_design_branch() -> None:
    problems = evaluate(BASELINE, replace(OBSERVED, branch="design/r2-m5b-narrative-context"))

    assert _codes(problems) == {"M8_PREREQUISITE_NOT_ACCEPTED"}


def test_rejects_dirty_tree() -> None:
    problems = evaluate(BASELINE, replace(OBSERVED, changed_paths=("r2/stray.py",)))

    assert _codes(problems) == {"M8_PREREQUISITE_NOT_ACCEPTED"}


@pytest.mark.parametrize(
    "observed",
    [
        replace(OBSERVED, file_hashes={"docs/adr/0079-m8.md": _SHA}),
        replace(
            OBSERVED,
            evidence_status={"docs/r2/evidence/R2_M7_IMPLEMENTATION_ACCEPTANCE.json": "M7_IMPLEMENTATION_NOT_ACCEPTED"},
        ),
        replace(OBSERVED, accepted_candidate_head="f" * 40),
    ],
)
def test_rejects_missing_or_rejected_m7_evidence(observed: Observed) -> None:
    assert _codes(evaluate(BASELINE, observed)) == {"M8_PREREQUISITE_NOT_ACCEPTED"}


@pytest.mark.parametrize(
    "observed",
    [replace(OBSERVED, base_is_ancestor=False), replace(OBSERVED, alembic_heads=("7b7c4a0e0001",))],
)
def test_rejects_head_or_alembic_mismatch(observed: Observed) -> None:
    assert _codes(evaluate(BASELINE, observed)) == {"M8_PREREQUISITE_NOT_ACCEPTED"}


def test_rejects_multiple_alembic_heads() -> None:
    problems = evaluate(BASELINE, replace(OBSERVED, alembic_heads=("c9e1f4a2b701", "8a8c4a0e0001")))

    assert _codes(problems) == {"M8_PREREQUISITE_NOT_ACCEPTED"}


def test_rejects_document_hash_drift() -> None:
    drifted = dict(OBSERVED.file_hashes) | {"docs/adr/0079-m8.md": _OTHER}

    assert _codes(evaluate(BASELINE, replace(OBSERVED, file_hashes=drifted))) == {"M8_PREREQUISITE_NOT_ACCEPTED"}


@pytest.mark.parametrize("field", ["path", "signature", "sha256"])
def test_rejects_seam_signature_or_path_drift(field: str) -> None:
    name = "r2.host_hardening.promotion:AtomicPromotionService.promote"
    seam = OBSERVED.seams[name]
    drifted = replace(seam, **{field: "other"})

    problems = evaluate(BASELINE, replace(OBSERVED, seams={name: drifted}))

    assert _codes(problems) == {"M8_BASE_SEAM_CHANGED"}


def test_rejects_a_missing_seam() -> None:
    assert _codes(evaluate(BASELINE, replace(OBSERVED, seams={}))) == {"M8_BASE_SEAM_CHANGED"}


@pytest.mark.parametrize(
    "observed",
    [
        replace(OBSERVED, donor_commits={"DramaClaw": "f" * 40}),
        replace(OBSERVED, donor_files={("DramaClaw", "frontend/src/stores/canvasStore.ts"): _OTHER}),
        replace(OBSERVED, donor_files={}),
    ],
)
def test_rejects_donor_pin_or_path_drift(observed: Observed) -> None:
    assert _codes(evaluate(BASELINE, observed)) == {"M8_DONOR_BASELINE_DRIFT"}


def test_the_baseline_schema_rejects_unknown_and_missing_fields() -> None:
    extra = copy.deepcopy(BASELINE) | {"unexpected": True}
    missing = {key: value for key, value in BASELINE.items() if key != "seams"}

    assert schema_problems(extra)
    assert schema_problems(missing)


def test_problems_are_sorted() -> None:
    problems = evaluate(
        BASELINE, replace(OBSERVED, changed_paths=("x.py",), donor_commits={"DramaClaw": "f" * 40}, seams={})
    )

    assert problems == sorted(problems)
    assert _codes(problems) == {"M8_PREREQUISITE_NOT_ACCEPTED", "M8_BASE_SEAM_CHANGED", "M8_DONOR_BASELINE_DRIFT"}
