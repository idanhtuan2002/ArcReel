"""The M7 master head is the one master writer; the manifest master is only its projection (ADR-0096).

An AST scan over the production packages: ``AtomicPromotionService`` is constructed only by the
master authority unit, ``ProductionApprovalService`` only inside the host integration that
projects it, and ``GoldenAHostIntegration.approve`` is called only by the projection step of the
Gate C route and by the offline M3 runner.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_PACKAGES = ("lib", "r2", "server", "scripts")


def _is_story_approval(rel: str, tree: ast.Module, call: ast.Call) -> bool:
    receivers = {
        "server/routers/story_runs.py": "service.approve",
        "server/story_authoring/service.py": "committer.approve",
    }
    if ast.unparse(call.func) != receivers.get(rel):
        return False
    if not {"principal", "manifest_digest_seen", "accepted_exceptions"} <= {k.arg for k in call.keywords}:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith(
                ("r2.m3", "r2.production", "r2.host_hardening.master_authority", "lib.artifact_manifest")
            ):
                return False
        elif isinstance(node, ast.Import):
            if any(
                a.name.startswith(
                    ("r2.m3", "r2.production", "r2.host_hardening.master_authority", "lib.artifact_manifest")
                )
                for a in node.names
            ):
                return False
    return True


def _calls(name: str) -> set[str]:
    found: set[str] = set()
    for package in _PACKAGES:
        for path in (_ROOT / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                called = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
                rel = path.relative_to(_ROOT).as_posix()
                if called == name and not (name == "approve" and _is_story_approval(rel, tree, node)):
                    found.add(rel)
    return found


def test_only_the_master_authority_unit_constructs_the_promotion_service() -> None:
    assert _calls("AtomicPromotionService") == {"r2/host_hardening/master_authority.py"}


def test_only_the_host_integration_constructs_the_manifest_approval() -> None:
    assert _calls("ProductionApprovalService") == {"r2/m3/host_integration.py"}


def test_the_manifest_master_is_approved_only_by_the_projection_step_and_the_offline_runner() -> None:
    assert _calls("approve") == {"r2/m3/golden_a.py", "server/routers/gates.py"}


def test_the_gate_c_route_promotes_the_database_head_before_projecting() -> None:
    source = (_ROOT / "server" / "routers" / "gates.py").read_text(encoding="utf-8")

    # ``host.approve`` runs inside ``_project_and_export``, which is called after the promotion.
    assert source.index(".promote_staged(") < source.index("lambda: _project_and_export(registered)")


@pytest.mark.parametrize(
    "source",
    [
        "host.approve(principal=p, manifest_digest_seen=d, accepted_exceptions=[])",
        "from r2.m3.host_integration import GoldenAHostIntegration as Owner\ncommitter.approve(principal=p, manifest_digest_seen=d, accepted_exceptions=[])",
        "committer.approve(candidate)",
        "import r2.m3.host_integration as owner\n"
        "committer.approve(principal=p, manifest_digest_seen=d, accepted_exceptions=[])",
    ],
)
def test_story_approval_exception_refuses_manifest_or_unbound_calls(source: str) -> None:
    tree = ast.parse(source)
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    assert not _is_story_approval("server/story_authoring/service.py", tree, call)
