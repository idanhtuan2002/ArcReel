"""Executable architecture fitness for the M6 dual-profile adaptation boundary
(plan Task 6, extended by later checkpoints).

Structural sensor only: an import-graph AST scan, mirroring
``tests/unit/r2/test_m5c_architecture_boundaries.py``'s ``forbidden_pure_import_offenders``
pattern. Task 6 proves ``r2.adaptation.evidence`` — the sole append-only proposal-evidence
service — carries no Canon writer, Production approval, provider/execution, or M6
adaptation-authority import. Later tasks (7+) extend this file with the authority kernel's
own sole-head-writer contract, mirroring M5C's Task 21 extension of its own boundary file.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_EVIDENCE_MODULE = _ROOT / "r2" / "adaptation" / "evidence.py"

_FORBIDDEN_EVIDENCE_IMPORT_ROOTS = {"sqlalchemy", "server", "httpx", "fastapi", "asyncpg", "aiosqlite"}
_FORBIDDEN_EVIDENCE_IMPORT_NEEDLES = (
    "lib.db",
    "alembic",
    "r2.narrative.canon_transaction",
    "r2.production.approval_service",
    "r2.production_intelligence.execution",
    "r2.production_intelligence.host_integration",
    "r2.adaptation.authority",
    "r2.adaptation.authority_kernel",
)


def _imports(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
            names += [f"{node.module}.{alias.name}" for alias in node.names]
    return names


def evidence_source() -> dict[str, str]:
    return {_EVIDENCE_MODULE.relative_to(_ROOT).as_posix(): _EVIDENCE_MODULE.read_text(encoding="utf-8")}


def forbidden_evidence_import_offenders(sources: Mapping[str, str]) -> list[tuple[str, str]]:
    """``(module, imported name)`` for every authority / persistence / provider import
    the M6 evidence service must never carry."""
    offenders: list[tuple[str, str]] = []
    for rel, text_ in sorted(sources.items()):
        for name in _imports(ast.parse(text_)):
            root = name.split(".")[0]
            if root in _FORBIDDEN_EVIDENCE_IMPORT_ROOTS or any(
                needle in name for needle in _FORBIDDEN_EVIDENCE_IMPORT_NEEDLES
            ):
                offenders.append((rel, name))
    return offenders


def test_adaptation_evidence_service_imports_no_authority_persistence_or_provider() -> None:
    assert forbidden_evidence_import_offenders(evidence_source()) == []


def test_the_forbidden_import_sensor_catches_a_direct_canon_transaction_call() -> None:
    mutated = {
        "r2/adaptation/evidence.py": "from r2.narrative.canon_transaction import CanonTransactionService\n",
    }
    assert forbidden_evidence_import_offenders(mutated) == [
        ("r2/adaptation/evidence.py", "r2.narrative.canon_transaction"),
        ("r2/adaptation/evidence.py", "r2.narrative.canon_transaction.CanonTransactionService"),
    ]


def test_the_forbidden_import_sensor_catches_a_direct_production_approval_call() -> None:
    mutated = {
        "r2/adaptation/evidence.py": "from r2.production.approval_service import ProductionApprovalService\n",
    }
    assert forbidden_evidence_import_offenders(mutated) == [
        ("r2/adaptation/evidence.py", "r2.production.approval_service"),
        ("r2/adaptation/evidence.py", "r2.production.approval_service.ProductionApprovalService"),
    ]


def test_the_forbidden_import_sensor_catches_a_direct_sqlalchemy_import() -> None:
    mutated = {"r2/adaptation/evidence.py": "from sqlalchemy.exc import IntegrityError\n"}
    assert forbidden_evidence_import_offenders(mutated) == [
        ("r2/adaptation/evidence.py", "sqlalchemy.exc"),
        ("r2/adaptation/evidence.py", "sqlalchemy.exc.IntegrityError"),
    ]


def test_the_forbidden_import_sensor_catches_a_not_yet_existing_authority_kernel_import() -> None:
    mutated = {"r2/adaptation/evidence.py": "from r2.adaptation.authority_kernel import fold_adaptation_head\n"}
    assert forbidden_evidence_import_offenders(mutated) == [
        ("r2/adaptation/evidence.py", "r2.adaptation.authority_kernel"),
        ("r2/adaptation/evidence.py", "r2.adaptation.authority_kernel.fold_adaptation_head"),
    ]
