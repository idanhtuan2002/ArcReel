"""Read-only custody of the separately accepted A3-P publication source slice."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, cast

BASELINE_REF = "dca138da92ca7bb3e8b6adbb44cacdfce84f0f84"
DESIGN_REF = "2e69816123c32ba057bfbed7d5e55344b3daa7d2"
ACCEPTANCE_REF = "c7a86813bd7a45f119262dc7acdfe9803967e181"
ACCEPTANCE_SHA256 = "a95b75e82440aabf024786f11f08fd384a5393d18a8a90ed3ee3349841fd5e28"
ACCEPTANCE_PATH = "docs/r2/evidence/R2_M10_A3_DESIGN_ACCEPTANCE.json"
PACKET_PATH = "docs/r2/evidence/R2_M10_A3_PACKET_2026-10-27.json"
GUARD_PATH = "scripts/r2/verify_m10_a3_scope.py"
REGISTRY_PATH = "lib/db/models/__init__.py"
MIGRATION_PATH = "alembic/versions/65f53650f3a8_quality_profile_publication.py"
COMPATIBILITY_REF = "0caf82042ae8319baa989e8bcb60ac05cd669633"
COMPATIBILITY_PARENT = "abaa866d0f53cdfcc76e9871b7f15557a1b0e24d"
COMPATIBILITY_PATH = "docs/r2/evidence/R2_M10_A3_TEST_COMPATIBILITY_AMENDMENT.json"
COMPATIBILITY_SHA256 = "2a0b4b6dbba45f7dab036bd9ad781b61b702931a04a6df36d35bb2d94e88bb4a"
BOOTSTRAP_PATH = "scripts/r2/verify_m10_bootstrap.py"
BOOTSTRAP_SHA256 = "b861916b2b0388f49af1df0576acd6aff7aa8447f6abe5490d4cd565055d5163"

_COMMON = {"__future__", "typing", "datetime", "collections.abc", "dataclasses", "types"}
_DOMAIN = {
    "r2.contracts.quality",
    "r2.contracts.advanced_creative",
    "r2.quality.digests",
    "r2.quality.errors",
    "r2.advanced_creative.digests",
}
_SQL = {"sqlalchemy", "sqlalchemy.orm", "sqlalchemy.engine", "sqlalchemy.ext.asyncio", "sqlalchemy.dialects.postgresql"}
_OWNERS = {
    "r2/quality/profiles.py": _COMMON | _DOMAIN,
    "lib/db/models/quality.py": _COMMON | _SQL | {"lib.db.base"},
    "lib/db/repositories/quality.py": _COMMON | _SQL | _DOMAIN | {"lib.db.models.quality", "r2.quality.profiles"},
    "server/services/quality_profile_custodian.py": _COMMON
    | _SQL
    | _DOMAIN
    | {
        "pathlib",
        "fastapi",
        "lib.db.repositories.quality",
        "r2.quality.profiles",
        "r2.advanced_creative.exploration",
        "r2.governance.grant_transition",
        "server.auth",
        "server.services.governance_startup",
        "server.services.governance_grants",
    },
    "server/services/quality_profiles.py": _COMMON
    | _SQL
    | _DOMAIN
    | {
        "lib.db.repositories.quality",
        "r2.quality.profiles",
        "server.services.quality_profile_custodian",
    },
    MIGRATION_PATH: _COMMON | _SQL | {"alembic"},
}
_MEMBERS = {
    "server.auth": {"get_current_interactive_user"},
    "server.services.governance_startup": {"verify_governance_activated_startup", "GovernanceStartupUnavailable"},
    "server.services.governance_grants": {"CheckpointedShowrunnerGrantReader", "ShowrunnerGrantUnavailableError"},
    "r2.advanced_creative.exploration": {"uuid7"},
    "lib.db.base": {"Base"},
    "alembic": {"op"},
}
_DECL_CALLS = {
    "types.MappingProxyType",
    "dataclasses.dataclass",
    "dataclasses.field",
    "pydantic.Field",
    "pydantic.model_validator",
    "pydantic.field_validator",
    "sqlalchemy.CheckConstraint",
    "sqlalchemy.ForeignKeyConstraint",
    "sqlalchemy.ForeignKey",
    "sqlalchemy.PrimaryKeyConstraint",
    "sqlalchemy.UniqueConstraint",
    "sqlalchemy.Index",
    "sqlalchemy.DateTime",
    "sqlalchemy.Integer",
    "sqlalchemy.BigInteger",
    "sqlalchemy.String",
    "sqlalchemy.Text",
    "sqlalchemy.JSON",
    "sqlalchemy.Column",
    "sqlalchemy.text",
    "sqlalchemy.orm.mapped_column",
}
_FORBIDDEN = {
    "open",
    "exec",
    "eval",
    "compile",
    "__import__",
    "getattr",
    "setattr",
    "delattr",
    "globals",
    "locals",
    "vars",
    "input",
    "breakpoint",
    "__builtins__",
    "__loader__",
    "__spec__",
}
_FORBIDDEN_ATTRIBUTES = {
    "write",
    "write_text",
    "write_bytes",
    "unlink",
    "rename",
    "mkdir",
    "rmdir",
    "connect",
    "send",
    "Popen",
    "system",
    "load_dotenv",
    "__dict__",
    "__globals__",
    "__getattribute__",
    "__subclasses__",
    "create_engine",
    "create_async_engine",
    "engine_from_config",
    "async_engine_from_config",
}
_FORBIDDEN_IMPORTS = {
    "create_engine",
    "create_async_engine",
    "engine_from_config",
    "async_engine_from_config",
    "get_current_user",
    "verify_governance_public_startup",
    "CurrentShowrunnerGrantReader",
    "SessionAuthenticatedShowrunnerAuthority",
}
_ASYNC_OWNERS = {
    "lib/db/repositories/quality.py",
    "server/services/quality_profile_custodian.py",
    "server/services/quality_profiles.py",
}


def _qualified(node: ast.expr, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return _qualified(node.value, aliases) + "." + node.attr
    return ""


def _declarations(nodes: list[ast.stmt], aliases: dict[str, str], *, asynchronous: bool, sentinel: bool) -> bool:
    allowed = _DECL_CALLS | ({"object"} if sentinel else set())
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Pass)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, ast.ClassDef):
            if any(
                not (isinstance(d, ast.Call) and _qualified(d.func, aliases) == "dataclasses.dataclass")
                for d in node.decorator_list
            ):
                return False
            if not _declarations(node.body, aliases, asynchronous=asynchronous, sentinel=sentinel):
                return False
            expressions: list[ast.AST] = [*node.bases, *node.keywords, *node.decorator_list, *node.type_params]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if isinstance(node, ast.AsyncFunctionDef) and not asynchronous:
                return False
            if any(
                not (
                    (isinstance(d, ast.Name) and _qualified(d, aliases) in {"classmethod", "staticmethod", "property"})
                    or (isinstance(d, ast.Call) and _qualified(d.func, aliases) in _DECL_CALLS)
                )
                for d in node.decorator_list
            ):
                return False
            expressions = [node.args, *node.decorator_list, *node.type_params]
            if node.returns is not None:
                expressions.append(node.returns)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.TypeAlias)):
            expressions = [node]
        else:
            return False
        for expression in expressions:
            for item in ast.walk(expression):
                if isinstance(item, ast.Call) and _qualified(item.func, aliases) not in allowed:
                    return False
                if (
                    isinstance(item, ast.Name)
                    and isinstance(item.ctx, ast.Store)
                    and (item.id in aliases or item.id in {"classmethod", "staticmethod", "property"})
                ):
                    return False
    return True


def source_problems(path: str, source: bytes) -> tuple[str, ...]:
    """Bound direct imports and initialization; this is not a general Python sandbox."""
    if path not in _OWNERS:
        return ("POST_M8_BASE_SEAM_CHANGED",)
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, UnicodeError):
        return ("POST_M8_BASE_SEAM_CHANGED",)
    refused = ("M10_NETWORK_SIDE_EFFECT_FORBIDDEN",)
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                if imported.name not in _OWNERS[path] or imported.name in _MEMBERS:
                    return refused
                local = imported.asname or imported.name.split(".")[0]
                qualified = imported.name if imported.asname else imported.name.split(".")[0]
                if local in aliases and aliases[local] != qualified:
                    return refused
                aliases[local] = qualified
        elif isinstance(node, ast.ImportFrom):
            parents = path.removesuffix(".py").split("/")[:-1]
            if node.level > len(parents):
                return refused
            module = (
                ".".join(parents[: len(parents) - node.level + 1] + ([node.module] if node.module else []))
                if node.level
                else node.module or ""
            )
            if module not in _OWNERS[path]:
                return refused
            for imported in node.names:
                local = imported.asname or imported.name
                qualified = module + "." + imported.name
                if (
                    imported.name == "*"
                    or imported.name in _FORBIDDEN_IMPORTS
                    or (module in _MEMBERS and imported.name not in _MEMBERS[module])
                    or local in {"classmethod", "staticmethod", "property"}
                    or (local in aliases and aliases[local] != qualified)
                ):
                    return refused
                aliases[local] = qualified
        if isinstance(node, (ast.Yield, ast.YieldFrom)) or (isinstance(node, ast.Await) and path not in _ASYNC_OWNERS):
            return refused
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in _FORBIDDEN:
            return refused
        if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_ATTRIBUTES:
            return refused
    return (
        ()
        if _declarations(
            tree.body,
            aliases,
            asynchronous=path in _ASYNC_OWNERS,
            sentinel=path == "server/services/quality_profile_custodian.py",
        )
        else refused
    )


def acceptance_problems(receipt: dict[str, Any], packet: dict[str, Any]) -> tuple[str, ...]:
    """Check data shape only; the caller must first verify the immutable Git/hash anchor."""
    try:
        amendment = packet["scope_amendment"]
        digest = hashlib.sha256(
            json.dumps(amendment, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        flags = (
            "original_a3_fully_accepted",
            "readiness_runtime_accepted",
            "runtime_activation_authorized",
            "production_migration_authorized",
            "provider_calls_authorized",
        )
        valid = (
            receipt["schema_version"] == "1"
            and receipt["status"] == "M10_A3_P_DESIGN_ACCEPTED"
            and receipt["baseline_head"] == BASELINE_REF
            and receipt["design_head"] == DESIGN_REF
            and receipt["scope_allowlist"] == packet["product_scope"]
            and receipt["scope_amendment"] == amendment
            and receipt["scope_amendment_sha256"] == packet["scope_amendment_sha256"] == digest
            and amendment["id"] == "M10_A3_P_READINESS_DEFERRAL_V1"
            and amendment["may_mark_original_a3_complete"] is False
            and all(receipt.get(flag) is False for flag in flags)
            and not receipt["required_skips"]
            and not receipt["material_unknowns"]
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    return () if valid else ("M10_DESIGN_NOT_ACCEPTED",)


def registry_problems(baseline: bytes, current: bytes, added_exports: tuple[str, ...]) -> tuple[str, ...]:
    """Permit the exact ORM import/exports amendment without other executable AST drift."""
    refused = ("POST_M8_BASE_SEAM_CHANGED",)
    try:
        before, after = ast.parse(baseline), ast.parse(current)
        expected = set(added_exports)
        imports = 0
        exports: list[str] = []
        remaining: list[ast.stmt] = []
        for node in after.body:
            if isinstance(node, ast.ImportFrom) and node.module == "lib.db.models.quality":
                if (
                    node.level
                    or {a.name for a in node.names} != expected
                    or len(node.names) != len(expected)
                    or any(a.asname for a in node.names)
                ):
                    return refused
                imports += 1
                continue
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
            ):
                if not isinstance(node.value, (ast.List, ast.Tuple)):
                    return refused
                kept: list[ast.expr] = []
                for value in node.value.elts:
                    if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value in expected:
                        exports.append(value.value)
                    else:
                        kept.append(value)
                node.value.elts = kept
            remaining.append(node)
        after.body = remaining
        if not (
            (imports == 0 and not exports)
            or (imports == 1 and len(exports) == len(expected) and set(exports) == expected)
        ):
            return refused
        return () if ast.dump(before) == ast.dump(after) else refused
    except (SyntaxError, ValueError, UnicodeError):
        return refused


def _migration_graph(sources: dict[str, bytes]) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    graph: dict[str, tuple[str, ...]] = {}
    paths: dict[str, str] = {}
    for path, raw in sources.items():
        fields: dict[str, Any] = {}
        for node in ast.parse(raw).body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                        if target.id in fields:
                            raise ValueError("migration boundary")
                        fields[target.id] = ast.literal_eval(node.value)
        revision, previous = fields["revision"], fields["down_revision"]
        if not isinstance(revision, str) or not revision or revision in graph:
            raise ValueError("migration boundary")
        parents = () if previous is None else (previous,) if isinstance(previous, str) else tuple(previous)
        if any(not isinstance(p, str) or not p for p in parents):
            raise ValueError("migration boundary")
        graph[revision], paths[path] = parents, revision
    visited: set[str] = set()
    active: set[str] = set()

    def visit(revision: str) -> None:
        if revision in active or revision not in graph:
            raise ValueError("migration boundary")
        if revision in visited:
            return
        active.add(revision)
        for parent in graph[revision]:
            visit(parent)
        active.remove(revision)
        visited.add(revision)

    for revision in graph:
        visit(revision)
    return graph, paths


def migration_problems(
    baseline: dict[str, bytes], current: dict[str, bytes], *, target_path: str, revision: str, predecessor: str
) -> tuple[str, ...]:
    """Validate literal assignments, the unchanged predecessor graph and its sole owned addition."""
    refused = ("M10_SCHEMA_CHANGE_REQUIRED",)
    try:
        if any(current.get(path) != raw for path, raw in baseline.items()) or set(current) - set(baseline) - {
            target_path
        }:
            return refused
        old, _ = _migration_graph(baseline)
        graph, paths = _migration_graph(current)
        old_heads = set(old) - {p for parents in old.values() for p in parents}
        heads = set(graph) - {p for parents in graph.values() for p in parents}
        if old_heads != {predecessor}:
            return refused
        if target_path not in current:
            return () if graph == old else refused
        return (
            ()
            if (
                paths[target_path] == revision
                and revision not in old
                and graph[revision] == (predecessor,)
                and heads == {revision}
                and len(graph) == len(old) + 1
            )
            else refused
        )
    except (SyntaxError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        return refused


class ScopeError(ValueError):
    """Fixed sanitized refusal code, with no source or credential payload."""


class BoundRepository(Protocol):
    head: str

    def current_head(self) -> str: ...
    def read(self, ref: str, path: str) -> bytes: ...
    def mode(self, ref: str, path: str) -> str: ...
    def paths(self, ref: str, prefix: str) -> tuple[str, ...]: ...
    def changed(self, older: str, newer: str) -> tuple[str, ...]: ...
    def parents(self, ref: str) -> tuple[str, ...]: ...
    def ancestor(self, older: str, newer: str) -> bool: ...
    def dirty(self, protected: set[str]) -> tuple[str, ...]: ...


class BootstrapApi(Protocol):
    GitRepository: Callable[[Path], BoundRepository]

    def load_json(self, data: bytes) -> dict[str, Any]: ...


def _git(root: Path, *args: str) -> bytes:
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    environment.update(
        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_GRAFT_FILE=os.devnull, GIT_NO_LAZY_FETCH="1"
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
            cwd=root,
            env=environment,
            check=True,
            capture_output=True,
            timeout=15,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScopeError("M10_PREREQUISITE_NOT_ACCEPTED") from exc


def _head(root: Path) -> str:
    head = _git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    if not re.fullmatch("[0-9a-f]{40}", head):
        raise ScopeError("POST_M8_BASE_SEAM_CHANGED")
    return head


def _bootstrap(root: Path) -> BootstrapApi:
    raw = _git(root, "show", "--no-ext-diff", "--no-textconv", f"{BASELINE_REF}:{BOOTSTRAP_PATH}")
    mode = _git(root, "ls-tree", BASELINE_REF, "--", BOOTSTRAP_PATH).decode().split()[0]
    if hashlib.sha256(raw).hexdigest() != BOOTSTRAP_SHA256 or mode != "100644":
        raise ScopeError("M10_PREREQUISITE_NOT_ACCEPTED")
    module = ModuleType("m10_a3_accepted_git_reader")
    module.__file__ = str(root / BOOTSTRAP_PATH)
    # Only fixed digest-verified historical bytes execute; no candidate module is imported.
    exec(compile(raw, module.__file__, "exec"), module.__dict__)
    return cast(BootstrapApi, module)


def _same(repo: BoundRepository, ref: str, row: dict[str, Any]) -> None:
    if (
        repo.mode(ref, row["path"]) != row.get("mode", "100644")
        or hashlib.sha256(repo.read(ref, row["path"])).hexdigest() != row["sha256"]
    ):
        raise ScopeError("POST_M8_BASE_SEAM_CHANGED")


def _accepted(bootstrap: BootstrapApi, repo: BoundRepository) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = repo.read(ACCEPTANCE_REF, ACCEPTANCE_PATH)
    if hashlib.sha256(raw).hexdigest() != ACCEPTANCE_SHA256:
        raise ScopeError("M10_DESIGN_NOT_ACCEPTED")
    receipt = bootstrap.load_json(raw)
    packet = bootstrap.load_json(repo.read(DESIGN_REF, PACKET_PATH))
    if acceptance_problems(receipt, packet) or not (
        repo.ancestor(BASELINE_REF, DESIGN_REF)
        and repo.parents(ACCEPTANCE_REF) == (DESIGN_REF,)
        and repo.ancestor(ACCEPTANCE_REF, repo.head)
        and set(repo.changed(BASELINE_REF, DESIGN_REF)) == set(packet["design_scope"])
    ):
        raise ScopeError("M10_DESIGN_NOT_ACCEPTED")
    reviewers, artifacts = receipt["reviewers"], receipt["reviewer_artifacts"]
    if len(reviewers) != 2 or len(artifacts) != 2 or len({r["reviewer_id"] for r in reviewers}) != 2:
        raise ScopeError("M10_DESIGN_NOT_ACCEPTED")
    for record, row in zip(reviewers, artifacts, strict=True):
        if not (
            record["verdict"] == "PASS"
            and record["conflict_declaration"] == "NO_CONFLICT"
            and record["reviewed_candidate_head"] == DESIGN_REF
            and record["qualification_evidence"]
            and record["rubric_version"] == "R2_M10_A3_DESIGN_REVIEW_V1"
            and record["reviewed_at"].endswith("Z")
            and not record["required_skips"]
            and not record["material_unknowns"]
        ):
            raise ScopeError("M10_DESIGN_NOT_ACCEPTED")
        _same(repo, ACCEPTANCE_REF, row)
        if bootstrap.load_json(repo.read(ACCEPTANCE_REF, row["path"])) != record:
            raise ScopeError("M10_DESIGN_NOT_ACCEPTED")
    if set(repo.changed(DESIGN_REF, ACCEPTANCE_REF)) != {ACCEPTANCE_PATH, *(r["path"] for r in artifacts)} or (
        {r["path"] for r in receipt["design_artifacts"]} != set(packet["design_scope"])
    ):
        raise ScopeError("M10_DESIGN_NOT_ACCEPTED")
    return receipt, packet


def compatibility_problems(row: dict[str, Any], source: bytes, *, mode: str) -> tuple[str, ...]:
    """Only exact qualified historical test bodies may supplement their baseline bytes."""
    return (
        ()
        if mode == "100644" and hashlib.sha256(source).hexdigest() in {row["baseline_sha256"], row["proposed_sha256"]}
        else ("POST_M8_BASE_SEAM_CHANGED",)
    )


def _compatibility(bootstrap: BootstrapApi, repo: BoundRepository) -> dict[str, dict[str, Any]]:
    row = {"path": COMPATIBILITY_PATH, "sha256": COMPATIBILITY_SHA256}
    _same(repo, COMPATIBILITY_REF, row)
    _same(repo, repo.head, row)
    if not (
        repo.parents(COMPATIBILITY_REF) == (COMPATIBILITY_PARENT,)
        and repo.ancestor(ACCEPTANCE_REF, COMPATIBILITY_PARENT)
        and repo.ancestor(COMPATIBILITY_REF, repo.head)
        and set(repo.changed(COMPATIBILITY_PARENT, COMPATIBILITY_REF)) == {COMPATIBILITY_PATH}
    ):
        raise ScopeError("M10_DESIGN_NOT_ACCEPTED")
    receipt = bootstrap.load_json(repo.read(COMPATIBILITY_REF, COMPATIBILITY_PATH))
    rows = {item["path"]: item for item in receipt["files"]}
    if len(rows) != 12 or receipt["source_head"] != COMPATIBILITY_PARENT:
        raise ScopeError("M10_DESIGN_NOT_ACCEPTED")
    for path, item in rows.items():
        _same(repo, BASELINE_REF, {"path": path, "sha256": item["baseline_sha256"]})
        _same(repo, COMPATIBILITY_PARENT, {"path": path, "sha256": item["baseline_sha256"]})
        if compatibility_problems(item, repo.read(repo.head, path), mode=repo.mode(repo.head, path)):
            raise ScopeError("POST_M8_BASE_SEAM_CHANGED")
    return rows


def verify_scope(root: Path, *, acceptance_ref: str) -> dict[str, Any]:
    """Recompute scoped source custody; success accepts no runtime or original-A3 gate."""
    result: dict[str, Any] = {"status": "REFUSED", "acceptance_ref": acceptance_ref, "stop_codes": []}
    try:
        if acceptance_ref != ACCEPTANCE_REF:
            raise ScopeError("M10_DESIGN_NOT_ACCEPTED")
        root = root.resolve()
        head = _head(root)
        result["head"] = head
        if _git(root, "show", "--no-ext-diff", "--no-textconv", f"{head}:{GUARD_PATH}") != Path(__file__).read_bytes():
            raise ScopeError("POST_M8_BASE_SEAM_CHANGED")
        bootstrap = _bootstrap(root)
        repo = bootstrap.GitRepository(root)
        if repo.head != head:
            raise ScopeError("POST_M8_BASE_SEAM_CHANGED")
        receipt, packet = _accepted(bootstrap, repo)
        compatibility = _compatibility(bootstrap, repo)
        products = set(packet["product_scope"]) | set(compatibility) | {COMPATIBILITY_PATH}
        pins = packet["baseline_pins"]
        editable = packet["editable_baseline_pins"]
        migration = packet["migration"]
        migration_rows = migration["baseline_graph"]
        design_rows = receipt["design_artifacts"]
        evidence_rows = [{"path": ACCEPTANCE_PATH, "sha256": ACCEPTANCE_SHA256}, *receipt["reviewer_artifacts"]]
        head_paths = set(repo.paths(head, "."))
        protected = products | {r["path"] for r in [*pins, *editable, *migration_rows, *design_rows, *evidence_rows]}
        python_paths = {p for p in protected if p.endswith(".py")}
        prefixes = {p.removesuffix(".py") + "/" for p in python_paths} | {"alembic/", "r2/quality/"}
        for path in python_paths:
            for parent in Path(path).parents:
                if str(parent) == ".":
                    continue
                protected.add(str(parent / "__init__.py"))
        dirty = set(repo.dirty(protected | prefixes))
        changed = set(repo.changed(ACCEPTANCE_REF, head))
        ignored = (
            _git(
                root,
                "ls-files",
                "--others",
                "--ignored",
                "--exclude-standard",
                "-z",
                "--",
                *sorted(protected | prefixes),
            )
            .decode()
            .split("\0")
        )
        caches = {
            p for p in ignored if re.fullmatch(r"(?:[^/]+/)*__pycache__/[^/]+\.cpython-[0-9]+(?:\.opt-[0-9]+)?\.pyc", p)
        }
        dirty -= caches
        if any(p.startswith("alembic/") for p in dirty):
            raise ScopeError("M10_SCHEMA_CHANGE_REQUIRED")
        if changed - products or any(p in protected or any(p.startswith(prefix) for prefix in prefixes) for p in dirty):
            # A committed out-of-scope migration retains its schema-specific stop code.
            if any(p.startswith("alembic/") for p in changed - products):
                raise ScopeError("M10_SCHEMA_CHANGE_REQUIRED")
            raise ScopeError("POST_M8_BASE_SEAM_CHANGED")
        old_migrations = {r["path"]: repo.read(BASELINE_REF, r["path"]) for r in migration_rows}
        current_migrations = {p: repo.read(head, p) for p in repo.paths(head, "alembic/versions/") if p.endswith(".py")}
        if migration_problems(
            old_migrations,
            current_migrations,
            target_path=migration["path"],
            revision=migration["revision"],
            predecessor=migration["predecessor"],
        ):
            raise ScopeError("M10_SCHEMA_CHANGE_REQUIRED")
        if any(repo.mode(head, p) != "100644" for p in current_migrations):
            raise ScopeError("M10_SCHEMA_CHANGE_REQUIRED")
        for row in [*pins, *migration_rows]:
            for ref in (BASELINE_REF, DESIGN_REF, head):
                if ref == head and row["path"] in compatibility:
                    continue
                _same(repo, ref, row)
        for row in editable:
            _same(repo, BASELINE_REF, row)
            _same(repo, DESIGN_REF, row)
            if (
                row["path"] != REGISTRY_PATH
                or repo.mode(head, REGISTRY_PATH) != row["mode"]
                or registry_problems(
                    repo.read(BASELINE_REF, REGISTRY_PATH),
                    repo.read(head, REGISTRY_PATH),
                    tuple(packet["registry_added_exports"]),
                )
            ):
                raise ScopeError("POST_M8_BASE_SEAM_CHANGED")
        for row in design_rows:
            _same(repo, DESIGN_REF, row)
            _same(repo, head, row)
        for row in evidence_rows:
            _same(repo, head, row)
        for path in products & head_paths:
            if repo.mode(head, path) != "100644":
                raise ScopeError("POST_M8_BASE_SEAM_CHANGED")
            if path in _OWNERS:
                problems = source_problems(path, repo.read(head, path))
                if problems:
                    raise ScopeError(problems[0])
        if repo.current_head() != head or _head(root) != head:
            raise ScopeError("POST_M8_BASE_SEAM_CHANGED")
        result.update(
            status="M10_A3_P_SCOPE_OK",
            scope_allowlist=sorted(products),
            test_compatibility_ref=COMPATIBILITY_REF,
            original_a3_fully_accepted=False,
            readiness_runtime_accepted=False,
        )
    except (ValueError, OSError, KeyError, TypeError, IndexError, UnicodeError, SyntaxError) as exc:
        result["stop_codes"] = [str(exc) if isinstance(exc, ScopeError) else "POST_M8_BASE_SEAM_CHANGED"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--acceptance-ref", required=True)
    args = parser.parse_args()
    result = verify_scope(args.repo, acceptance_ref=args.acceptance_ref)
    print(json.dumps(result, sort_keys=True))
    return 2 if result["stop_codes"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
