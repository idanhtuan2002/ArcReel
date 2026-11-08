"""Reviewer and launch qualification started from the run panel: host settings, recorded results, refusals."""

from __future__ import annotations

import pytest

from r2.contracts.automation import ModelRoute
from server.production_run import qualification_jobs
from server.production_run.qualification_jobs import QualificationJobs, QualificationRefused
from tests.integration.scripts.r2.test_qualify_reviewers import ROUTE, Reviewer, _corpus

PROFILE = "sha256:" + "a" * 64


class Projects:
    def __init__(self, automation: dict) -> None:
        self.project = {"automation": automation}

    def load_project(self, name: str) -> dict:
        return self.project


def _routes(*roles: str):
    async def routes(project_name: str) -> list[ModelRoute]:
        return [ROUTE.model_copy(update={"role": role, "model_identity": f"vl-{role}"}) for role in roles] + [
            ROUTE.model_copy(update={"role": "writer", "model_identity": "writer"})
        ]

    return routes


def _jobs(sessions, reviewer: Reviewer, *roles: str) -> QualificationJobs:
    projects = Projects({"profile_digest": PROFILE, "launch_profile_id": "fiction_narration_vi_v1"})
    return QualificationJobs(sessions, projects, evaluator=reviewer, routes=_routes(*roles))


async def test_both_reviewers_are_qualified_on_the_host_corpus_and_recorded(session_factory, tmp_path, monkeypatch):
    monkeypatch.setenv(qualification_jobs.CORPUS_ENV, str(_corpus(tmp_path)))
    monkeypatch.setenv(qualification_jobs.RECEIPTS_ENV, str(tmp_path / "receipts"))
    jobs = _jobs(session_factory, Reviewer(), "reviewer_a", "reviewer_b")

    started = await jobs.start_reviewers(user_id="default", project_name="p")
    await jobs.wait()
    status = await jobs.status(user_id="default", project_name="p")

    assert [r["role"] for r in started["reviewers"]] == ["reviewer_a", "reviewer_b"]
    assert [(r["qualified"], r["job"]["state"], r["job"]["done"]) for r in status["reviewers"]] == [
        (True, "done", 40),
        (True, "done", 40),
    ]
    assert (tmp_path / "receipts" / "reviewer_a").is_dir()


async def test_a_reviewer_that_accepts_a_defect_is_not_recorded(session_factory, tmp_path, monkeypatch):
    monkeypatch.setenv(qualification_jobs.CORPUS_ENV, str(_corpus(tmp_path)))
    monkeypatch.setenv(qualification_jobs.RECEIPTS_ENV, str(tmp_path / "receipts"))
    missing, sound = Reviewer(miss_defects=1), Reviewer()

    class OneMisses:
        """reviewer_a accepts one defect; reviewer_b sees every defect, whichever job runs first."""

        async def assess(self, *, route, evidence):
            return await (missing if route.role == "reviewer_a" else sound).assess(route=route, evidence=evidence)

    jobs = QualificationJobs(
        session_factory,
        Projects({"profile_digest": PROFILE, "launch_profile_id": "fiction_narration_vi_v1"}),
        evaluator=OneMisses(),
        routes=_routes("reviewer_a", "reviewer_b"),
    )

    await jobs.start_reviewers(user_id="default", project_name="p")
    await jobs.wait()
    status = await jobs.status(user_id="default", project_name="p")

    assert [(r["qualified"], r["job"]["qualified"]) for r in status["reviewers"]] == [(False, False), (True, True)]


async def test_without_host_corpus_or_evidence_nothing_starts(session_factory, monkeypatch):
    monkeypatch.delenv(qualification_jobs.CORPUS_ENV, raising=False)
    monkeypatch.delenv(qualification_jobs.EVIDENCE_ENV, raising=False)
    jobs = _jobs(session_factory, Reviewer(), "reviewer_a", "reviewer_b")

    with pytest.raises(QualificationRefused, match="QUALIFICATION_CORPUS_NOT_CONFIGURED"):
        await jobs.start_reviewers(user_id="default", project_name="p")
    with pytest.raises(QualificationRefused, match="LAUNCH_EVIDENCE_NOT_CONFIGURED"):
        await jobs.record_launch(user_id="default", project_name="p")
    assert (await jobs.status(user_id="default", project_name="p"))["corpus_configured"] is False
