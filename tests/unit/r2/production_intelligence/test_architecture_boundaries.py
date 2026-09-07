"""D12 — executable architecture fitness for the M4 production-intelligence layer."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

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
}
_MUTATION_WORDS = ("promote", "approve", "commit", "mutate", "set_master", "update_manifest")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_r2_stays_in_every_static_analysis_root() -> None:
    cfg = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "r2" in cfg["tool"]["importlinter"]["root_packages"]
    assert "r2" in cfg["tool"]["basedpyright"]["include"]
    assert "r2" in cfg["tool"]["deptry"]["known_first_party"]


def test_stable_semantic_contracts_carry_no_provider_or_runtime_fields() -> None:
    for model in (
        SceneSpec,
        ShotSpec,
        MethodDecision,
        PromptPlan,
        VisualIdentityProfile,
        ResolvedVisualIdentity,
    ):
        assert set(model.model_fields).isdisjoint(_FORBIDDEN_STABLE_FIELDS), model.__name__


def test_execution_side_contracts_do_carry_provider_identity() -> None:
    assert {"provider_id", "model_or_tool_id", "adapter_id"} <= set(ExecutionDecision.model_fields)
    assert {"provider", "model", "endpoint"} <= set(ProviderRequest.model_fields)


def test_provider_neutrality_is_enforced_on_semantic_values_not_only_field_names() -> None:
    # D05/D08 — a provider CLI flag / payload token in a *value* is rejected even
    # though the carrying field name is provider-neutral.
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
    for path in sorted(_PI_DIR.glob("*.py")):
        for name in _imports(path):
            assert not name.startswith("lib.db"), f"{path.name} imports {name}"


def test_only_host_integration_touches_the_server_layer_and_only_the_c04_guard() -> None:
    for path in sorted(_PI_DIR.glob("*.py")):
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


def test_telemetry_has_no_authority_write_surface() -> None:
    names = _imports(_PI_DIR / "telemetry.py")
    assert not any(
        n.startswith(
            ("lib.artifact_manifest", "lib.db", "r2.production.approval_service", "r2.production.artifact_bridge")
        )
        for n in names
    )
    from r2.production_intelligence.telemetry import ProductionTelemetryProjector

    assert not any(any(w in m.lower() for w in _MUTATION_WORDS) for m in dir(ProductionTelemetryProjector))


def test_m4_introduces_no_second_queue_ledger_or_master_store() -> None:
    banned = ("queue", "ledger", "masterstore", "currencyengine", "artifactregistry")
    for path in sorted(_PI_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                lowered = node.name.lower()
                assert not any(term in lowered for term in banned), f"{path.name}:{node.name}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
