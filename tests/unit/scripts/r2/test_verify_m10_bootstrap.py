"""Design eligibility requires exact Git evidence rather than a success-shaped file."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.r2.verify_m10_bootstrap import (
    ACCEPTANCE_PATH,
    REQUIRED_DESIGN_PATHS,
    SCHEMA_PATH,
    STOP_CODES,
    TEST_PATHS,
    VERIFIER_PATH,
    BootstrapError,
    load_json,
    verify,
)

BASE, CANDIDATE, ACCEPTANCE, PARENT = (c * 40 for c in "1234")


class MemoryRepository:
    def __init__(self) -> None:
        self.head = ACCEPTANCE
        self.live_head = ACCEPTANCE
        self.blobs: dict[tuple[str, str], bytes] = {}
        self.parent_map = {ACCEPTANCE: (CANDIDATE,), CANDIDATE: (BASE,), BASE: (PARENT,), PARENT: ()}
        self.changed_paths: tuple[str, ...] = (ACCEPTANCE_PATH,)
        self.dirty_paths: tuple[str, ...] = ()
        self.candidate_changes: tuple[str, ...] = ()

    def current_head(self) -> str:
        return self.live_head

    def read(self, ref: str, path: str) -> bytes:
        try:
            return self.blobs[(ref, path)]
        except KeyError as exc:
            raise BootstrapError("M10_REQUIRED_EVIDENCE_MISSING") from exc

    def mode(self, ref: str, path: str) -> str:
        self.read(ref, path)
        return "100644"

    def parents(self, ref: str) -> tuple[str, ...]:
        return self.parent_map[ref]

    def ancestor(self, older: str, newer: str) -> bool:
        while newer != older:
            parents = self.parent_map.get(newer, ())
            if not parents:
                return False
            newer = parents[0]
        return True

    def changed(self, older: str, newer: str) -> tuple[str, ...]:
        if newer == CANDIDATE:
            return self.candidate_changes
        return () if older == newer else self.changed_paths

    def dirty(self, protected: set[str]) -> tuple[str, ...]:
        return self.dirty_paths

    def paths(self, ref: str, prefix: str) -> tuple[str, ...]:
        return tuple(p for r, p in self.blobs if r == ref and p.startswith(prefix))


def put(repo: MemoryRepository, ref: str, path: str, value: object) -> dict[str, str]:
    data = value if isinstance(value, bytes) else json.dumps(value).encode()
    repo.blobs[(ref, path)] = data
    return {"path": path, "sha256": hashlib.sha256(data).hexdigest()}


@pytest.fixture
def fixture() -> tuple[MemoryRepository, dict[str, Any], dict[str, Any]]:
    repo = MemoryRepository()
    schema = json.loads((Path(__file__).resolve().parents[4] / SCHEMA_PATH).read_text())
    artifacts = [put(repo, CANDIDATE, p, b"fixture") for p in REQUIRED_DESIGN_PATHS]
    verifier = put(repo, CANDIDATE, VERIFIER_PATH, b"verifier")
    tests = [put(repo, CANDIDATE, p, b"tests") for p in TEST_PATHS]
    schema_ref = put(repo, CANDIDATE, SCHEMA_PATH, json.dumps(schema).encode())
    prerequisites = []
    for owner in ("M7", "M8", "M9", "FACTUAL"):
        ref = put(
            repo,
            BASE,
            f"docs/{owner}.json",
            {"status": f"{owner}_IMPLEMENTATION_ACCEPTED", "accepted_candidate_head": PARENT},
        )
        prerequisites.append({"owner": owner, "accepted_head": BASE, "acceptance_artifact": ref})
    reviewers = []
    for name in ("reviewer-one", "reviewer-two"):
        row = {
            "reviewer_id": name,
            "qualification_evidence": "declared qualification fixture",
            "conflict_declaration": "NO_CONFLICT",
            "rubric_version": "R2_M10_DESIGN_REVIEW_V1",
            "reviewed_candidate_head": CANDIDATE,
            "verdict": "PASS",
            "reviewed_at": "2026-10-25T00:00:00Z",
        }
        reviewers.append({**row, "blind_review_artifact": put(repo, ACCEPTANCE, f"docs/{name}.json", row)})
    envelope: dict[str, Any] = {
        "schema_version": "1",
        "status": "M10_DESIGN_ACCEPTED",
        "milestone": "M10",
        "accepted_design_head": CANDIDATE,
        "accepted_candidate_parent": BASE,
        "author_id": "author",
        "contract_paths_and_sha256": artifacts,
        "evidence_schema_paths_and_sha256": [schema_ref],
        "bootstrap": {"verifier": verifier, "tests": tests},
        "migration_boundary": {
            "implementation_base_head": BASE,
            "singleton_predecessor": "first",
            "production_migration_authorized": False,
        },
        "prerequisite_evidence": prerequisites,
        "scope_allowlist": ["r2/contracts/quality.py"],
        "stop_codes": sorted(STOP_CODES),
        "reviewers": reviewers,
        "rubric_version": "R2_M10_DESIGN_REVIEW_V1",
        "reviewed_at": "2026-10-25T01:00:00Z",
        "required_skips": [],
        "material_unknowns": [],
    }
    for ref in (BASE, CANDIDATE, ACCEPTANCE):
        put(repo, ref, "alembic/versions/first.py", b'revision = "first"\ndown_revision = None\n')
    return repo, envelope, schema


def run(fixture: tuple[MemoryRepository, dict[str, Any], dict[str, Any]]) -> tuple[str, ...]:
    repo, envelope, schema = fixture
    put(repo, ACCEPTANCE, ACCEPTANCE_PATH, envelope)
    return verify(repo, acceptance_ref=ACCEPTANCE, schema=schema)


def test_exact_fixture_closure_is_eligible(fixture) -> None:
    assert run(fixture) == ()


def test_missing_acceptance_is_not_authorization(fixture) -> None:
    repo, _, schema = fixture
    assert verify(repo, acceptance_ref=ACCEPTANCE, schema=schema) == ("M10_DESIGN_NOT_ACCEPTED",)


@pytest.mark.parametrize("body", [b'{"a":1,"a":2}', b'{"n":NaN}', b"[]", b"not json"])
def test_rejects_ambiguous_json(body: bytes) -> None:
    with pytest.raises(BootstrapError):
        load_json(body)


@pytest.mark.parametrize("path", [*REQUIRED_DESIGN_PATHS, VERIFIER_PATH, *TEST_PATHS, SCHEMA_PATH])
def test_changed_bound_bytes_are_refused(fixture, path: str) -> None:
    repo, _, _ = fixture
    repo.blobs[(CANDIDATE, path)] = b"changed"
    assert "M10_SCHEMA_FREEZE_FAILED" in run(fixture)


@pytest.mark.parametrize(
    ("field", "value"),
    [("reviewed_at", "2026-10-25T00:00:00"), ("author_id", "reviewer-one"), ("accepted_candidate_parent", PARENT)],
)
def test_rejects_invalid_time_independence_or_parent(fixture, field: str, value: str) -> None:
    fixture[1][field] = value
    assert run(fixture)


def test_same_reviewer_cannot_supply_two_independent_records(fixture) -> None:
    reviewers = fixture[1]["reviewers"]
    reviewers[1] = copy.deepcopy(reviewers[0])
    assert run(fixture)


def test_review_body_cannot_disagree_with_its_envelope(fixture) -> None:
    repo, envelope, _ = fixture
    reviewer = envelope["reviewers"][0]
    reviewer["blind_review_artifact"] = put(repo, ACCEPTANCE, "docs/reviewer-one.json", {"verdict": "REJECT"})
    assert "M10_REVIEW_INDEPENDENCE_FAILED" in run(fixture)


def test_acceptance_must_be_direct_child_of_reviewed_candidate(fixture) -> None:
    fixture[0].parent_map[ACCEPTANCE] = (BASE,)
    assert "M10_SCHEMA_FREEZE_FAILED" in run(fixture)


@pytest.mark.parametrize("owner", ["M7", "M8", "M9", "FACTUAL"])
def test_unaccepted_predecessor_cannot_be_replaced_by_a_release_label(fixture, owner: str) -> None:
    repo, envelope, _ = fixture
    row = next(r for r in envelope["prerequisite_evidence"] if r["owner"] == owner)
    row["acceptance_artifact"] = put(
        repo, BASE, f"docs/{owner}.json", {"status": "RELEASED", "accepted_candidate_head": PARENT}
    )
    assert "M10_PREREQUISITE_NOT_ACCEPTED" in run(fixture)


def test_two_migration_heads_are_refused_without_importing_code(fixture) -> None:
    put(
        fixture[0],
        CANDIDATE,
        "alembic/versions/second.py",
        b'revision = "second"\ndown_revision = None\nraise RuntimeError("must not execute")\n',
    )
    assert "M10_MIGRATION_BOUNDARY_INVALID" in run(fixture)


def test_same_migration_head_does_not_hide_changed_graph(fixture) -> None:
    put(fixture[0], CANDIDATE, "alembic/versions/first.py", b'revision = "first"\ndown_revision = "missing"\n')
    assert "M10_MIGRATION_BOUNDARY_INVALID" in run(fixture)


def test_dirty_owned_path_is_refused_but_unrelated_work_is_preserved(fixture) -> None:
    fixture[0].dirty_paths = ("notes.txt",)
    assert run(fixture) == ()
    fixture[0].dirty_paths = ("r2/contracts/quality.py",)
    assert "M10_OWNED_PATH_DIRTY" in run(fixture)


def test_acceptance_commit_cannot_change_product_code(fixture) -> None:
    fixture[0].changed_paths = (ACCEPTANCE_PATH, "server/app.py")
    assert "M10_SCHEMA_FREEZE_FAILED" in run(fixture)


def test_dirty_uncommitted_migration_is_not_hidden_by_clean_accepted_head(fixture) -> None:
    fixture[0].dirty_paths = ("alembic/versions/uncommitted.py",)
    assert "M10_OWNED_PATH_DIRTY" in run(fixture)


def test_design_candidate_cannot_smuggle_product_changes_before_acceptance(fixture) -> None:
    fixture[0].candidate_changes = ("server/app.py",)
    assert "M10_SCOPE_EXPANSION_REQUIRED" in run(fixture)


def test_stop_code_freeze_cannot_omit_verifier_refusals(fixture) -> None:
    fixture[1]["stop_codes"] = ["M10_DESIGN_NOT_ACCEPTED"]
    assert "M10_SCHEMA_FREEZE_FAILED" in run(fixture)


def test_invalid_schema_is_a_sanitized_refusal(fixture) -> None:
    fixture[2]["type"] = 12
    assert run(fixture) == ("M10_SCHEMA_FREEZE_FAILED",)


def test_schema_cannot_load_remote_references(fixture, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("schema attempted outbound I/O")

    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    fixture[2]["$ref"] = "https://fixture.invalid/schema.json"
    assert run(fixture) == ("M10_SCHEMA_FREEZE_FAILED",)


def test_unrelated_documentation_is_outside_design_candidate_scope(fixture) -> None:
    fixture[0].candidate_changes = ("docs/r2/evidence/UNRELATED_ACCEPTANCE.json",)
    assert "M10_SCOPE_EXPANSION_REQUIRED" in run(fixture)


def test_head_moved_before_verification_is_not_attested_as_the_old_head(fixture) -> None:
    fixture[0].live_head = BASE
    assert "M10_SCHEMA_FREEZE_FAILED" in run(fixture)


def test_head_moved_during_dirty_checks_is_refused(fixture, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = fixture[0]

    def moved(protected: set[str]) -> tuple[str, ...]:
        repo.live_head = BASE
        return ()

    monkeypatch.setattr(repo, "dirty", moved)
    assert "M10_SCHEMA_FREEZE_FAILED" in run(fixture)
