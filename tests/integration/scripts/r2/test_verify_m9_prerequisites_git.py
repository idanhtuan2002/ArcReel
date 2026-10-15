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
