from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.r2.verify_m9_prerequisites import GitPrerequisiteReader, verify_repository


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def git_evidence(tmp_path: Path) -> tuple[GitPrerequisiteReader, Path, str]:
    _git(tmp_path, "init", "-q")
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "a.py").write_text("revision = 'a'\ndown_revision = None\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    return GitPrerequisiteReader(tmp_path), tmp_path, _git(tmp_path, "rev-parse", "HEAD")


def test_migration_evidence_uses_the_pinned_tree_despite_working_tree_changes(git_evidence) -> None:
    source, repo, base = git_evidence
    (repo / "alembic" / "versions" / "b.py").write_text("revision = 'b'\ndown_revision = 'a'\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "next")
    head = source.head()
    (repo / "alembic" / "versions" / "rogue.py").write_text("revision = 'rogue'\ndown_revision = None\n")

    base_heads, base_digest = source.migration_metadata(base)
    head_heads, head_digest = source.migration_metadata(head)

    assert base_heads == ("a",)
    assert head_heads == ("b",)
    assert base_digest != head_digest
    assert source.is_ancestor(base, head)
    assert not source.is_ancestor(head, base)
    assert source.dirty_paths() == ["alembic/versions/rogue.py"]


def test_unresolvable_ancestry_is_not_treated_as_an_unrelated_valid_commit(git_evidence) -> None:
    source, _repo, head = git_evidence
    with pytest.raises(ValueError, match="could not resolve"):
        source.is_ancestor("0" * 40, head)


def test_missing_prerequisite_file_fails_closed_in_a_real_git_repository(git_evidence) -> None:
    _source, repo, _head = git_evidence
    errors = verify_repository(repo)
    assert len(errors) == 1
    assert errors[0].startswith("M9_REQUIRED_EVIDENCE_MISSING:")


@pytest.mark.parametrize("fault", [None, "missing", "malformed", "accepted_parent", "evidence_drift"])
def test_real_git_requires_the_reviewed_candidate_before_acceptance(tmp_path: Path, fault: str | None) -> None:
    import hashlib
    import json

    from scripts.r2.verify_m9_prerequisites import (
        M8_ACCEPTANCE,
        M8_PATH,
        M9_PATH,
        P0_PATH,
        P0_SCHEMA,
        P0_SCRIPT,
        SPONSOR_ACCEPTANCE,
    )

    root = Path(__file__).resolve().parents[4]
    repo = tmp_path / "ceremony"
    _git(tmp_path, "clone", "--shared", "--no-checkout", str(root), str(repo))
    _git(repo, "sparse-checkout", "set", "--no-cone", "/docs/", "/alembic/", "/scripts/r2/")
    _git(repo, "checkout", "--detach", SPONSOR_ACCEPTANCE)
    for path in (P0_SCRIPT, P0_SCHEMA):
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / path).read_bytes())
    _git(repo, "add", P0_SCRIPT, P0_SCHEMA)
    _git(repo, "commit", "-qm", "tooling")
    source = GitPrerequisiteReader(repo)
    base = source.head()
    heads, graph = source.migration_metadata(base)
    record = {
        "schema_version": "1",
        "status": "M9_PREREQUISITES_CANDIDATE",
        "combined_base_head": base,
        "alembic_head": heads[0],
        "revision_graph_digest": graph,
        "acceptances": {
            name: {"path": path, "acceptance_commit": ref, "sha256": hashlib.sha256(source.blob(ref, path)).hexdigest()}
            for name, ref, path in (("m8", M8_ACCEPTANCE, M8_PATH), ("m9", SPONSOR_ACCEPTANCE, M9_PATH))
        },
        "tooling": {"path": P0_SCRIPT, "sha256": hashlib.sha256(source.blob(base, P0_SCRIPT)).hexdigest()},
        "schema_sha256": hashlib.sha256(source.blob(base, P0_SCHEMA)).hexdigest(),
        "review": None,
        "required_skips": [],
        "material_unknowns": [],
    }
    path = repo / P0_PATH
    if fault != "missing":
        payload = dict(record)
        if fault == "malformed":
            payload = {}
        elif fault == "accepted_parent":
            payload["status"] = "M9_PREREQUISITES_ACCEPTED"
        elif fault == "evidence_drift":
            payload["tooling"] = {"path": P0_SCRIPT, "sha256": "0" * 64}
        path.write_text(json.dumps(payload))
        _git(repo, "add", P0_PATH)
        _git(repo, "commit", "-qm", "candidate fixture")
    reviewed = source.head()
    record.update(
        status="M9_PREREQUISITES_ACCEPTED",
        combined_base_head=reviewed,
        review={
            "reviewer_id": "disposable-test-fixture",
            "reviewed_candidate_head": reviewed,
            "independent_of_author": True,
            "verdict": "PASS",
            "findings": [],
            "required_skips": [],
            "material_unknowns": [],
            "sealed_at": "2026-10-15T15:00:00Z",
        },
    )
    path.write_text(json.dumps(record))
    _git(repo, "add", P0_PATH)
    _git(repo, "commit", "-qm", "acceptance fixture")
    errors = verify_repository(repo)
    if fault is None:
        assert errors == []
    else:
        assert errors
        assert all(error.startswith("M9_REQUIRED_EVIDENCE_MISSING:") for error in errors)
