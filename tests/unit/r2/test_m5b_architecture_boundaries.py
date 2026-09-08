"""Executable architecture fitness for the M5B authorities (schema-v2, NarrativePlan).

Structural sensors only: import graphs and AST call/annotation shapes. Task 11 extends
this module with the NarrativeContextCompiler leakage rules.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_PURE_NARRATIVE_DIRS = (_ROOT / "r2" / "narrative", _ROOT / "r2" / "narrative_plan")
_CONTEXT_DIR = _ROOT / "r2" / "narrative_context"
_CONTEXT_FORBIDDEN_IMPORT_ROOTS = {"sqlalchemy", "server", "httpx", "fastapi"}
_CONTEXT_FORBIDDEN_IMPORT_NEEDLES = (
    "lib.db",
    "alembic",
    "canon_transaction",
    "r2.narrative.ports",
    "r2.narrative_plan.service",
    "r2.narrative_plan.ports",
    "WritePort",
    "UnitOfWork",
    "uow_factory",
)
_MUTATION_ATTRS = {"insert", "update", "delete", "flush", "commit", "rollback", "add", "execute"}
# Plan-unique write attrs (``insert_version`` / ``advance_head`` names are shared with the
# Canon repository, so the sensor keys on the two that are unambiguously plan-scoped).
_PLAN_WRITE_ATTRS = {"insert_plan", "lock_plan"}
_CANON_WRITE_IMPORT_NEEDLES = (
    "canon_transaction",
    "r2.narrative.ports",
    "lib.db.canon_uow",
    "CanonWriteRepositoryPort",
    "CanonAuthorityUnitOfWork",
)


def _tree(rel_path: str) -> ast.Module:
    return ast.parse((_ROOT / rel_path).read_text(encoding="utf-8"))


def _imports(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
            names += [f"{node.module}.{alias.name}" for alias in node.names]
    return names


def _called_attrs(tree: ast.Module) -> set[str]:
    return {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def _py_files(base: Path) -> list[Path]:
    return sorted(base.rglob("*.py"))


def test_pure_narrative_and_plan_modules_never_import_host_persistence_or_runtime() -> None:
    for base in _PURE_NARRATIVE_DIRS:
        for path in _py_files(base):
            for name in _imports(ast.parse(path.read_text(encoding="utf-8"))):
                root = name.split(".")[0]
                assert not name.startswith(("sqlalchemy", "lib.db", "alembic")), (path.name, name)
                assert root not in {"server", "httpx", "fastapi"}, (path.name, name)


def test_narrative_plan_contracts_are_provider_and_orm_neutral() -> None:
    tree = _tree("r2/contracts/narrative_plan.py")
    for name in _imports(tree):
        root = name.split(".")[0]
        assert root not in {"sqlalchemy", "lib", "server", "fastapi", "alembic", "httpx"}, name
    forbidden_fields = {"provider", "model", "endpoint", "api_key", "base_url", "runtime_task_id"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            annotated = {
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            }
            assert annotated.isdisjoint(forbidden_fields), (node.name, annotated & forbidden_fields)


def test_narrative_plan_service_cannot_reach_canon_authoritative_writes() -> None:
    names = _imports(_tree("r2/narrative_plan/service.py"))
    for needle in _CANON_WRITE_IMPORT_NEEDLES:
        assert all(needle not in name for name in names), needle


def test_only_the_plan_service_calls_plan_authoritative_writes() -> None:
    allowed = {
        "r2/narrative_plan/service.py",
        "lib/db/repositories/narrative_plan.py",
        "lib/db/narrative_plan_uow.py",
    }
    offenders: set[str] = set()
    for root in ("r2", "server", "lib"):
        for path in _py_files(_ROOT / root):
            rel = path.relative_to(_ROOT).as_posix()
            if rel in allowed:
                continue
            if _PLAN_WRITE_ATTRS & _called_attrs(ast.parse(path.read_text(encoding="utf-8"))):
                offenders.add(rel)
    assert offenders == set()


def test_only_the_plan_service_references_the_plan_write_port() -> None:
    allowed = {
        "r2/narrative_plan/ports.py",
        "r2/narrative_plan/service.py",
        "r2/narrative_plan/__init__.py",
        "lib/db/narrative_plan_uow.py",
        "lib/db/repositories/narrative_plan.py",
    }
    referencing: set[str] = set()
    for root in ("r2", "lib", "server"):
        for path in _py_files(_ROOT / root):
            if "NarrativePlanWritePort" in path.read_text(encoding="utf-8"):
                referencing.add(path.relative_to(_ROOT).as_posix())
    assert referencing <= allowed, referencing - allowed


def test_narrative_context_never_imports_writes_persistence_or_runtime() -> None:
    for path in _py_files(_CONTEXT_DIR):
        names = _imports(ast.parse(path.read_text(encoding="utf-8")))
        for name in names:
            root = name.split(".")[0]
            assert root not in _CONTEXT_FORBIDDEN_IMPORT_ROOTS, (path.name, name)
            for needle in _CONTEXT_FORBIDDEN_IMPORT_NEEDLES:
                assert needle not in name, (path.name, needle)


def test_narrative_context_has_no_session_or_mutation_call_shapes() -> None:
    for path in _py_files(_CONTEXT_DIR):
        text = path.read_text(encoding="utf-8")
        assert "AsyncSession" not in text, path.name
        called = _called_attrs(ast.parse(text))
        assert called.isdisjoint({"commit", "rollback", "flush"}), (path.name, called & _MUTATION_ATTRS)


def test_narrative_context_does_not_inspect_prose_with_regexes_or_classifiers() -> None:
    for path in _py_files(_CONTEXT_DIR):
        names = _imports(ast.parse(path.read_text(encoding="utf-8")))
        for name in names:
            assert name.split(".")[0] not in {"re", "regex"}, (path.name, name)
            assert "keyword" not in name, (path.name, name)
            assert "classifier" not in name.lower(), (path.name, name)


def test_compiler_exposes_only_the_compile_entry_point() -> None:
    tree = _tree("r2/narrative_context/compiler.py")
    compiler_cls = next(
        node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "NarrativeContextCompiler"
    )
    public = {
        node.name
        for node in compiler_cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
    }
    assert public == {"compile"}


def test_import_linter_pins_the_m5b_authority_boundaries() -> None:
    config = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = config["tool"]["importlinter"]["contracts"]
    plan_pure = next((item for item in contracts if item.get("source_modules") == ["r2.narrative_plan"]), None)
    assert plan_pure is not None
    assert plan_pure["type"] == "forbidden"
    assert {"lib.db", "lib.db.models", "lib.db.repositories"} <= set(plan_pure["forbidden_modules"])

    service = next((item for item in contracts if item.get("source_modules") == ["r2.narrative_plan.service"]), None)
    assert service is not None
    assert service["type"] == "forbidden"
    assert "r2.narrative.canon_transaction" in service["forbidden_modules"]
