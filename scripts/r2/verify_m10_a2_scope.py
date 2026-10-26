"""Read-only custody guard for the separately accepted, pure M10 A2 packet."""

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

BASELINE_REF = "655080af1660707b0b3c9b08f2b313ce638500f2"
DESIGN_REF = "5eda15b8931cc6537c784970672094373230e6f5"
ACCEPTANCE_REF = "f3d9cf97877e60a21818bb74d184c7c81867ff4c"
ACCEPTANCE_SHA256 = "8a51f562280d21bbf4284e94783b454eed159b67a87db900fa23f147e3ed2136"
ACCEPTANCE_PATH = "docs/r2/evidence/R2_M10_A2_DESIGN_ACCEPTANCE.json"
PACKET_PATH = "docs/r2/evidence/R2_M10_A2_PACKET_2026-10-26.json"
BOOTSTRAP_PATH = "scripts/r2/verify_m10_bootstrap.py"
BOOTSTRAP_SHA256 = "b861916b2b0388f49af1df0576acd6aff7aa8447f6abe5490d4cd565055d5163"
GUARD_PATH = "scripts/r2/verify_m10_a2_scope.py"
_PRODUCT_PYTHON = {"r2/quality/errors.py", "r2/quality/ports.py", "r2/quality/parity.py"}
_IMPORTS = {
    "__future__",
    "typing",
    "types",
    "re",
    "pydantic",
    "r2.contracts.quality",
    "r2.contracts.advanced_creative",
    "r2.quality.digests",
    "r2.advanced_creative.parity",
}
_DECLARATION_CALLS = {"types.MappingProxyType", "pydantic.model_validator", "re.compile"}
_FORBIDDEN_NAMES = {
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


def _declarations(nodes: list[ast.stmt], aliases: dict[str, str], *, protocol: bool = False) -> bool:
    for node in nodes:
        expressions: list[ast.AST] = []
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Pass)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, ast.ClassDef):
            is_protocol = any(_qualified(base, aliases) == "typing.Protocol" for base in node.bases)
            if node.decorator_list or not _declarations(node.body, aliases, protocol=is_protocol):
                return False
            expressions = [*node.bases, *node.keywords, *node.type_params]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if isinstance(node, ast.AsyncFunctionDef) and not (
                protocol
                and len(node.body) == 1
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and node.body[0].value.value is Ellipsis
            ):
                return False
            if any(
                not (
                    (isinstance(d, ast.Call) and _qualified(d.func, aliases) in _DECLARATION_CALLS)
                    or (
                        isinstance(d, ast.Name)
                        and _qualified(d, aliases) in {"classmethod", "staticmethod", "property"}
                    )
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
                if isinstance(item, ast.Call) and _qualified(item.func, aliases) not in _DECLARATION_CALLS:
                    return False
                if (
                    isinstance(item, ast.Name)
                    and isinstance(item.ctx, ast.Store)
                    and (item.id in aliases or item.id in {"classmethod", "staticmethod", "property"})
                ):
                    return False
    return True


def source_problems(path: str, source: bytes) -> tuple[str, ...]:
    """Inspect the bounded direct import/initialization surface; not a Python sandbox."""
    refused = ("M10_NETWORK_SIDE_EFFECT_FORBIDDEN",)
    if path not in _PRODUCT_PYTHON:
        return ("POST_M8_BASE_SEAM_CHANGED",)
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, UnicodeError):
        return ("POST_M8_BASE_SEAM_CHANGED",)
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        imports: list[tuple[str, str, str]] = []
        if isinstance(node, ast.Import):
            imports = [
                (a.name, a.asname or a.name.split(".")[0], a.name if a.asname else a.name.split(".")[0])
                for a in node.names
            ]
        elif isinstance(node, ast.ImportFrom):
            parents = path.removesuffix(".py").split("/")[:-1]
            if node.level > len(parents) or any(a.name == "*" for a in node.names):
                return refused
            module = (
                ".".join(parents[: len(parents) - node.level + 1] + ([node.module] if node.module else []))
                if node.level
                else node.module or ""
            )
            imports = [(module, a.asname or a.name, module + "." + a.name) for a in node.names]
        for module, local, qualified in imports:
            if module not in _IMPORTS or local in {"classmethod", "staticmethod", "property"}:
                return refused
            if local in aliases and aliases[local] != qualified:
                return refused
            aliases[local] = qualified
        if isinstance(node, (ast.Await, ast.Yield, ast.YieldFrom)):
            return refused
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in _FORBIDDEN_NAMES:
            return refused
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and (
                node.func.attr in _FORBIDDEN_ATTRIBUTES
                or (node.func.attr.startswith("__") and _qualified(node.func, aliases) != "Exception.__init__")
            )
        ):
            return refused
    return () if _declarations(tree.body, aliases) else refused


class ScopeError(ValueError):
    """Only fixed guard stop codes cross this boundary."""


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
    module = ModuleType("m10_a2_accepted_git_reader")
    module.__file__ = str(root / BOOTSTRAP_PATH)
    # Execute only the fixed, digest-verified historical blob, never candidate filesystem modules.
    exec(compile(raw, module.__file__, "exec"), module.__dict__)
    return cast(BootstrapApi, module)


def _same(repo: BoundRepository, ref: str, row: dict[str, Any]) -> None:
    if repo.mode(ref, row["path"]) != row.get("mode", "100644") or (
        hashlib.sha256(repo.read(ref, row["path"])).hexdigest() != row["sha256"]
    ):
        raise ScopeError("POST_M8_BASE_SEAM_CHANGED")


def _accepted(bootstrap: BootstrapApi, repo: BoundRepository) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = repo.read(ACCEPTANCE_REF, ACCEPTANCE_PATH)
    if hashlib.sha256(raw).hexdigest() != ACCEPTANCE_SHA256:
        raise ScopeError("M10_DESIGN_NOT_ACCEPTED")
    receipt = bootstrap.load_json(raw)
    packet = bootstrap.load_json(repo.read(DESIGN_REF, PACKET_PATH))
    if not (
        receipt["schema_version"] == "1"
        and receipt["status"] == "M10_A2_DESIGN_ACCEPTED"
        and receipt["baseline_head"] == BASELINE_REF
        and receipt["design_head"] == DESIGN_REF
        and receipt["scope_allowlist"] == packet["product_scope"]
        and not receipt["required_skips"]
        and not receipt["material_unknowns"]
        and repo.ancestor(BASELINE_REF, DESIGN_REF)
        and repo.parents(ACCEPTANCE_REF) == (DESIGN_REF,)
        and repo.ancestor(ACCEPTANCE_REF, repo.head)
        and set(repo.changed(BASELINE_REF, DESIGN_REF)) == set(packet["design_scope"])
    ):
        raise ScopeError("M10_DESIGN_NOT_ACCEPTED")
    reviewers = receipt["reviewers"]
    artifacts = receipt["reviewer_artifacts"]
    if len(reviewers) != 2 or len(artifacts) != 2 or len({r["reviewer_id"] for r in reviewers}) != 2:
        raise ScopeError("M10_DESIGN_NOT_ACCEPTED")
    for record, row in zip(reviewers, artifacts, strict=True):
        if not (
            record["verdict"] == "PASS"
            and record["conflict_declaration"] == "NO_CONFLICT"
            and record["reviewed_candidate_head"] == DESIGN_REF
            and record["qualification_evidence"]
            and record["rubric_version"] == "R2_M10_A2_DESIGN_REVIEW_V1"
            and record["reviewed_at"].endswith("Z")
            and not record["required_skips"]
            and not record["material_unknowns"]
        ):
            raise ScopeError("M10_DESIGN_NOT_ACCEPTED")
        _same(repo, ACCEPTANCE_REF, row)
        if bootstrap.load_json(repo.read(ACCEPTANCE_REF, row["path"])) != record:
            raise ScopeError("M10_DESIGN_NOT_ACCEPTED")
    if set(repo.changed(DESIGN_REF, ACCEPTANCE_REF)) != {ACCEPTANCE_PATH, *(r["path"] for r in artifacts)}:
        raise ScopeError("M10_DESIGN_NOT_ACCEPTED")
    if {r["path"] for r in receipt["design_artifacts"]} != set(packet["design_scope"]):
        raise ScopeError("M10_DESIGN_NOT_ACCEPTED")
    return receipt, packet


def verify_scope(root: Path, *, acceptance_ref: str) -> dict[str, Any]:
    """Validate actual immutable lineage and pure scope without executing candidate code."""
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
        products = set(packet["product_scope"])
        design_rows = receipt["design_artifacts"]
        evidence_rows = [{"path": ACCEPTANCE_PATH, "sha256": ACCEPTANCE_SHA256}, *receipt["reviewer_artifacts"]]
        pins = packet["baseline_pins"]
        migration_paths = set(repo.paths(BASELINE_REF, "alembic/")) | set(repo.paths(head, "alembic/"))
        protected = (
            products
            | {r["path"] for r in [*pins, *design_rows, *evidence_rows]}
            | migration_paths
            | {
                "alembic/",
                "r2/quality/",
            }
        )
        changed = set(repo.changed(ACCEPTANCE_REF, head))
        dirty = set(repo.dirty(protected))
        # Generated, untracked bytecode is not a revision or owned source file.
        ignored = (
            _git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--", "alembic/", "r2/quality/")
            .decode()
            .split("\0")
        )
        caches = {
            p
            for p in ignored
            if re.fullmatch(
                r"(?:alembic|r2/quality)/(?:[^/]+/)*__pycache__/[^/]+\.cpython-[0-9]+(?:\.opt-[0-9]+)?\.pyc", p
            )
        }
        dirty -= caches
        if any(p.startswith("alembic/") for p in changed | dirty):
            raise ScopeError("M10_SCHEMA_CHANGE_REQUIRED")
        if changed - products or any(p in protected or p.startswith("r2/quality/") for p in dirty):
            raise ScopeError("POST_M8_BASE_SEAM_CHANGED")
        for row in pins:
            for ref in (BASELINE_REF, DESIGN_REF, head):
                _same(repo, ref, row)
        for row in design_rows:
            _same(repo, DESIGN_REF, row)
            _same(repo, head, row)
        for row in evidence_rows:
            _same(repo, head, row)
        for path in products & set(repo.paths(head, ".")):
            if repo.mode(head, path) != "100644":
                raise ScopeError("POST_M8_BASE_SEAM_CHANGED")
            if path in _PRODUCT_PYTHON:
                problems = source_problems(path, repo.read(head, path))
                if problems:
                    raise ScopeError(problems[0])
        if repo.current_head() != head or _head(root) != head:
            raise ScopeError("POST_M8_BASE_SEAM_CHANGED")
        result.update(status="M10_A2_SCOPE_OK", scope_allowlist=packet["product_scope"])
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
