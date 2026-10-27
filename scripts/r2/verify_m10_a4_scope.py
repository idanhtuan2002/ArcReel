"""Read-only A4 source custody; this guard grants no runtime or production authority."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

BASELINE_REF = "2ce1478bef93a77c888f3fc8fe2a5eefd8a46d4c"
DESIGN_REF = "ec838aa1a0d96ad51509339c2d69424c3d6592f6"
ACCEPTANCE_REF = "cf9f2f2c76d1eea46dd9f0b69db744c0d3f97327"
ACCEPTANCE_SHA256 = "e15100cac808a8a9a7eec73ea22c2abdd0cea10b24e7581d309d7e4675293431"
HELPER_PATH = "scripts/r2/verify_m10_a3_scope.py"
HELPER_SHA256 = "071e0ed119cb1748cba9ec883152edc3b278c5fd0bf8dfc6783be448f1c14269"
PACKET_PATH = "docs/r2/evidence/R2_M10_A4_PACKET_2026-10-27.json"
ACCEPTANCE_PATH = "docs/r2/evidence/R2_M10_A4_DESIGN_ACCEPTANCE.json"
GUARD_PATH = "scripts/r2/verify_m10_a4_scope.py"
MIGRATION_PATH = "alembic/versions/07fd34535384_quality_probe_evidence.py"
REGISTRY_PATH = "lib/db/models/__init__.py"
ROUTE_PATH = "r2/host_hardening/route_inventory.py"
CAPABILITY_PATH = "r2/provider_capabilities/registry.json"
_REFUSAL = ("POST_M8_BASE_SEAM_CHANGED",)


def _git(root: Path, *args: str) -> bytes:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_GRAFT_FILE=os.devnull, GIT_NO_LAZY_FETCH="1")
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
        env=env,
        capture_output=True,
        check=True,
        timeout=15,
    ).stdout


@lru_cache(maxsize=4)
def _helpers(root: Path) -> Any:
    raw = _git(root, "show", "--no-ext-diff", "--no-textconv", f"{BASELINE_REF}:{HELPER_PATH}")
    mode = _git(root, "ls-tree", BASELINE_REF, "--", HELPER_PATH).decode().split()[0]
    if hashlib.sha256(raw).hexdigest() != HELPER_SHA256 or mode != "100644":
        raise ValueError("historical helper integrity")
    module = ModuleType("m10_a4_verified_historical_helpers")
    module.__file__ = str(root / HELPER_PATH)
    # Execute only fixed digest-verified historical verifier bytes, never candidate product code.
    exec(compile(raw, module.__file__, "exec"), module.__dict__)
    return module


def compatibility_problems(row: dict[str, Any], current: bytes, *, mode: str) -> tuple[str, ...]:
    digest = hashlib.sha256(current).hexdigest()
    return () if mode == "100644" and digest in {row["baseline_sha256"], row["proposed_sha256"]} else _REFUSAL


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
            if isinstance(node, ast.ImportFrom) and node.module == "lib.db.models.quality_probes":
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


def qualified_route_source(baseline: bytes) -> bytes:
    old = b"_ALL_SUBMIT_FAMILIES = PAID_ASYNC_SUBMIT_FAMILIES + SPATIAL_SUBMIT_FAMILIES + FORMAT_RENDER_SUBMIT_FAMILIES"
    new = b"""HOST_QUALITY_ADAPTER_VERSION = "host-quality-v1"
QUALITY_PROBE_SUBMIT_FAMILIES = (
    PaidAsyncSubmitFamily(
        SubmitRouteKey("local-ffmpeg", "quality-probe", HOST_QUALITY_ADAPTER_VERSION),
        "local-ffmpeg-quality-probe@host-quality-v1",
        "server.services.quality_probes:QualityProbeService.observe",
    ),
)
_ALL_SUBMIT_FAMILIES = (
    PAID_ASYNC_SUBMIT_FAMILIES + SPATIAL_SUBMIT_FAMILIES + FORMAT_RENDER_SUBMIT_FAMILIES + QUALITY_PROBE_SUBMIT_FAMILIES
)"""
    if baseline.count(old) != 1:
        raise ValueError("route baseline")
    return baseline.replace(old, new)


def route_problems(baseline: bytes, current: bytes) -> tuple[str, ...]:
    try:
        actual = ast.dump(ast.parse(current))
        return (
            ()
            if actual in {ast.dump(ast.parse(baseline)), ast.dump(ast.parse(qualified_route_source(baseline)))}
            else _REFUSAL
        )
    except (SyntaxError, ValueError, UnicodeError):
        return _REFUSAL


def capability_problems(baseline: bytes, current: bytes) -> tuple[str, ...]:
    try:
        before, after = json.loads(baseline), json.loads(current)
        if before == after:
            return ()
        old, rows = before["profiles"], after["profiles"]
        if set(before) != set(after) or any(before[k] != after[k] for k in before if k != "profiles"):
            return _REFUSAL
        if len(rows) != len(old) + 1 or rows[:-1] != old:
            return _REFUSAL
        entry = rows[-1]
        expected = {
            "ref": "local-ffmpeg-quality-probe@host-quality-v1",
            "provider_id": "local-ffmpeg",
            "api_version": "ffmpeg-cli",
            "adapter_version": "host-quality-v1",
            "idempotency_mode": "NONE",
            "token_scope": None,
            "token_scope_value": None,
            "token_ttl_seconds": None,
            "not_found_semantics": "NON_AUTHORITATIVE",
            "lookup_settling_window_seconds": None,
            "supports_poll": False,
            "supports_cancel": False,
            "supports_webhook": False,
            "supports_lookup": False,
            "provider_sequence_is_monotonic": False,
            "evidence_expires_at": None,
        }
        variable = {"evidence_digest", "entry_digest", "qualification_status", "evidence_recorded_at"}
        if set(entry) != set(expected) | variable or any(entry[k] != v for k, v in expected.items()):
            return _REFUSAL
        if entry["qualification_status"] != "OFFLINE_VERIFIED":
            return _REFUSAL
        if any(not re.fullmatch(r"sha256:[0-9a-f]{64}", entry[k]) for k in ("evidence_digest", "entry_digest")):
            return _REFUSAL
        return ()
    except (ValueError, TypeError, KeyError, IndexError):
        return _REFUSAL


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
_DECL_CALLS |= {
    "ProbeCatalog",
    "ProbeConfig",
    "MediaTime",
    "frozenset",
    "tuple",
    "decimal.Decimal",
    "fractions.Fraction",
    "contextlib.asynccontextmanager",
    "contextlib.contextmanager",
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
                    (
                        isinstance(d, ast.Name)
                        and _qualified(d, aliases)
                        in {
                            "classmethod",
                            "staticmethod",
                            "property",
                            "contextlib.asynccontextmanager",
                            "contextlib.contextmanager",
                        }
                    )
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
                    and (
                        item.id in aliases
                        or item.id
                        in {
                            "classmethod",
                            "staticmethod",
                            "property",
                            "contextlib.asynccontextmanager",
                            "contextlib.contextmanager",
                        }
                    )
                ):
                    return False
    return True


_COMMON_IMPORTS = {"__future__", "typing", "collections.abc", "dataclasses", "datetime", "types", "enum"}
_PURE_IMPORTS = _COMMON_IMPORTS | {
    "decimal",
    "fractions",
    "math",
    "re",
    "json",
    "pydantic",
    "hashlib",
    "r2.contracts.quality",
    "r2.contracts.advanced_creative",
    "r2.advanced_creative.digests",
    "r2.quality.digests",
    "r2.quality.ports",
    "r2.quality.errors",
}
_SQL_IMPORTS = {
    "sqlalchemy",
    "sqlalchemy.orm",
    "sqlalchemy.ext.asyncio",
    "sqlalchemy.dialects.postgresql",
    "lib.db.base",
}
_IO_IMPORTS = _COMMON_IMPORTS | {
    "asyncio",
    "contextlib",
    "ctypes",
    "decimal",
    "errno",
    "fcntl",
    "fractions",
    "hashlib",
    "json",
    "math",
    "os",
    "pathlib",
    "re",
    "resource",
    "selectors",
    "signal",
    "stat",
    "struct",
    "subprocess",
    "sys",
    "tempfile",
    "time",
    "uuid",
}
_OWNER_IMPORTS = {
    "r2/quality/probes.py": _PURE_IMPORTS,
    "lib/db/models/quality_probes.py": _COMMON_IMPORTS | _SQL_IMPORTS,
    "lib/db/repositories/quality_probes.py": _PURE_IMPORTS
    | _SQL_IMPORTS
    | {
        "lib.db.models.quality_probes",
        "lib.db.models.host_hardening",
        "lib.db.repositories.host_hardening",
        "r2.quality.probes",
        "r2.contracts.host_hardening",
        "r2.contracts.execution",
    },
    "server/services/quality_probe_inputs.py": _IO_IMPORTS
    | {"r2.quality.probes", "r2.quality.ports", "r2.quality.errors", "r2.contracts.quality"},
    "server/services/quality_probe_runtime.py": _IO_IMPORTS
    | {"r2.quality.probes", "r2.quality.ports", "r2.quality.errors", "server.services.quality_probe_inputs"},
    "server/services/quality_probe_worker.py": _IO_IMPORTS,
    "server/services/quality_probes.py": _PURE_IMPORTS
    | _SQL_IMPORTS
    | {
        "asyncio",
        "pathlib",
        "fastapi",
        "lib.db.repositories.quality",
        "lib.db.repositories.quality_probes",
        "lib.db.repositories.host_hardening",
        "r2.quality.probes",
        "r2.contracts.execution",
        "r2.contracts.host_hardening",
        "r2.advanced_creative.exploration",
        "r2.host_hardening.host_submit",
        "r2.host_hardening.ports",
        "r2.host_hardening.route_inventory",
        "r2.host_hardening.provider_capabilities",
        "server.auth",
        "server.services.execution_attempts",
        "server.services.quality_probe_inputs",
        "server.services.quality_probe_runtime",
    },
    MIGRATION_PATH: _COMMON_IMPORTS | _SQL_IMPORTS | {"alembic"},
}


def source_problems(path: str, source: bytes) -> tuple[str, ...]:
    """Bound direct imports and obvious import effects; this is not a Python sandbox."""
    refused = ("M10_NETWORK_SIDE_EFFECT_FORBIDDEN",)
    if path not in _OWNER_IMPORTS:
        return _REFUSAL
    try:
        tree = ast.parse(source)
    except (ValueError, SyntaxError, UnicodeError):
        return _REFUSAL
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                local = item.asname or item.name.split(".")[0]
                qualified = item.name if item.asname else item.name.split(".")[0]
                if local in aliases and aliases[local] != qualified:
                    return refused
                aliases[local] = qualified
            if any(item.name not in _OWNER_IMPORTS[path] or item.name == "server.auth" for item in node.names):
                return refused
        elif isinstance(node, ast.ImportFrom):
            for item in node.names:
                local = item.asname or item.name
                qualified = (node.module or "") + "." + item.name
                if local in aliases and aliases[local] != qualified:
                    return refused
                aliases[local] = qualified
            if node.level or node.module not in _OWNER_IMPORTS[path]:
                return refused
            if any(item.name == "*" for item in node.names):
                return refused
            if node.module == "server.auth" and any(item.name != "get_current_interactive_user" for item in node.names):
                return refused
            if any(
                item.name in {"create_engine", "create_async_engine", "engine_from_config", "async_engine_from_config"}
                for item in node.names
            ):
                return refused
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id
            in {"exec", "eval", "compile", "__import__", "globals", "locals", "__builtins__", "__loader__", "__spec__"}
        ):
            return refused
        if isinstance(node, ast.Attribute) and node.attr in {"__globals__", "__subclasses__", "__getattribute__"}:
            return refused
    return (
        ()
        if _declarations(
            tree.body,
            aliases,
            asynchronous=path.startswith(("server/", "lib/db/repositories/")),
            sentinel=path == "server/services/quality_probes.py",
        )
        else refused
    )


def _protected(path: str, owned: set[str]) -> bool:
    if "/__pycache__/" in path and path.endswith(".pyc"):
        return False
    return path in owned or any(
        path == p or path.startswith(p + "/")
        for p in ("r2", "server", "lib", "alembic", "scripts", "tests", "pyproject.toml", "uv.lock")
    )


def verify(repo: Path, *, acceptance_ref: str = ACCEPTANCE_REF) -> dict[str, object]:
    root = repo.resolve()
    result: dict[str, object] = {
        "status": "M10_A4_SCOPE_REFUSED",
        "head": None,
        "runtime_accepted": False,
        "stop_codes": [],
    }
    try:
        helper = _helpers(root)
        bootstrap = helper._bootstrap(root)
        store = bootstrap.GitRepository(root)
        result["head"] = store.head
        if acceptance_ref != ACCEPTANCE_REF or not store.ancestor(ACCEPTANCE_REF, store.head):
            raise ValueError("design")
        raw = store.read(ACCEPTANCE_REF, ACCEPTANCE_PATH)
        if hashlib.sha256(raw).hexdigest() != ACCEPTANCE_SHA256:
            raise ValueError("design")
        acceptance = bootstrap.load_json(raw)
        packet_raw = store.read(DESIGN_REF, PACKET_PATH)
        if (
            hashlib.sha256(packet_raw).hexdigest() != acceptance["packet_sha256"]
            or acceptance["design_ref"] != DESIGN_REF
        ):
            raise ValueError("design")
        packet = bootstrap.load_json(packet_raw)
        docs = {r["path"] for r in packet["design_artifacts"]}
        owned = (
            set(packet["source_paths"] + packet["seam_paths"] + packet["test_paths"])
            | docs
            | {
                PACKET_PATH,
                ACCEPTANCE_PATH,
                "docs/r2/evidence/R2_M10_A4_CANDIDATE.json",
            }
        )

        def allowed(path: str) -> bool:
            return path in owned or path.startswith(
                ("tests/fixtures/r2/quality_probes/", "docs/r2/evidence/m10-a4-reviews/")
            )

        changes = set(store.changed(BASELINE_REF, store.head))
        if any(not allowed(p) for p in changes):
            raise ValueError("scope")
        protected = {"r2", "server", "lib", "alembic", "scripts", "tests", "pyproject.toml", "uv.lock", *owned}
        if any(_protected(p, owned) for p in store.dirty(protected)):
            raise ValueError("dirty")
        if any(store.mode(store.head, p) != "100644" for p in changes):
            raise ValueError("mode")
        for path, ref in [(PACKET_PATH, DESIGN_REF), (ACCEPTANCE_PATH, ACCEPTANCE_REF)]:
            if store.read(store.head, path) != store.read(ref, path):
                raise ValueError("frozen design")
        for row in packet["design_artifacts"]:
            if hashlib.sha256(store.read(store.head, row["path"])).hexdigest() != row["sha256"]:
                raise ValueError("design artifact")
        for row in packet["seam_baselines"]:
            if hashlib.sha256(store.read(BASELINE_REF, row["path"])).hexdigest() != row["sha256"]:
                raise ValueError("baseline")
        old_migrations = {
            p: store.read(BASELINE_REF, p) for p in store.paths(BASELINE_REF, "alembic/versions") if p.endswith(".py")
        }
        current_migrations = {
            p: store.read(store.head, p) for p in store.paths(store.head, "alembic/versions") if p.endswith(".py")
        }
        codes = migration_problems(
            old_migrations,
            current_migrations,
            target_path=MIGRATION_PATH,
            revision="07fd34535384",
            predecessor="65f53650f3a8",
        )
        codes += registry_problems(
            store.read(BASELINE_REF, REGISTRY_PATH),
            store.read(store.head, REGISTRY_PATH),
            tuple(packet["model_exports"]),
        )
        codes += route_problems(store.read(BASELINE_REF, ROUTE_PATH), store.read(store.head, ROUTE_PATH))
        codes += capability_problems(store.read(BASELINE_REF, CAPABILITY_PATH), store.read(store.head, CAPABILITY_PATH))
        row = packet["migration_test_compatibility"]
        codes += compatibility_problems(
            row, store.read(store.head, row["path"]), mode=store.mode(store.head, row["path"])
        )
        for path in packet["source_paths"]:
            if path != GUARD_PATH and path in store.paths(store.head, path):
                codes += source_problems(path, store.read(store.head, path))
        if codes:
            result["stop_codes"] = sorted(set(codes))
            return result
        if store.current_head() != store.head:
            raise ValueError("head changed")
        result["status"] = "M10_A4_SCOPE_OK"
        return result
    except Exception:
        result["stop_codes"] = ["POST_M8_BASE_SEAM_CHANGED"]
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--acceptance-ref", default=ACCEPTANCE_REF)
    args = parser.parse_args()
    result = verify(args.repo, acceptance_ref=args.acceptance_ref)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "M10_A4_SCOPE_OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
