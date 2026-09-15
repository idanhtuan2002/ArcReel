"""Executable architecture fitness for the M6 dual-profile adaptation boundary
(plan Task 6, extended by Task 7).

Structural sensor only: an import-graph AST scan, mirroring
``tests/unit/r2/test_m5c_architecture_boundaries.py``'s ``forbidden_pure_import_offenders``
pattern. Every M6 domain module — the append-only evidence service, the authority
service, and the pure authority kernel — carries no Canon writer, Production approval,
or provider/execution import, and none of them import ``lib.db``/``sqlalchemy``
directly: concrete persistence wiring is always injected from outside, through
``AdaptationUnitOfWorkFactory``. Only ``r2.adaptation.evidence`` additionally forbids
importing the authority modules at all (plan Task 6: "no method can mutate an
authority head"); ``authority.py`` legitimately imports its own ``authority_kernel``.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_ADAPTATION_DIR = _ROOT / "r2" / "adaptation"

_SHARED_FORBIDDEN_IMPORT_ROOTS = {"sqlalchemy", "server", "httpx", "fastapi", "asyncpg", "aiosqlite"}
_SHARED_FORBIDDEN_IMPORT_NEEDLES = (
    "lib.db",
    "alembic",
    "r2.narrative.canon_transaction",
    "r2.production.approval_service",
    "r2.production_intelligence.execution",
    "r2.production_intelligence.host_integration",
)
_EVIDENCE_ONLY_FORBIDDEN_NEEDLES = ("r2.adaptation.authority", "r2.adaptation.authority_kernel")


def _imports(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
            names += [f"{node.module}.{alias.name}" for alias in node.names]
    return names


def _module_source(name: str) -> dict[str, str]:
    path = _ADAPTATION_DIR / name
    return {path.relative_to(_ROOT).as_posix(): path.read_text(encoding="utf-8")}


def evidence_source() -> dict[str, str]:
    return _module_source("evidence.py")


def authority_source() -> dict[str, str]:
    return _module_source("authority.py")


def authority_kernel_source() -> dict[str, str]:
    return _module_source("authority_kernel.py")


def forbidden_domain_import_offenders(
    sources: Mapping[str, str], *, extra_needles: tuple[str, ...] = ()
) -> list[tuple[str, str]]:
    """``(module, imported name)`` for every authority / persistence / provider import
    an M6 domain module must never carry."""
    needles = _SHARED_FORBIDDEN_IMPORT_NEEDLES + extra_needles
    offenders: list[tuple[str, str]] = []
    for rel, text_ in sorted(sources.items()):
        for name in _imports(ast.parse(text_)):
            root = name.split(".")[0]
            if root in _SHARED_FORBIDDEN_IMPORT_ROOTS or any(needle in name for needle in needles):
                offenders.append((rel, name))
    return offenders


def test_adaptation_evidence_service_imports_no_authority_persistence_or_provider() -> None:
    assert forbidden_domain_import_offenders(evidence_source(), extra_needles=_EVIDENCE_ONLY_FORBIDDEN_NEEDLES) == []


def test_adaptation_authority_service_imports_no_persistence_canon_or_provider() -> None:
    assert forbidden_domain_import_offenders(authority_source()) == []


def test_adaptation_authority_kernel_imports_no_persistence_canon_or_provider() -> None:
    assert forbidden_domain_import_offenders(authority_kernel_source()) == []


def test_the_forbidden_import_sensor_catches_a_direct_canon_transaction_call() -> None:
    mutated = {
        "r2/adaptation/evidence.py": "from r2.narrative.canon_transaction import CanonTransactionService\n",
    }
    assert forbidden_domain_import_offenders(mutated) == [
        ("r2/adaptation/evidence.py", "r2.narrative.canon_transaction"),
        ("r2/adaptation/evidence.py", "r2.narrative.canon_transaction.CanonTransactionService"),
    ]


def test_the_forbidden_import_sensor_catches_a_direct_production_approval_call() -> None:
    mutated = {
        "r2/adaptation/evidence.py": "from r2.production.approval_service import ProductionApprovalService\n",
    }
    assert forbidden_domain_import_offenders(mutated) == [
        ("r2/adaptation/evidence.py", "r2.production.approval_service"),
        ("r2/adaptation/evidence.py", "r2.production.approval_service.ProductionApprovalService"),
    ]


def test_the_forbidden_import_sensor_catches_a_direct_sqlalchemy_import() -> None:
    mutated = {"r2/adaptation/evidence.py": "from sqlalchemy.exc import IntegrityError\n"}
    assert forbidden_domain_import_offenders(mutated) == [
        ("r2/adaptation/evidence.py", "sqlalchemy.exc"),
        ("r2/adaptation/evidence.py", "sqlalchemy.exc.IntegrityError"),
    ]


def test_the_evidence_only_sensor_catches_an_authority_kernel_import_that_authority_py_may_legitimately_carry() -> None:
    mutated = {"r2/adaptation/evidence.py": "from r2.adaptation.authority_kernel import fold_adaptation_head\n"}
    assert forbidden_domain_import_offenders(mutated, extra_needles=_EVIDENCE_ONLY_FORBIDDEN_NEEDLES) == [
        ("r2/adaptation/evidence.py", "r2.adaptation.authority_kernel"),
        ("r2/adaptation/evidence.py", "r2.adaptation.authority_kernel.fold_adaptation_head"),
    ]
    assert forbidden_domain_import_offenders(mutated) == []


def test_the_forbidden_import_sensor_catches_a_direct_lib_db_import_in_the_authority_service() -> None:
    mutated = {"r2/adaptation/authority.py": "from lib.db.repositories.adaptation import AdaptationRepository\n"}
    assert forbidden_domain_import_offenders(mutated) == [
        ("r2/adaptation/authority.py", "lib.db.repositories.adaptation"),
        ("r2/adaptation/authority.py", "lib.db.repositories.adaptation.AdaptationRepository"),
    ]
