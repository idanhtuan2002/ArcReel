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


def test_a_wordless_video_gets_its_story_from_its_frames(tmp_path: Path) -> None:
    frames = []
    for i in range(3):
        frame = tmp_path / f"f{i}.jpg"
        frame.write_bytes(b"jpeg")
        frames.append(frame)
    seen: list[list[dict]] = []

    def fake_call(content: list[dict]) -> str:
        seen.append(content)
        return "  Chú chó nhỏ nhìn ra biển.  "

    assert from_video.visual_story(frames, step=3.0, call=fake_call) == "Chú chó nhỏ nhìn ra biển."
    assert seen[0][0]["type"] == "text"
    assert [c["type"] for c in seen[0][1:]] == ["image_url"] * 3
