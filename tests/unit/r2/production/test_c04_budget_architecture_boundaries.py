"""Executable architecture rules for the C04 budget authorization exception."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]

BUDGET_MODULES = (
    "lib/budget_reservation.py",
    "lib/db/models/budget_reservation.py",
    "lib/db/repositories/budget_reservation_repo.py",
    "server/services/budget_reservation_service.py",
    "server/services/budget_reservation_events.py",
    "server/services/paid_submission_guard.py",
)

BUDGET_PORT = "r2/production/budget_port.py"
EVENT_PROJECTION = "server/services/budget_reservation_events.py"

CANON_NARRATIVE_PREFIXES = (
    "r2.canon",
    "r2.narrative",
    "r2.factual",
    "r2.director",
    "lib.canon",
    "lib.narrative",
)

ARTIFACT_AUTHORITY_MODULES = {
    "lib.artifact_manifest",
    "lib.artifact_currency",
    "lib.artifact_activation",
    "lib.version_manager",
    "r2.production.artifact_bridge",
    "r2.production.approval_service",
    "r2.production.artifact_metadata",
}


def _imports(rel_path: str) -> set[str]:
    tree = ast.parse((REPO / rel_path).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _prompt_compiler_files() -> list[str]:
    roots = (REPO / "r2", REPO / "server")
    return [
        str(path.relative_to(REPO))
        for root in roots
        if root.exists()
        for path in root.rglob("*.py")
        if "prompt_compiler" in path.name.lower()
    ]


def test_budget_port_does_not_import_host_db_or_server() -> None:
    imports = _imports(BUDGET_PORT)
    forbidden = sorted(name for name in imports if name == "server" or name.startswith(("lib.db", "server.")))
    assert forbidden == []


def _code_without_docstrings(rel_path: str) -> str:
    tree = ast.parse((REPO / rel_path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            node.value.value = ""
    return ast.unparse(tree)


def test_budget_port_writes_no_usage_or_cost_truth() -> None:
    code = _code_without_docstrings(BUDGET_PORT)
    for marker in (
        "UsageRepository",
        "ApiCall",
        "cost_amount",
        "AsyncSession",
        "sessionmaker",
        "session_factory",
        ".execute(",
        ".commit(",
        ".add(",
    ):
        assert marker not in code


def test_budget_modules_do_not_import_artifact_authority() -> None:
    offenders: dict[str, set[str]] = {}
    for module in BUDGET_MODULES:
        bad = _imports(module) & ARTIFACT_AUTHORITY_MODULES
        if bad:
            offenders[module] = bad
    assert offenders == {}


def test_budget_modules_do_not_import_canon_or_narrative() -> None:
    offenders: dict[str, list[str]] = {}
    for module in (*BUDGET_MODULES, BUDGET_PORT):
        bad = sorted(name for name in _imports(module) if name.startswith(CANON_NARRATIVE_PREFIXES))
        if bad:
            offenders[module] = bad
    assert offenders == {}


def test_event_projection_cannot_reach_persistence_authority() -> None:
    imports = _imports(EVENT_PROJECTION)
    assert not any(name.endswith(("_repo", "repositories")) for name in imports)
    assert "lib.db.repositories.budget_reservation_repo" not in imports
    assert "lib.db.repositories.usage_repo" not in imports
    code = _code_without_docstrings(EVENT_PROJECTION)
    for marker in ("Repository(", "AsyncSession", ".commit(", "INSERT", "UPDATE "):
        assert marker not in code


def test_prompt_compiler_never_imports_budget_repository_or_service() -> None:
    for rel_path in _prompt_compiler_files():
        imports = _imports(rel_path)
        assert "lib.db.repositories.budget_reservation_repo" not in imports
        assert "server.services.budget_reservation_service" not in imports


def test_import_linter_contract_pins_the_budget_port_boundary() -> None:
    config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = config["tool"]["importlinter"]["contracts"]
    match = [c for c in contracts if c.get("source_modules") == ["r2.production.budget_port"]]
    assert len(match) == 1
    contract = match[0]
    assert contract["type"] == "forbidden"
    assert {"lib.db.models", "lib.db.repositories"} <= set(contract["forbidden_modules"])
    assert "ignore_imports" not in contract
