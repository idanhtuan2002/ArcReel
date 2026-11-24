"""A local video's transcript becomes the story file and origin record (ADR-0161 unit reused)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from assembly.connector import from_video


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_a_local_file_becomes_a_story_with_its_origin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(clip)], check=True
    )

    async def fake_whisper(chunk: Path) -> dict:
        return {"language": "en", "segments": [{"start": 0.0, "end": 1.5, "text": "An old watchmaker waits."}]}

    monkeypatch.setattr(from_video, "_whisper", fake_whisper)
    story, origin = from_video.story_from_video(str(clip), tmp_path / "work")
    assert story.read_text(encoding="utf-8") == "clip\n\nAn old watchmaker waits.\n"
    assert origin["language"] == "en"
    assert origin["use"].startswith("transformed variant only")
    assert json.loads((tmp_path / "work" / "origin.json").read_text(encoding="utf-8"))["segments"] == 1
