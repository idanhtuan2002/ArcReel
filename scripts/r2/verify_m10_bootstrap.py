"""Read-only structural custody checks for the M10 design acceptance envelope.

This verifier never imports candidate modules or migrations, writes repository files,
qualifies a custodian, or substitutes for independent substantive design review.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

ACCEPTANCE_PATH = "docs/r2/evidence/R2_M10_DESIGN_ACCEPTANCE.json"
SCHEMA_PATH = "docs/r2/evidence/schemas/R2_M10_DESIGN_ACCEPTANCE.schema.json"
VERIFIER_PATH = "scripts/r2/verify_m10_bootstrap.py"
CONTRACT_ACCEPTANCE_PATH = "docs/r2/evidence/R2_M10_CONTRACT_DESIGN_ACCEPTANCE.json"
CONTRACT_SCHEMA_PATH = "docs/r2/evidence/schemas/R2_M10_CONTRACT_DESIGN_ACCEPTANCE.schema.json"
CONTRACT_PACKET_PATH = "docs/r2/evidence/R2_M10_CONTRACT_PACKET_2026-10-25.json"
CONTRACT_SPEC_PATH = "docs/superpowers/specs/2026-10-25-r2-m10-contract-packet.md"
CONTRACT_PLAN_PATH = "docs/superpowers/plans/2026-10-25-r2-m10-contract-foundation.md"
CONTRACT_RELEASE_BASE = "14565f9d8a181654be272267a097ddafe2c87c79"
CONTRACT_IMPLEMENTATION_BASE = "dda0f273e035615e1c10a67f8712279d23b7053c"
CONTRACT_PREPARATION_ARTIFACT = {
    "path": "docs/r2/evidence/R2_PURE_ARTIFACT_SEAMS_VERIFICATION_2026-10-25.json",
    "sha256": "b53367f9fe9f02e0716365c26d3d79b992ec372e3f83375951e939aa39b80101",
}
_CONTRACT_CHARACTERIZATION = (
    {
        "path": "lib/__init__.py",
        "sha256": "58b1e0ba3f28dd34c03229fa5e36030cd73710b77df814067ae3c7d0a57133d9",
        "mode": "100644",
    },
    {
        "path": "lib/artifact_manifest.py",
        "sha256": "3d7d4afdcf4a592151348231be3d6a52d3bf9ad3062b94694967fb64dd684d28",
        "mode": "100644",
    },
    {
        "path": "lib/env_init.py",
        "sha256": "b4b5ec318cfe1fc5752bf24c86a4d1f5c994e360009c75fae6fd0459e6b585df",
        "mode": "100644",
    },
    {
        "path": "r2/m3/__init__.py",
        "sha256": "fcbb93a080eefdd459356663fc0d1ce4560cc3e9b5fdbb444fc04d33318cd492",
        "mode": "100644",
    },
    {
        "path": "r2/m3/deliverables.py",
        "sha256": "78f3ddcbe7b16ab7206cc81fd4d9481c7162cbdb5d26507f20f031654451c785",
        "mode": "100644",
    },
    {
        "path": "r2/m3/host_integration.py",
        "sha256": "89c6b66b4a371253da306da56e86b1fd54d6807f604d5ce576959652a948bd03",
        "mode": "100644",
    },
    {
        "path": "r2/production/__init__.py",
        "sha256": "f835c29af0d56e088dbc37d1fa776ef09c55ef08895e7b24492cfb962cbe00ab",
        "mode": "100644",
    },
    {
        "path": "r2/production/artifact_metadata.py",
        "sha256": "d1f6669f6edf483d13ee0194f10401e29f95fb2204cec6fa582309dcd8c46103",
        "mode": "100644",
    },
    {
        "path": "r2/host_hardening/master_authority.py",
        "sha256": "ca2bf5668743c0d336e6c1db71cc5e9ea071c8d79d7b640b31193b343f74952b",
        "mode": "100644",
    },
    {
        "path": "r2/host_hardening/promotion.py",
        "sha256": "14381eb7751270f380af5b5e15766fe9bf84e8f390de3ab05efa7e7508d16e10",
        "mode": "100644",
    },
    {
        "path": "r2/host_hardening/master_resolver.py",
        "sha256": "6de1b6eb534da038a94503134afd5dd50568edbdfd589c73f0b67903890c802f",
        "mode": "100644",
    },
    {
        "path": "r2/production/approval_service.py",
        "sha256": "d16442ddef3c094b172d743e60fc79d65bcb5aaae817e1296b354519e012d393",
        "mode": "100644",
    },
    {
        "path": "docs/adr/0106-m7-candidate-ids-are-scoped-to-user-and-project.md",
        "sha256": "9c5a7467df8bc7cbb8631726a19d5da48c777c90022a26cb50f6eedbd4383001",
        "mode": "100644",
    },
)

_CONTRACT_IMPORTS = frozenset(
    [
        "r2/__init__.py",
        "r2/advanced_creative/__init__.py",
        "r2/advanced_creative/digests.py",
        "r2/artifact_identity.py",
        "r2/contracts/__init__.py",
        "r2/contracts/advanced_creative.py",
        "r2/contracts/artifact_metadata.py",
        "r2/contracts/capabilities.py",
        "r2/contracts/common.py",
        "r2/contracts/content_basis.py",
        "r2/contracts/director.py",
        "r2/contracts/enums.py",
        "r2/contracts/execution.py",
        "r2/contracts/factual.py",
        "r2/contracts/fingerprints.py",
        "r2/contracts/host_hardening.py",
        "r2/contracts/narrative.py",
        "r2/contracts/narrative_context.py",
        "r2/contracts/narrative_lifecycle.py",
        "r2/contracts/narrative_plan.py",
        "r2/contracts/observability.py",
        "r2/contracts/preparation.py",
        "r2/contracts/production.py",
        "r2/contracts/provenance.py",
        "r2/contracts/provider_syntax.py",
        "r2/contracts/results.py",
        "r2/contracts/script.py",
    ]
)
CONTRACT_SCOPE = frozenset(
    {
        "scripts/r2/verify_m10_scope.py",
        "tests/unit/scripts/r2/test_verify_m10_scope.py",
        "tests/integration/scripts/r2/test_verify_m10_scope.py",
        "r2/contracts/quality.py",
        "r2/quality/__init__.py",
        "r2/quality/digests.py",
        "tests/unit/r2/contracts/test_quality.py",
        "tests/unit/r2/quality/test_quality_digests.py",
        "docs/r2/evidence/R2_M10_A_CONTRACTS_CANDIDATE.json",
    }
)
_CONTRACT_PREDECESSORS = {
    "M7": "b2816af45c9e81be76540ff03134c008ccdceafa",
    "M8": "23cf146a61c3b7acfb78440d2b1498fd9d77db4b",
}
_CONTRACT_SOURCES = {
    "canonical": "r2/advanced_creative/digests.py",
    "immutable_json": "r2/contracts/advanced_creative.py",
    "master_snapshot": "r2/contracts/host_hardening.py",
    "metadata_validation": "r2/contracts/artifact_metadata.py",
    "artifact_identity": "r2/artifact_identity.py",
    "master_ref_validation": "r2/artifact_identity.py",
    "contract_common": "r2/contracts/common.py",
    "contract_content_basis": "r2/contracts/content_basis.py",
    "contract_enums": "r2/contracts/enums.py",
    "r2_package_init": "r2/__init__.py",
    "contracts_package_init": "r2/contracts/__init__.py",
    "creative_package_init": "r2/advanced_creative/__init__.py",
    "project_config": "pyproject.toml",
    "dependency_lock": "uv.lock",
}

TEST_PATHS = (
    "tests/unit/scripts/r2/test_verify_m10_bootstrap.py",
    "tests/integration/scripts/r2/test_verify_m10_bootstrap.py",
)
ADR_PATH = "docs/adr/0082-m10-quality-evidence-and-export-packaging.md"
REQUIRED_DESIGN_PATHS = (
    ADR_PATH,
    "docs/research/2026-09-16-r2-m10-quality-evidence-packaging.md",
    "docs/superpowers/specs/2026-09-16-r2-m10-quality-packaging-design.md",
    "docs/superpowers/plans/2026-09-16-r2-m10-quality-packaging.md",
    "docs/superpowers/plans/2026-09-16-r2-m10a-quality-evidence-foundation.md",
    "docs/superpowers/specs/2026-10-25-r2-m10-v2-rebase.md",
    "docs/superpowers/specs/2026-10-25-r2-m10-foundation-bindings.md",
    "docs/r2/evidence/R2_M10_MASTER_BINDING_VECTORS.json",
    "docs/superpowers/plans/2026-10-25-r2-m10-design-resume.md",
)
DESIGN_OWNED_PATHS = frozenset(
    (
        "docs/adr/0082-m10-quality-evidence-and-export-packaging.md",
        "docs/r2/evidence/R2_M10_BOOTSTRAP_CANDIDATE_2026-10-25.json",
        "docs/r2/evidence/R2_M10_BOOTSTRAP_REVIEW_2026-10-25.md",
        "docs/r2/evidence/R2_M10_MASTER_BINDING_VECTORS.json",
        "docs/r2/evidence/R2_M10_PAUSE_HANDOFF_2026-10-23.md",
        "docs/r2/evidence/R2_M10_RESEARCH_AUDIT_2026-10-23.json",
        "docs/r2/evidence/R2_M10_RESUME_2026-10-25.json",
        "docs/r2/evidence/R2_M10_RESUME_REVIEW_2026-10-25.md",
        "docs/r2/evidence/R2_M10_V2_RESEARCH_2026-10-23.json",
        "docs/r2/evidence/R2_M10_V2_START_2026-10-23.json",
        "docs/r2/evidence/R2_V2_0_8_PRODUCTION_DEPLOYMENT.json",
        "docs/r2/evidence/schemas/R2_M10_DESIGN_ACCEPTANCE.schema.json",
        "docs/research/2026-09-16-r2-m10-quality-evidence-packaging.md",
        "docs/research/2026-10-23-r2-m10-research-decision-donor-audit.md",
        "docs/research/2026-10-23-r2-m10-v2-quality-packaging-seams.md",
        "docs/research/2026-10-23-r2-m10-v2-reuse-inventory.md",
        "docs/research/2026-10-23-r2-m10-v2-start.md",
        "docs/superpowers/plans/2026-09-16-r2-m10-quality-packaging.md",
        "docs/superpowers/plans/2026-09-16-r2-m10a-quality-evidence-foundation.md",
        "docs/superpowers/plans/2026-10-25-r2-m10-design-resume.md",
        "docs/superpowers/specs/2026-09-16-r2-m10-quality-packaging-design.md",
        "docs/superpowers/specs/2026-10-23-r2-m10-quality-packaging-design.md",
        "docs/superpowers/specs/2026-10-25-r2-m10-foundation-bindings.md",
        "docs/superpowers/specs/2026-10-25-r2-m10-v2-rebase.md",
        "scripts/r2/verify_m10_bootstrap.py",
        "tests/integration/scripts/r2/test_verify_m10_bootstrap.py",
        "tests/unit/scripts/r2/test_verify_m10_bootstrap.py",
    )
)

DESIGN_OWNED_PATHS = DESIGN_OWNED_PATHS | {
    "docs/r2/evidence/R2_M10_CONTRACT_DESIGN_CANDIDATE_2026-10-25.json",
    CONTRACT_PACKET_PATH,
    CONTRACT_SPEC_PATH,
    CONTRACT_SCHEMA_PATH,
    CONTRACT_PLAN_PATH,
}

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_OWNERS = {"M7", "M8", "M9", "FACTUAL"}
STOP_CODES = frozenset(
    {
        "M10_DESIGN_NOT_ACCEPTED",
        "M10_SCHEMA_FREEZE_FAILED",
        "M10_REVIEW_INDEPENDENCE_FAILED",
        "M10_PREREQUISITE_NOT_ACCEPTED",
        "M10_MIGRATION_BOUNDARY_INVALID",
        "M10_OWNED_PATH_DIRTY",
        "M10_SCOPE_EXPANSION_REQUIRED",
        "M10_REQUIRED_EVIDENCE_MISSING",
    }
)


class BootstrapError(ValueError):
    """A sanitized refusal code, without source, media, provider or reviewer payloads."""


class Repository(Protocol):
    head: str

    def current_head(self) -> str: ...

    def read(self, ref: str, path: str) -> bytes: ...
    def mode(self, ref: str, path: str) -> str: ...
    def parents(self, ref: str) -> tuple[str, ...]: ...
    def ancestor(self, older: str, newer: str) -> bool: ...
    def changed(self, older: str, newer: str) -> tuple[str, ...]: ...
    def dirty(self, protected: set[str]) -> tuple[str, ...]: ...
    def paths(self, ref: str, prefix: str) -> tuple[str, ...]: ...


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")


def load_json(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data, object_pairs_hook=_pairs, parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise BootstrapError("M10_SCHEMA_FREEZE_FAILED") from exc
    if not isinstance(value, dict):
        raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
    return value


def _path(value: str) -> str:
    if (
        not value
        or any(ord(c) < 32 for c in value)
        or "\\" in value
        or value.startswith(("/", "-"))
        or any(part in ("", ".", "..") for part in value.split("/"))
        or str(PurePosixPath(value)) != value
    ):
        raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
    return value


def _time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() != timedelta(0):
            raise ValueError("not UTC")
        return result
    except (ValueError, TypeError) as exc:
        raise BootstrapError("M10_SCHEMA_FREEZE_FAILED") from exc


def _bound(repo: Repository, ref: str, artifact: dict[str, Any], code: str) -> bytes:
    path = _path(artifact["path"])
    try:
        data = repo.read(ref, path)
        if repo.mode(ref, path) not in ("100644", "100755"):
            raise BootstrapError(code)
        if hashlib.sha256(data).hexdigest() != artifact["sha256"]:
            raise BootstrapError(code)
        return data
    except BootstrapError as exc:
        raise BootstrapError(code) from exc


def _check_artifacts(repo: Repository, envelope: dict[str, Any], *, packet: str = "full") -> set[str]:
    candidate = envelope["accepted_design_head"]
    bootstrap = envelope["bootstrap"]
    groups = (
        envelope["contract_paths_and_sha256"],
        envelope["evidence_schema_paths_and_sha256"],
        [bootstrap["verifier"]],
        bootstrap["tests"],
    )
    seen: set[str] = set()
    for group in groups:
        for artifact in group:
            if artifact["path"] in seen:
                raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
            seen.add(artifact["path"])
            _bound(repo, candidate, artifact, "M10_SCHEMA_FREEZE_FAILED")
    required = {*REQUIRED_DESIGN_PATHS, SCHEMA_PATH, VERIFIER_PATH, *TEST_PATHS}
    if packet == "contracts":
        required.update({CONTRACT_SCHEMA_PATH, CONTRACT_PACKET_PATH, CONTRACT_SPEC_PATH, CONTRACT_PLAN_PATH})
    if not required <= seen:
        raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
    if bootstrap["verifier"]["path"] != VERIFIER_PATH or {r["path"] for r in bootstrap["tests"]} != set(TEST_PATHS):
        raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
    return seen


def _check_reviews(repo: Repository, ref: str, envelope: dict[str, Any]) -> None:
    identities = {row["reviewer_id"] for row in envelope["reviewers"]}
    if len(identities) != len(envelope["reviewers"]) or envelope["author_id"] in identities:
        raise BootstrapError("M10_REVIEW_INDEPENDENCE_FAILED")
    end = _time(envelope["reviewed_at"])
    paths: set[str] = set()
    for row in envelope["reviewers"]:
        artifact = row["blind_review_artifact"]
        if artifact["path"] in paths:
            raise BootstrapError("M10_REVIEW_INDEPENDENCE_FAILED")
        paths.add(artifact["path"])
        if (
            row["reviewed_candidate_head"] != envelope["accepted_design_head"]
            or row["conflict_declaration"] != "NO_CONFLICT"
            or _time(row["reviewed_at"]) > end
        ):
            raise BootstrapError("M10_REVIEW_INDEPENDENCE_FAILED")
        body = load_json(_bound(repo, ref, artifact, "M10_REVIEW_INDEPENDENCE_FAILED"))
        if body != {key: value for key, value in row.items() if key != "blind_review_artifact"}:
            raise BootstrapError("M10_REVIEW_INDEPENDENCE_FAILED")


def require_release_ancestry(repo: Repository, *, release_base: str, accepted_heads: tuple[str, ...]) -> None:
    """Require each accepted predecessor in the released history, including merge parents."""
    if any(not repo.ancestor(ref, release_base) for ref in accepted_heads):
        raise BootstrapError("M10_PREREQUISITE_NOT_ACCEPTED")


def _check_prerequisites(repo: Repository, envelope: dict[str, Any], *, owners: set[str] = _OWNERS) -> None:
    rows = envelope["prerequisite_evidence"]
    if len(rows) != len(owners) or {row["owner"] for row in rows} != owners:
        raise BootstrapError("M10_PREREQUISITE_NOT_ACCEPTED")
    base = envelope["migration_boundary"]["implementation_base_head"]
    for row in rows:
        ref = row["accepted_head"]
        if not repo.ancestor(ref, base):
            raise BootstrapError("M10_PREREQUISITE_NOT_ACCEPTED")
        body = load_json(_bound(repo, ref, row["acceptance_artifact"], "M10_PREREQUISITE_NOT_ACCEPTED"))
        if body.get("status") != f"{row['owner']}_IMPLEMENTATION_ACCEPTED":
            raise BootstrapError("M10_PREREQUISITE_NOT_ACCEPTED")
        candidate = body.get("accepted_candidate_head", "")
        if not _SHA.fullmatch(candidate) or repo.parents(ref) != (candidate,):
            raise BootstrapError("M10_PREREQUISITE_NOT_ACCEPTED")


def _check_contract_packet(repo: Repository, envelope: dict[str, Any]) -> None:
    artifact = envelope["packet_definition"]
    if artifact["path"] != CONTRACT_PACKET_PATH:
        raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
    definition = load_json(_bound(repo, envelope["accepted_design_head"], artifact, "M10_SCHEMA_FREEZE_FAILED"))
    flags = (
        "full_m10_accepted",
        "runtime_activation_authorized",
        "m9_implementation_accepted",
        "factual_runtime_qualified",
        "custodian_runtime_qualified",
        "migration_authorized",
    )
    if (
        definition.get("packet") != "M10_A_A0_A1"
        or definition.get("status") != "CONTRACT_PACKET_DEFINITION"
        or definition.get("release_base") != CONTRACT_RELEASE_BASE
        or definition.get("implementation_scope") != "CONTRACTS_ONLY"
        or definition.get("full_m10_gate_unchanged") is not True
        or any(definition.get(flag) is not False for flag in flags)
    ):
        raise BootstrapError("M10_SCOPE_EXPANSION_REQUIRED")
    if (
        definition.get("scope_allowlist") != sorted(CONTRACT_SCOPE)
        or envelope["scope_allowlist"] != sorted(CONTRACT_SCOPE)
        or envelope.get("implementation_scope") != "CONTRACTS_ONLY"
        or envelope.get("full_m10_accepted") is not False
        or envelope.get("runtime_activation_authorized") is not False
    ):
        raise BootstrapError("M10_SCOPE_EXPANSION_REQUIRED")
    boundary = envelope["migration_boundary"]
    if (
        boundary["implementation_base_head"] != CONTRACT_IMPLEMENTATION_BASE
        or boundary["singleton_predecessor"] != "918c4a0e0001"
    ):
        raise BootstrapError("M10_PREREQUISITE_NOT_ACCEPTED")
    if (
        definition.get("implementation_base") != CONTRACT_IMPLEMENTATION_BASE
        or definition.get("preparation_verification") != CONTRACT_PREPARATION_ARTIFACT
        or definition.get("import_closure") != sorted(_CONTRACT_IMPORTS)
        or definition.get("characterization_sources") != list(_CONTRACT_CHARACTERIZATION)
    ):
        raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
    preparation_bytes = _bound(
        repo, CONTRACT_IMPLEMENTATION_BASE, CONTRACT_PREPARATION_ARTIFACT, "M10_SCHEMA_FREEZE_FAILED"
    )
    preparation = load_json(preparation_bytes)
    if (
        preparation.get("status") != "R2_PURE_ARTIFACT_SEAMS_VERIFIED"
        or preparation.get("scope") != "LOCAL_SOURCE_COMPATIBILITY_ONLY"
        or preparation.get("release_ancestor") != CONTRACT_RELEASE_BASE
        or preparation.get("runtime_activation_authorized") is not False
        or preparation.get("m10_design_accepted") is not False
        or repo.parents(CONTRACT_IMPLEMENTATION_BASE) != (preparation["verified_source_head"],)
        or not repo.ancestor(CONTRACT_RELEASE_BASE, CONTRACT_IMPLEMENTATION_BASE)
        or not repo.ancestor(CONTRACT_IMPLEMENTATION_BASE, envelope["accepted_design_head"])
    ):
        raise BootstrapError("M10_PREREQUISITE_NOT_ACCEPTED")
    for path, digest in preparation["source_sha256"].items():
        _bound(repo, CONTRACT_IMPLEMENTATION_BASE, {"path": path, "sha256": digest}, "M10_SCHEMA_FREEZE_FAILED")
    expected_rows = []
    require_release_ancestry(
        repo, release_base=CONTRACT_RELEASE_BASE, accepted_heads=tuple(_CONTRACT_PREDECESSORS.values())
    )
    for owner, ref in _CONTRACT_PREDECESSORS.items():
        path = f"docs/r2/evidence/R2_{owner}_IMPLEMENTATION_ACCEPTANCE.json"
        data = repo.read(CONTRACT_RELEASE_BASE, path)
        expected_rows.append(
            {
                "owner": owner,
                "accepted_head": ref,
                "acceptance_artifact": {"path": path, "sha256": hashlib.sha256(data).hexdigest()},
            }
        )
    if definition.get("prerequisite_evidence") != expected_rows or envelope["prerequisite_evidence"] != expected_rows:
        raise BootstrapError("M10_PREREQUISITE_NOT_ACCEPTED")
    architecture = definition["architecture_contract"]
    if architecture["path"] != "docs/r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE_CONTRACT_2026-09-14.json":
        raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
    base_contract = _bound(repo, CONTRACT_RELEASE_BASE, architecture, "M10_SCHEMA_FREEZE_FAILED")
    if definition.get("source_reuse") != _CONTRACT_SOURCES:
        raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
    for ref in (CONTRACT_IMPLEMENTATION_BASE, envelope["accepted_design_head"], repo.head):
        for artifact in _CONTRACT_CHARACTERIZATION:
            _bound(repo, ref, artifact, "M10_SCHEMA_FREEZE_FAILED")
            if repo.mode(ref, artifact["path"]) != artifact["mode"]:
                raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
    for ref in (envelope["accepted_design_head"], repo.head):
        if repo.read(ref, architecture["path"]) != base_contract:
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        if repo.read(ref, CONTRACT_PREPARATION_ARTIFACT["path"]) != preparation_bytes or repo.mode(
            ref, CONTRACT_PREPARATION_ARTIFACT["path"]
        ) != repo.mode(CONTRACT_IMPLEMENTATION_BASE, CONTRACT_PREPARATION_ARTIFACT["path"]):
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        for path in {*_CONTRACT_SOURCES.values(), *_CONTRACT_IMPORTS}:
            if (
                repo.read(ref, path) != repo.read(CONTRACT_IMPLEMENTATION_BASE, path)
                or repo.mode(CONTRACT_IMPLEMENTATION_BASE, path) not in {"100644", "100755"}
                or repo.mode(ref, path) != repo.mode(CONTRACT_IMPLEMENTATION_BASE, path)
            ):
                raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")


def _migration_graph(repo: Repository, ref: str) -> dict[str, str | None]:
    graph: dict[str, str | None] = {}
    for path in repo.paths(ref, "alembic/versions/"):
        if not path.endswith(".py") or path.endswith("/__init__.py"):
            continue
        assignments: dict[str, Any] = {}
        for node in ast.parse(repo.read(ref, path)).body:
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
                if isinstance(node, ast.AnnAssign)
                else []
            )
            for target in targets:
                if isinstance(target, ast.Name) and target.id in ("revision", "down_revision"):
                    if target.id in assignments:
                        raise BootstrapError("M10_MIGRATION_BOUNDARY_INVALID")
                    assignments[target.id] = ast.literal_eval(node.value)
        revision, parent = assignments["revision"], assignments["down_revision"]
        if (
            not isinstance(revision, str)
            or not revision
            or revision in graph
            or (parent is not None and not isinstance(parent, str))
        ):
            raise BootstrapError("M10_MIGRATION_BOUNDARY_INVALID")
        graph[revision] = parent
    if not graph or any(parent is not None and parent not in graph for parent in graph.values()):
        raise BootstrapError("M10_MIGRATION_BOUNDARY_INVALID")
    for revision in graph:
        seen: set[str] = set()
        cursor: str | None = revision
        while cursor is not None:
            if cursor in seen:
                raise BootstrapError("M10_MIGRATION_BOUNDARY_INVALID")
            seen.add(cursor)
            cursor = graph[cursor]
    return graph


def verify(repo: Repository, *, acceptance_ref: str, schema: dict[str, Any], packet: str = "full") -> tuple[str, ...]:
    """Return sanitized refusal codes; a synthetic fixture pass is not real acceptance."""
    try:
        if packet not in {"full", "contracts"}:
            raise BootstrapError("M10_SCOPE_EXPANSION_REQUIRED")
        acceptance_path = CONTRACT_ACCEPTANCE_PATH if packet == "contracts" else ACCEPTANCE_PATH
        schema_path = CONTRACT_SCHEMA_PATH if packet == "contracts" else SCHEMA_PATH
        if repo.current_head() != repo.head:
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        try:
            raw = repo.read(acceptance_ref, acceptance_path)
        except BootstrapError:
            return ("M10_DESIGN_NOT_ACCEPTED",)
        if repo.mode(acceptance_ref, acceptance_path) != "100644":
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        envelope = load_json(raw)
        pending: list[Any] = [schema]
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                if {"$ref", "$dynamicRef", "$recursiveRef"} & node.keys():
                    raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)
        Draft202012Validator.check_schema(schema)
        if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(envelope):
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        expected_status = "M10_CONTRACT_DESIGN_ACCEPTED" if packet == "contracts" else "M10_DESIGN_ACCEPTED"
        if envelope["status"] != expected_status:
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        candidate = envelope["accepted_design_head"]
        if (
            repo.parents(acceptance_ref) != (candidate,)
            or repo.parents(candidate) != (envelope["accepted_candidate_parent"],)
            or not repo.ancestor(acceptance_ref, repo.head)
            or not repo.ancestor(envelope["migration_boundary"]["implementation_base_head"], candidate)
        ):
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        if not set(envelope["stop_codes"]) >= STOP_CODES:
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        changed_candidate = set(repo.changed(envelope["migration_boundary"]["implementation_base_head"], candidate))
        if not changed_candidate <= DESIGN_OWNED_PATHS:
            raise BootstrapError("M10_SCOPE_EXPANSION_REQUIRED")
        protected = _check_artifacts(repo, envelope, packet=packet)
        if load_json(repo.read(candidate, schema_path)) != schema:
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        _check_reviews(repo, acceptance_ref, envelope)
        allowed_acceptance = (
            {acceptance_path}
            | ({ADR_PATH} if packet == "full" else set())
            | {r["blind_review_artifact"]["path"] for r in envelope["reviewers"]}
        )
        changed = set(repo.changed(candidate, acceptance_ref))
        if acceptance_path not in changed or not changed <= allowed_acceptance:
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        if ADR_PATH in changed and repo.read(acceptance_ref, ADR_PATH) != repo.read(candidate, ADR_PATH).replace(
            b"status: proposed", b"status: accepted", 1
        ):
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        if packet == "contracts":
            _check_contract_packet(repo, envelope)
            protected.update(_CONTRACT_SOURCES.values())
            protected.update(_CONTRACT_IMPORTS)
            protected.update(row["path"] for row in _CONTRACT_CHARACTERIZATION)
            protected.add(CONTRACT_PREPARATION_ARTIFACT["path"])
            protected.add("docs/r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE_CONTRACT_2026-09-14.json")
            if any(
                not row["blind_review_artifact"]["path"].startswith("docs/r2/evidence/m10-contract-reviews/")
                for row in envelope["reviewers"]
            ):
                raise BootstrapError("M10_REVIEW_INDEPENDENCE_FAILED")
        _check_prerequisites(repo, envelope, owners=set(_CONTRACT_PREDECESSORS) if packet == "contracts" else _OWNERS)
        expected = envelope["migration_boundary"]["singleton_predecessor"]
        base_graph = _migration_graph(repo, envelope["migration_boundary"]["implementation_base_head"])
        for ref in (candidate, acceptance_ref, repo.head):
            graph = _migration_graph(repo, ref)
            if graph != base_graph or set(graph) - {p for p in graph.values() if p is not None} != {expected}:
                raise BootstrapError("M10_MIGRATION_BOUNDARY_INVALID")
        scope = {_path(p) for p in envelope["scope_allowlist"]}
        if any(p.endswith("/") or not PurePosixPath(p).suffix for p in scope):
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        dirty = set(repo.dirty(scope | protected | allowed_acceptance | {"alembic/versions/"}))
        if dirty & (scope | protected | allowed_acceptance) or any(
            p.startswith("alembic/versions/") and p.endswith(".py") for p in dirty
        ):
            raise BootstrapError("M10_OWNED_PATH_DIRTY")
        if not set(repo.changed(acceptance_ref, repo.head)) <= scope:
            raise BootstrapError("M10_SCOPE_EXPANSION_REQUIRED")
        if repo.current_head() != repo.head:
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        return ()
    except BootstrapError as exc:
        return (str(exc),)
    except (KeyError, TypeError, ValueError, SyntaxError, RecursionError, SchemaError):
        return ("M10_SCHEMA_FREEZE_FAILED",)


class GitRepository:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root = Path(self._git("rev-parse", "--show-toplevel").decode().strip())
        self.head = self.current_head()

    def current_head(self) -> str:
        return self._git("rev-parse", "--verify", "HEAD^{commit}").decode().strip()

    def _git(self, *args: str) -> bytes:
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        environment.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_GRAFT_FILE": os.devnull,
                "GIT_NO_LAZY_FETCH": "1",
            }
        )
        try:
            return subprocess.run(
                [
                    "git",
                    "--no-replace-objects",
                    "--no-optional-locks",
                    "--literal-pathspecs",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "core.untrackedCache=false",
                    "-c",
                    "core.hooksPath=" + os.devnull,
                    "-c",
                    "protocol.allow=never",
                    *args,
                ],
                cwd=self.root,
                env=environment,
                capture_output=True,
                check=True,
                timeout=15,
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise BootstrapError("M10_REQUIRED_EVIDENCE_MISSING") from exc

    def read(self, ref: str, path: str) -> bytes:
        if not _SHA.fullmatch(ref):
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        return self._git("show", "--no-ext-diff", "--no-textconv", f"{ref}:{_path(path)}")

    def mode(self, ref: str, path: str) -> str:
        return self._git("ls-tree", ref, "--", _path(path)).decode().split()[0]

    def parents(self, ref: str) -> tuple[str, ...]:
        if not _SHA.fullmatch(ref):
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        return tuple(self._git("rev-list", "--parents", "-n", "1", ref).decode().split()[1:])

    def ancestor(self, older: str, newer: str) -> bool:
        if not _SHA.fullmatch(older) or not _SHA.fullmatch(newer):
            return False
        try:
            self._git("merge-base", "--is-ancestor", older, newer)
            return True
        except BootstrapError:
            return False

    def changed(self, older: str, newer: str) -> tuple[str, ...]:
        return tuple(
            p
            for p in self._git(
                "diff", "--no-ext-diff", "--no-textconv", "--name-only", "--no-renames", "-z", older, newer, "--"
            )
            .decode()
            .split("\0")
            if p
        )

    def dirty(self, protected: set[str]) -> tuple[str, ...]:
        data = (
            self._git(
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--name-only",
                "--no-renames",
                "--cached",
                "-z",
                self.head,
                "--",
            )
            + self._git("diff", "--no-ext-diff", "--no-textconv", "--name-only", "--no-renames", "-z", "--")
            + self._git("ls-files", "--others", "--exclude-standard", "-z")
            + self._git("ls-files", "--others", "-z", "--", *sorted(protected))
        )
        hidden = self._git("ls-files", "-v", "-z", "--", *sorted(protected)).decode().split("\0")
        marked = tuple(row[2:] for row in hidden if row and (row[0] == "S" or row[0].islower()))
        return tuple(p for p in data.decode().split("\0") if p) + marked

    def paths(self, ref: str, prefix: str) -> tuple[str, ...]:
        return tuple(
            p for p in self._git("ls-tree", "-r", "--name-only", "-z", ref, "--", prefix).decode().split("\0") if p
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--acceptance-ref")
    parser.add_argument("--packet", choices=("full", "contracts"), default="full")
    parser.add_argument("--preflight", action="store_true", help="verify eligibility without repository writes")
    args = parser.parse_args()
    try:
        repo = GitRepository(args.repo.resolve())
        ref = args.acceptance_ref or repo.head
        acceptance_path = CONTRACT_ACCEPTANCE_PATH if args.packet == "contracts" else ACCEPTANCE_PATH
        schema_path = CONTRACT_SCHEMA_PATH if args.packet == "contracts" else SCHEMA_PATH
        schema = load_json(repo.read(repo.head, schema_path))
        problems = verify(repo, acceptance_ref=ref, schema=schema, packet=args.packet)
        if not problems:
            envelope = load_json(repo.read(ref, acceptance_path))
            if repo.read(envelope["accepted_design_head"], VERIFIER_PATH) != Path(__file__).read_bytes():
                problems = ("M10_SCHEMA_FREEZE_FAILED",)
        result = {
            "status": "REFUSED"
            if problems
            else "CONTRACT_IMPLEMENTATION_ELIGIBLE"
            if args.packet == "contracts"
            else "IMPLEMENTATION_ELIGIBLE",
            "packet": args.packet,
            "head": repo.head,
            "stop_codes": list(problems),
        }
        if not problems and args.packet == "contracts":
            result["scope_allowlist"] = sorted(CONTRACT_SCOPE)
    except (BootstrapError, OSError) as exc:
        result = {
            "status": "REFUSED",
            "stop_codes": [str(exc) if isinstance(exc, BootstrapError) else "M10_REQUIRED_EVIDENCE_MISSING"],
        }
    print(json.dumps(result, sort_keys=True))
    return 2 if result["stop_codes"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
