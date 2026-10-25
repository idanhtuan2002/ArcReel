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


def _check_artifacts(repo: Repository, envelope: dict[str, Any]) -> set[str]:
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
    if not {*REQUIRED_DESIGN_PATHS, SCHEMA_PATH, VERIFIER_PATH, *TEST_PATHS} <= seen:
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


def _check_prerequisites(repo: Repository, envelope: dict[str, Any]) -> None:
    rows = envelope["prerequisite_evidence"]
    if len(rows) != 4 or {row["owner"] for row in rows} != _OWNERS:
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


def verify(repo: Repository, *, acceptance_ref: str, schema: dict[str, Any]) -> tuple[str, ...]:
    """Return sanitized refusal codes; a synthetic fixture pass is not real acceptance."""
    try:
        if repo.current_head() != repo.head:
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        try:
            raw = repo.read(acceptance_ref, ACCEPTANCE_PATH)
        except BootstrapError:
            return ("M10_DESIGN_NOT_ACCEPTED",)
        if repo.mode(acceptance_ref, ACCEPTANCE_PATH) != "100644":
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
        protected = _check_artifacts(repo, envelope)
        if load_json(repo.read(candidate, SCHEMA_PATH)) != schema:
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        _check_reviews(repo, acceptance_ref, envelope)
        allowed_acceptance = {ACCEPTANCE_PATH, ADR_PATH} | {
            r["blind_review_artifact"]["path"] for r in envelope["reviewers"]
        }
        changed = set(repo.changed(candidate, acceptance_ref))
        if ACCEPTANCE_PATH not in changed or not changed <= allowed_acceptance:
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        if ADR_PATH in changed and repo.read(acceptance_ref, ADR_PATH) != repo.read(candidate, ADR_PATH).replace(
            b"status: proposed", b"status: accepted", 1
        ):
            raise BootstrapError("M10_SCHEMA_FREEZE_FAILED")
        _check_prerequisites(repo, envelope)
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
        return tuple(p for p in data.decode().split("\0") if p)

    def paths(self, ref: str, prefix: str) -> tuple[str, ...]:
        return tuple(
            p for p in self._git("ls-tree", "-r", "--name-only", "-z", ref, "--", prefix).decode().split("\0") if p
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--acceptance-ref")
    parser.add_argument("--preflight", action="store_true", help="verify eligibility without repository writes")
    args = parser.parse_args()
    try:
        repo = GitRepository(args.repo.resolve())
        ref = args.acceptance_ref or repo.head
        schema = load_json(repo.read(repo.head, SCHEMA_PATH))
        problems = verify(repo, acceptance_ref=ref, schema=schema)
        if not problems:
            envelope = load_json(repo.read(ref, ACCEPTANCE_PATH))
            if repo.read(envelope["accepted_design_head"], VERIFIER_PATH) != Path(__file__).read_bytes():
                problems = ("M10_SCHEMA_FREEZE_FAILED",)
        result = {
            "status": "REFUSED" if problems else "IMPLEMENTATION_ELIGIBLE",
            "head": repo.head,
            "stop_codes": list(problems),
        }
    except (BootstrapError, OSError) as exc:
        result = {
            "status": "REFUSED",
            "stop_codes": [str(exc) if isinstance(exc, BootstrapError) else "M10_REQUIRED_EVIDENCE_MISSING"],
        }
    print(json.dumps(result, sort_keys=True))
    return 2 if result["stop_codes"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
