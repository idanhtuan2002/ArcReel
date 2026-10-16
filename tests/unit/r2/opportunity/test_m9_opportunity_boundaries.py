"""M9's deep module can call ports but cannot acquire another authority's writes."""

import ast
from pathlib import Path

from r2.opportunity import ports

ROOT = Path(__file__).resolve().parents[4]


def test_opportunity_module_exposes_only_protocols_at_external_seams():
    assert issubclass(ports.OpportunityProfileCustodianPort, ports.Protocol)
    assert issubclass(ports.FactualAuthorityPort, ports.Protocol)
    assert issubclass(ports.M8CanvasSeedPort, ports.Protocol)
    assert issubclass(ports.M8LearningReadPort, ports.Protocol)


def test_deep_module_cannot_import_credentials_providers_or_foreign_repositories():
    violations = []
    forbidden = (
        "server",
        "lib",
        "httpx",
        "requests",
        "openai",
        "anthropic",
        "boto3",
        "r2.production",
        "r2.production_intelligence",
    )
    for path in sorted((ROOT / "r2/opportunity").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports = [node.module or ""]
            else:
                imports = []
            for name in imports:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    violations.append(f"{path.name}:{node.lineno}:{name}")
                if name.startswith("r2.advanced_creative.") and name not in {
                    "r2.advanced_creative.digests",
                    "r2.advanced_creative.parity",
                }:
                    violations.append(f"{path.name}:{node.lineno}:{name}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__import__":
                violations.append(f"{path.name}:{node.lineno}:dynamic import")
    assert violations == []


def test_repository_never_commits_or_calls_another_authority():
    path = ROOT / "lib/db/repositories/opportunity.py"
    violations = []
    if path.exists():
        violations.extend(
            f"{node.lineno}:{node.func.attr}"
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"commit", "authorize_publication", "create_seed", "submit_evidence"}
        )
    assert violations == []
