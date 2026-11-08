"""Deterministic checks of one automatic media unit: a storyboard image or a narration line.

No model judges here. A storyboard must decode, have the project's orientation and a usable size, and not be blank;
a narration line must decode, last long enough, be audible and hold no long silence. Each check returns a problem
code or ``None``; the MEDIA owner regenerates a failing unit a bounded number of times (ADR-0112).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from PIL import Image, ImageStat, UnidentifiedImageError

MIN_SHORT_SIDE = 256
MIN_MEAN_LUMA = 8.0
MAX_MEAN_LUMA = 247.0
MIN_LUMA_STDDEV = 6.0
MIN_NARRATION_SECONDS = 0.5
MIN_MEAN_VOLUME_DB = -50.0
SILENCE_THRESHOLD_DB = -40
MAX_SILENCE_SECONDS = 2.0

_MEAN_VOLUME = re.compile(r"mean_volume:\s*(-?[0-9.]+|-inf) dB")
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_SILENCE = re.compile(r"silence_duration:\s*([0-9.]+)")


def storyboard_problem(path: Path, *, portrait: bool) -> str | None:
    """Why the storyboard at ``path`` is unusable, or ``None``."""
    try:
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            luma = ImageStat.Stat(image.convert("L"))
    except (OSError, UnidentifiedImageError, ValueError):
        return "IMAGE_UNREADABLE"
    if min(width, height) < MIN_SHORT_SIDE:
        return "IMAGE_TOO_SMALL"
    if width != height and (height > width) != portrait:
        return "IMAGE_WRONG_ORIENTATION"
    mean, stddev = luma.mean[0], luma.stddev[0]
    if not MIN_MEAN_LUMA <= mean <= MAX_MEAN_LUMA or stddev < MIN_LUMA_STDDEV:
        return "IMAGE_BLANK"
    return None


def narration_problem(path: Path, *, ffmpeg: str = "ffmpeg") -> str | None:
    """Why the narration line at ``path`` is unusable, or ``None``."""
    if not path.is_file():
        return "AUDIO_UNREADABLE"
    completed = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-i",
            str(path),
            "-vn",
            "-af",
            f"volumedetect,silencedetect=noise={SILENCE_THRESHOLD_DB}dB:d={MAX_SILENCE_SECONDS}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    duration = _DURATION.search(completed.stderr)
    volume = _MEAN_VOLUME.search(completed.stderr)
    if completed.returncode != 0 or duration is None or volume is None:
        return "AUDIO_UNREADABLE"
    hours, minutes, seconds = duration.groups()
    if int(hours) * 3600 + int(minutes) * 60 + float(seconds) < MIN_NARRATION_SECONDS:
        return "AUDIO_TOO_SHORT"
    if volume.group(1) == "-inf" or float(volume.group(1)) <= MIN_MEAN_VOLUME_DB:
        return "AUDIO_SILENT"
    if any(float(found) >= MAX_SILENCE_SECONDS for found in _SILENCE.findall(completed.stderr)):
        return "AUDIO_LONG_SILENCE"
    return None


__all__ = ["narration_problem", "storyboard_problem"]
