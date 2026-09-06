from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

from r2.bootstrap import frozen_docs_dir
from r2.production import DependencySnapshot, R2ArtifactMetadata


REPO = Path(__file__).resolve().parents[4]
M1_HEAD = "9330bcf3"


def changed_paths() -> set[str]:
    output = subprocess.check_output(
        ["git", "diff", "--name-only", f"{M1_HEAD}..HEAD"],
        cwd=REPO,
        text=True,
    )
    return {line for line in output.splitlines() if line}


def production_imports() -> set[str]:
    imports: set[str] = set()
    for path in (REPO / "r2" / "production").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


def runtime_m2_text() -> str:
    paths = list((REPO / "r2" / "production").glob("*.py"))
    discovery = json.loads(
        (REPO / "docs/r2/evidence/R2_M2_SEAM_DISCOVERY.json").read_text()
    )
    paths.extend(REPO / path for path in discovery["host_files_if_patch_required"])
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def test_production_layer_has_no_forbidden_authority_or_provider_execution_imports():
    imports = production_imports()

    forbidden_prefixes = (
        "r2.canon",
        "r2.factual",
        "r2.narrative",
        "r2.director",
        "server.",
    )
    violations = sorted(
        name for name in imports if name.startswith(forbidden_prefixes)
    )

    assert violations == []


def test_no_r2_sql_migration_was_added_or_modified():
    migration_markers = (
        "/migrations/",
        "alembic/versions/",
        "migration",
    )
    suspicious = {
        path
        for path in changed_paths()
        if any(marker in path.lower() for marker in migration_markers)
        and path.endswith(".py")
    }

    assert suspicious == set()


def test_no_parallel_r2_artifact_registry_path_exists_in_runtime_code():
    assert ".r2_artifacts.json" not in runtime_m2_text()


def test_dependency_snapshot_contract_is_direct_only():
    assert set(DependencySnapshot.model_fields) == {
        "ref",
        "version",
        "fingerprint",
    }
    assert "direct_dependencies" in R2ArtifactMetadata.model_fields
    for forbidden in (
        "transitive_dependencies",
        "dependency_graph",
        "ancestors",
        "descendants",
    ):
        assert forbidden not in R2ArtifactMetadata.model_fields


def test_r2_artifact_metadata_excludes_execution_identity_fields():
    fields = set(R2ArtifactMetadata.model_fields)
    forbidden = {
        "provider",
        "model",
        "endpoint",
        "seed",
        "resolution",
        "execution_fingerprint",
        "provider_job_id",
        "submitted_base_url",
    }

    assert fields.isdisjoint(forbidden)


def test_host_files_changed_since_m1_are_subset_of_task0_allowlist():
    discovery = json.loads(
        (REPO / "docs/r2/evidence/R2_M2_SEAM_DISCOVERY.json").read_text()
    )
    allowlist = set(discovery["host_files_if_patch_required"])

    host_changed = {
        path
        for path in changed_paths()
        if path.startswith(("lib/", "server/"))
    }

    assert host_changed <= allowlist
    assert host_changed == {"lib/artifact_manifest.py"}


def test_r2_host_001_remains_open_production_blocker():
    registry = json.loads(
        (frozen_docs_dir() / "R2_05_HOST_HARDENING_REGISTRY.json").read_text()
    )
    h1 = next(item for item in registry["requirements"] if item["id"] == "H1")

    assert h1["severity"] == "PRODUCTION_BLOCKER"
    assert h1["decision_ref"] == "R2-HOST-001"
    assert h1.get("status") != "CLOSED"
