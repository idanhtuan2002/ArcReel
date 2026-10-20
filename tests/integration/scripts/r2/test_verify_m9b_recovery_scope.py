"""Real Git lineage and ownership enforcement for the additive recovery release."""

from __future__ import annotations

import importlib
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
RELEASE = "3964da7a705ca9c555b7515c6cc7b73531224244"
RECORD = "docs/r2/evidence/R2_M9_B_RECOVERY_V2_RELEASE.json"
MIGRATION = "alembic/versions/9b9c4a0e0002_add_m9_manual_admission.py"


def git(repo: Path, *args: str, data: str | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], input=data, text=True, capture_output=True, check=True
    ).stdout.strip()


def module() -> Any:
    assert importlib.util.find_spec("scripts.r2.verify_m9b_recovery_scope") is not None, (
        "recovery scope verifier missing"
    )
    return importlib.import_module("scripts.r2.verify_m9b_recovery_scope")


@pytest.fixture
def released_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    git(ROOT, "clone", "--shared", "--no-checkout", "-q", str(ROOT), str(repo))
    original = json.loads(
        git(ROOT, "show", "5b7a4be9f4b083f1d00db8005b49d7ba664658b8:docs/r2/evidence/R2_M9_B_PACKET_RELEASE.json")
    )
    readiness = json.loads(
        git(ROOT, "show", "5b7a4be9f4b083f1d00db8005b49d7ba664658b8:docs/r2/evidence/R2_M9_B_READINESS.json")
    )
    record = json.loads(git(ROOT, "show", RELEASE + ":" + RECORD))
    paths = set(original["artifacts"]) | set(readiness["files"]) | set(record["artifacts"])
    paths |= set(record["frozen_baseline_paths"]) | {RECORD, "docs/r2/evidence/R2_M9_B_PACKET_RELEASE.json"}
    git(repo, "sparse-checkout", "init", "--no-cone")
    git(repo, "sparse-checkout", "set", "--no-cone", "--stdin", data="".join("/" + p + "\n" for p in sorted(paths)))
    git(repo, "checkout", "-q", "-B", "impl/r2-m9b-acquisition-observations", RELEASE)
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Recovery scope fixture")
    return repo


def verify(repo: Path, record: dict[str, Any] | None = None, *, environment_ok: bool = True) -> list[str]:
    if record is None:
        record = json.loads(git(ROOT, "show", RELEASE + ":" + RECORD))
    return module().verify_m9b_recovery_scope(
        repo, record, environment_check=list if environment_ok else lambda: ["fixture target unavailable"]
    )


def commit(repo: Path) -> None:
    git(repo, "add", "--sparse", "-A")
    git(repo, "commit", "-qm", "synthetic fixture mutation")


def test_exact_released_descendant_is_eligible(released_repo: Path) -> None:
    before = git(released_repo, "status", "--porcelain=v1")
    assert verify(released_repo) == []
    assert git(released_repo, "status", "--porcelain=v1") == before == ""


@pytest.mark.parametrize(
    "path",
    [
        "docs/superpowers/specs/2026-10-20-r2-m9b-manual-recovery-v2-design.md",
        "docs/superpowers/plans/2026-10-20-r2-m9b-manual-recovery-v2.md",
        "docs/research/2026-10-20-r2-m9b-upload-custody.md",
        RECORD,
        "docs/r2/evidence/R2_M9_B_PACKET_RELEASE.json",
        "docs/r2/evidence/R2_M9_A_IMPLEMENTATION_ACCEPTANCE.json",
        "r2/contracts/opportunity.py",
        "r2/opportunity/ports.py",
        "scripts/r2/verify_m9b_scope.py",
        "alembic/versions/9b9c4a0e0001_add_m9_acquisition_observations.py",
    ],
)
def test_committed_frozen_authority_drift_is_refused(released_repo: Path, path: str) -> None:
    with (released_repo / path).open("a") as stream:
        stream.write("\n# synthetic tamper\n")
    commit(released_repo)
    assert verify(released_repo)


@pytest.mark.parametrize("fault", ["extra_key", "ownership", "approval", "parent", "activation"])
def test_caller_cannot_substitute_amendment_authority(released_repo: Path, fault: str) -> None:
    record = json.loads((released_repo / RECORD).read_text())
    if fault == "extra_key":
        record["unreviewed"] = True
    elif fault == "ownership":
        record["owned_modify_paths"].append("server/auth.py")
    elif fault == "approval":
        record["approval"]["plan_approved"] = False
    elif fault == "parent":
        record["baseline"] = "0" * 40
    else:
        record["production_activation_authorized"] = True
    assert verify(released_repo, record)


@pytest.mark.parametrize("fault", ["dirty", "outside_commit", "wrong_branch", "detached", "pre_amendment"])
def test_ineligible_git_state_is_refused(released_repo: Path, fault: str) -> None:
    if fault in {"dirty", "outside_commit"}:
        (released_repo / "outside.txt").write_text("synthetic")
        if fault == "outside_commit":
            commit(released_repo)
    elif fault == "wrong_branch":
        git(released_repo, "checkout", "-qb", "unreleased")
    elif fault == "detached":
        git(released_repo, "checkout", "-q", "--detach")
    else:
        git(released_repo, "checkout", "-q", "--detach", "4c4861e9ae6fe74ca6828d676791ae203252e139")
    assert verify(released_repo)


@pytest.mark.parametrize("fault", ["valid", "wrong_parent", "extra_head"])
def test_only_the_released_linear_successor_migration_is_eligible(released_repo: Path, fault: str) -> None:
    target = released_repo / MIGRATION
    target.parent.mkdir(parents=True, exist_ok=True)
    parent = "9b9c4a0e0001" if fault != "wrong_parent" else "9a9c4a0e0001"
    target.write_text(f"revision = '9b9c4a0e0002'\ndown_revision = {parent!r}\n")
    if fault == "extra_head":
        (target.parent / "rogue.py").write_text("revision = 'rogue'\ndown_revision = '9b9c4a0e0001'\n")
    commit(released_repo)
    errors = verify(released_repo)
    if fault == "valid":
        assert errors == []
    else:
        assert errors


def test_missing_or_malformed_authority_refuses_without_writes(released_repo: Path, tmp_path: Path) -> None:
    (released_repo / RECORD).unlink()
    commit(released_repo)
    assert verify(released_repo)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert verify(empty, {})
    assert list(empty.iterdir()) == []


def test_missing_disposable_environment_is_not_pass(released_repo: Path) -> None:
    errors = verify(released_repo, environment_ok=False)
    assert any("fixture target unavailable" in error for error in errors)


@pytest.mark.parametrize("field", ["private_key_in_runtime", "production_activation_authorized"])
def test_numeric_false_alias_cannot_replace_boolean_authority(released_repo: Path, field: str) -> None:
    record = json.loads((released_repo / RECORD).read_text())
    record[field] = 0
    assert verify(released_repo, record)
