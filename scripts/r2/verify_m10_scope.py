"""Read-only scope guard for the independently accepted M10 A0/A1 packet."""

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

ACCEPTANCE_REF = "cf18b9f6156ed9e6337c40708e217a73271027fa"
DESIGN_REF = "97e03c2ccee778e2797940f245fca9900fbf7a8e"
BOOTSTRAP_PATH = "scripts/r2/verify_m10_bootstrap.py"
BOOTSTRAP_SHA256 = "b861916b2b0388f49af1df0576acd6aff7aa8447f6abe5490d4cd565055d5163"
GUARD_PATH = "scripts/r2/verify_m10_scope.py"
_SCHEMA_PATH = "docs/r2/evidence/schemas/R2_M10_CONTRACT_DESIGN_ACCEPTANCE.schema.json"
_PACKET_PATH = "docs/r2/evidence/R2_M10_CONTRACT_PACKET_2026-10-25.json"

_PRODUCT_PYTHON = {"r2/contracts/quality.py", "r2/quality/__init__.py", "r2/quality/digests.py"}
_PURE_IMPORTS = {
    "__future__",
    "collections.abc",
    "datetime",
    "enum",
    "hashlib",
    "math",
    "re",
    "typing",
    "uuid",
    "pydantic",
    "pydantic_core",
    "pydantic_core.core_schema",
    "types",
}
_DECLARATION_CALLS = {
    "pydantic.Field",
    "pydantic.ConfigDict",
    "pydantic.field_validator",
    "pydantic.model_validator",
    "pydantic.BeforeValidator",
    "pydantic.AfterValidator",
    "pydantic.StringConstraints",
    "pydantic.Tag",
    "pydantic.Discriminator",
    "pydantic.TypeAdapter",
    "types.MappingProxyType",
    "re.compile",
}
_FORBIDDEN_CALLS = {
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
}
_FORBIDDEN_ATTRIBUTES = {
    "write",
    "write_text",
    "write_bytes",
    "mkdir",
    "unlink",
    "rmdir",
    "rename",
    "connect",
    "send",
    "Popen",
    "system",
    "load_dotenv",
}


def _qualified(node: ast.expr, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return _qualified(node.value, aliases) + "." + node.attr
    return ""


def _declarations(nodes: list[ast.stmt], aliases: dict[str, str]) -> bool:
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Pass)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        expressions: list[ast.AST]
        if isinstance(node, ast.ClassDef):
            if node.decorator_list:
                return False
            if not _declarations(node.body, aliases):
                return False
            expressions = [*node.bases, *node.keywords, *node.decorator_list, *node.type_params]
        elif isinstance(node, ast.FunctionDef):
            if any(
                not (
                    (isinstance(decorator, ast.Call) and _qualified(decorator.func, aliases) in _DECLARATION_CALLS)
                    or (
                        isinstance(decorator, ast.Name)
                        and _qualified(decorator, aliases) in {"classmethod", "staticmethod", "property"}
                    )
                )
                for decorator in node.decorator_list
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
                if isinstance(item, ast.Call) and _qualified(item.func, aliases) not in _DECLARATION_CALLS:
                    return False
                if (
                    isinstance(item, ast.Name)
                    and isinstance(item.ctx, ast.Store)
                    and (item.id in aliases or item.id in {"classmethod", "staticmethod", "property"})
                ):
                    return False
    return True


def source_problems(path: str, source: bytes, *, allowed_project_modules: frozenset[str]) -> tuple[str, ...]:
    """Check direct imports/calls and initialization; this is not a Python sandbox."""
    refused = ("M10_SCOPE_EXPANSION_REQUIRED",)
    if path not in _PRODUCT_PYTHON:
        return refused
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, UnicodeError):
        return ("M10_SCHEMA_FREEZE_FAILED",)
    if path.endswith("/__init__.py"):
        return (
            ()
            if all(
                isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
                for n in tree.body
            )
            else refused
        )
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports = [
                (a.name, a.asname or a.name.split(".")[0], a.name if a.asname else a.name.split(".")[0])
                for a in node.names
            ]
        elif isinstance(node, ast.ImportFrom):
            parents = path.removesuffix(".py").split("/")[:-1]
            if node.level > len(parents):
                return refused
            module = (
                ".".join(parents[: len(parents) - node.level + 1] + ([node.module] if node.module else []))
                if node.level
                else node.module or ""
            )
            imports = [(module, a.asname or a.name, module + "." + a.name) for a in node.names]
            if any(a.name == "*" for a in node.names):
                return refused
        else:
            imports = []
        for module, local, qualified in imports:
            if module not in _PURE_IMPORTS and module not in allowed_project_modules:
                return refused
            if local in aliases and aliases[local] != qualified:
                return refused
            aliases[local] = qualified
        if isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom)):
            return refused
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and (node.id in _FORBIDDEN_CALLS or node.id in {"__builtins__", "__loader__", "__spec__"})
        ):
            return refused
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_CALLS:
                return refused
            if isinstance(node.func, ast.Attribute) and (
                node.func.attr in _FORBIDDEN_ATTRIBUTES or node.func.attr.startswith("__")
            ):
                return refused
    return () if _declarations(tree.body, aliases) else refused


class ScopeError(ValueError):
    """A sanitized scope refusal without candidate or environment payloads."""


class BoundRepository(Protocol):
    head: str

    def current_head(self) -> str: ...
    def read(self, ref: str, path: str) -> bytes: ...
    def mode(self, ref: str, path: str) -> str: ...
    def paths(self, ref: str, prefix: str) -> tuple[str, ...]: ...


class BootstrapApi(Protocol):
    GitRepository: Callable[[Path], BoundRepository]

    def load_json(self, data: bytes) -> dict[str, Any]: ...
    def verify(
        self, repo: BoundRepository, *, acceptance_ref: str, schema: dict[str, Any], packet: str
    ) -> tuple[str, ...]: ...


def _git(root: Path, *args: str) -> bytes:
    """Read immutable bootstrap bytes before its accepted Git reader can be loaded."""
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
        raise ScopeError("M10_REQUIRED_EVIDENCE_MISSING") from exc


def _head(root: Path) -> str:
    value = _git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    if not re.fullmatch("[0-9a-f]{40}", value):
        raise ScopeError("M10_SCHEMA_FREEZE_FAILED")
    return value


def _load_bootstrap(root: Path) -> BootstrapApi:
    source = _git(root, "show", "--no-ext-diff", "--no-textconv", f"{DESIGN_REF}:{BOOTSTRAP_PATH}")
    mode = _git(root, "ls-tree", DESIGN_REF, "--", BOOTSTRAP_PATH).decode().split()
    live = root / BOOTSTRAP_PATH
    if (
        hashlib.sha256(source).hexdigest() != BOOTSTRAP_SHA256
        or not mode
        or mode[0] != "100644"
        or live.is_symlink()
        or live.read_bytes() != source
    ):
        raise ScopeError("M10_SCHEMA_FREEZE_FAILED")
    module = ModuleType("m10_accepted_bootstrap")
    module.__file__ = str(live)
    # Only the fixed digest-verified Git blob is executable; candidate filesystem modules are not imported.
    exec(compile(source, str(live), "exec"), module.__dict__)
    return cast(BootstrapApi, module)


def verify_scope(root: Path, *, acceptance_ref: str) -> dict[str, Any]:
    """Recompute accepted custody and inspect committed product code without executing it."""
    result: dict[str, Any] = {"status": "REFUSED", "acceptance_ref": acceptance_ref, "stop_codes": []}
    try:
        if acceptance_ref != ACCEPTANCE_REF:
            raise ScopeError("M10_DESIGN_NOT_ACCEPTED")
        root = root.resolve()
        head = _head(root)
        result["head"] = head
        own_source = _git(root, "show", "--no-ext-diff", "--no-textconv", f"{head}:{GUARD_PATH}")
        if own_source != Path(__file__).read_bytes():
            raise ScopeError("M10_SCHEMA_FREEZE_FAILED")
        bootstrap = _load_bootstrap(root)
        repo = bootstrap.GitRepository(root)
        if repo.head != head:
            raise ScopeError("M10_SCHEMA_FREEZE_FAILED")
        schema = bootstrap.load_json(repo.read(DESIGN_REF, _SCHEMA_PATH))
        problems = bootstrap.verify(repo, acceptance_ref=acceptance_ref, schema=schema, packet="contracts")
        if problems:
            result["stop_codes"] = list(problems)
            return result
        definition = bootstrap.load_json(repo.read(DESIGN_REF, _PACKET_PATH))
        imports = frozenset(
            p.removesuffix(".py").replace("/", ".").removesuffix(".__init__") for p in definition["import_closure"]
        )
        present = set(repo.paths(head, "r2/")) & _PRODUCT_PYTHON
        for path in sorted(present):
            if repo.mode(head, path) != "100644":
                raise ScopeError("M10_SCHEMA_FREEZE_FAILED")
            allowed = imports | ({"r2.contracts.quality"} if path == "r2/quality/digests.py" else set())
            problems = source_problems(path, repo.read(head, path), allowed_project_modules=frozenset(allowed))
            if problems:
                result["stop_codes"] = list(problems)
                return result
        if repo.current_head() != head or _head(root) != head:
            raise ScopeError("M10_SCHEMA_FREEZE_FAILED")
        result.update(status="M10_CONTRACT_SCOPE_OK", scope_allowlist=definition["scope_allowlist"])
    except (ScopeError, ValueError, OSError, KeyError, TypeError, IndexError, UnicodeError, SyntaxError) as exc:
        code = str(exc) if isinstance(exc, ScopeError) else "M10_SCHEMA_FREEZE_FAILED"
        result["stop_codes"] = [code]
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
