"""Media probes and the launch record started from the run panel: host settings and refusals; reviewers have no
qualification job (ADR-0169)."""

from __future__ import annotations

import pytest

from r2.contracts.automation import ModelRoute
from server.production_run import qualification_jobs
from server.production_run.qualification_jobs import QualificationJobs, QualificationRefused

PROFILE = "sha256:" + "a" * 64
ROUTE = ModelRoute(
    role="reviewer_a",
    provider_id="custom-9",
    model_id="vl",
    model_identity="vl-7b",
    config_digest="sha256:" + "1" * 64,
    local=True,
    paid=False,
    currency="USD",
    max_cost_per_call=None,
)


class Projects:
    def __init__(self, automation: dict) -> None:
        self.project = {"automation": automation}

    def load_project(self, name: str) -> dict:
        return self.project


async def _routes(project_name: str) -> list[ModelRoute]:
    return [ROUTE, ROUTE.model_copy(update={"role": "reviewer_b", "model_identity": "vl-b"})]


def _jobs(sessions) -> QualificationJobs:
    projects = Projects({"profile_digest": PROFILE, "launch_profile_id": "fiction_narration_vi_v1"})
    return QualificationJobs(sessions, projects, routes=_routes)


async def test_status_reports_the_launch_and_host_settings_without_reviewer_jobs(
    session_factory, tmp_path, monkeypatch
):
    monkeypatch.setenv(qualification_jobs.RECEIPTS_ENV, str(tmp_path / "receipts"))
    monkeypatch.setenv(qualification_jobs.EVIDENCE_ENV, str(tmp_path / "evidence.json"))

    status = await _jobs(session_factory).status(user_id="default", project_name="p")

    assert status == {"receipts_configured": True, "evidence_configured": True, "launch_recorded": False, "media": []}


async def test_without_host_receipts_or_evidence_nothing_starts(session_factory, monkeypatch):
    monkeypatch.delenv(qualification_jobs.RECEIPTS_ENV, raising=False)
    monkeypatch.delenv(qualification_jobs.EVIDENCE_ENV, raising=False)
    jobs = _jobs(session_factory)

    with pytest.raises(QualificationRefused, match="PROBE_RECEIPTS_NOT_CONFIGURED"):
        await jobs.start_media_probes(user_id="default", project_name="p")
    with pytest.raises(QualificationRefused, match="LAUNCH_EVIDENCE_NOT_CONFIGURED"):
        await jobs.record_launch(user_id="default", project_name="p")
    status = await jobs.status(user_id="default", project_name="p")
    assert (status["receipts_configured"], status["evidence_configured"]) == (False, False)
