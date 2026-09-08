from __future__ import annotations

import ast
import json
from pathlib import Path

from r2.bootstrap import frozen_docs_dir
from r2.contracts import (
    MethodDecision,
    PromptPlan,
    ResolvedVisualIdentity,
    SceneSpec,
    ShotSpec,
    VisualIdentityProfile,
)

FORBIDDEN_PROVIDER_FIELDS = {
    "provider",
    "model",
    "endpoint",
    "payload",
    "provider_job_id",
    "provider_request",
    "execution_options",
    "submitted_base_url",
    "api_key",
}


def _registry_by_name():
    registry = json.loads((frozen_docs_dir() / "R2_03_CONTRACT_REGISTRY.json").read_text(encoding="utf-8"))
    return registry, {item["name"]: item for item in registry["contracts"]}


def test_provider_neutral_contracts_have_no_provider_runtime_fields():
    for model in (
        SceneSpec,
        ShotSpec,
        MethodDecision,
        PromptPlan,
        VisualIdentityProfile,
        ResolvedVisualIdentity,
    ):
        fields = set(model.model_fields)
        overlap = fields & FORBIDDEN_PROVIDER_FIELDS
        assert overlap == set(), (model.__name__, overlap)


def test_implementation_matches_frozen_registry_provider_boundaries():
    registry, by_name = _registry_by_name()
    assert registry["global_rules"]["content_basis_required_at_production_boundary"] is True
    assert registry["global_rules"]["content_fingerprint_separate_from_execution_fingerprint"] is True
    for name in ("SceneSpec", "ShotSpec", "MethodDecision", "PromptPlan"):
        assert by_name[name]["provider_neutral"] is True
    assert by_name["ProviderRequest"]["provider_neutral"] is False
    assert by_name["SceneSpec"]["content_basis_required"] is True
    assert by_name["ShotSpec"]["content_basis_required"] is True
    assert {"provider", "model", "endpoint", "payload", "provider_job_id"} <= set(
        by_name["SceneSpec"]["forbidden_fields"]
    )
    assert {"provider", "model", "endpoint", "payload", "provider_job_id"} <= set(
        by_name["ShotSpec"]["forbidden_fields"]
    )
    assert {"provider", "model", "endpoint"} <= set(by_name["MethodDecision"]["forbidden_fields"])


def test_contract_modules_do_not_import_arcreel_runtime_or_persistence_layers():
    root = Path(__file__).resolve().parents[4] / "r2" / "contracts"
    forbidden_roots = ("server", "lib", "sqlalchemy", "alembic")
    violations: list[str] = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            violations.extend(
                f"{path.name}: {name}"
                for name in names
                if name in forbidden_roots or name.startswith(tuple(f"{root_name}." for root_name in forbidden_roots))
            )
    assert violations == []
