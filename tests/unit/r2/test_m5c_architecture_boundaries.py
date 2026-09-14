"""Executable architecture fitness for the M5C-1A blast radius, extended in Task 21
(M5C-2 checkpoint freeze) with the acceptance-authority surface and in Task 31 with the
three §16.8 mutation rows whose required result is an architecture / import fitness
failure.

Structural sensors only: import graphs, AST shapes, and string-literal scans. The one
Task 21 sensor that needs a real PostgreSQL connection (the §7.2 isolation precondition)
lives in ``tests/integration/r2/test_m5c_architecture_boundaries_db.py`` — unit-tier
tests may not touch a real database in this repo.

The three structural sensors the §16.8 matrix reuses are exposed as plain functions over
a ``{repository-relative path: source text}`` mapping: the tests below run them over the
real tree, and ``tests/integration/r2/test_m5c_acceptance.py`` runs them over the real
tree plus one mutated source, so each sensor is proven to fire as well as to pass.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import ValidationError

from r2.contracts.narrative_plan import SceneContract, SceneTemporalWindow
from r2.narrative_lifecycle.acceptance import NarrativeAcceptanceService
from r2.narrative_plan.hashing import compute_scene_semantic_hash, compute_scene_semantic_hash_v2
from tests.unit.r2.narrative_plan._helpers import V1_GOLDEN_SCENE, V1_GOLDEN_SCENE_HASH

_ROOT = Path(__file__).resolve().parents[3]
_PURE_LIFECYCLE_DIR = _ROOT / "r2" / "narrative_lifecycle"
_R2_RUNTIME_DIR = _ROOT / "r2"
_ACCEPTANCE_DECISION_METHODS = ("decide_revision", "review_change_set", "resolve_change_set_conflict")
_F9_MODULES = (
    "r2/narrative/relationship_facts.py",
    "r2/narrative/validation.py",
    "r2/narrative_plan/schema_upgrade.py",
    "r2/narrative_plan/validation.py",
)
_DONOR_NEEDLES = ("donor_parity", "novel-change-record", "novel-memory-parser", "hardRules")
M5A_COMMIT_PATH_MODULES = ("server/services/narrative_canon_handoff.py", "r2/narrative/canon_transaction.py")
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


def _sources(base: Path) -> dict[str, str]:
    return {path.relative_to(_ROOT).as_posix(): path.read_text(encoding="utf-8") for path in _py_files(base)}


# --- reusable structural sensors (also driven by the §16.8 mutation matrix) ------


def pure_lifecycle_sources() -> dict[str, str]:
    """Every module of the pure ``r2/narrative_lifecycle`` package, by repo-relative path."""
    return _sources(_PURE_LIFECYCLE_DIR)


def r2_runtime_sources() -> dict[str, str]:
    """Every module under ``r2/``, by repo-relative path."""
    return _sources(_R2_RUNTIME_DIR)


def forbidden_pure_import_offenders(sources: Mapping[str, str]) -> list[tuple[str, str]]:
    """``(module, imported name)`` for every authority / persistence / runtime import a
    pure lifecycle module must never carry — a direct Canon repository, unit of work,
    session, ORM, transaction service, or server import included."""
    offenders: list[tuple[str, str]] = []
    for rel, text_ in sorted(sources.items()):
        for name in _imports(ast.parse(text_)):
            root = name.split(".")[0]
            if root in _FORBIDDEN_PURE_IMPORT_ROOTS or any(needle in name for needle in _FORBIDDEN_PURE_IMPORT_NEEDLES):
                offenders.append((rel, name))
    return offenders


def relationship_predicate_literal_offenders(sources: Mapping[str, str]) -> list[str]:
    """Modules other than the shared versioned helper that build an ``r2rel:`` predicate
    string of their own."""
    owner = "r2/narrative/relationship_facts.py"
    return sorted(
        rel for rel, text_ in sources.items() if rel != owner and ('"r2rel:"' in text_ or "'r2rel:'" in text_)
    )


_CURRENTNESS_APIS = (
    "verify_exact_current_selection",
    "get_current_revision_selection",
    "get_current_change_set_selection",
    "get_current_conflict_resolution",
    "admit_canon_handoff",
)


def narrative_currentness_dependency_offenders(sources: Mapping[str, str]) -> list[tuple[str, str]]:
    """``(module, dependency)`` for every module on the M5A commit path that imports the
    Narrative acceptance surface or names one of its currentness / admission APIs.

    Structural, not textual: a module docstring may *describe* the boundary (and the
    handoff facade's does), but an import or an attribute access would make M5A depend on
    Narrative currentness, which spec §11.4 forbids.
    """
    offenders: list[tuple[str, str]] = []
    for rel, text_ in sorted(sources.items()):
        tree = ast.parse(text_)
        offenders += [(rel, name) for name in _imports(tree) if name.startswith("r2.narrative_lifecycle.acceptance")]
        offenders += [
            (rel, node.attr)
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in _CURRENTNESS_APIS
        ]
    return offenders


def acceptance_import_offenders(sources: Mapping[str, str]) -> list[tuple[str, str]]:
    """``(module, imported name)`` for every lifecycle module that reaches into the
    decision-authority surface — the extractor / parser / compiler side must not be able
    to invoke ``review_change_set`` at all."""
    allowed = {"r2/narrative_lifecycle/acceptance.py", "r2/narrative_lifecycle/__init__.py"}
    offenders: list[tuple[str, str]] = []
    for rel, text_ in sorted(sources.items()):
        if rel in allowed:
            continue
        offenders += [
            (rel, name) for name in _imports(ast.parse(text_)) if name.startswith("r2.narrative_lifecycle.acceptance")
        ]
    return offenders


def test_pure_lifecycle_ports_import_no_authority_persistence_or_runtime() -> None:
    assert forbidden_pure_import_offenders(pure_lifecycle_sources()) == []


def test_the_pure_import_sensor_catches_a_direct_canon_repository_call_from_m5c() -> None:
    mutated = {
        **pure_lifecycle_sources(),
        "r2/narrative_lifecycle/compiler.py": "from lib.db.repositories.canon import CanonRepository\n",
    }
    assert forbidden_pure_import_offenders(mutated) == [
        ("r2/narrative_lifecycle/compiler.py", "lib.db.repositories.canon"),
        ("r2/narrative_lifecycle/compiler.py", "lib.db.repositories.canon.CanonRepository"),
    ]


def test_the_acceptance_import_sensor_catches_an_extractor_reaching_for_review_change_set() -> None:
    mutated = {
        **pure_lifecycle_sources(),
        "r2/narrative_lifecycle/changeset_parser.py": (
            "from r2.narrative_lifecycle.acceptance import NarrativeAcceptanceService\n"
        ),
    }
    assert sorted({rel for rel, _ in acceptance_import_offenders(mutated)}) == [
        "r2/narrative_lifecycle/changeset_parser.py"
    ]


def test_the_m5a_commit_path_never_depends_on_narrative_currentness() -> None:
    m5a_path = {rel: (_ROOT / rel).read_text(encoding="utf-8") for rel in M5A_COMMIT_PATH_MODULES}
    assert narrative_currentness_dependency_offenders(m5a_path) == []


def test_the_currentness_dependency_sensor_catches_an_implicit_narrative_check() -> None:
    mutated = {
        "server/services/narrative_canon_handoff.py": (
            "async def commit(self, admission_id):\n"
            "    if not await self._acceptance.verify_exact_current_selection(admission_id):\n"
            "        return None\n"
        )
    }
    assert narrative_currentness_dependency_offenders(mutated) == [
        ("server/services/narrative_canon_handoff.py", "verify_exact_current_selection")
    ]


def test_the_r2rel_literal_sensor_catches_a_predicate_built_outside_the_shared_helper() -> None:
    mutated = {**r2_runtime_sources(), "r2/narrative_lifecycle/changeset_parser.py": 'PREDICATE = "r2rel:" + key\n'}
    assert relationship_predicate_literal_offenders(mutated) == ["r2/narrative_lifecycle/changeset_parser.py"]


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
    assert relationship_predicate_literal_offenders(r2_runtime_sources()) == []


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


# --- M5C-2 (Task 21) acceptance-authority fitness sensors -------------------


def test_only_acceptance_module_may_import_acceptance_within_narrative_lifecycle() -> None:
    assert acceptance_import_offenders(pure_lifecycle_sources()) == []


def test_public_decision_methods_take_only_command_and_authenticated_principal() -> None:
    for name in _ACCEPTANCE_DECISION_METHODS:
        method = getattr(NarrativeAcceptanceService, name)
        params = [p for p in inspect.signature(method).parameters if p != "self"]
        assert params == ["command", "authenticated_principal"], (name, params)
        assert "authorization" not in inspect.signature(method).parameters


def test_acceptance_service_without_an_authority_port_raises_instead_of_defaulting_open() -> None:
    with pytest.raises(ValueError, match="NarrativeShowrunnerAuthorityPort"):
        NarrativeAcceptanceService(lambda: (_ for _ in ()).throw(AssertionError("uow must not be built")), None)


def test_db_wiring_never_overrides_the_isolation_level_default() -> None:
    for rel in ("lib/db/engine.py", "lib/db/narrative_lifecycle_uow.py"):
        text_ = (_ROOT / rel).read_text(encoding="utf-8")
        assert "isolation_level" not in text_, rel
