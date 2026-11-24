from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from assembly import finish


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_a_composed_episode_gets_captions_and_loudness(tmp_path: Path) -> None:
    film = tmp_path / "ep.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:s=360x640:r=30:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=300:duration=3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(film),
        ],
        check=True,
    )
    beats = [{"narration_segment": "Xin chào các bạn.", "audio_duration_seconds": 3.0}]
    result = finish.finish_episode(film, beats, tmp_path / "out", music=None, episode=1)
    assert Path(result["final"]).is_file()
    assert "Xin chào các bạn." in Path(result["subtitles"]).read_text(encoding="utf-8")
    assert abs(result["loudness"]["output_lufs"] - (-14.0)) < 1.5
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["screen_text"]["captions"] is True
