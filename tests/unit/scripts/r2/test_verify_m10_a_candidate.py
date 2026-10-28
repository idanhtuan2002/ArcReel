"""The M10-A candidate verifier refuses forbidden surfaces, broken lineage and untrusted parity."""

from __future__ import annotations

import copy
import importlib
import itertools
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
HEAD = "a" * 40


def verifier():
    return importlib.import_module("scripts.r2.verify_m10_a_candidate")


def builder():
    return importlib.import_module("scripts.r2.build_m10_a7_parity")


@pytest.mark.parametrize(
    ("path", "source", "code"),
    [
        ("r2/quality/runs.py", b"import httpx\n", "M10_NETWORK_SIDE_EFFECT_FORBIDDEN"),
        (
            "server/services/quality_runs.py",
            b"from urllib.request import urlopen\n",
            "M10_NETWORK_SIDE_EFFECT_FORBIDDEN",
        ),
        ("server/services/quality_runs.py", b"import subprocess\n", "M10_SUBPROCESS_OUTSIDE_ADAPTER"),
        ("r2/quality/probes.py", b"import os\nos.system('x')\n", "M10_SUBPROCESS_OUTSIDE_ADAPTER"),
        (
            "server/services/quality_probe_runtime.py",
            b"import asyncio\nasyncio.create_subprocess_shell('x')\n",
            "M10_SUBPROCESS_OUTSIDE_ADAPTER",
        ),
        (
            "server/services/quality_dispositions.py",
            b"import os\nos.environ['TOKEN']\n",
            "M10_CREDENTIAL_READ_FORBIDDEN",
        ),
        ("lib/db/repositories/quality_runs.py", b"import os\nos.getenv('KEY')\n", "M10_CREDENTIAL_READ_FORBIDDEN"),
        (
            "server/services/quality_runs.py",
            b"from lib.jianying_export import build\n",
            "M10_PACKAGING_TARGET_FORBIDDEN",
        ),
        ("r2/quality/runs.py", b"from server.services.packaging import select\n", "M10_PACKAGING_TARGET_FORBIDDEN"),
        ("r2/quality/runs.py", b"def broken(:\n", "M10_SOURCE_UNPARSEABLE"),
    ],
)
def test_m10_modules_refuse_forbidden_surfaces(path: str, source: bytes, code: str) -> None:
    assert code in verifier().source_problems(path, source)


def test_bounded_adapter_and_profile_publication_are_admitted() -> None:
    v = verifier()
    runtime = b"import asyncio\nimport os\nasyncio.create_subprocess_exec('x')\nos.environ.get('XDG_RUNTIME_DIR')\n"
    assert v.source_problems("server/services/quality_probe_runtime.py", runtime) == []
    assert v.source_problems("server/services/quality_probe_worker.py", b"import subprocess\n") == []
    publication = b"from r2.quality.profiles import build_published_profile\n"
    assert v.source_problems("server/services/quality_profiles.py", publication) == []


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("server/routers/quality.py", b"from server.services.quality_runs import QualityRunService\n"),
        ("server/app.py", b"import server.services.quality_dispositions\n"),
        ("server/agent_runtime/tools.py", b"TARGET = 'server.services.quality_probes:QualityProbeService.observe'\n"),
        ("lib/db/models/__init__.py", b"from server.services.quality_runs import QualityRunService\n"),
        (
            "r2/host_hardening/route_inventory.py",
            b"TARGET = 'server.services.quality_runs:QualityRunService.complete'\n",
        ),
    ],
)
def test_outside_modules_cannot_reach_m10_except_the_frozen_entries(path: str, source: bytes) -> None:
    assert verifier().importer_problems(path, source) == ["M10_PUBLIC_ROUTE_FORBIDDEN"]


def test_registry_and_m7_inventory_entries_are_admitted() -> None:
    v = verifier()
    assert v.importer_problems("lib/db/models/__init__.py", b"from lib.db.models.quality_runs import RunModel\n") == []
    inventory = b"TARGET = 'server.services.quality_probes:QualityProbeService.observe'\n"
    assert v.importer_problems("r2/host_hardening/route_inventory.py", inventory) == []
    assert v.importer_problems("server/routers/projects.py", b"import json\n") == []


def migration(revision: str, down: str | None) -> bytes:
    return f"revision = {revision!r}\ndown_revision = {down!r}\nother = dict(a=1)\n".encode()


def chain() -> dict[str, bytes]:
    ids = verifier().MIGRATION_CHAIN
    sources = {"alembic/versions/base.py": migration(ids[0], None)}
    for parent, child in itertools.pairwise(ids):
        sources[f"alembic/versions/{child}.py"] = migration(child, parent)
    return sources


def test_migration_lineage_requires_the_exact_chain_and_one_head() -> None:
    v = verifier()
    assert v.migration_problems(chain()) == []
    forked = chain() | {"alembic/versions/extra.py": migration("ffffffffffff", v.MIGRATION_CHAIN[1])}
    assert v.migration_problems(forked) == ["M10_MIGRATION_LINEAGE_INVALID"]
    skipped = chain()
    skipped[f"alembic/versions/{v.MIGRATION_CHAIN[2]}.py"] = migration(v.MIGRATION_CHAIN[2], "000000000000")
    assert v.migration_problems(skipped) == ["M10_MIGRATION_LINEAGE_INVALID"]
    duplicate = chain() | {"alembic/versions/copy.py": migration(v.MIGRATION_CHAIN[3], v.MIGRATION_CHAIN[2])}
    assert v.migration_problems(duplicate) == ["M10_MIGRATION_LINEAGE_INVALID"]


def report_and_baseline():
    report = builder().build(ROOT, HEAD, {"command": "pytest", "result": "17 passed"})
    baseline = json.loads((ROOT / builder().BASELINE).read_text("utf-8"))
    return report, baseline


def test_recorded_parity_is_blocked_by_its_unverified_resource_dimension() -> None:
    report, baseline = report_and_baseline()
    assert report["verdict"] == "BLOCKED"
    assert report["material_unknowns"]
    assert verifier().parity_problems(report, baseline, HEAD) == ["M10_DONOR_PARITY_INCOMPLETE"]


def test_parity_passes_only_when_every_frozen_row_is_resolved() -> None:
    report, baseline = report_and_baseline()
    resolved = copy.deepcopy(report)
    resolved["material_unknowns"] = []
    row = next(row for row in resolved["rows"] if row["behavior_id"] == "tool_failure_typed")
    row["resources"] = "IMPROVED"
    v = verifier()
    assert v.parity_problems(resolved, baseline, HEAD) == []
    assert v.parity_problems(resolved, baseline, "b" * 40) == ["M10_DONOR_PARITY_INCOMPLETE"]
    for tamper in (
        lambda r: r["rows"].pop(),
        lambda r: r["rows"][0].update(intentional_difference="excluded later"),
        lambda r: r["donor"].update(commit_sha="c" * 40),
        lambda r: r["required_skips"].append("ffmpeg missing"),
        lambda r: r["rows"][-1].update(intentional_difference=None),
    ):
        changed = copy.deepcopy(resolved)
        tamper(changed)
        assert v.parity_problems(changed, baseline, HEAD) == ["M10_DONOR_PARITY_INCOMPLETE"]
    trusted_verdict = copy.deepcopy(report)
    trusted_verdict["verdict"] = "PASS"
    assert v.parity_problems(trusted_verdict, baseline, HEAD) == ["M10_DONOR_PARITY_INCOMPLETE"]
