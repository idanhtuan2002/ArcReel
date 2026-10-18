from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from server.story_authoring.checks import DONOR_PUNCTUATION
from server.story_authoring.repair import ContinuityPatch, apply_continuity_patches, build_conflict_excerpt_block
from tests.integration.donor_parity._harness import load_jsonl, run_node_runner

_REPO_ROOT = Path(__file__).parents[3]
_CASES = "tests/integration/donor_parity/fixtures/huohuo_continuity_patch/cases.jsonl"


def test_the_vendored_donor_files_are_the_pinned_bytes() -> None:
    baseline = json.loads((_REPO_ROOT / "docs/r2/evidence/R2_STORY_DONOR_BASELINE.json").read_text(encoding="utf-8"))
    surface = next(s for s in baseline["surfaces"] if s["id"] == "S07_span_local_repair")
    vendored = surface["vendored"]
    assert surface["source_sha256"] == vendored["files"][vendored["entry"]]
    for relative, digest in vendored["files"].items():
        assert hashlib.sha256((_REPO_ROOT / vendored["root"] / relative).read_bytes()).hexdigest() == digest


@pytest.fixture(scope="session")
def patch_node_baseline(donor_node_env) -> dict[str, dict]:
    return run_node_runner(donor_node_env, "huohuo_continuity_patch_runner.mjs", _CASES)


def _python_row(case: dict) -> dict:
    row: dict = {}
    if "patches" in case:
        content, applied, skipped = apply_continuity_patches(
            case["content"], [ContinuityPatch(p["before"], p["after"]) for p in case["patches"]]
        )
        row["apply"] = {"content": content, "applied": applied, "skipped": skipped}
    if "conflicts" in case:
        kwargs = {} if "max_chars" not in case else {"max_chars": case["max_chars"]}
        row["excerpt"] = build_conflict_excerpt_block(
            case["content"], case["conflicts"], profile=DONOR_PUNCTUATION, **kwargs
        )
    return row


@pytest.mark.parametrize("case", load_jsonl(_CASES), ids=lambda case: case["id"])
def test_python_port_matches_node_baseline(case: dict, patch_node_baseline: dict[str, dict]) -> None:
    expected = {key: value for key, value in patch_node_baseline[case["id"]].items() if key != "id"}
    assert _python_row(case) == expected
