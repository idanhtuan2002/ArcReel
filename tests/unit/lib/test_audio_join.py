"""Speech clips joined with a fixed silence (ADR-0166)."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from lib.audio_join import join_with_gaps

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def _tone(path: Path, seconds: float, rate: int) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=300:sample_rate={rate}",
         "-t", str(seconds), str(path)],
        check=True,
    )  # fmt: skip
    return path


def _seconds(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return float(out)


def test_lines_are_joined_in_order_with_gaps(tmp_path: Path):
    parts = [
        _tone(tmp_path / "a.wav", 1.0, 24000),
        _tone(tmp_path / "b.mp3", 0.5, 44100),
        _tone(tmp_path / "c.wav", 0.7, 16000),
    ]
    out = tmp_path / "joined.wav"
    asyncio.run(join_with_gaps(parts, out, gap_seconds=0.25))
    assert abs(_seconds(out) - (1.0 + 0.5 + 0.7 + 2 * 0.25)) < 0.08


def test_a_single_line_is_copied(tmp_path: Path):
    out = tmp_path / "one.wav"
    asyncio.run(join_with_gaps([_tone(tmp_path / "a.wav", 0.6, 22050)], out, gap_seconds=0.25))
    assert abs(_seconds(out) - 0.6) < 0.05
