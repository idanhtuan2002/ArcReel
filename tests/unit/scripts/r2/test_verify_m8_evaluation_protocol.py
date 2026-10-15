"""The M8-F pre-registration verifier (plan F1)."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.r2.verify_m8_evaluation_protocol import PROTOCOL, SCHEMA, protocol_problems, results_problems
from tests.fixtures.r2.m8f_corpus import manifest_digest

REPO = Path(__file__).resolve().parents[4]


def _load(path: Path) -> dict:
    return json.loads((REPO / path).read_text(encoding="utf-8"))


def test_the_current_protocol_passes_and_locks_the_current_corpus() -> None:
    protocol = _load(PROTOCOL)

    assert protocol_problems(protocol, _load(SCHEMA), REPO) == []
    assert protocol["corpus"]["manifest_digest"] == manifest_digest()


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda p: p.pop("effect_policy"), "'effect_policy' is a required property"),
        (lambda p: p["exclusions"].append("video-1"), "exclusions"),
        (lambda p: p["cohorts"].pop(), "cohorts"),
        (lambda p: p.update(unexpected=True), "Additional properties"),
    ],
    ids=["missing-effect-policy", "late-exclusion", "one-cohort", "unknown-field"],
)
def test_an_incomplete_or_widened_protocol_fails(mutate, expected: str) -> None:
    protocol = copy.deepcopy(_load(PROTOCOL))
    mutate(protocol)

    problems = protocol_problems(protocol, _load(SCHEMA), REPO)

    assert any(expected in problem for problem in problems), problems


def test_a_corpus_source_changed_after_registration_fails(tmp_path: Path) -> None:
    protocol = _load(PROTOCOL)
    source = protocol["corpus"]["sources"][0]["path"]
    (tmp_path / source).parent.mkdir(parents=True)
    shutil.copyfile(REPO / source, tmp_path / source)
    for item in protocol["corpus"]["sources"][1:]:
        (tmp_path / item["path"]).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / item["path"], tmp_path / item["path"])
    assert protocol_problems(protocol, _load(SCHEMA), tmp_path) == []

    (tmp_path / source).write_bytes((tmp_path / source).read_bytes() + b"\n# tuned\n")

    assert protocol_problems(protocol, _load(SCHEMA), tmp_path) == [
        f"corpus source {source} changed after registration"
    ]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _commit(repo: Path, path: Path, content: bytes, message: str) -> None:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_bytes(content)
    _git(repo, "add", str(path))
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", message)


def test_results_must_bind_the_protocol_and_follow_its_commit(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    protocol_bytes = b'{"protocol": 1}'
    digest = "sha256:" + hashlib.sha256(protocol_bytes).hexdigest()
    results = Path("docs/r2/evidence/R2_M8_F_RESULTS.json")
    _commit(tmp_path, PROTOCOL, protocol_bytes, "register")
    _commit(tmp_path, results, b"{}", "results")

    assert results_problems({"protocol_digest": digest}, protocol_bytes, tmp_path, results) == []
    assert results_problems({"protocol_digest": "sha256:" + "0" * 64}, protocol_bytes, tmp_path, results) == [
        "results do not bind the registered protocol digest"
    ]


def test_results_committed_before_the_protocol_fail(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    protocol_bytes = b'{"protocol": 1}'
    digest = "sha256:" + hashlib.sha256(protocol_bytes).hexdigest()
    results = Path("docs/r2/evidence/R2_M8_F_RESULTS.json")
    _commit(tmp_path, results, b"{}", "results first")
    _commit(tmp_path, PROTOCOL, protocol_bytes, "late registration")

    assert results_problems({"protocol_digest": digest}, protocol_bytes, tmp_path, results) == [
        "results were committed before or together with the protocol"
    ]
