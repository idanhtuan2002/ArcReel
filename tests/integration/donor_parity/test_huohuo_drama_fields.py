"""R2-DEC-031 donor-parity coverage for the bounded Huohuo outline-drama-fields port
(plan Task 10): baseline manifest, branch-complete corpus, same-fixture source
parity, exact-HEAD evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from r2.adaptation.shuangwen_profile import _parse_chapter_fields
from r2.contracts.adaptation import ShuangwenType
from tests.integration.donor_parity._harness import load_jsonl, run_node_runner

_REPO_ROOT = Path(__file__).parents[3]
_CASES_PATH = "tests/integration/donor_parity/fixtures/huohuo_drama_fields/cases.jsonl"
_SIX_SHUANG_TYPES = {member.value for member in ShuangwenType}


def _load_cases() -> list[dict]:
    return load_jsonl(_CASES_PATH)


def test_huohuo_baseline_manifest_matches_every_pinned_vendored_file() -> None:
    manifest = json.loads((_REPO_ROOT / "docs/r2/evidence/R2_M6_DONOR_BASELINE.json").read_text())
    entry = manifest["ports"]["huohuo_drama_fields"]
    assert entry["revision"] == "f104b853b3563e124d9cde25f9331d323fb483b9"
    assert len(entry["vendored_files"]) == 5
    for file_entry in entry["vendored_files"]:
        vendored = _REPO_ROOT / "tests/integration/donor_parity/vendor" / file_entry["vendored_path"]
        assert hashlib.sha256(vendored.read_bytes()).hexdigest() == file_entry["sha256"], file_entry["vendored_path"]
    entry_path = _REPO_ROOT / "tests/integration/donor_parity/vendor" / entry["entry_vendored_path"]
    assert entry_path.exists()


def test_the_six_pinned_shuang_types_have_at_least_one_valid_fixture_each() -> None:
    """Branch-complete corpus: every one of the six closed values is exercised."""
    cases = _load_cases()
    covered_ids = {case["id"] for case in cases}
    for shuang_type in _SIX_SHUANG_TYPES:
        assert f"valid_shuang_type_{shuang_type}" in covered_ids


def test_the_corpus_covers_chapter_9_plus_ambiguous_type_and_stakes_variants() -> None:
    cases = _load_cases()
    covered_ids = {case["id"] for case in cases}
    required = {
        "chapter_nine_not_applicable",
        "chapter_nine_beats_present_still_not_applicable",
        "ambiguous_shuang_type_first_token_invalid",
        "compound_shuang_type_first_token_valid",
        "unrecognized_shuang_type",
        "missing_beat_ji",
        "short_beat_pan",
        "empty_semantic_beats",
        "stakes_mismatch_small_demand",
        "stakes_ok_explicit_anchor",
        "stakes_no_signal",
        "translated_english_beats",
        "non_keyword_filler_beats",
        "cross_episode_chapter_3",
        "cross_episode_chapter_9",
    }
    assert required <= covered_ids


@pytest.fixture(scope="session")
def huohuo_node_baseline(donor_node_env) -> dict[str, dict]:
    return run_node_runner(donor_node_env, "huohuo_drama_fields_runner.mjs", _CASES_PATH)


def test_python_shuang_type_set_matches_the_node_baseline_exactly(huohuo_node_baseline: dict[str, dict]) -> None:
    node_members = huohuo_node_baseline["__shuang_type_set__"]["members"]
    assert sorted(node_members) == sorted(_SIX_SHUANG_TYPES)
    assert len(node_members) == 6


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: case["id"])
def test_python_field_parsing_matches_the_node_baseline_for_every_case(
    case: dict, huohuo_node_baseline: dict[str, dict]
) -> None:
    donor = huohuo_node_baseline[case["id"]]
    got = _parse_chapter_fields(case["outline"], case["chapter_number"])
    assert sorted(got.missing) == sorted(donor["missing"]), case["id"]
    assert sorted(got.invalid) == sorted(donor["invalid"]), case["id"]
    assert got.hate == donor["hate"], case["id"]
    assert got.shuang == donor["shuang"], case["id"]
    assert got.ji == donor["ji"], case["id"]
    assert got.pan == donor["pan"], case["id"]
    assert got.shuang_type_raw == donor["shuang_type_raw"], case["id"]
