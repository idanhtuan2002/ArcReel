from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from scripts.r2.verify_m9_scope import ScopeObservation, evaluate_scope, verify_m9_scope


def _clean() -> ScopeObservation:
    return ScopeObservation(
        design_errors=(),
        m8_errors=(),
        prerequisite_errors=(),
        branch="impl/r2-m9a-opportunity-foundation",
        base_is_ancestor=True,
        dirty_paths=(),
        outside_paths=(),
        collisions=(),
        heads=("918c4a0e0001",),
        seam_errors=(),
        donor_errors=(),
        environment_errors=(),
        baseline_errors=(),
    )


def test_complete_scope_gate_accepts_only_a_fully_verified_observation() -> None:
    assert evaluate_scope(_clean()) == []


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("design_errors", ("missing design",), "M9_DESIGN_NOT_ACCEPTED"),
        ("design_errors", ("candidate hash drift",), "M9_DESIGN_NOT_ACCEPTED"),
        ("m8_errors", ("missing M8",), "M9_M8_IMPLEMENTATION_NOT_ACCEPTED"),
        ("m8_errors", ("rejected M8",), "M9_M8_IMPLEMENTATION_NOT_ACCEPTED"),
        ("prerequisite_errors", ("missing P0",), "M9_REQUIRED_EVIDENCE_MISSING"),
        ("prerequisite_errors", ("acceptance parent mismatch",), "M9_REQUIRED_EVIDENCE_MISSING"),
        ("branch", "design/r2-m9-v2-revalidation", "M9_REQUIRED_EVIDENCE_MISSING"),
        ("base_is_ancestor", False, "M9_REQUIRED_EVIDENCE_MISSING"),
        ("dirty_paths", ("unrelated.txt",), "M9_REQUIRED_EVIDENCE_MISSING"),
        ("outside_paths", ("server/auth.py",), "POST_M8_BASE_SEAM_CHANGED"),
        ("collisions", ("r2/contracts/opportunity.py",), "POST_M8_BASE_SEAM_CHANGED"),
        ("heads", ("918c4a0e0001", "rogue"), "POST_M8_BASE_SEAM_CHANGED"),
        ("seam_errors", ("signature changed",), "POST_M8_BASE_SEAM_CHANGED"),
        ("donor_errors", ("missing pinned object",), "M9_DONOR_PARITY_INCOMPLETE"),
        ("donor_errors", ("selected path drift",), "M9_DONOR_PARITY_INCOMPLETE"),
        ("environment_errors", ("no disposable target",), "M9_REQUIRED_EVIDENCE_MISSING"),
        ("environment_errors", ("no current grant",), "M9_REQUIRED_EVIDENCE_MISSING"),
        ("baseline_errors", ("required skip",), "M9_REQUIRED_EVIDENCE_MISSING"),
        ("baseline_errors", ("material unknown",), "M9_REQUIRED_EVIDENCE_MISSING"),
    ],
)
def test_scope_failure_routes_to_the_normative_stop_code(field: str, value: object, code: str) -> None:
    errors = evaluate_scope(replace(_clean(), **{field: value}))
    assert errors
    assert all(error.startswith(code + ":") for error in errors)


def test_scope_failures_keep_the_contracts_first_failure_order() -> None:
    observed = replace(
        _clean(),
        design_errors=("design",),
        m8_errors=("M8",),
        dirty_paths=("dirty",),
        seam_errors=("seam",),
        donor_errors=("donor",),
    )
    assert [e.split(":", 1)[0] for e in evaluate_scope(observed)] == [
        "M9_DESIGN_NOT_ACCEPTED",
        "M9_M8_IMPLEMENTATION_NOT_ACCEPTED",
        "M9_REQUIRED_EVIDENCE_MISSING",
        "POST_M8_BASE_SEAM_CHANGED",
        "M9_DONOR_PARITY_INCOMPLETE",
    ]


def test_unreadable_repository_fails_before_creating_any_file(tmp_path: Path) -> None:
    assert verify_m9_scope(tmp_path, {})[0].startswith("M9_DESIGN_NOT_ACCEPTED:")
    assert list(tmp_path.iterdir()) == []


def test_owned_path_inventory_includes_all_translation_paths_in_one_bullet() -> None:
    from scripts.r2.verify_m9_scope import owned_paths

    packet = b"## Exact owned file map\nCreate:\n- `new.py`\nModify only when exact accepted integration requires it:\n- `lib/en.py`, `lib/vi.py`, `lib/zh.py`\n\n## Fixed HTTP surface\n"
    assert owned_paths(packet) == (["lib/en.py", "lib/vi.py", "lib/zh.py", "new.py"], ["new.py"])


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "unknown_field",
        "status",
        "skip",
        "unknown",
        "document_hash",
        "omit_document",
        "seam_hash",
        "omit_seam",
        "expanded_scope",
        "omit_translation",
    ],
)
def test_baseline_recomputes_authority_and_rejects_inventory_changes(fault: str | None) -> None:
    import json

    from scripts.r2.verify_m9_prerequisites import GitPrerequisiteReader
    from scripts.r2.verify_m9_scope import BASELINE, baseline_problems

    root = Path(__file__).resolve().parents[4]
    baseline = json.loads((root / BASELINE).read_bytes())
    if fault == "unknown_field":
        baseline["unreviewed"] = True
    elif fault == "status":
        baseline["status"] = "M9_CANDIDATE"
    elif fault == "skip":
        baseline["required_skips"] = ["seam"]
    elif fault == "unknown":
        baseline["material_unknowns"] = ["authority"]
    elif fault == "document_hash":
        baseline["documents"][next(iter(baseline["documents"]))] = "0" * 64
    elif fault == "omit_document":
        baseline["documents"].pop(next(iter(baseline["documents"])))
    elif fault == "seam_hash":
        baseline["seams"][next(iter(baseline["seams"]))]["sha256"] = "0" * 64
    elif fault == "omit_seam":
        baseline["seams"].pop(next(iter(baseline["seams"])))
    elif fault == "expanded_scope":
        baseline["scope_allowlist"].append("server/auth.py")
    elif fault == "omit_translation":
        baseline["scope_allowlist"].remove("lib/i18n/vi/errors.py")
    errors = baseline_problems(root, baseline, GitPrerequisiteReader(root))
    if fault is None:
        assert errors == []
    else:
        assert errors


@pytest.mark.parametrize("fault", ["missing", "pin", "omit_path", "duplicate_donor"])
def test_donor_gate_refuses_unavailable_or_substituted_pinned_source(fault: str) -> None:
    import json

    from scripts.r2.verify_m9_scope import BASELINE, CONTRACT, donor_problems

    root = Path(__file__).resolve().parents[4]
    baseline = json.loads((root / BASELINE).read_bytes())
    contract = json.loads((root / CONTRACT).read_bytes())
    if fault == "pin":
        baseline["donors"][0]["commit"] = "0" * 40
    elif fault == "omit_path":
        baseline["donors"][0]["files"].pop(next(iter(baseline["donors"][0]["files"])))
    elif fault == "duplicate_donor":
        baseline["donors"].append(baseline["donors"][0])
    errors = donor_problems(baseline, contract, None)
    assert errors
    if fault == "pin":
        assert any("pin or selected paths" in e for e in errors)
    elif fault == "duplicate_donor":
        assert any("inventory" in e for e in errors)


def test_environment_gate_requires_explicit_target_and_grant_inputs(monkeypatch) -> None:
    from scripts.r2.verify_m9_scope import environment_problems

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ARCREEL_M9_ENVIRONMENT_EVIDENCE", raising=False)
    assert environment_problems() == ["attested disposable target and current custodian grant inputs are missing"]


@pytest.fixture
def scope_repo(tmp_path: Path) -> Path:
    import subprocess

    from scripts.r2.verify_m9_scope import BASE, BRANCH

    root = Path(__file__).resolve().parents[4]
    repo = tmp_path / "scope"
    subprocess.run(["git", "clone", "--shared", "--no-checkout", str(root), str(repo)], capture_output=True, check=True)
    from tests.integration.scripts.r2.test_verify_m9_prerequisites_git import _git

    _git(repo, "sparse-checkout", "set", "--no-cone", "/docs/", "/r2/", "/lib/", "/server/", "/scripts/", "/alembic/")
    _git(repo, "checkout", "--detach", BASE)
    _git(repo, "checkout", "-B", BRANCH)
    return repo


def test_actual_scope_verifier_routes_missing_baseline_to_required_evidence(scope_repo: Path) -> None:
    import json

    from scripts.r2.verify_m9_scope import CONTRACT

    errors = verify_m9_scope(scope_repo, json.loads((scope_repo / CONTRACT).read_bytes()))
    assert errors[0].startswith("M9_REQUIRED_EVIDENCE_MISSING:")
    assert not (scope_repo / "r2/contracts/opportunity.py").exists()


def test_actual_scope_verifier_routes_dirty_checkout_without_claiming_design_rejection(scope_repo: Path) -> None:
    import json

    from scripts.r2.verify_m9_scope import BASELINE, CONTRACT, SCHEMA
    from tests.integration.scripts.r2.test_verify_m9_prerequisites_git import _git

    root = Path(__file__).resolve().parents[4]
    for path in (BASELINE, SCHEMA):
        (scope_repo / path).write_bytes((root / path).read_bytes())
    _git(scope_repo, "add", BASELINE, SCHEMA)
    _git(scope_repo, "commit", "-qm", "baseline fixture")
    (scope_repo / "unrelated.txt").write_text("preserve me")
    before = _git(scope_repo, "status", "--porcelain")
    errors = verify_m9_scope(scope_repo, json.loads((scope_repo / CONTRACT).read_bytes()))
    assert not any(error.startswith("M9_DESIGN_NOT_ACCEPTED:") for error in errors)
    assert any("worktree is dirty" in error for error in errors)
    assert _git(scope_repo, "status", "--porcelain") == before
    assert (scope_repo / "unrelated.txt").read_text() == "preserve me"


def test_scope_schema_damage_fails_closed_without_a_traceback(scope_repo: Path) -> None:
    import json

    from scripts.r2.verify_m9_scope import BASELINE, CONTRACT, SCHEMA

    root = Path(__file__).resolve().parents[4]
    (scope_repo / BASELINE).write_bytes((root / BASELINE).read_bytes())
    (scope_repo / SCHEMA).write_text('{"type":"unknown-type"}')
    errors = verify_m9_scope(scope_repo, json.loads((scope_repo / CONTRACT).read_bytes()))
    assert any(error.startswith("M9_REQUIRED_EVIDENCE_MISSING:") for error in errors)


def test_missing_m8_is_reported_before_missing_baseline(scope_repo: Path) -> None:
    import json

    from scripts.r2.verify_m9_scope import CONTRACT, M8_PATH

    (scope_repo / M8_PATH).unlink()
    errors = verify_m9_scope(scope_repo, json.loads((scope_repo / CONTRACT).read_bytes()))
    assert errors[0].startswith("M9_M8_IMPLEMENTATION_NOT_ACCEPTED:")
    assert errors[-1].startswith("M9_REQUIRED_EVIDENCE_MISSING:")


@pytest.mark.parametrize("query", ["host=other-host", "port=5432", "database=other-database"])
def test_disposable_target_rejects_url_query_overrides_before_connecting(monkeypatch, query: str) -> None:
    import asyncio
    import json

    from scripts.r2.verify_m9_scope import _read_environment

    metadata = {
        "id": "fixture-container",
        "labels": {"arcreel.disposable": "true", "arcreel.task": "m9a"},
        "ports": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "32772"}]},
    }
    monkeypatch.setattr(
        "scripts.r2.verify_m9_scope.subprocess.check_output", lambda *args, **kwargs: json.dumps(metadata).encode()
    )
    proof = {"container_name": "fixture", "container_id": "fixture-container", "database": "m9a"}
    with pytest.raises(ValueError, match="database URL differs"):
        asyncio.run(_read_environment(proof, f"postgresql+asyncpg://m9test:test@127.0.0.1:32772/m9a?{query}"))


def test_owned_paths_maps_only_the_m9_architecture_test_into_the_required_unit_tier() -> None:
    from scripts.r2.verify_m9_scope import owned_paths

    packet = b"## Exact owned file map\nCreate:\n- `tests/architecture/test_m9_opportunity_boundaries.py`\n- `tests/architecture/unrelated.py`\nModify only when exact accepted integration requires it:\n- `server/app.py`\n\n## Fixed HTTP surface\n"
    owned, creates = owned_paths(packet)
    assert creates == ["tests/architecture/unrelated.py", "tests/unit/r2/opportunity/test_m9_opportunity_boundaries.py"]
    assert owned == ["server/app.py", *creates]
