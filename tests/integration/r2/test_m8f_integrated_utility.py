"""M8-F integrated utility (plan F2): both M6 cohorts run every M8 workflow on one database, beat the
registered host-only baseline on every capability, never leak across profiles, and replay to the same
digests from a second empty database.

With ``M8F_RESULTS_OUT`` set, the run writes its measured results there for the evidence file.
"""

from __future__ import annotations

import asyncio
import json
import os
import resource
import shutil
import time
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.adaptation import AdaptationRepository
from r2.advanced_creative.digests import digest_payload
from r2.contracts.advanced_creative import CanvasCandidate, LineageBinding
from scripts.r2.verify_m8f_determinism import stable_view
from server.services.format_render import ffmpeg_available
from tests.fixtures.r2 import m8f_corpus as corpus
from tests.integration.r2.m8f_utility_support import (
    USER,
    CohortResult,
    _FixtureVision,
    app_client,
    observations_for,
    run_cohort,
)

type Factory = async_sessionmaker[AsyncSession]

pytestmark = pytest.mark.skipif(not ffmpeg_available(), reason="needs ffmpeg and ffprobe")

REPO = Path(__file__).resolve().parents[3]
PROTOCOL = json.loads((REPO / "docs/r2/evidence/R2_M8_EVALUATION_PROTOCOL_V3.json").read_text(encoding="utf-8"))
REGISTERED_AT = datetime.fromisoformat(PROTOCOL["registered_at"].replace("Z", "+00:00"))
MINIMUM_DELTA = {item["capability"]: item["minimum_delta"] for item in PROTOCOL["endpoints"]}
CEILINGS = PROTOCOL["resource_envelope"]["ceilings"]


def _stable(result: CohortResult) -> dict[str, object]:
    """The whole cohort record minus run-scoped fields (scripts/r2/verify_m8f_determinism.py)."""
    return stable_view(json.loads(json.dumps(result.__dict__, default=str)))


def _export_review_media(measured: dict[str, dict[str, object]], root: Path, target: Path) -> None:
    """Copy each cohort's source shots and projections, for the offline blind review packet."""
    for profile in corpus.COHORTS:
        result = measured[profile.value]["result"]
        assert isinstance(result, CohortResult)
        project_dir = root / result.project
        out = target / profile.value
        out.mkdir(parents=True, exist_ok=True)
        for shot in ("SH01", "SH02"):
            shutil.copyfile(project_dir / "production" / f"{shot}.mp4", out / f"{shot}.mp4")
        for profile_ref, render in result.digests["format"].items():
            shutil.copyfile(project_dir / render["artifact_ref"], out / f"{profile_ref.split('@', 1)[0]}.mp4")
        (out / "spatial.json").write_text(
            json.dumps(result.digests["spatial"]["assertions"], indent=2), encoding="utf-8"
        )


def _disk_mib(path: Path) -> float:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) / 2**20


async def _run(factory: Factory, root: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, object]]:
    vision = _FixtureVision()
    measured: dict[str, dict[str, object]] = {}
    async with app_client(monkeypatch, factory, root, vision) as client:
        for profile in corpus.COHORTS:
            started = time.monotonic()
            result = await run_cohort(client, factory, root, profile, monkeypatch, registered_at=REGISTERED_AT)
            wall = time.monotonic() - started
            disk = sum(
                _disk_mib(root / name)
                for name in (corpus.creative_project(profile), *corpus.learning_projects(profile))
            )
            measured[profile.value] = {
                "result": result,
                "wall_seconds": round(wall, 1),
                "disk_mib": round(disk, 1),
            }
        measured["probes"] = {"result": await _leak_probes(client, factory, root), "vision_calls": vision.calls}
    return measured


async def _leak_probes(client, factory: Factory, root: Path) -> dict[str, object]:
    """A Western observation cannot enter a shuangwen project, and a cohort never sees the other's data."""
    western, shuang = corpus.COHORTS
    western_train, _ = corpus.learning_projects(western)
    shuang_train, _ = corpus.learning_projects(shuang)
    async with factory() as session:
        (western_ref,) = await AdaptationRepository(session).list_effective_screenplay_admissions(
            user_id=USER.id, project_name=western_train
        )
    foreign = observations_for(western, western_train, corpus.episode_script(western), western_ref)[0]
    refused = await client.post(
        f"/api/v1/projects/{shuang_train}/m8/learning/observations",
        json={"episode": 1, "observation": foreign.model_dump(mode="json"), "command_id": "m8f-leak"},
    )
    crossed = await client.post(
        f"/api/v1/projects/{shuang_train}/m8/learning/recommendations/evaluate",
        json={
            "source_family": foreign.source_family,
            "metric_name": "views",
            "metric_definition_version": foreign.metric_definition_version.rsplit("/", 1)[0]
            + "/views@"
            + foreign.metric_definition_version.rsplit("@", 1)[1],
            "aggregation": "sum_day",
            "creative_profile_id": western.value,
            "creative_profile_version": "v1",
            "arm_a": corpus.BASELINE_ARM,
            "arm_b": corpus.TREATMENT_ARM,
            "min_per_arm": 7,
            "min_relative_lift": "0.10",
            "expires_in_days": 30,
            "command_id": "m8f-cross-cohort",
        },
    )
    western_project = corpus.creative_project(western)
    shuang_project = corpus.creative_project(shuang)
    context = (
        await client.get(f"/api/v1/projects/{western_project}/m8/exploration/context", params={"episode": 1})
    ).json()
    forged_lineage = {**context["lineage"], "project_name": shuang_project}
    payload = {
        "kind": "CANVAS",
        "graph_schema_version": "1",
        "nodes": [],
        "edges": [],
        "groups": [],
        "storyboard_order": [],
        "viewport_bookmarks": [],
    }
    forged_revision = {
        "candidate_id": "m8f-forged",
        "revision": 1,
        "kind": "CANVAS",
        "parent_revision": None,
        "payload": payload,
        "payload_digest": digest_payload(
            CanvasCandidate.model_validate(payload), LineageBinding.model_validate(forged_lineage)
        ),
        "lineage": forged_lineage,
        "created_by": context["created_by"],
        "created_at": "2026-10-15T12:00:00Z",
    }
    forged = await client.post(
        f"/api/v1/projects/{shuang_project}/m8/exploration/revisions",
        json={"candidate": forged_revision, "expected_head_version": None, "command_id": "m8f-forged"},
    )
    return {
        "forged_canvas_append_status": forged.status_code,
        "forged_canvas_append_code": "M8_LINEAGE_NOT_SERVER_RESOLVED" in forged.text,
        "foreign_observation_status": refused.status_code,
        "cross_cohort_evaluation": {key: crossed.json()[key] for key in ("fired", "reason")},
    }


@pytest.mark.asyncio
async def test_both_cohorts_beat_the_baseline_without_leaking_and_replay_identically(
    session_factory: Factory, concurrent_session_factory: Factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await _run(session_factory, tmp_path / "run-1", monkeypatch)
    # A second, independent empty database: a separate file on SQLite, a separate schema on PostgreSQL.
    second = await _run(concurrent_session_factory, tmp_path / "run-2", monkeypatch)

    peak_rss_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    for profile in corpus.COHORTS:
        result = first[profile.value]["result"]
        assert isinstance(result, CohortResult)
        for capability, delta in MINIMUM_DELTA.items():
            assert result.deliverables[capability] - result.baseline[capability] >= delta, (profile, capability)
        assert result.master_heads_after == result.master_heads_before
        assert set(result.lineage_profiles.values()) == {profile.value}
        assert result.replay["language"] == "associative"
        assert result.replay["evaluation_projects"] == [corpus.learning_projects(profile)[1]]
        assert first[profile.value]["wall_seconds"] <= CEILINGS["cohort_wall_seconds"]
        assert first[profile.value]["disk_mib"] <= CEILINGS["cohort_disk_mib"]
        replayed = second[profile.value]["result"]
        assert isinstance(replayed, CohortResult)
        assert _stable(result) == _stable(replayed)
    probes = first["probes"]["result"]
    assert probes == {
        "forged_canvas_append_status": 409,
        "forged_canvas_append_code": True,
        "foreign_observation_status": 422,
        "cross_cohort_evaluation": {"fired": False, "reason": "both arms need observations"},
    }
    assert peak_rss_mib <= CEILINGS["peak_rss_mib"]

    out = os.environ.get("M8F_RESULTS_OUT")
    if out:
        payload = {
            "cohorts": {
                profile.value: {
                    "run_1": {
                        **first[profile.value]["result"].__dict__,
                        **{k: v for k, v in first[profile.value].items() if k != "result"},
                    },
                    "run_2_matches_run_1": True,
                    "run_2": second[profile.value]["result"].__dict__,
                    "run_2_wall_seconds": second[profile.value]["wall_seconds"],
                }
                for profile in corpus.COHORTS
            },
            "probes": probes,
            "vision_calls_per_run": first["probes"]["vision_calls"],
            "peak_rss_mib": round(peak_rss_mib, 1),
            "database": session_factory.kw["bind"].dialect.name,
        }
        await asyncio.to_thread(
            Path(out).write_text,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    review_dir = os.environ.get("M8F_REVIEW_DIR")
    if review_dir:
        await asyncio.to_thread(_export_review_media, first, tmp_path / "run-1", Path(review_dir))
    shutil.rmtree(tmp_path / "run-1", ignore_errors=True)
    shutil.rmtree(tmp_path / "run-2", ignore_errors=True)
