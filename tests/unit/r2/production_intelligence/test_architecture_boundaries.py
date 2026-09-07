"""D12 — executable architecture fitness for the M4 production-intelligence layer.

These sensors are structural: they read import graphs, AST call shapes, nested
model types and value-level validators — never a filename or a class-name
substring on its own.
"""

from __future__ import annotations

import ast
import tomllib
import typing
from collections.abc import Iterable
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from r2.contracts import (
    ExecutionDecision,
    IdentityConstraint,
    IdentityStrength,
    MethodDecision,
    PromptPlan,
    ProviderRequest,
    ResolvedVisualIdentity,
    SceneSpec,
    ShotSpec,
    VisualIdentityProfile,
)

_ROOT = Path(__file__).resolve().parents[4]
_PI_DIR = _ROOT / "r2" / "production_intelligence"
_FORBIDDEN_STABLE_FIELDS = {
    "provider",
    "model",
    "endpoint",
    "payload",
    "provider_job_id",
    "submitted_base_url",
    "api_key",
    "backend_id",
    "vendor_options",
}
# Authority-mutating verbs. A telemetry/projection module must not *call* any of
# these (name on the call target, not on a method of its own class).
_AUTHORITY_WRITE_ATTRS = {
    "promote",
    "approve",
    "commit",
    "mutate",
    "set_master",
    "update_manifest",
    "persist",
    "save",
    "reserve",
    "claim",
    "release",
}
# Collection-accumulation calls that betray a hand-rolled queue/ledger.
_ACCUMULATE_CALLS = {"append", "appendleft", "extend", "add", "insert", "push", "enqueue"}
# cost_records is the C04-sanctioned per-attempt attributable list, not a ledger.
_QUEUE_ROLE_ALLOWLIST = {"M4HostIntegration"}


def _py_files() -> list[Path]:
    return sorted(_PI_DIR.rglob("*.py"))


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _iter_annotation_types(annotation: object) -> Iterable[object]:
    if annotation is None:
        return
    yield annotation
    for arg in typing.get_args(annotation):
        yield from _iter_annotation_types(arg)


def _nested_models(root: type[BaseModel], seen: set[type[BaseModel]] | None = None) -> set[type[BaseModel]]:
    seen = seen if seen is not None else set()
    if root in seen:
        return seen
    seen.add(root)
    for field in root.model_fields.values():
        for candidate in _iter_annotation_types(field.annotation):
            if not (isinstance(candidate, type) and issubclass(candidate, BaseModel)):
                continue
            # Provenance is the shared lineage envelope: it deliberately records
            # tool_or_adapter / model / model_version for audit and is not part of
            # the provider-neutral semantic payload.
            if candidate.__module__.endswith("contracts.provenance"):
                continue
            _nested_models(candidate, seen)
    return seen


def _self_attr_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        return node.attr
    return None


def test_r2_stays_in_every_static_analysis_root() -> None:
    cfg = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "r2" in cfg["tool"]["importlinter"]["root_packages"]
    assert "r2" in cfg["tool"]["basedpyright"]["include"]
    assert "r2" in cfg["tool"]["deptry"]["known_first_party"]


def test_stable_semantic_contracts_carry_no_provider_fields_recursively() -> None:
    for root in (
        SceneSpec,
        ShotSpec,
        MethodDecision,
        PromptPlan,
        VisualIdentityProfile,
        ResolvedVisualIdentity,
    ):
        for model in _nested_models(root):
            assert set(model.model_fields).isdisjoint(_FORBIDDEN_STABLE_FIELDS), f"{root.__name__} -> {model.__name__}"


def test_execution_side_contracts_do_carry_provider_identity() -> None:
    assert {"provider_id", "model_or_tool_id", "adapter_id"} <= set(ExecutionDecision.model_fields)
    assert {"provider", "model", "endpoint"} <= set(ProviderRequest.model_fields)


def test_provider_neutrality_is_enforced_on_semantic_values_not_only_field_names() -> None:
    with pytest.raises(ValidationError):
        IdentityConstraint(
            semantic_key="wardrobe",
            strength=IdentityStrength.LOCKED,
            semantic_value="--cref https://ref.example --cw 100",
        )
    with pytest.raises(ValidationError):
        PromptPlan(
            id="PP:SH01",
            schema_version="1",
            version=1,
            target_ref="SH01",
            semantic_instruction="establish the courtyard",
            compiler_version="m4-prompt-planner-v1",
            visual_identity_constraints=["style=<lora:add_detail:0.8>"],
        )


def test_production_intelligence_never_imports_lib_db() -> None:
    for path in _py_files():
        for name in _imports(path):
            assert not name.startswith("lib.db"), f"{path.name} imports {name}"


def test_only_host_integration_touches_the_server_layer_and_only_the_c04_guard() -> None:
    for path in _py_files():
        server_imports = [n for n in _imports(path) if n == "server" or n.startswith("server.")]
        if path.name == "host_integration.py":
            assert server_imports == ["server.services.paid_submission_guard"]
        else:
            assert server_imports == [], f"{path.name} imports {server_imports}"


def test_method_router_does_not_depend_on_capability_or_execution_layers() -> None:
    names = _imports(_PI_DIR / "method_router.py")
    for forbidden in (
        "r2.production_intelligence.capability_registry",
        "r2.production_intelligence.admission",
        "r2.production_intelligence.execution",
        "r2.production_intelligence.host_integration",
    ):
        assert forbidden not in names


def test_prompt_compiler_module_does_not_import_the_method_router_or_admission() -> None:
    names = _imports(_PI_DIR / "prompting.py")
    assert "r2.production_intelligence.method_router" not in names
    assert "r2.production_intelligence.admission" not in names


def test_telemetry_imports_no_authority_layer() -> None:
    names = _imports(_PI_DIR / "telemetry.py")
    assert not any(
        n.startswith(
            ("lib.artifact_manifest", "lib.db", "r2.production.approval_service", "r2.production.artifact_bridge")
        )
        for n in names
    )


def test_telemetry_module_makes_no_authority_write_call() -> None:
    tree = ast.parse((_PI_DIR / "telemetry.py").read_text(encoding="utf-8"))
    called_attrs = [
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    offenders = sorted({attr for attr in called_attrs if attr in _AUTHORITY_WRITE_ATTRS})
    assert offenders == [], offenders


def test_telemetry_projector_methods_are_projection_only() -> None:
    tree = ast.parse((_PI_DIR / "telemetry.py").read_text(encoding="utf-8"))
    projectors = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "ProductionTelemetryProjector"]
    assert projectors, "ProductionTelemetryProjector not found"
    for cls in projectors:
        for fn in cls.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name == "__init__":
                continue
            assert fn.returns is not None, f"{fn.name} has no return annotation"
            assert ast.unparse(fn.returns) != "None", f"{fn.name} returns None (side effect, not a projection)"


def test_m4_class_names_do_not_shadow_an_authority_subsystem() -> None:
    banned = ("queue", "ledger", "masterstore", "currencyengine", "artifactregistry")
    for path in _py_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef):
                lowered = node.name.lower()
                assert not any(term in lowered for term in banned), f"{path.name}:{node.name}"


def test_no_hand_rolled_queue_or_ledger_by_structural_role() -> None:
    """A class that keeps a collection instance attribute and accumulates into it
    outside ``__init__`` is a queue/ledger regardless of what it is named."""
    offenders: list[str] = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            if cls.name in _QUEUE_ROLE_ALLOWLIST:
                continue
            collection_attrs: set[str] = set()
            for node in ast.walk(cls):
                if isinstance(node, ast.AnnAssign):
                    name = _self_attr_name(node.target)
                    if name and isinstance(node.annotation, ast.Subscript):
                        base = node.annotation.value
                        if isinstance(base, ast.Name) and base.id in {"list", "dict", "set", "deque"}:
                            collection_attrs.add(name)
                elif isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        name = _self_attr_name(tgt)
                        if not name:
                            continue
                        val = node.value
                        if isinstance(val, (ast.List, ast.Dict, ast.Set)) or (
                            isinstance(val, ast.Call)
                            and isinstance(val.func, ast.Name)
                            and val.func.id
                            in {
                                "list",
                                "dict",
                                "set",
                                "deque",
                            }
                        ):
                            collection_attrs.add(name)
            if not collection_attrs:
                continue
            for fn in cls.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name == "__init__":
                    continue
                offenders.extend(
                    f"{path.name}:{cls.name}.{fn.name} accumulates a collection attr"
                    for attr in _accumulated_self_attrs(fn)
                    if attr in collection_attrs
                )
    assert offenders == [], offenders


def _accumulated_self_attrs(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterable[str]:
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _ACCUMULATE_CALLS:
            name = _self_attr_name(node.func.value)
            if name is not None:
                yield name
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Subscript):
                    name = _self_attr_name(tgt.value)
                    if name is not None:
                        yield name


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
