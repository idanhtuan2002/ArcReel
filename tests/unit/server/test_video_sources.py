"""Video-source jobs write the transcript as a project source with its origin (ADR-0161)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from lib.video_ingest import IngestRefused, Segment, SourceInfo, Transcript
from server.services import video_sources
from server.services.video_sources import VideoSourceJobs, slug


class _Projects:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_project_path(self, name: str) -> Path:
        return self.root / name


def test_a_title_becomes_an_ascii_slug():
    assert slug("Chuyện ông lái đò: Đêm cuối!") == "chuyen-ong-lai-do-dem-cuoi"
    assert slug("！？") == "video-source"


def test_a_job_writes_the_source_and_its_origin(tmp_path: Path, monkeypatch):
    info = SourceInfo(url="https://example.com/v/1", title="Ông lái đò", uploader="A", duration=60.0, extractor="X")

    async def route(_sessions):
        return "https://api.example.com/v1", "key", "whisper-large-v3"

    def download(url: str, work: Path):
        del url
        path = work / "source.m4a"
        path.write_bytes(b"x")
        return path, info

    async def chunks(_source: Path, work: Path):
        return [work / "chunk-000.mp3"]

    async def fake_transcribe(_chunks, _call):
        return Transcript(language="vi", segments=[Segment(0, 2, "Ông Bảy chèo đò."), Segment(5, 6, "Hết.")])

    monkeypatch.setattr(video_sources, "whisper_route", route)
    monkeypatch.setattr(video_sources, "download_audio", download)
    monkeypatch.setattr(video_sources, "audio_chunks", chunks)
    monkeypatch.setattr(video_sources, "transcribe", fake_transcribe)
    monkeypatch.setattr(video_sources, "create_openai_client", lambda **_kw: object())
    jobs = VideoSourceJobs(_Projects(tmp_path), sessions=None)

    async def scenario() -> list[dict]:
        await jobs.start(project_name="p", url="https://example.com/v/1")
        await asyncio.gather(*list(jobs._tasks))
        return jobs.status("p")

    [job] = asyncio.run(scenario())
    assert job["state"] == "done", job["error"]
    assert job["source"] == "source/ong-lai-do.txt"
    text = (tmp_path / "p" / "source" / "ong-lai-do.txt").read_text(encoding="utf-8")
    assert text.startswith("Ông lái đò\n\nÔng Bảy chèo đò.")
    origin = json.loads((tmp_path / "p" / "source_origins" / "ong-lai-do.json").read_text(encoding="utf-8"))
    assert origin["url"] == "https://example.com/v/1"


def test_a_non_http_url_is_refused(tmp_path: Path):
    jobs = VideoSourceJobs(_Projects(tmp_path), sessions=None)
    with pytest.raises(IngestRefused, match="UNSUPPORTED_URL"):
        asyncio.run(jobs.start(project_name="p", url="file:///etc/passwd"))
