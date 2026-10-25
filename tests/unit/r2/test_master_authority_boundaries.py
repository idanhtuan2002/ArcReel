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
    expected = {
        "server/routers/story_runs.py": (
            ("approve_run",),
            "service.approve",
            {
                "user_id": "user.id",
                "project_name": "project_name",
                "run_id": "run_id",
                "principal": "user.sub",
                "manifest_digest_seen": "req.manifest_digest",
                "accepted_exceptions": "req.accepted_exceptions",
            },
        ),
        "server/story_authoring/service.py": (
            ("StoryAuthoringService", "approve"),
            "committer.approve",
            {
                "principal": "principal",
                "manifest_digest_seen": "manifest_digest_seen",
                "accepted_exceptions": "accepted_exceptions",
            },
        ),
    }
    if rel not in expected:
        return False
    scope, receiver, keywords = expected[rel]
    approvals = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "approve"
    ]
    if approvals != [call] or ast.unparse(call.func) != receiver or call.args:
        return False
    if len(call.keywords) != len(keywords) or {k.arg: ast.unparse(k.value) for k in call.keywords} != keywords:
        return False
    body = tree.body
    owner = None
    for index, part in enumerate(scope):
        matches = (
            [n for n in body if isinstance(n, ast.ClassDef) and n.name == part]
            if index < len(scope) - 1
            else [n for n in body if isinstance(n, ast.AsyncFunctionDef) and n.name == part]
        )
        if len(matches) != 1:
            return False
        owner = matches[0]
        body = owner.body
    if owner is None or call not in ast.walk(owner):
        return False
    if any(
        call in ast.walk(n)
        for n in ast.walk(owner)
        if n is not owner and isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ):
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


@pytest.mark.parametrize(
    ("rel", "receiver", "scope", "keywords"),
    [
        (
            "server/routers/story_runs.py",
            "service",
            "approve_run",
            "user_id=user.id, project_name=project_name, run_id=run_id, principal=user.sub, manifest_digest_seen=req.manifest_digest, accepted_exceptions=req.accepted_exceptions",
        ),
        (
            "server/story_authoring/service.py",
            "committer",
            "approve",
            "principal=principal, manifest_digest_seen=manifest_digest_seen, accepted_exceptions=accepted_exceptions",
        ),
    ],
)
@pytest.mark.parametrize(
    "mutation", ["duplicate", "extra_keyword", "positional", "wrong_scope", "nested", "wrong_principal", "sync_scope"]
)
def test_story_delegation_requires_one_exact_call_in_its_own_function(
    rel: str, receiver: str, scope: str, keywords: str, mutation: str
) -> None:
    call = f"{receiver}.approve({keywords})"
    if mutation == "wrong_principal":
        call = call.replace("principal=user.sub", "principal=other").replace("principal=principal", "principal=other")
    if mutation == "extra_keyword":
        call = f"{receiver}.approve({keywords}, unexpected=x)"
    if mutation == "positional":
        call = f"{receiver}.approve(x, {keywords})"
    if mutation == "wrong_scope":
        scope = "another_function"
    body = f"    {call}\n"
    if mutation == "duplicate":
        body += f"    {call}\n"
    if mutation == "nested":
        body = f"    async def nested():\n        {call}\n"
    source = f"async def {scope}():\n{body}"
    if receiver == "committer":
        source = "class StoryAuthoringService:\n" + "\n".join("    " + line for line in source.splitlines())
    if mutation == "sync_scope":
        source = source.replace("async def ", "def ", 1)
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert calls
    assert all(not _is_story_approval(rel, tree, call_node) for call_node in calls)
