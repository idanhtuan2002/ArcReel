"""Shared real-media assertion helpers for M3's real-media closure tests
(Tasks 3 and 5) -- both the Remotion-engine-level tests and the end-to-end
corpus tests need the same "is this frame real content, not a solid color"
check."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image


def frame_pixel_stddev(video_path: Path, tmp_path: Path, *, frame_index: int = 30) -> float:
    """Extract one frame and return the standard deviation of its pixel
    values -- a real, content-bearing frame (text, an image) has meaningfully
    non-zero variance; a solid-color frame's variance is ~0 (H.264 lossy
    artifacts aside)."""
    frame_path = tmp_path / "frame.png"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"select=eq(n\\,{frame_index})",
            "-vframes",
            "1",
            "-update",
            "1",
            str(frame_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    image = Image.open(frame_path).convert("L")
    pixels = np.asarray(image, dtype=np.float64)
    return float(pixels.std())
