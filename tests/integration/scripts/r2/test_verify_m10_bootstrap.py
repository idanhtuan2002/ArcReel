"""A Git-object bootstrap reads synthetic acceptance without mutating repository state."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
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
    GitRepository,
    load_json,
    require_release_ancestry,
    verify,
)

SOURCE = Path(__file__).resolve().parents[4]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "--no-optional-locks", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def write(repo: Path, path: str, value: object) -> dict[str, str]:
    data = value if isinstance(value, bytes) else json.dumps(value).encode()
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"path": path, "sha256": hashlib.sha256(data).hexdigest()}


def commit(repo: Path) -> str:
    git(repo, "add", ".")
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "fixture", "--allow-empty")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def accepted_repo(tmp_path: Path) -> tuple[Path, dict[str, Any], str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    parent = commit(repo)
    prerequisites = []
    for owner in ("M7", "M8", "M9", "FACTUAL"):
        artifact = write(
            repo,
            f"docs/{owner}.json",
            {"status": f"{owner}_IMPLEMENTATION_ACCEPTED", "accepted_candidate_head": parent},
        )
        prerequisites.append({"owner": owner, "acceptance_artifact": artifact})
    write(
        repo,
        "alembic/versions/first.py",
        b'revision = "first"\ndown_revision = None\nraise RuntimeError("never import migrations")\n',
    )
    base = commit(repo)
    for row in prerequisites:
        row["accepted_head"] = base
    contracts = [write(repo, p, (SOURCE / p).read_bytes()) for p in REQUIRED_DESIGN_PATHS]
    verifier = write(repo, VERIFIER_PATH, (SOURCE / VERIFIER_PATH).read_bytes())
    tests = [write(repo, p, (SOURCE / p).read_bytes()) for p in TEST_PATHS]
    schema = write(repo, SCHEMA_PATH, (SOURCE / SCHEMA_PATH).read_bytes())
    candidate = commit(repo)
    reviewers = []
    for name in ("reviewer-one", "reviewer-two"):
        body = {
            "reviewer_id": name,
            "qualification_evidence": "synthetic declaration only",
            "conflict_declaration": "NO_CONFLICT",
            "rubric_version": "R2_M10_DESIGN_REVIEW_V1",
            "reviewed_candidate_head": candidate,
            "verdict": "PASS",
            "reviewed_at": "2026-10-25T00:00:00Z",
        }
        reviewers.append({**body, "blind_review_artifact": write(repo, f"docs/{name}.json", body)})
    envelope: dict[str, Any] = {
        "schema_version": "1",
        "status": "M10_DESIGN_ACCEPTED",
        "milestone": "M10",
        "accepted_design_head": candidate,
        "accepted_candidate_parent": base,
        "author_id": "author",
        "contract_paths_and_sha256": contracts,
        "evidence_schema_paths_and_sha256": [schema],
        "bootstrap": {"verifier": verifier, "tests": tests},
        "migration_boundary": {
            "implementation_base_head": base,
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
    write(repo, ACCEPTANCE_PATH, envelope)
    acceptance = commit(repo)
    return repo, envelope, acceptance


def snapshot(repo: Path) -> dict[str, str]:
    return {
        str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in repo.rglob("*") if p.is_file()
    }


def invoke(repo: Path, runner: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(runner), "--repo", str(repo), "--preflight"],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_release_ancestry_rejects_a_predecessor_only_merged_after_release(tmp_path: Path) -> None:
    repo = tmp_path / "release-lineage"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    common = commit(repo)
    write(repo, "release.txt", b"released")
    release = commit(repo)
    git(repo, "checkout", "--detach", common)
    write(repo, "accepted.txt", b"accepted on a side branch")
    accepted = commit(repo)
    git(repo, "-c", "core.hooksPath=/dev/null", "merge", "--no-ff", "-qm", "implementation merge", release)
    implementation = git(repo, "rev-parse", "HEAD")
    repository = GitRepository(repo)
    assert repository.ancestor(release, implementation)
    assert repository.ancestor(accepted, implementation)
    assert not repository.ancestor(accepted, release)
    before = snapshot(repo)
    with pytest.raises(BootstrapError, match="M10_PREREQUISITE_NOT_ACCEPTED"):
        require_release_ancestry(repository, release_base=release, accepted_heads=(accepted,))
    assert snapshot(repo) == before


def test_exact_source_extracted_from_git_is_read_only_and_does_not_import_migrations(
    accepted_repo, tmp_path: Path
) -> None:
    repo, _, _ = accepted_repo
    source = subprocess.run(["git", "show", f"HEAD:{VERIFIER_PATH}"], cwd=repo, capture_output=True, check=True).stdout
    runner = tmp_path / "git-object-runner.py"
    runner.write_bytes(source)
    before = snapshot(repo)
    result = invoke(repo, runner)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "IMPLEMENTATION_ELIGIBLE"
    assert snapshot(repo) == before


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "duplicate_json",
        "wrong_parent",
        "same_reviewer",
        "wrong_hash",
        "naive_time",
        "unaccepted_m9",
        "dirty_owned",
        "dirty_bound",
        "staged_bound",
        "skip_worktree",
        "assume_unchanged",
        "dirty_migration",
        "ignored_owned",
        "two_heads",
    ],
)
def test_refusals_never_write_repository_files(accepted_repo, case: str) -> None:
    repo, envelope, _ = accepted_repo
    candidate = envelope["accepted_design_head"]
    if case == "missing":
        (repo / ACCEPTANCE_PATH).unlink()
    elif case == "duplicate_json":
        (repo / ACCEPTANCE_PATH).write_text('{"status":"x","status":"M10_DESIGN_ACCEPTED"}')
    elif case == "wrong_parent":
        envelope["accepted_design_head"] = envelope["accepted_candidate_parent"]
    elif case == "same_reviewer":
        envelope["author_id"] = "reviewer-one"
    elif case == "wrong_hash":
        envelope["bootstrap"]["verifier"]["sha256"] = "0" * 64
    elif case == "naive_time":
        envelope["reviewed_at"] = "2026-10-25T00:00:00"
    elif case == "unaccepted_m9":
        envelope["prerequisite_evidence"] = [r for r in envelope["prerequisite_evidence"] if r["owner"] != "M9"]
    elif case == "dirty_owned":
        write(repo, "r2/contracts/quality.py", b"uncommitted")
    elif case == "dirty_bound":
        (repo / VERIFIER_PATH).write_text("uncommitted")
    elif case == "staged_bound":
        original = (repo / VERIFIER_PATH).read_bytes()
        write(repo, VERIFIER_PATH, b"staged tamper")
        git(repo, "add", VERIFIER_PATH)
        (repo / VERIFIER_PATH).write_bytes(original)
    elif case in {"skip_worktree", "assume_unchanged"}:
        flag = "--skip-worktree" if case == "skip_worktree" else "--assume-unchanged"
        git(repo, "update-index", flag, VERIFIER_PATH)
        write(repo, VERIFIER_PATH, b"hidden uncommitted bytes")
    elif case == "dirty_migration":
        write(repo, "alembic/versions/new.py", b'revision="new"\ndown_revision="first"\n')
    elif case == "ignored_owned":
        (repo / ".git/info/exclude").write_text("r2/contracts/quality.py\n")
        write(repo, "r2/contracts/quality.py", b"uncommitted")
    elif case == "two_heads":
        write(repo, "alembic/versions/second.py", b'revision="second"\ndown_revision=None\n')
    if case in {"wrong_parent", "same_reviewer", "wrong_hash", "naive_time", "unaccepted_m9"}:
        write(repo, ACCEPTANCE_PATH, envelope)
    if case not in {
        "dirty_owned",
        "dirty_bound",
        "staged_bound",
        "skip_worktree",
        "assume_unchanged",
        "dirty_migration",
        "ignored_owned",
    }:
        git(repo, "reset", "--soft", candidate)
        commit(repo)
    before = snapshot(repo)
    result = invoke(repo, SOURCE / VERIFIER_PATH)
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "REFUSED"
    assert "Traceback" not in result.stderr
    assert snapshot(repo) == before


def test_inherited_git_environment_cannot_redirect_the_requested_repo(
    accepted_repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _, _ = accepted_repo
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    git(other, "config", "user.name", "Fixture")
    git(other, "config", "user.email", "fixture@example.invalid")
    expected = commit(other)
    monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
    assert GitRepository(other).head == expected


def test_a_commit_after_repository_capture_cannot_get_stale_eligibility(accepted_repo) -> None:
    repo, _, acceptance = accepted_repo
    view = GitRepository(repo)
    write(repo, "server/app.py", b"outside scope")
    commit(repo)
    before = snapshot(repo)
    schema = load_json((repo / SCHEMA_PATH).read_bytes())
    assert verify(view, acceptance_ref=acceptance, schema=schema) == ("M10_SCHEMA_FREEZE_FAILED",)
    assert snapshot(repo) == before


@pytest.mark.parametrize(
    "dirty_path",
    [
        "r2/contracts/factual.py",
        "r2/m3/host_integration.py",
        "r2/m3/deliverables.py",
        "lib/env_init.py",
        "r2/host_hardening/master_authority.py",
        "docs/adr/0106-m7-candidate-ids-are-scoped-to-user-and-project.md",
    ],
)
def test_contract_packet_uses_real_v2_predecessors_without_opening_full_m10(tmp_path: Path, dirty_path: str) -> None:
    from scripts.r2.verify_m10_bootstrap import (
        CONTRACT_ACCEPTANCE_PATH,
        CONTRACT_IMPLEMENTATION_BASE,
        CONTRACT_PACKET_PATH,
        CONTRACT_PLAN_PATH,
        CONTRACT_SCHEMA_PATH,
        CONTRACT_SPEC_PATH,
    )

    repo = tmp_path / "contract-repo"
    subprocess.run(
        ["git", "clone", "--shared", "--no-checkout", "--quiet", str(SOURCE), str(repo)],
        check=True,
        capture_output=True,
    )
    git(repo, "checkout", "--detach", "-q", CONTRACT_IMPLEMENTATION_BASE)
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    extras = [CONTRACT_PACKET_PATH, CONTRACT_SPEC_PATH, CONTRACT_SCHEMA_PATH, CONTRACT_PLAN_PATH]
    for path in [*REQUIRED_DESIGN_PATHS, SCHEMA_PATH, VERIFIER_PATH, *TEST_PATHS, *extras]:
        write(repo, path, (SOURCE / path).read_bytes())
    candidate = commit(repo)
    arguments = [
        sys.executable,
        str(SOURCE / VERIFIER_PATH),
        "--repo",
        str(repo),
        "--packet",
        "contracts",
        "--preflight",
    ]
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    missing = subprocess.run(arguments, capture_output=True, text=True, env=environment, timeout=30)
    assert missing.returncode == 2
    assert json.loads(missing.stdout)["stop_codes"] == ["M10_DESIGN_NOT_ACCEPTED"]
    definition = json.loads((repo / CONTRACT_PACKET_PATH).read_text())
    reviewers = []
    for identity in ["synthetic-one", "synthetic-two"]:
        row = {
            "reviewer_id": identity,
            "qualification_evidence": "synthetic fixture, no real acceptance",
            "conflict_declaration": "NO_CONFLICT",
            "rubric_version": "R2_M10_CONTRACT_REVIEW_V1",
            "reviewed_candidate_head": candidate,
            "verdict": "PASS",
            "reviewed_at": "2026-10-25T00:00:00Z",
        }
        reviewers.append(
            {**row, "blind_review_artifact": write(repo, f"docs/r2/evidence/m10-contract-reviews/{identity}.json", row)}
        )

    def bound(path: str) -> dict[str, str]:
        return {"path": path, "sha256": hashlib.sha256((repo / path).read_bytes()).hexdigest()}

    envelope = {
        "schema_version": "1",
        "status": "M10_CONTRACT_DESIGN_ACCEPTED",
        "milestone": "M10_A_A0_A1",
        "accepted_design_head": candidate,
        "accepted_candidate_parent": CONTRACT_IMPLEMENTATION_BASE,
        "author_id": "fixture-author",
        "contract_paths_and_sha256": [
            bound(p) for p in [*REQUIRED_DESIGN_PATHS, CONTRACT_SPEC_PATH, CONTRACT_PACKET_PATH, CONTRACT_PLAN_PATH]
        ],
        "evidence_schema_paths_and_sha256": [bound(SCHEMA_PATH), bound(CONTRACT_SCHEMA_PATH)],
        "bootstrap": {"verifier": bound(VERIFIER_PATH), "tests": [bound(p) for p in TEST_PATHS]},
        "migration_boundary": {
            "implementation_base_head": CONTRACT_IMPLEMENTATION_BASE,
            "singleton_predecessor": "918c4a0e0001",
            "production_migration_authorized": False,
        },
        "prerequisite_evidence": definition["prerequisite_evidence"],
        "scope_allowlist": definition["scope_allowlist"],
        "stop_codes": sorted(STOP_CODES),
        "reviewers": reviewers,
        "rubric_version": "R2_M10_CONTRACT_REVIEW_V1",
        "reviewed_at": "2026-10-25T01:00:00Z",
        "required_skips": [],
        "material_unknowns": [],
        "packet_definition": bound(CONTRACT_PACKET_PATH),
        "implementation_scope": "CONTRACTS_ONLY",
        "full_m10_accepted": False,
        "runtime_activation_authorized": False,
    }
    write(repo, CONTRACT_ACCEPTANCE_PATH, envelope)
    commit(repo)
    before = snapshot(repo)
    result = subprocess.run(arguments, capture_output=True, text=True, env=environment, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "CONTRACT_IMPLEMENTATION_ELIGIBLE"
    assert json.loads(result.stdout)["scope_allowlist"] == definition["scope_allowlist"]
    full = invoke(repo, SOURCE / VERIFIER_PATH)
    assert full.returncode == 2
    assert json.loads(full.stdout)["stop_codes"] == ["M10_DESIGN_NOT_ACCEPTED"]
    assert snapshot(repo) == before

    imported = repo / dirty_path
    imported.write_text(imported.read_text() + "\n# dirty transitive import\n")
    dirty_before = snapshot(repo)
    dirty = subprocess.run(arguments, capture_output=True, text=True, env=environment, timeout=30)
    assert dirty.returncode == 2
    assert json.loads(dirty.stdout)["stop_codes"] == ["M10_OWNED_PATH_DIRTY"]
    assert snapshot(repo) == dirty_before
