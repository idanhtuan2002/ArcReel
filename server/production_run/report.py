"""What an automatic run decided on its own, for the run panel: reviewer verdicts and accepted story exceptions.

Read-only. Reviews are the ones QUALITY stored beside each target's final for the run's current generation; story
exceptions are the findings of the offered manuscript's quality record that the automatic commit accepted as they
are. A stage the run has not reached, or a project folder that is gone, contributes nothing.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.production_runs import ProductionRunRepository
from lib.project_manager import ProjectManager
from r2.automation.assessment import ModelAssessment
from r2.contracts.automation import RunSnapshot, RunStage
from server.production_run.render_adapter import render_dir
from server.story_authoring.artifacts import StoryBlobStore
from server.story_authoring.commit import load_offered_manifest
from server.story_authoring.runtime import RunStateStore

REVIEWER_ROLES = ("reviewer_a", "reviewer_b")


def _reviews(projects: ProjectManager, run: RunSnapshot) -> list[dict[str, Any]]:
    project = projects.get_project_path(run.project_name)
    episodes = []
    for target in run.targets:
        episode = int(target.split(":")[1])
        folder = project / render_dir(run, episode) / "quality"
        reviews = []
        for role in REVIEWER_ROLES:
            # A re-reviewed final leaves the earlier subject's reviews beside it; the newest one is current.
            found = sorted(folder.glob(f"*.{role}.json"), key=lambda path: path.stat().st_mtime)
            if not found:
                continue
            review = ModelAssessment.model_validate_json(found[-1].read_text(encoding="utf-8"))
            reviews.append(
                {
                    "role": role,
                    "model_identity": review.model_identity,
                    "outcome": review.outcome,
                    "accepted": review.outcome == "COMPLETED" and review.accepts(),
                    "scores": dict(review.scores),
                    "findings": [{"code": f.code, "severity": f.severity, "detail": f.detail} for f in review.findings],
                }
            )
        if reviews:
            episodes.append({"target": target, "reviews": reviews})
    return episodes


async def _story_exceptions(
    sessions: async_sessionmaker[AsyncSession], projects: ProjectManager, run: RunSnapshot
) -> list[dict[str, Any]]:
    async with sessions() as session:
        receipt = await ProductionRunRepository(session).stage_receipt(run=run, stage=RunStage.STORY)
    if receipt is None or receipt.task_id is None:
        return []
    state = await RunStateStore(sessions, task_id=str(receipt.task_id)).load()
    if state.commit is None:
        return []
    blobs = StoryBlobStore(projects.get_project_path(run.project_name))
    manifest = load_offered_manifest(blobs, state)
    if manifest.quality_record_digest is None or not manifest.exceptions_offered:
        return []
    record = json.loads(blobs.read_exact(manifest.quality_record_digest))
    offered = set(manifest.exceptions_offered)
    return [
        {key: finding.get(key, "") for key in ("code", "severity", "node_id", "message", "quote")}
        for finding in record.get("findings", [])
        if finding.get("id") in offered
    ]


async def run_report(
    sessions: async_sessionmaker[AsyncSession], projects: ProjectManager, run: RunSnapshot
) -> dict[str, Any]:
    try:
        projects.get_project_path(run.project_name)
    except FileNotFoundError:
        # The project folder is gone; there is nothing stored to read.
        return {"run_id": run.run_id, "quality": [], "story_exceptions": []}
    return {
        "run_id": run.run_id,
        "quality": _reviews(projects, run),
        "story_exceptions": await _story_exceptions(sessions, projects, run),
    }


__all__ = ["run_report"]
