"""Executable architecture fitness for the M5C-1A blast radius.

Structural sensors only: import graphs, AST shapes, and string-literal scans. Later M5C
checkpoints extend this module with the evidence / acceptance / compiler boundaries.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from r2.contracts.narrative_plan import SceneContract, SceneTemporalWindow
from r2.narrative_plan.hashing import compute_scene_semantic_hash, compute_scene_semantic_hash_v2
from tests.unit.r2.narrative_plan._helpers import V1_GOLDEN_SCENE, V1_GOLDEN_SCENE_HASH

_ROOT = Path(__file__).resolve().parents[3]
_PURE_LIFECYCLE_DIR = _ROOT / "r2" / "narrative_lifecycle"
_R2_RUNTIME_DIR = _ROOT / "r2"
_F9_MODULES = (
    "r2/narrative/relationship_facts.py",
    "r2/narrative/validation.py",
    "r2/narrative_plan/schema_upgrade.py",
    "r2/narrative_plan/validation.py",
)
_DONOR_NEEDLES = ("donor_parity", "novel-change-record", "novel-memory-parser", "hardRules")
_FORBIDDEN_PURE_IMPORT_ROOTS = {"sqlalchemy", "server", "httpx", "fastapi", "asyncpg", "aiosqlite"}
_FORBIDDEN_PURE_IMPORT_NEEDLES = (
    "lib.db",
    "alembic",
    "r2.narrative.canon_transaction",
    "r2.narrative.ports",
    "r2.narrative_plan.service",
    "r2.narrative_plan.ports",
    "r2.narrative_context",
    "r2.production",
    "agent_runtime",
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
            names += [f"{node.module}.{alias.name}" for alias in node.names]
    return names


def _py_files(base: Path) -> list[Path]:
    return sorted(base.rglob("*.py"))


def test_pure_lifecycle_ports_import_no_authority_persistence_or_runtime() -> None:
    for path in _py_files(_PURE_LIFECYCLE_DIR):
        for name in _imports(_tree(path)):
            root = name.split(".")[0]
            assert root not in _FORBIDDEN_PURE_IMPORT_ROOTS, (path.name, name)
            assert not any(needle in name for needle in _FORBIDDEN_PURE_IMPORT_NEEDLES), (path.name, name)


def test_no_r2_runtime_module_imports_the_donor_parity_harness() -> None:
    for path in _py_files(_R2_RUNTIME_DIR):
        text = path.read_text(encoding="utf-8")
        for name in _imports(ast.parse(text)):
            assert "donor_parity" not in name, (path.name, name)
            assert not name.startswith("tests"), (path.name, name)


def test_f9_modules_reference_no_donor_source() -> None:
    for rel in _F9_MODULES:
        text = (_ROOT / rel).read_text(encoding="utf-8")
        for needle in _DONOR_NEEDLES:
            assert needle not in text, (rel, needle)


def test_relationship_fact_predicate_string_is_produced_only_in_one_module() -> None:
    owner = "r2/narrative/relationship_facts.py"
    for path in _py_files(_R2_RUNTIME_DIR):
        rel = path.relative_to(_ROOT).as_posix()
        if rel == owner:
            continue
        assert '"r2rel:"' not in path.read_text(encoding="utf-8"), rel
        assert "'r2rel:'" not in path.read_text(encoding="utf-8"), rel


def test_cross_scene_thread_lifecycle_lives_only_in_the_plan_wide_pass() -> None:
    owner = "r2/narrative_plan/validation.py"
    for path in _py_files(_R2_RUNTIME_DIR):
        rel = path.relative_to(_ROOT).as_posix()
        if rel == owner:
            continue
        assert "SCENE_THREAD_LIFECYCLE_" not in path.read_text(encoding="utf-8"), rel


def test_relationship_predicate_helper_is_the_only_r2rel_source_and_scene_validate_has_no_lifecycle() -> None:
    scene_validation = (_ROOT / "r2/narrative/validation.py").read_text(encoding="utf-8")
    assert "validate_plan_thread_lifecycle" not in scene_validation
    compiler = (_ROOT / "r2/narrative_context/compiler.py").read_text(encoding="utf-8")
    assert "SCENE_THREAD_LIFECYCLE_" not in compiler


# --- v1 immutability sensors -------------------------------------------------


def test_v1_scene_contract_rejects_the_v2_omniscient_field() -> None:
    window = SceneTemporalWindow(
        effective_from=V1_GOLDEN_SCENE.temporal_window.effective_from,
        effective_until=V1_GOLDEN_SCENE.temporal_window.effective_until,
    )
    with pytest.raises(ValidationError):
        SceneContract.model_validate(
            {
                "scene_contract_id": "sc",
                "version": 1,
                "semantic_hash": "sh:x",
                "sequence_index": 0,
                "purpose": "p",
                "pov": None,
                "location_ref": None,
                "temporal_window": window.model_dump(mode="json"),
                "omniscient_authoring_allowed_by_scene": True,
            }
        )


def test_v1_scene_dump_carries_no_v2_only_fields() -> None:
    dumped = V1_GOLDEN_SCENE.model_dump(mode="json")
    assert "omniscient_authoring_allowed_by_scene" not in dumped
    assert dumped["semantic_hash_version"] == "r2-scene-contract-content-v1"


def test_recomputing_a_v1_golden_hash_with_v2_code_diverges() -> None:
    assert compute_scene_semantic_hash(V1_GOLDEN_SCENE) == V1_GOLDEN_SCENE_HASH
    assert compute_scene_semantic_hash_v2(V1_GOLDEN_SCENE) != V1_GOLDEN_SCENE_HASH
