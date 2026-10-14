"""Executable architecture fitness for the M8-A exploration boundary (plan Task A3.3, ADR-0097).

An AST scan:

- The M8 domain (contracts, ``r2/advanced_creative`` and ``r2/learning``) carries no persistence, server, HTTP
  or provider import, and no Canon, NarrativePlan, CreativePolicy, Claim or legacy approval
  writer.
- Only ``promotion.py`` invokes the authority adapter.
- The M8 repositories never commit.
- ``server/app.py`` registers the M8 router exactly once, behind authentication and the
  project migration gate.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_DOMAIN = [
    _ROOT / "r2" / "contracts" / "advanced_creative.py",
    *sorted((_ROOT / "r2" / "advanced_creative").glob("*.py")),
    *sorted((_ROOT / "r2" / "learning").glob("*.py")),
]
_FORBIDDEN_ROOTS = {"sqlalchemy", "server", "fastapi", "httpx", "asyncpg", "aiosqlite", "alembic"}
_FORBIDDEN_NEEDLES = (
    "lib.db",
    "lib.generation_queue",
    "lib.image_backends",
    "lib.video_backends",
    "lib.text_backends",
    "r2.narrative.canon_transaction",
    "r2.narrative_plan",
    "r2.production.approval_service",
    "r2.production_intelligence.execution",
)


def _imports(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _attribute_calls(path: Path, receiver: str, method: str) -> int:
    count = 0
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == method
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == receiver
        ):
            count += 1
    return count


def test_the_m8_domain_carries_no_persistence_server_provider_or_foreign_writer_import() -> None:
    offenders = {
        path.relative_to(_ROOT).as_posix(): name
        for path in _DOMAIN
        for name in _imports(path)
        if name.split(".")[0] in _FORBIDDEN_ROOTS or any(name.startswith(needle) for needle in _FORBIDDEN_NEEDLES)
    }

    assert offenders == {}


def test_only_the_promotion_module_invokes_the_authority_adapter() -> None:
    calls = {path.name: _attribute_calls(path, "_slots", "promote") for path in _DOMAIN}

    assert {name: count for name, count in calls.items() if count} == {"promotion.py": 1}


def test_the_m8_repositories_never_commit() -> None:
    for name in ("advanced_creative.py", "learning.py", "learning_recommendations.py", "formats.py"):
        source = (_ROOT / "lib" / "db" / "repositories" / name).read_text(encoding="utf-8")

        assert ".commit(" not in source, name


def test_the_m8_router_is_registered_once_behind_auth_and_the_migration_gate() -> None:
    tree = ast.parse((_ROOT / "server" / "app.py").read_text(encoding="utf-8"))
    registrations = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "include_router"
        and node.args
        and ast.unparse(node.args[0]) == "advanced_creative.router"
    ]

    assert len(registrations) == 1
    dependencies = next(keyword for keyword in registrations[0].keywords if keyword.arg == "dependencies")
    rendered = ast.unparse(dependencies.value)
    assert "get_current_user" in rendered
    assert "require_project_migration_ok" in rendered


_LEARNING_HOST = [
    _ROOT / "server" / "services" / "learning.py",
    _ROOT / "server" / "routers" / "learning.py",
    _ROOT / "lib" / "db" / "repositories" / "learning.py",
    _ROOT / "lib" / "db" / "repositories" / "learning_recommendations.py",
]
_AUTHORITY_WRITERS = (
    "r2.narrative",
    "r2.narrative_plan",
    "r2.narrative_lifecycle",
    "r2.production",
    "r2.production_binding",
    "r2.governance",
    "r2.adaptation",
    "r2.gates",
    "lib.db.repositories.production",
    "lib.db.repositories.canon",
    "lib.db.repositories.governance",
    "lib.generation_queue",
    "server.services.governance",
    "server.services.production",
    "server.services.gates",
)


def test_learning_has_no_authority_write_port() -> None:
    offenders = {
        path.relative_to(_ROOT).as_posix(): name
        for path in _LEARNING_HOST
        for name in _imports(path)
        if any(name == writer or name.startswith((writer + ".", writer + "_")) for writer in _AUTHORITY_WRITERS)
    }

    assert offenders == {}


def test_the_learning_router_is_registered_once_behind_auth_and_the_migration_gate() -> None:
    tree = ast.parse((_ROOT / "server" / "app.py").read_text(encoding="utf-8"))
    registrations = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "include_router"
        and node.args
        and ast.unparse(node.args[0]) == "learning.router"
    ]

    assert len(registrations) == 1
    dependencies = next(keyword for keyword in registrations[0].keywords if keyword.arg == "dependencies")
    rendered = ast.unparse(dependencies.value)
    assert "get_current_user" in rendered
    assert "require_project_migration_ok" in rendered


def test_the_format_router_is_registered_once_behind_auth_and_the_migration_gate() -> None:
    tree = ast.parse((_ROOT / "server" / "app.py").read_text(encoding="utf-8"))
    registrations = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "include_router"
        and node.args
        and ast.unparse(node.args[0]) == "formats.router"
    ]

    assert len(registrations) == 1
    dependencies = next(keyword for keyword in registrations[0].keywords if keyword.arg == "dependencies")
    rendered = ast.unparse(dependencies.value)
    assert "get_current_user" in rendered
    assert "require_project_migration_ok" in rendered
