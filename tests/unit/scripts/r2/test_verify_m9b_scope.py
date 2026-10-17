from __future__ import annotations

import importlib
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

RELEASE = "5b7a4be9f4b083f1d00db8005b49d7ba664658b8"
RELEASE_PATH = "docs/r2/evidence/R2_M9_B_PACKET_RELEASE.json"
ROOT = Path(__file__).resolve().parents[4]


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL, text=True).strip()


@pytest.fixture
def released_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", "--shared", "--no-checkout", "-q", str(ROOT), str(repo)], check=True)
    _git(repo, "checkout", "-q", "-B", "impl/r2-m9b-acquisition-observations", RELEASE)
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "Scope fixture")
    if importlib.util.find_spec("scripts.r2.verify_m9b_scope") is not None:
        monkeypatch.setattr(_module(), "environment_problems", list)
    return repo


def _module() -> Any:
    assert importlib.util.find_spec("scripts.r2.verify_m9b_scope") is not None, "B0 verifier is missing"
    return importlib.import_module("scripts.r2.verify_m9b_scope")


def _verify(repo: Path, release: dict[str, Any] | None = None) -> list[str]:
    if release is None:
        release = json.loads(_git(ROOT, "show", f"{RELEASE}:{RELEASE_PATH}"))
    return _module().verify_m9b_scope(repo, release)


def _commit(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fixture change")


def test_released_clean_predecessor_is_eligible(released_repo: Path) -> None:
    assert _verify(released_repo) == []


@pytest.mark.parametrize(
    "path",
    [
        "docs/r2/evidence/R2_M9_A_IMPLEMENTATION_ACCEPTANCE.json",
        "docs/r2/evidence/reviews/2026-10-16-m9a-foundation-acceptance.md",
        "docs/r2/evidence/R2_M9_B_MANUAL_IMPORT_FIXTURE_PROPOSAL.json",
        "docs/superpowers/plans/2026-10-16-r2-m9b-acquisition-observations.md",
        "r2/contracts/opportunity.py",
        RELEASE_PATH,
    ],
)
def test_modified_frozen_authority_is_refused_even_after_commit(released_repo: Path, path: str) -> None:
    with (released_repo / path).open("a") as stream:
        stream.write("\n# tampered\n")
    _commit(released_repo)
    assert _verify(released_repo, json.loads(_git(ROOT, "show", f"{RELEASE}:{RELEASE_PATH}")))


@pytest.mark.parametrize("fault", ["unapproved", "wrong_parent", "nonpass", "expand_scope", "unknown"])
def test_caller_cannot_substitute_release_authority(released_repo: Path, fault: str) -> None:
    record = json.loads((released_repo / RELEASE_PATH).read_bytes())
    if fault == "unapproved":
        record["approval"]["fixture_approved"] = False
    elif fault == "wrong_parent":
        record["accepted_predecessor"] = "0" * 40
    elif fault == "nonpass":
        record["status"] = "M9_B_CANDIDATE"
    elif fault == "expand_scope":
        record["owned_modify_paths"].append("server/auth.py")
    else:
        record["unreviewed"] = True
    assert _verify(released_repo, record)


@pytest.mark.parametrize(
    "fault", ["dirty", "outside", "wrong_branch", "detached", "wrong_head", "multiple_heads", "wrong_migration"]
)
def test_git_and_migration_admission_fail_closed(released_repo: Path, fault: str) -> None:
    if fault in {"dirty", "outside"}:
        (released_repo / "outside.txt").write_text("unrelated")
        if fault == "outside":
            _commit(released_repo)
    elif fault == "wrong_branch":
        _git(released_repo, "checkout", "-qb", "design/not-released")
    elif fault == "detached":
        _git(released_repo, "checkout", "-q", "--detach")
    elif fault == "wrong_head":
        _git(released_repo, "checkout", "-q", "--detach", "04b1b92184a5d5b0643256be533332de6ed8b009")
    else:
        migration = released_repo / "alembic/versions/9b9c4a0e0001_add_m9_acquisition_observations.py"
        down = "9a9c4a0e0001" if fault == "multiple_heads" else "918c4a0e0001"
        rev = "rogue" if fault == "multiple_heads" else "9b9c4a0e0001"
        migration.write_text(f"revision = {rev!r}\ndown_revision = {down!r}\n")
        _commit(released_repo)
    assert _verify(released_repo)


def test_missing_accepted_artifact_is_refused(released_repo: Path) -> None:
    (released_repo / "docs/r2/evidence/R2_M9_A_IMPLEMENTATION_ACCEPTANCE.json").unlink()
    _commit(released_repo)
    assert _verify(released_repo)


def test_missing_disposable_target_is_refused(released_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_module(), "environment_problems", lambda: ["not a disposable target"])
    assert any(e.startswith("M9_REQUIRED_EVIDENCE_MISSING:") for e in _verify(released_repo))


def test_scope_verification_does_not_create_files_in_nonrepository(tmp_path: Path) -> None:
    assert _verify(tmp_path, {})
    assert list(tmp_path.iterdir()) == []
