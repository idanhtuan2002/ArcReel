"""Documentary jobs store the research and the narration source (ADR-0162)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from lib.documentary import Documentary
from r2.contracts.factual import ClaimLedger, ResearchPack
from server.services import documentary_jobs
from server.services.documentary_jobs import DocumentaryJobs


class _Projects:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_project_path(self, name: str) -> Path:
        return self.root / name


def test_a_job_writes_the_research_and_a_narration_source(tmp_path: Path, monkeypatch):
    pack = ResearchPack(
        id="r",
        version=1,
        topic="t",
        scope="s",
        source_refs=["S1"],
        evidence_refs=["E1"],
        synthesis="h",
        uncertainties=[],
        open_questions=[],
        provenance={},
    )
    doc = Documentary(
        title="Cây cầu trăm tuổi",
        manuscript="# Cây cầu trăm tuổi\n\nVì sao?\n\n## Ra đời\n\nNăm 1898 công trường mở.\n",
        citations="# sources\n",
        research_pack=pack,
        ledger=ClaimLedger(id="l", version=1, research_pack_ref="r", claims=[]),
        sources=[],
        evidence=[],
    )

    class _Generator:
        async def generate(self, request, project_name, *, user_id):
            raise AssertionError("not called")

    async def create(_task, _project):
        return _Generator()

    async def make(topic, *, language, fetch, generate):
        del topic, language, fetch, generate
        return doc

    monkeypatch.setattr(documentary_jobs.TextGenerator, "create", create)
    monkeypatch.setattr(documentary_jobs, "make_documentary", make)
    jobs = DocumentaryJobs(_Projects(tmp_path))

    async def scenario() -> list[dict]:
        await jobs.start(project_name="p", topic="cầu Long Biên", language="vi", user_id="u")
        await asyncio.gather(*list(jobs._tasks))
        return jobs.status("p")

    [job] = asyncio.run(scenario())
    assert job["state"] == "done", job["error"]
    assert job["source"] == "source/cay-cau-tram-tuoi.txt"
    narration = (tmp_path / "p" / "source" / "cay-cau-tram-tuoi.txt").read_text(encoding="utf-8")
    assert narration.startswith("Cây cầu trăm tuổi\n\nVì sao?")
    assert "##" not in narration
    folder = tmp_path / "p" / "research" / "cay-cau-tram-tuoi"
    assert json.loads((folder / "research_pack.json").read_text(encoding="utf-8"))["topic"] == "t"
    assert (folder / "manuscript.md").read_text(encoding="utf-8").startswith("# Cây cầu trăm tuổi")
