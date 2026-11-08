"""The run report reads the reviews QUALITY stored beside each target's final for the current generation."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from r2.automation.assessment import AssessmentFinding, ModelAssessment
from r2.contracts.automation import RunSnapshot, RunStage
from server.production_run.render_adapter import render_dir
from server.production_run.report import _reviews, _story_counts
from server.story_authoring.artifacts import StoryBlobStore
from server.story_authoring.runtime import NodeHead, RevisionOutcome, RevisionRecord, StoryLimits, new_run_state
from tests.unit.server.production_run.test_controller import _policy

DIGEST = "sha256:" + "1" * 64


class Projects:
    def __init__(self, root) -> None:
        self.root = root

    def get_project_path(self, name: str):
        return self.root / name


def _run(generation: int = 1) -> RunSnapshot:
    return RunSnapshot.model_validate(
        {
            "user_id": "u1",
            "project_name": "film",
            "run_id": "run-1",
            "policy": _policy(max_target_episodes=2),
            "input_digest": DIGEST,
            "status": "RUNNING",
            "stage": RunStage.QUALITY,
            "generation": generation,
            "targets": ("episode:1", "episode:2"),
            "created_at": datetime(2026, 11, 4, tzinfo=UTC),
        }
    )


def _review(identity: str, *, visual: int, findings=()) -> ModelAssessment:
    return ModelAssessment.model_validate(
        {
            "reviewer_route_digest": DIGEST,
            "model_identity": identity,
            "prompt_digest": DIGEST,
            "subject_digest": DIGEST,
            "evidence_digest": DIGEST,
            "outcome": "COMPLETED",
            "language": "vi",
            "scores": {"story": 5, "visual": visual, "audio": 5, "continuity": 5, "pacing": 5},
            "findings": list(findings),
        }
    )


def _store(tmp_path, run: RunSnapshot, episode: int, name: str, review: ModelAssessment, mtime: int) -> None:
    folder = tmp_path / "film" / render_dir(run, episode) / "quality"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(review.model_dump_json(), encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_each_target_shows_its_newest_review_per_reviewer(tmp_path):
    run = _run()
    finding = AssessmentFinding(code="AUDIO_DRIFT", severity="MAJOR", unit_key="episode:1", detail="lệch tiếng")
    _store(tmp_path, run, 1, "aaaa.reviewer_a.json", _review("model-a", visual=2), 100)
    _store(tmp_path, run, 1, "bbbb.reviewer_a.json", _review("model-a", visual=4), 200)
    _store(tmp_path, run, 1, "bbbb.reviewer_b.json", _review("model-b", visual=3, findings=[finding]), 200)

    [episode] = _reviews(Projects(tmp_path), run)

    assert episode["target"] == "episode:1"
    first, second = episode["reviews"]
    assert (first["role"], first["scores"]["visual"], first["accepted"]) == ("reviewer_a", 4, True)
    assert (second["role"], second["accepted"]) == ("reviewer_b", False)
    assert second["findings"] == [{"code": "AUDIO_DRIFT", "severity": "MAJOR", "detail": "lệch tiếng"}]


def test_reviews_of_an_earlier_generation_are_not_current(tmp_path):
    _store(tmp_path, _run(1), 1, "aaaa.reviewer_a.json", _review("model-a", visual=4), 100)

    assert _reviews(Projects(tmp_path), _run(2)) == []


def _story_state(blobs, *, plans: dict[int, int], drafted: int, reviews: tuple[str, ...] = ()):
    nodes, revisions = {}, {}
    now = datetime(2026, 11, 8, tzinfo=UTC)

    def head(node: str, data: bytes) -> None:
        digest = blobs.put(data)
        revision = f"rev-{node}"
        revisions[revision] = RevisionRecord(
            revision_id=revision,
            node_id=node,
            digest=digest,
            fingerprint="f",
            attempt_id=None,
            outcome=RevisionOutcome.HEAD,
            created_at=now,
        )
        nodes[node] = NodeHead(node_id=node, head_revision_id=revision)

    for node in ("seed", "story_bible", "style_bible", "outline"):
        head(node, node.encode())
    for chapter, scenes in plans.items():
        head(f"chapter_plan[{chapter}]", json.dumps({"scenes": [{}] * scenes}).encode())
    for index in range(drafted):
        head(f"scene_draft[1,{index + 1}]", f"scene {index}".encode())
    for node in reviews:
        head(node, node.encode())
    state = new_run_state(
        run_id="story-1",
        limits=StoryLimits(input_tokens_max=10**6, output_tokens_max=10**6, wall_clock_max_seconds=10**5),
        now=now,
    )
    return state.model_copy(update={"nodes": nodes, "revisions": revisions})


def test_story_progress_counts_scenes_drafted_of_the_planned_total(tmp_path):
    blobs = StoryBlobStore(tmp_path)
    state = _story_state(blobs, plans={1: 3, 2: 4, 3: 3}, drafted=2, reviews=("chapter_review[1]",))

    counts = _story_counts(state, blobs)

    assert counts["planning_done"] == counts["planning_total"] == 7
    assert (counts["scenes_drafted"], counts["scenes_planned"]) == (2, 10)
    assert (counts["reviews_done"], counts["reviews_total"]) == (1, 5)
    assert counts["phase"] == "RUNNING"
    assert counts["generate_calls"] == 0
    assert counts["generate_calls_max"] == state.limits.generate_calls_max


def test_story_progress_leaves_the_scene_total_unknown_until_every_chapter_is_planned(tmp_path):
    blobs = StoryBlobStore(tmp_path)

    counts = _story_counts(_story_state(blobs, plans={1: 3}, drafted=0), blobs)

    assert (counts["planning_done"], counts["scenes_planned"], counts["scenes_drafted"]) == (5, None, 0)
