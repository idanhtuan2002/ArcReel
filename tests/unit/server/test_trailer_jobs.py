"""Trailer jobs cut a succeeded run's verified finals (ADR-0164)."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.trailer import TrailerPlan
from r2.contracts.automation import RunStatus
from server.services import trailer_jobs
from server.services.trailer_jobs import TrailerJobs, TrailerRefused


class _Projects:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_project_path(self, name: str) -> Path:
        return self.root / name

    def load_project(self, name: str) -> dict:
        del name
        return {"title": "Chuyến đò cuối", "episodes": [{"episode": 1}]}


def _jobs(tmp_path: Path, monkeypatch, status: RunStatus) -> TrailerJobs:
    run = SimpleNamespace(status=status, completed_targets=[])

    class _Repo:
        def __init__(self, _session) -> None:
            pass

        async def get(self, **_kw):
            return run

    @asynccontextmanager
    async def sessions():
        yield None

    monkeypatch.setattr(trailer_jobs, "ProductionRunRepository", _Repo)
    return TrailerJobs(_Projects(tmp_path), sessions)


def test_a_run_that_has_not_succeeded_is_refused(tmp_path: Path, monkeypatch):
    jobs = _jobs(tmp_path, monkeypatch, RunStatus.RUNNING)
    with pytest.raises(TrailerRefused, match="RUN_NOT_SUCCEEDED"):
        asyncio.run(jobs.start(user_id="u", project_name="p", run_id="r"))


def test_a_job_writes_the_trailer_and_its_cut_list(tmp_path: Path, monkeypatch):
    jobs = _jobs(tmp_path, monkeypatch, RunStatus.SUCCEEDED)
    final = tmp_path / "p" / "episode_1.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"x")
    final.with_suffix(".srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nMột.\n", encoding="utf-8")
    plan = TrailerPlan(hook="E1L1", beats=["E1L1", "E1L1"], end_card="Xem")
    seen: dict = {}

    async def fake_probe(_path: Path):
        return 576, 1024, 24.0, 20.0

    async def fake_create(*_args):
        return SimpleNamespace()

    async def fake_plan(title, episodes, _generate):
        seen["title"], seen["episodes"] = title, episodes
        return plan

    async def fake_cut(_plan, _episodes, *, title, output):
        del title
        output.write_bytes(b"mp4")
        return [{"line": "E1L1"}]

    monkeypatch.setattr(trailer_jobs, "run_episodes", lambda _projects, _run: [(1, final)])
    monkeypatch.setattr(trailer_jobs, "probe", fake_probe)
    monkeypatch.setattr(trailer_jobs.TextGenerator, "create", fake_create)
    monkeypatch.setattr(trailer_jobs, "plan_trailer", fake_plan)
    monkeypatch.setattr(trailer_jobs, "cut_trailer", fake_cut)

    async def scenario() -> dict | None:
        await jobs.start(user_id="u", project_name="p", run_id="r")
        await asyncio.gather(*list(jobs._tasks))
        return jobs.status("u", "p", "r")

    job = asyncio.run(scenario())
    assert job is not None
    assert job["state"] == "done", job
    assert seen["title"] == "Chuyến đò cuối"
    assert seen["episodes"][0].has_end_card is False
    work = tmp_path / "p" / "output" / "trailer" / "r"
    assert (work / "trailer.mp4").read_bytes() == b"mp4"
    assert json.loads((work / "trailer.json").read_text(encoding="utf-8"))["cuts"] == [{"line": "E1L1"}]
    after_restart = TrailerJobs(_Projects(tmp_path), None).status("u", "p", "r")
    assert after_restart is not None
    assert (after_restart["state"], after_restart["duration"]) == ("done", 20.0)
