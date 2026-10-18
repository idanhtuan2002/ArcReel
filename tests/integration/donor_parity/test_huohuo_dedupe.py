from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from server.story_authoring.checks import DONOR_PUNCTUATION, find_intra_chapter_near_duplicate
from tests.integration.donor_parity._harness import load_jsonl, run_node_runner

_REPO_ROOT = Path(__file__).parents[3]
_CASES = "tests/integration/donor_parity/fixtures/huohuo_dedupe/cases.jsonl"


def _vendored() -> dict:
    baseline = json.loads((_REPO_ROOT / "docs/r2/evidence/R2_STORY_DONOR_BASELINE.json").read_text(encoding="utf-8"))
    surface = next(s for s in baseline["surfaces"] if s["id"] == "S08_intra_chapter_dedupe")
    assert surface["source_sha256"] == surface["vendored"]["files"][surface["vendored"]["entry"]]
    return surface["vendored"]


def test_the_vendored_donor_files_are_the_pinned_bytes() -> None:
    vendored = _vendored()
    for relative, digest in vendored["files"].items():
        assert hashlib.sha256((_REPO_ROOT / vendored["root"] / relative).read_bytes()).hexdigest() == digest


@pytest.fixture(scope="session")
def dedupe_node_baseline(donor_node_env) -> dict[str, dict]:
    return run_node_runner(donor_node_env, "huohuo_dedupe_runner.mjs", _CASES)


def _python_hit(case: dict) -> dict | None:
    hit = find_intra_chapter_near_duplicate(case["input"], case.get("min_fingerprint", 36), profile=DONOR_PUNCTUATION)
    if hit is None:
        return None
    return {
        "removeStart": hit.remove_start,
        "removeEnd": hit.remove_end,
        "fingerprintLen": hit.fingerprint_len,
        "excerpt": hit.excerpt,
    }


@pytest.mark.parametrize("case", load_jsonl(_CASES), ids=lambda case: case["id"])
def test_python_port_matches_node_baseline(case: dict, dedupe_node_baseline: dict[str, dict]) -> None:
    assert _python_hit(case) == dedupe_node_baseline[case["id"]]["hit"]


def test_the_fixtures_exercise_both_outcomes(dedupe_node_baseline: dict[str, dict]) -> None:
    hits = [row["hit"] for row in dedupe_node_baseline.values()]
    assert sum(hit is not None for hit in hits) >= 8
    assert sum(hit is None for hit in hits) >= 4
