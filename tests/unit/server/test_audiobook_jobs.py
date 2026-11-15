"""Audiobook jobs: a committed manuscript spoken with the project's narration route (ADR-0159)."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services import audiobook_jobs
from server.services.audiobook_jobs import AudiobookJobs, AudiobookRefused

MANUSCRIPT = "# Đò\n\n## Chương 1\n\nÔng Bảy chèo đò. Trời tối.\n\n## Chương 2\n\nCây cầu sáng đèn.\n".encode()


class _Projects:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_project_path(self, name: str) -> Path:
        return self.root / name

    def load_project(self, name: str) -> dict:
        return {"title": name}


class _Backend:
    model = "vieneu-tts-v3-turbo"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def synthesize(self, request):
        self.calls.append((request.text, request.voice))
        await asyncio.to_thread(
            subprocess.run,
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=330:sample_rate=24000",
                "-t",
                "0.3",
                str(request.output_path),
            ],
            check=True,
        )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_a_job_speaks_the_story_with_the_project_voice_and_offers_the_files(tmp_path: Path, monkeypatch):
    backend = _Backend()

    class _Resolver:
        async def resolve_audio_backend(self, project, payload):
            del project, payload
            return SimpleNamespace(provider_id="custom-2", model_id="vieneu-tts-v3-turbo")

        async def resolve_narration_voice(self, project):
            del project
            return "nova"

    class _Config:
        def __init__(self, sessions) -> None:
            del sessions

        @asynccontextmanager
        async def session(self):
            yield _Resolver()

    async def assemble(**_kwargs):
        return backend

    monkeypatch.setattr(audiobook_jobs, "ConfigResolver", _Config)
    monkeypatch.setattr(audiobook_jobs, "assemble_backend", assemble)
    monkeypatch.setattr(audiobook_jobs, "music_service_from_env", lambda: None)
    jobs = AudiobookJobs(_Projects(tmp_path), sessions=None)

    async def scenario() -> list[dict]:
        await jobs.start(user_id="u", project_name="p", run_id="story-1", preset="sleep", manuscript=MANUSCRIPT)
        await asyncio.gather(*list(jobs._tasks))
        return jobs.status("u", "p", "story-1")

    [job] = asyncio.run(scenario())
    assert job["state"] == "done", job["error"]
    assert job["preset"] == "sleep"
    assert {"m4b", "mp3", "chapters"} <= set(job["files"])
    assert ("Ông Bảy chèo đò. Trời tối.", "nova") in backend.calls
    assert (tmp_path / "p" / "output" / "audiobook" / "story-1-sleep" / "audiobook.m4b").is_file()

    fresh = AudiobookJobs(_Projects(tmp_path), sessions=None)
    assert [j["state"] for j in fresh.status("u", "p", "story-1")] == ["done"]


def test_an_unknown_preset_or_an_empty_manuscript_is_refused(tmp_path: Path):
    jobs = AudiobookJobs(_Projects(tmp_path), sessions=None)
    with pytest.raises(AudiobookRefused, match="UNKNOWN_PRESET"):
        asyncio.run(jobs.start(user_id="u", project_name="p", run_id="r", preset="loud", manuscript=MANUSCRIPT))
    with pytest.raises(AudiobookRefused, match="EMPTY_MANUSCRIPT"):
        asyncio.run(jobs.start(user_id="u", project_name="p", run_id="r", preset="standard", manuscript=b"# T\n"))
