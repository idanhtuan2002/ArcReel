from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from r2.narrative_lifecycle import changeset_parser as port
from tests.integration.donor_parity._harness import load_jsonl, run_node_runner

_REPO_ROOT = Path(__file__).parents[3]
_CASES = "tests/integration/donor_parity/fixtures/huohuo_change_record/cases.jsonl"


def test_huohuo_baseline_manifest_matches_the_pinned_source() -> None:
    manifest = json.loads((_REPO_ROOT / "docs/r2/evidence/R2_M5C_DONOR_BASELINE.json").read_text())
    entry = manifest["ports"]["huohuo_change_record"]
    assert entry["revision"] == "f104b853b3563e124d9cde25f9331d323fb483b9"
    assert entry["source_sha256"] == "dd3a310e1d83f80fca132a6ea64380c3d953c780054d0ea93e9f865c09fb5088"

    vendored = _REPO_ROOT / "tests/integration/donor_parity/vendor" / entry["vendored_path"]
    assert hashlib.sha256(vendored.read_bytes()).hexdigest() == entry["source_sha256"]


def _py_results(text: str) -> dict[str, object]:
    parsed = port.normalize_change_record_artifacts(text)
    peel_prose, peel_blocks = port.peel_orphaned_structured_from_prose(text)
    split_block, split_trailing = port.split_structured_block_and_trailing_prose(text)
    prose, change_block = port.split_prose_and_change_record(text)
    return {
        "canonicalize": port.canonicalize_change_record_headers(text),
        "split_structured": {"changeBlock": split_block, "trailingProse": split_trailing},
        "is_structured": port.is_structured_change_record_block(text),
        "peel_orphan": {"prose": peel_prose, "changeBlocks": peel_blocks},
        "normalize": {
            "prose": parsed.prose,
            "changeBlock": parsed.change_block,
            "reclaimedFakeBlocks": parsed.reclaimed_fake_blocks,
        },
        "split_prose": {"prose": prose, "changeBlock": change_block},
        "strip_echo": port.strip_length_adjust_instruction_echo(text),
    }


def _node_results(row: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in row.items() if key != "id"}


@pytest.fixture(scope="session")
def huohuo_node_baseline(donor_node_env) -> dict[str, dict]:
    return run_node_runner(donor_node_env, "huohuo_change_record_runner.mjs", _CASES)


@pytest.mark.parametrize("case", load_jsonl(_CASES), ids=lambda case: case["id"])
def test_python_port_matches_node_baseline(case: dict, huohuo_node_baseline: dict[str, dict]) -> None:
    assert _py_results(case["input"]) == _node_results(huohuo_node_baseline[case["id"]])
