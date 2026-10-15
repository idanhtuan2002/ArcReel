from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scripts.r2.verify_m9_prerequisites import (
    verify_prerequisite_record,
    verify_repository,
    verify_sponsor_design,
)

ROOT = Path(__file__).resolve().parents[4]
BASE = "b" * 40
HEAD = "d" * 40
CANDIDATE = "24fa05e0610efa6fb60db50d1b22b10de48f2786"
SPONSOR = "9d4e4ce6a01a4d1077de263b5cbadf4412055103"
M8 = "23cf146a61c3b7acfb78440d2b1498fd9d77db4b"
M9_PATH = "docs/r2/evidence/R2_M9_DESIGN_ACCEPTANCE.json"
M8_PATH = "docs/r2/evidence/R2_M8_IMPLEMENTATION_ACCEPTANCE.json"
P0_PATH = "docs/r2/evidence/R2_M9_PREREQUISITE_ACCEPTANCE.json"
P0_SCHEMA = "docs/r2/evidence/schemas/R2_M9_PREREQUISITE_ACCEPTANCE.schema.json"
P0_SCRIPT = "scripts/r2/verify_m9_prerequisites.py"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class MemoryEvidence:
    def __init__(self) -> None:
        self.blobs: dict[tuple[str, str], bytes] = {}
        self.parent_map: dict[str, list[str]] = {}
        self.changes: dict[str, set[str]] = {}
        self.dirty: list[str] = []
        self.current_head = HEAD
        self.ancestry = {(M8, BASE), (SPONSOR, BASE)}
        self.migrations = {
            BASE: (("918c4a0e0001",), "sha256:" + "1" * 64),
            M8: (("918c4a0e0001",), "sha256:" + "1" * 64),
        }

    def blob(self, ref: str, path: str) -> bytes:
        return self.blobs[(ref, path)]

    def parents(self, ref: str) -> list[str]:
        return self.parent_map[ref]

    def changed_paths(self, ref: str) -> set[str]:
        return self.changes[ref]

    def dirty_paths(self) -> list[str]:
        return self.dirty

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return (ancestor, descendant) in self.ancestry

    def migration_metadata(self, ref: str) -> tuple[tuple[str, ...], str]:
        return self.migrations[ref]

    def head(self) -> str:
        return self.current_head


@pytest.fixture
def evidence() -> tuple[dict[str, Any], MemoryEvidence]:
    source = MemoryEvidence()
    design = json.loads((ROOT / M9_PATH).read_bytes())
    adr = "docs/adr/0081-m9-evidence-first-opportunity-intelligence.md"
    for path in design["artifacts"]:
        current = (ROOT / path).read_bytes()
        original = current.replace(b"status: accepted", b"status: proposed", 1) if path == adr else current
        source.blobs[CANDIDATE, path] = original
        design["artifacts"][path] = _sha(original)
        for ref in (SPONSOR, BASE, HEAD):
            source.blobs[ref, path] = current
    for path in (design["amendment"]["path"], "docs/r2/evidence/schemas/R2_M9_SPONSOR_DESIGN_ACCEPTANCE.schema.json"):
        for ref in (SPONSOR, BASE, HEAD):
            source.blobs[ref, path] = (ROOT / path).read_bytes()
    design_bytes = json.dumps(design).encode()
    base_contract = "docs/r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE_CONTRACT_2026-09-14.json"
    source.blobs[CANDIDATE, base_contract] = (ROOT / base_contract).read_bytes()
    m8_bytes = (ROOT / M8_PATH).read_bytes()
    for ref in (SPONSOR, BASE, HEAD):
        source.blobs[ref, M9_PATH] = design_bytes
    for ref in (M8, BASE, HEAD):
        source.blobs[ref, M8_PATH] = m8_bytes
    source.parent_map = {
        SPONSOR: [CANDIDATE],
        CANDIDATE: [design["accepted_candidate_parent"]],
        HEAD: [BASE],
        M8: [json.loads(m8_bytes)["accepted_candidate_head"]],
    }
    source.changes = {SPONSOR: set(design["acceptance_changed_paths"]), HEAD: {P0_PATH}}
    for ref in (BASE, HEAD):
        source.blobs[ref, P0_SCHEMA] = (ROOT / P0_SCHEMA).read_bytes()
        source.blobs[ref, P0_SCRIPT] = b"verifier tooling fixture"
    record = {
        "schema_version": "1",
        "status": "M9_PREREQUISITES_CANDIDATE",
        "combined_base_head": BASE,
        "alembic_head": "918c4a0e0001",
        "revision_graph_digest": "sha256:" + "1" * 64,
        "acceptances": {
            "m8": {"path": M8_PATH, "sha256": _sha(m8_bytes), "acceptance_commit": M8},
            "m9": {"path": M9_PATH, "sha256": _sha(design_bytes), "acceptance_commit": SPONSOR},
        },
        "tooling": {"path": P0_SCRIPT, "sha256": _sha(b"verifier tooling fixture")},
        "schema_sha256": _sha(source.blobs[HEAD, P0_SCHEMA]),
        "review": None,
        "required_skips": [],
        "material_unknowns": [],
    }
    source.blobs[HEAD, P0_PATH] = json.dumps(record).encode()
    return record, source


def test_sponsor_acceptance_checks_original_git_artifacts(evidence) -> None:
    _record, source = evidence
    assert verify_sponsor_design(source, SPONSOR, current_ref=BASE) == []


@pytest.mark.parametrize("fault", ["candidate", "artifact", "adr", "amendment", "paths", "review_claim"])
def test_sponsor_acceptance_refuses_authority_or_artifact_changes(evidence, fault: str) -> None:
    _record, source = evidence
    value = json.loads(source.blobs[SPONSOR, M9_PATH])
    if fault == "candidate":
        source.parent_map[SPONSOR] = ["a" * 40]
    elif fault == "artifact":
        value["artifacts"]["scripts/r2/verify_m9_design_acceptance.py"] = "0" * 64
    elif fault == "adr":
        source.blobs[SPONSOR, "docs/adr/0081-m9-evidence-first-opportunity-intelligence.md"] += b"changed"
    elif fault == "amendment":
        source.blobs[SPONSOR, "docs/adr/0110-m9-design-acceptance-by-explicit-sponsor-decision.md"] += b"changed"
    elif fault == "paths":
        source.changes[SPONSOR].add("server/auth.py")
    else:
        value["independent_reviews"] = [{"verdict": "PASS"}]
    if fault in {"artifact", "review_claim"}:
        for ref in (SPONSOR, BASE, HEAD):
            source.blobs[ref, M9_PATH] = json.dumps(value).encode()
    assert verify_sponsor_design(source, SPONSOR, current_ref=BASE)


def test_combined_base_candidate_verifies_but_does_not_release_implementation(evidence) -> None:
    record, source = evidence
    assert verify_prerequisite_record(record, source, acceptance_ref=HEAD, candidate=True) == []
    errors = verify_prerequisite_record(record, source, acceptance_ref=HEAD)
    assert any("independent review" in error.lower() for error in errors)


@pytest.mark.parametrize("name", ["m8", "m9"])
def test_combined_base_refuses_missing_acceptance_or_unrelated_lineage(evidence, name: str) -> None:
    record, source = evidence
    ref = record["acceptances"][name]["acceptance_commit"]
    source.ancestry.remove((ref, BASE))
    assert verify_prerequisite_record(record, source, acceptance_ref=HEAD, candidate=True)


@pytest.mark.parametrize("fault", ["dirty", "merge", "extra_path", "multiple_heads", "graph_drift", "tool_drift"])
def test_combined_base_refuses_unreviewable_or_drifted_base(evidence, fault: str) -> None:
    record, source = evidence
    if fault == "dirty":
        source.dirty = ["untracked-work.json"]
    elif fault == "merge":
        source.parent_map[HEAD].append("e" * 40)
    elif fault == "extra_path":
        source.changes[HEAD].add("server/auth.py")
    elif fault == "multiple_heads":
        source.migrations[BASE] = (("918c4a0e0001", "rogue"), "sha256:" + "1" * 64)
    elif fault == "graph_drift":
        source.migrations[BASE] = (("918c4a0e0001",), "sha256:" + "2" * 64)
    else:
        source.blobs[BASE, P0_SCRIPT] += b"changed"
    assert verify_prerequisite_record(record, source, acceptance_ref=HEAD, candidate=True)


@pytest.mark.parametrize(
    "fault", ["missing_m8", "wrong_m8_status", "m8_hash", "m9_hash", "design_drift", "schema_drift"]
)
def test_combined_base_refuses_missing_or_changed_acceptance_evidence(evidence, fault: str) -> None:
    record, source = evidence
    if fault == "missing_m8":
        del source.blobs[M8, M8_PATH]
    elif fault == "wrong_m8_status":
        value = json.loads(source.blobs[M8, M8_PATH])
        value["status"] = "M8_CANDIDATE"
        payload = json.dumps(value).encode()
        for ref in (M8, BASE, HEAD):
            source.blobs[ref, M8_PATH] = payload
        record["acceptances"]["m8"]["sha256"] = _sha(payload)
    elif fault in {"m8_hash", "m9_hash"}:
        record["acceptances"][fault[:2]]["sha256"] = "0" * 64
    elif fault == "design_drift":
        path = "docs/superpowers/specs/2026-09-14-r2-m9-opportunity-research-intelligence-design.md"
        source.blobs[BASE, path] += b"changed"
    else:
        record["schema_sha256"] = "0" * 64
    assert verify_prerequisite_record(record, source, acceptance_ref=HEAD, candidate=True)


def _prepare_accepted(evidence) -> None:
    record, source = evidence
    candidate = deepcopy(record)
    candidate["combined_base_head"] = "c" * 40
    source.blobs[BASE, P0_PATH] = json.dumps(candidate).encode()
    source.parent_map[BASE] = ["c" * 40]
    source.changes[BASE] = {P0_PATH}
    source.ancestry.update({(M8, "c" * 40), (SPONSOR, "c" * 40), (BASE, HEAD)})
    source.migrations["c" * 40] = source.migrations[BASE]
    source.blobs.update(
        {("c" * 40, path): data for (ref, path), data in list(source.blobs.items()) if ref == BASE and path != P0_PATH}
    )
    record["status"] = "M9_PREREQUISITES_ACCEPTED"
    record["review"] = {
        "reviewer_id": "independent-p0-reviewer",
        "reviewed_candidate_head": BASE,
        "independent_of_author": True,
        "verdict": "PASS",
        "findings": [],
        "required_skips": [],
        "material_unknowns": [],
        "sealed_at": "2026-10-15T14:45:00Z",
    }


def test_accepted_prerequisites_require_a_pass_review_of_the_exact_base(evidence) -> None:
    record, source = evidence
    _prepare_accepted(evidence)
    assert verify_prerequisite_record(record, source, acceptance_ref=HEAD) == []
    record["review"]["reviewed_candidate_head"] = "f" * 40
    assert verify_prerequisite_record(record, source, acceptance_ref=HEAD)


@pytest.mark.parametrize("fault", ["missing", "malformed", "accepted_parent", "evidence_drift"])
def test_accepted_prerequisites_require_the_reviewed_candidate_record(evidence, fault: str) -> None:
    record, source = evidence
    _prepare_accepted(evidence)
    record["review"]["reviewed_candidate_head"] = BASE
    candidate = json.loads(source.blobs[BASE, P0_PATH])
    if fault == "missing":
        del source.blobs[BASE, P0_PATH]
    elif fault == "malformed":
        source.blobs[BASE, P0_PATH] = b"{}"
    elif fault == "accepted_parent":
        candidate["status"] = "M9_PREREQUISITES_ACCEPTED"
        candidate["review"] = record["review"]
        source.blobs[BASE, P0_PATH] = json.dumps(candidate).encode()
    else:
        candidate["alembic_head"] = "different"
        source.migrations["c" * 40] = (("different",), candidate["revision_graph_digest"])
        source.blobs[BASE, P0_PATH] = json.dumps(candidate).encode()
    assert verify_prerequisite_record(record, source, acceptance_ref=HEAD)


def test_repository_rejects_duplicate_json_and_missing_prerequisite_record(evidence, tmp_path: Path) -> None:
    _record, source = evidence
    source.blobs[HEAD, P0_PATH] = b'{"status":"x","status":"y"}'
    assert verify_repository(tmp_path, reader=source)
    del source.blobs[HEAD, P0_PATH]
    assert verify_repository(tmp_path, reader=source)


def test_accepted_status_without_review_does_not_release_prerequisites(evidence) -> None:
    record, source = evidence
    changed = deepcopy(record)
    changed["status"] = "M9_PREREQUISITES_ACCEPTED"
    assert verify_prerequisite_record(changed, source, acceptance_ref=HEAD)


def test_historical_prerequisite_ceremony_can_be_verified_only_from_its_descendants(evidence) -> None:
    record, source = evidence
    source.current_head = "e" * 40
    source.ancestry.add((HEAD, source.current_head))
    assert verify_prerequisite_record(record, source, acceptance_ref=HEAD, candidate=True) == []
    source.ancestry.remove((HEAD, source.current_head))
    assert verify_prerequisite_record(record, source, acceptance_ref=HEAD, candidate=True)


@pytest.mark.parametrize("fault", ["head", "dirty"])
def test_worktree_changes_during_verification_fail_closed(evidence, tmp_path: Path, monkeypatch, fault: str) -> None:
    _record, source = evidence
    if fault == "head":
        reads = iter([HEAD, HEAD, "e" * 40])
        monkeypatch.setattr(source, "head", lambda: next(reads))
    else:
        reads = iter([[], ["late-work.json"]])
        monkeypatch.setattr(source, "dirty_paths", lambda: next(reads))
    errors = verify_repository(tmp_path, reader=source, candidate=True)
    assert any("changed during prerequisite verification" in error for error in errors)
