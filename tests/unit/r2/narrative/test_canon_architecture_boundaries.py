"""Executable architecture fitness for the M5A Canon authority.

Structural sensors only: import graphs, AST call/def/annotation shapes, and the
frozen contract registry — never a filename or class-name substring on its own.
"""

from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
_NARRATIVE_DIR = _ROOT / "r2" / "narrative"
# Every authoritative Canon write-port method.
_AUTHORITY_WRITE_ATTRS = {"insert_branch", "insert_delta", "insert_version", "advance_head", "lock_branch"}
# ``insert_version`` / ``advance_head`` names are also used by the SEPARATE NarrativePlan
# authority repository. Those three plan files are allowlisted and additionally asserted
# to carry no Canon authority symbol, so a second Canon writer cannot hide among them.
_CANON_WRITE_CALLERS = {"r2/narrative/canon_transaction.py", "lib/db/repositories/canon_repo.py"}
_PLAN_AUTHORITY_FILES = {
    "r2/narrative_plan/service.py",
    "lib/db/repositories/narrative_plan.py",
    "lib/db/narrative_plan_uow.py",
}
_CANON_AUTHORITY_SYMBOLS = ("CanonWriteRepositoryPort", "CanonRepository", "CanonAuthorityUnitOfWork")
_AUTHORITY_ONLY_SYMBOLS = (
    "CanonWriteRepositoryPort",
    "CanonRepository",
    "SqlAlchemyCanonAuthorityUnitOfWork",
    "canon_authority_uow_factory",
    "CanonAuthorityUnitOfWork",
    "CanonAuthorityUnitOfWorkFactory",
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


def _imported_symbols(tree: ast.Module) -> set[str]:
    symbols: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.ImportFrom, ast.Import)):
            symbols.update(alias.name for alias in node.names)
    return symbols


def _called_attrs(tree: ast.Module) -> set[str]:
    return {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def _annotation_strings(tree: ast.Module) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.arg) and node.annotation is not None) or isinstance(node, ast.AnnAssign):
            out.add(ast.unparse(node.annotation))
    return out


def _narrative_files() -> list[Path]:
    return sorted(_NARRATIVE_DIR.rglob("*.py"))


def test_import_linter_contract_keeps_narrative_core_off_host_persistence() -> None:
    config = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = config["tool"]["importlinter"]["contracts"]
    narrative = next((item for item in contracts if item.get("source_modules") == ["r2.narrative"]), None)
    assert narrative is not None, "missing the r2.narrative forbidden-import contract"
    assert narrative["type"] == "forbidden"
    assert {"lib.db", "lib.db.models", "lib.db.repositories"} <= set(narrative["forbidden_modules"])
    assert "ignore_imports" not in narrative


def test_narrative_core_never_imports_sqlalchemy_or_host_db() -> None:
    for path in _narrative_files():
        for name in _imports(ast.parse(path.read_text(encoding="utf-8"))):
            assert not name.startswith(("sqlalchemy", "lib.db", "alembic")), f"{path.name} imports {name}"


def test_only_the_transaction_service_calls_canon_authority_writes() -> None:
    roots = ("r2", "server", "lib")
    allowed = _CANON_WRITE_CALLERS | _PLAN_AUTHORITY_FILES
    offenders: set[str] = set()
    for root in roots:
        for path in sorted((_ROOT / root).rglob("*.py")):
            rel = path.relative_to(_ROOT).as_posix()
            if rel in allowed:
                continue
            if _AUTHORITY_WRITE_ATTRS & _called_attrs(ast.parse(path.read_text(encoding="utf-8"))):
                offenders.add(rel)
    assert offenders == set()


def test_plan_authority_files_carry_no_canon_authority_symbol() -> None:
    for rel in _PLAN_AUTHORITY_FILES:
        text = (_ROOT / rel).read_text(encoding="utf-8")
        for symbol in _CANON_AUTHORITY_SYMBOLS:
            assert symbol not in text, (rel, symbol)


def test_repository_and_resolver_never_own_a_transaction() -> None:
    for rel_path in ("lib/db/repositories/canon_repo.py", "r2/narrative/canon_resolver.py"):
        tree = _tree(rel_path)
        called = _called_attrs(tree)
        assert "commit" not in called, rel_path
        assert "rollback" not in called, rel_path
        assert "async_sessionmaker" not in _imported_symbols(tree), rel_path
        assert "async_sessionmaker" not in {
            node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }, rel_path


def test_authority_write_symbols_stay_out_of_downstream_layers() -> None:
    downstream = ("server", "r2/production", "r2/production_intelligence", "r2/m3")
    for root in downstream:
        base = _ROOT / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            names = _imports(ast.parse(path.read_text(encoding="utf-8")))
            for symbol in _AUTHORITY_ONLY_SYMBOLS:
                assert not any(name.endswith(f".{symbol}") or name == symbol for name in names), (
                    path.relative_to(_ROOT).as_posix(),
                    symbol,
                )


def test_authority_uow_factory_is_referenced_only_where_expected() -> None:
    allowed = {
        "r2/narrative/ports.py",
        "r2/narrative/canon_transaction.py",
        "lib/db/canon_uow.py",
    }
    referencing: set[str] = set()
    for root in ("r2", "lib", "server"):
        for path in sorted((_ROOT / root).rglob("*.py")):
            if "CanonAuthorityUnitOfWorkFactory" in path.read_text(encoding="utf-8"):
                referencing.add(path.relative_to(_ROOT).as_posix())
    assert referencing <= allowed, referencing - allowed


def test_transaction_service_takes_the_authority_factory_and_resolution_takes_the_projection_factory() -> None:
    transaction_annotations = _annotation_strings(_tree("r2/narrative/canon_transaction.py"))
    assert "CanonAuthorityUnitOfWorkFactory" in transaction_annotations

    resolution_tree = _tree("r2/narrative/canon_resolution.py")
    resolution_annotations = _annotation_strings(resolution_tree)
    assert "CanonProjectionUnitOfWorkFactory" in resolution_annotations
    assert "CanonAuthorityUnitOfWorkFactory" not in _imports(resolution_tree)
    assert "CanonAuthorityUnitOfWorkFactory" not in resolution_annotations


def test_projection_unit_of_work_constructs_only_the_projection_repository() -> None:
    tree = _tree("lib/db/canon_uow.py")
    projection_cls = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "SqlAlchemyCanonProjectionUnitOfWork"
    )
    constructed = {
        node.func.id
        for node in ast.walk(projection_cls)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "CanonProjectionRepository" in constructed
    assert "CanonRepository" not in constructed


def test_projection_repository_class_exposes_no_authority_write_methods() -> None:
    tree = _tree("lib/db/repositories/canon_repo.py")
    projection_cls = next(
        node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "CanonProjectionRepository"
    )
    method_names = {
        node.name for node in projection_cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert method_names.isdisjoint({"insert_branch", "insert_delta", "insert_version", "advance_head", "lock_branch"})


def test_canon_modules_do_not_import_or_instantiate_production_approval() -> None:
    for path in _narrative_files():
        text = path.read_text(encoding="utf-8")
        for name in _imports(ast.parse(text)):
            assert "approval_service" not in name, path.name
            assert "ProductionApprovalService" not in name, path.name
        assert "ProductionApprovalService(" not in text, path.name


def test_contracts_narrative_module_is_provider_orm_and_endpoint_neutral() -> None:
    tree = _tree("r2/contracts/narrative.py")
    for name in _imports(tree):
        root = name.split(".")[0]
        assert root not in {"sqlalchemy", "lib", "server", "fastapi", "alembic", "httpx"}, name
    forbidden_fields = {"provider", "model", "endpoint", "payload", "api_key", "base_url"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            annotated = {
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            }
            assert annotated.isdisjoint(forbidden_fields), (node.name, annotated & forbidden_fields)


def test_frozen_contract_registry_still_names_the_transaction_service() -> None:
    registry = json.loads((_ROOT / "docs" / "r2" / "R2_03_CONTRACT_REGISTRY.json").read_text(encoding="utf-8"))
    canon_contracts = [item for item in registry["contracts"] if item.get("family") == "CANON"]
    assert canon_contracts, "no CANON-family contracts in the frozen registry"
    for item in canon_contracts:
        assert item["commit_authority"] == "CanonTransactionService", item["name"]
