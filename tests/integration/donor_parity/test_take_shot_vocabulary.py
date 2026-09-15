from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path

import pytest

from r2.contracts.production import CameraAngle, CameraMovement, ShotSize
from tests.integration.donor_parity._harness import run_node_runner

_REPO_ROOT = Path(__file__).parents[3]
_CASES_PATH = "tests/integration/donor_parity/fixtures/take_shot_vocabulary/cases.json"

_PY_GROUPS: dict[str, type[StrEnum]] = {
    "shot_size": ShotSize,
    "camera_angle": CameraAngle,
    "camera_movement": CameraMovement,
}


def _load_cases() -> list[dict]:
    return json.loads((_REPO_ROOT / _CASES_PATH).read_text())


def _is_valid_member(enum_cls: type[StrEnum], candidate: str) -> bool:
    try:
        enum_cls(candidate)
    except ValueError:
        return False
    return True


def test_take_baseline_manifest_matches_the_pinned_source() -> None:
    manifest = json.loads((_REPO_ROOT / "docs/r2/evidence/R2_M6_DONOR_BASELINE.json").read_text())
    entry = manifest["ports"]["take_shot_vocabulary"]
    assert entry["revision"] == "47c17216b5ad74ee7dd376e8508266e29aefae2c"
    assert entry["source_sha256"] == "a068c66b20a364ebff19d6d0ec407b499d0e0f1f1d34559e42af5344b6649bbc"
    vendored = _REPO_ROOT / "tests/integration/donor_parity/vendor" / entry["vendored_path"]
    assert hashlib.sha256(vendored.read_bytes()).hexdigest() == entry["source_sha256"]


def test_every_group_is_covered_by_at_least_one_valid_and_one_invalid_case() -> None:
    cases = _load_cases()
    for group in _PY_GROUPS:
        group_cases = [c for c in cases if c["group"] == group]
        assert any(_is_valid_member(_PY_GROUPS[group], c["candidate"]) for c in group_cases)
        assert any(not _is_valid_member(_PY_GROUPS[group], c["candidate"]) for c in group_cases)


@pytest.fixture(scope="session")
def take_node_baseline(donor_node_env) -> dict[str, dict]:
    return run_node_runner(donor_node_env, "take_shot_vocabulary_runner.mjs", _CASES_PATH)


@pytest.mark.parametrize("group", sorted(_PY_GROUPS))
def test_python_enum_order_matches_the_pinned_source_exactly(group: str, take_node_baseline: dict[str, dict]) -> None:
    node_members = take_node_baseline[f"__{group}__"]["members"]
    python_members = [member.value for member in _PY_GROUPS[group]]
    assert python_members == node_members


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: case["id"])
def test_python_vocabulary_matches_the_node_baseline_for_every_case(
    case: dict, take_node_baseline: dict[str, dict]
) -> None:
    python_valid = _is_valid_member(_PY_GROUPS[case["group"]], case["candidate"])
    assert python_valid == take_node_baseline[case["id"]]["valid"]
