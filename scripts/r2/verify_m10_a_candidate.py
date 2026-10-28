"""Read-only M10-A candidate verifier: forbidden surfaces, migration lineage, hash binding and donor parity.

Every byte is read from Git objects at one ref, never from the working tree. Import scanning is static and
direct (no transitive closure); it grants no runtime, production or acceptance authority.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import itertools
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

M10_MODULES = (
    "r2/contracts/quality.py",
    "r2/quality/",
    "server/services/quality_",
    "lib/db/models/quality",
    "lib/db/repositories/quality",
)
M10_IMPORT_PREFIXES = (
    "r2.contracts.quality",
    "r2.quality",
    "server.services.quality_",
    "lib.db.models.quality",
    "lib.db.repositories.quality",
)
# The model registry imports the tables; the M7 submit inventory names the one accepted local probe family.
ALLOWED_IMPORTERS = {
    "lib/db/models/__init__.py": None,
    "r2/host_hardening/route_inventory.py": "server.services.quality_probes:QualityProbeService.observe",
}
SUBPROCESS_OWNERS = {"server/services/quality_probe_runtime.py", "server/services/quality_probe_worker.py"}
NETWORK_MODULES = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "urllib3",
    "requests",
    "httpx",
    "aiohttp",
    "websockets",
    "smtplib",
    "ftplib",
    "telnetlib",
    "paramiko",
    "boto3",
    "botocore",
    "google",
    "openai",
    "anthropic",
    "ollama",
    "grpc",
}
EXPORT_TOKENS = ("export", "jianying", "publish", "upload", "packaging")
MIGRATION_CHAIN = ("65f53650f3a8", "07fd34535384", "57f67bae0cb4", "bed415be3608")
SCANNED_ROOTS = ("r2/", "server/", "lib/", "alembic/")


def is_m10(path: str) -> bool:
    return path.endswith(".py") and (path == M10_MODULES[0] or path.startswith(M10_MODULES[1:]))


def _imports(tree: ast.AST, *, symbols: bool = True) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.append(node.module)
            if symbols:
                names.extend(f"{node.module}.{item.name}" for item in node.names)
    return names


def _export_module(name: str) -> bool:
    return any(segment.startswith(EXPORT_TOKENS) for segment in name.lower().split("."))


def _m10_reference(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix) for prefix in M10_IMPORT_PREFIXES)


def source_problems(path: str, source: bytes) -> list[str]:
    """Stop codes for one M10-A product module."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return ["M10_SOURCE_UNPARSEABLE"]
    codes: set[str] = set()
    for name in _imports(tree, symbols=False):
        root = name.split(".")[0]
        if root in NETWORK_MODULES:
            codes.add("M10_NETWORK_SIDE_EFFECT_FORBIDDEN")
        if _export_module(name):
            codes.add("M10_PACKAGING_TARGET_FORBIDDEN")
        if root == "subprocess" and path not in SUBPROCESS_OWNERS:
            codes.add("M10_SUBPROCESS_OUTSIDE_ADAPTER")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr in {"create_subprocess_exec", "create_subprocess_shell", "system", "popen", "spawnv"} and (
                path not in SUBPROCESS_OWNERS or node.attr != "create_subprocess_exec"
            ):
                codes.add("M10_SUBPROCESS_OUTSIDE_ADAPTER")
            if node.attr in {"environ", "getenv", "environb"} and path not in SUBPROCESS_OWNERS:
                codes.add("M10_CREDENTIAL_READ_FORBIDDEN")
    return sorted(codes)


def importer_problems(path: str, source: bytes) -> list[str]:
    """A non-M10 product module may reach M10-A only through the frozen registry and M7 inventory entries."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return ["M10_SOURCE_UNPARSEABLE"]
    imported = [name for name in _imports(tree) if _m10_reference(name)]
    named = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _m10_reference(node.value)
    ]
    if not imported and not named:
        return []
    if path not in ALLOWED_IMPORTERS:
        return ["M10_PUBLIC_ROUTE_FORBIDDEN"]
    allowed = ALLOWED_IMPORTERS[path]
    if allowed is None:
        return (
            []
            if not named and all(name.startswith("lib.db.models.quality") for name in imported)
            else ["M10_PUBLIC_ROUTE_FORBIDDEN"]
        )
    return [] if not imported and set(named) == {allowed} else ["M10_PUBLIC_ROUTE_FORBIDDEN"]


def _migration_ids(source: bytes) -> tuple[str | None, tuple[str, ...]]:
    revision: str | None = None
    down: tuple[str, ...] = ()
    for node in ast.parse(source).body:
        targets = (
            [node.target] if isinstance(node, ast.AnnAssign) else node.targets if isinstance(node, ast.Assign) else []
        )
        value = getattr(node, "value", None)
        for target in targets:
            if not isinstance(target, ast.Name) or value is None or target.id not in {"revision", "down_revision"}:
                continue
            literal = ast.literal_eval(value)
            if target.id == "revision":
                revision = literal
            elif target.id == "down_revision":
                down = tuple(literal) if isinstance(literal, (tuple, list)) else ((literal,) if literal else ())
    return revision, down


def migration_problems(sources: dict[str, bytes]) -> list[str]:
    """One head, and the M10-A revisions form the exact chain from the accepted predecessor."""
    graph: dict[str, tuple[str, ...]] = {}
    try:
        for source in sources.values():
            revision, down = _migration_ids(source)
            if revision is None or revision in graph:
                return ["M10_MIGRATION_LINEAGE_INVALID"]
            graph[revision] = down
    except (SyntaxError, ValueError):
        return ["M10_MIGRATION_LINEAGE_INVALID"]
    parents = {parent for downs in graph.values() for parent in downs}
    heads = set(graph) - parents
    if heads != {MIGRATION_CHAIN[-1]}:
        return ["M10_MIGRATION_LINEAGE_INVALID"]
    for parent, child in itertools.pairwise(MIGRATION_CHAIN):
        if graph.get(child) != (parent,):
            return ["M10_MIGRATION_LINEAGE_INVALID"]
    return []


def parity_problems(report: dict[str, Any], baseline: dict[str, Any], head: str) -> list[str]:
    """Recompute the verdict; never trust the report's own verdict field."""
    from r2.contracts.advanced_creative import DonorParityReport, ParityVerdict
    from r2.quality.parity import evaluate_quality_parity

    try:
        parsed = DonorParityReport.model_validate(report)
    except ValueError:
        return ["M10_DONOR_PARITY_INCOMPLETE"]
    expected = [row["behavior_id"] for row in baseline["rows"]]
    if [row.behavior_id for row in parsed.rows] != expected or parsed.donor.commit_sha != baseline["donor"][
        "commit_sha"
    ]:
        return ["M10_DONOR_PARITY_INCOMPLETE"]
    for row, frozen in zip(parsed.rows, baseline["rows"], strict=True):
        if row.intentional_difference != frozen["intentional_difference"]:
            return ["M10_DONOR_PARITY_INCOMPLETE"]
    if evaluate_quality_parity(parsed, head) is not ParityVerdict.PASS:
        return ["M10_DONOR_PARITY_INCOMPLETE"]
    return []


class GitTree:
    def __init__(self, repo: Path, ref: str) -> None:
        self.repo = repo
        self.head = self._git("rev-parse", "--verify", ref + "^{commit}").decode().strip()

    def _git(self, *args: str) -> bytes:
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, check=True).stdout

    def paths(self) -> list[str]:
        return self._git("ls-tree", "-r", "--name-only", self.head).decode("utf-8").splitlines()

    def read(self, path: str) -> bytes:
        return self._git("show", f"{self.head}:{path}")


def verify(repo: Path, *, ref: str = "HEAD", parity_ref: str | None = None) -> dict[str, Any]:
    tree = GitTree(repo, ref)
    paths = tree.paths()
    codes: set[str] = set()
    modules = [p for p in paths if is_m10(p)]
    for path in modules:
        codes.update(source_problems(path, tree.read(path)))
    importers = [p for p in paths if p.endswith(".py") and p.startswith(SCANNED_ROOTS) and not is_m10(p)]
    for path in importers:
        codes.update(importer_problems(path, tree.read(path)))
    migrations = {p: tree.read(p) for p in paths if p.startswith("alembic/versions/") and p.endswith(".py")}
    codes.update(migration_problems(migrations))
    parity: str | None = None
    if parity_ref is not None:
        report = json.loads(tree.read(parity_ref))
        baseline = json.loads(tree.read("docs/r2/evidence/R2_M10_A7_KALINGA_BASELINE.json"))
        integrated = report.get("integrated_head", "")
        parity_codes = parity_problems(report, baseline, integrated)
        if not _ancestor(repo, integrated, tree.head):
            parity_codes = ["M10_DONOR_PARITY_INCOMPLETE"]
        parity = "PASS" if not parity_codes else "BLOCKED"
        codes.update(parity_codes)
    return {
        "status": "M10_A_CANDIDATE_OK" if not codes else "M10_A_CANDIDATE_REFUSED",
        "head": tree.head,
        "stop_codes": sorted(codes),
        "m10_modules": len(modules),
        "importers_scanned": len(importers),
        "migrations": len(migrations),
        "parity": parity,
        "runtime_accepted": False,
        "modules_sha256": {p: hashlib.sha256(tree.read(p)).hexdigest() for p in modules},
    }


def _ancestor(repo: Path, older: str, newer: str) -> bool:
    if not older:
        return False
    command = ["git", "-C", str(repo), "merge-base", "--is-ancestor", older, newer]
    return subprocess.run(command, capture_output=True, check=False).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--parity", default=None, help="repository path of the DonorParityReport JSON at --ref")
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve()))
    result = verify(args.repo.resolve(), ref=args.ref, parity_ref=args.parity)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "M10_A_CANDIDATE_OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
