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


MIN_CLIP_SECONDS = 1.0


def clip_problem(path: Path, *, portrait: bool, ffprobe: str = "ffprobe") -> str | None:
    """Why the video clip at ``path`` is unusable, or ``None``: it must decode as video of the project's orientation,
    at least the storyboard's short side, lasting at least ``MIN_CLIP_SECONDS``."""
    if not path.is_file():
        return "VIDEO_UNREADABLE"
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_packets",
            "-show_entries",
            "stream=width,height,nb_read_packets:format=duration",
            "-of",
            "default=noprint_wrappers=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    fields = dict(line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line)
    try:
        width, height = int(fields["width"]), int(fields["height"])
        duration, packets = float(fields["duration"]), int(fields["nb_read_packets"])
    except (KeyError, ValueError):
        return "VIDEO_UNREADABLE"
    if completed.returncode != 0 or packets < 1:
        return "VIDEO_UNREADABLE"
    if min(width, height) < MIN_SHORT_SIDE:
        return "VIDEO_TOO_SMALL"
    if (height >= width) != portrait:
        return "VIDEO_WRONG_ORIENTATION"
    if duration < MIN_CLIP_SECONDS:
        return "VIDEO_TOO_SHORT"
    return None


__all__ = ["clip_problem", "narration_problem", "storyboard_problem"]
