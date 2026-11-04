"""The run report reads the reviews QUALITY stored beside each target's final for the current generation."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from r2.automation.assessment import AssessmentFinding, ModelAssessment
from r2.contracts.automation import RunSnapshot, RunStage
from server.production_run.render_adapter import render_dir
from server.production_run.report import _reviews
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
