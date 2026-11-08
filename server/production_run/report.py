"""What an automatic run decided on its own, for the run panel: reviewer verdicts and accepted story exceptions.

Read-only. Reviews are the ones QUALITY stored beside each target's final for the run's current generation; story
exceptions are the findings of the offered manuscript's quality record that the automatic commit accepted as they
are. A stage the run has not reached, or a project folder that is gone, contributes nothing.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.production_runs import ProductionRunRepository
from lib.db.repositories.task_repo import StoryRunStateConflict
from lib.project_manager import ProjectManager
from r2.automation.assessment import ModelAssessment
from r2.contracts.automation import RunSnapshot, RunStage
from server.production_run.owner_tasks import attempt_window_tasks, step_tasks
from server.production_run.render_adapter import render_dir
from server.story_authoring.artifacts import BlobCorrupt, BlobMissing, StoryBlobStore
from server.story_authoring.commit import load_offered_manifest
from server.story_authoring.driver import CHAPTERS
from server.story_authoring.pipeline import PLANNING_NODES, chapter_plan, chapter_review, node_kind
from server.story_authoring.runtime import RunState, RunStateStore

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


def verified_final(projects: ProjectManager, run: RunSnapshot, episode: int) -> Path | None:
    """The completed target's final while its bytes are still the verified ones; otherwise ``None``."""
    output = next((o for o in run.completed_targets if o.target == f"episode:{episode}"), None)
    if output is None:
        return None
    final = projects.get_project_path(run.project_name) / render_dir(run, episode) / f"episode_{episode}.mp4"
    if not final.is_file() or "sha256:" + hashlib.sha256(final.read_bytes()).hexdigest() != output.final_digest:
        return None
    return final


def _previews(projects: ProjectManager, run: RunSnapshot) -> list[dict[str, str]]:
    """The completed targets whose verified final can be previewed (served only to the authenticated owner)."""
    return [
        {"target": output.target}
        for output in run.completed_targets
        if verified_final(projects, run, int(output.target.split(":")[1])) is not None
    ]


def _story_counts(state: RunState, blobs: StoryBlobStore) -> dict[str, Any]:
    """How far the story run has written: planning nodes, scenes drafted of the planned total, reviews, calls.

    The planned scene total is known once every chapter plan has a head; until then it is ``None``.
    """
    heads = {node: head for node, head in state.nodes.items() if head.head_revision_id is not None}
    plans = [chapter_plan(c) for c in range(1, CHAPTERS + 1)]
    scenes_planned: int | None = 0
    for plan in plans:
        revision = state.revisions.get(heads[plan].head_revision_id or "") if plan in heads else None
        if revision is None or scenes_planned is None:
            scenes_planned = None
            continue
        try:
            scenes_planned += len(json.loads(blobs.read_exact(revision.digest)).get("scenes") or ())
        except (OSError, ValueError, BlobMissing, BlobCorrupt):
            scenes_planned = None
    planning = (*PLANNING_NODES, *plans)
    reviews = (*(chapter_review(c) for c in range(1, CHAPTERS + 1)), "manuscript_review", "packaging")
    return {
        "phase": state.phase.value,
        "planning_done": sum(1 for node in planning if node in heads),
        "planning_total": len(planning),
        "scenes_drafted": sum(1 for node in heads if node_kind(node) == "scene_draft"),
        "scenes_planned": scenes_planned,
        "reviews_done": sum(1 for node in reviews if node in heads),
        "reviews_total": len(reviews),
        "generate_calls": state.usage.generate_calls,
        "generate_calls_max": state.limits.generate_calls_max,
    }


async def _story_progress(
    sessions: async_sessionmaker[AsyncSession], projects: ProjectManager, run: RunSnapshot
) -> dict[str, Any] | None:
    async with sessions() as session:
        receipt = await ProductionRunRepository(session).stage_receipt(run=run, stage=RunStage.STORY)
    if receipt is None or receipt.task_id is None:
        return None
    try:
        state = await RunStateStore(sessions, task_id=str(receipt.task_id)).load()
    except StoryRunStateConflict:
        return None
    return _story_counts(state, StoryBlobStore(projects.get_project_path(run.project_name)))


async def run_progress(
    sessions: async_sessionmaker[AsyncSession], run: RunSnapshot, projects: ProjectManager | None = None
) -> dict[str, Any]:
    """The run's timeline (start and each stage's pass time) and its current stage's progress: the owner tasks by
    status, like a queue's running/queued counts, and inside STORY how far the story has been written."""
    async with sessions() as session:
        repository = ProductionRunRepository(session)
        finished = await repository.stage_finish_times(run=run)
        current = await repository.current_step(run=run)
    progress: dict[str, Any] = {
        "run_id": run.run_id,
        "stage": run.stage.value,
        "started_at": run.created_at.isoformat(),
        "stages": [
            {"stage": stage.value, "finished_at": finished[stage.value].isoformat()}
            for stage in RunStage
            if stage.value in finished
        ],
        "tasks": {},
    }
    if current is not None:
        intent, _ = current
        tasks = await step_tasks(sessions, intent) or await attempt_window_tasks(sessions, intent)
        progress["tasks"] = dict(Counter(task.status for task in tasks))
    if run.stage is RunStage.STORY and projects is not None:
        progress["story"] = await _story_progress(sessions, projects, run)
    return progress


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
        return {"run_id": run.run_id, "quality": [], "story_exceptions": [], "previews": []}
    return {
        "run_id": run.run_id,
        "quality": _reviews(projects, run),
        "previews": _previews(projects, run),
        "story_exceptions": await _story_exceptions(sessions, projects, run),
    }


__all__ = ["run_progress", "run_report", "verified_final"]
