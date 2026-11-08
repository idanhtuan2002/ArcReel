"""A storyboard or narration line fails its deterministic check only for the defect each rule names."""

from __future__ import annotations

import random
import shutil
import subprocess

import pytest
from PIL import Image

from server.production_run.unit_checks import narration_problem, storyboard_problem


def _picture(path, size=(576, 1024), *, fill=None):
    if fill is not None:
        Image.new("RGB", size, fill).save(path)
        return path
    rng = random.Random(7)
    image = Image.new("RGB", size)
    image.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(size[0] * size[1])])
    image.save(path)
    return path


def test_a_detailed_portrait_storyboard_passes(tmp_path):
    assert storyboard_problem(_picture(tmp_path / "ok.png"), portrait=True) is None


@pytest.mark.parametrize(
    ("make", "problem"),
    [
        (lambda p: _picture(p, fill=(0, 0, 0)), "IMAGE_BLANK"),
        (lambda p: _picture(p, fill=(255, 255, 255)), "IMAGE_BLANK"),
        (lambda p: _picture(p, fill=(120, 120, 120)), "IMAGE_BLANK"),
        (lambda p: _picture(p, size=(1024, 576)), "IMAGE_WRONG_ORIENTATION"),
        (lambda p: _picture(p, size=(120, 200)), "IMAGE_TOO_SMALL"),
        (lambda p: (p.write_bytes(b"not an image"), p)[1], "IMAGE_UNREADABLE"),
    ],
)
def test_a_defective_storyboard_names_its_defect(tmp_path, make, problem):
    assert storyboard_problem(make(tmp_path / "bad.png"), portrait=True) == problem


def test_a_landscape_project_accepts_landscape_storyboards(tmp_path):
    assert storyboard_problem(_picture(tmp_path / "wide.png", size=(1024, 576)), portrait=False) is None


FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is required")


def _audio(path, source: str):
    subprocess.run(
        [FFMPEG or "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-filter_complex", source, str(path)],
        check=True,
    )
    return path


@needs_ffmpeg
def test_an_audible_narration_line_passes(tmp_path):
    assert narration_problem(_audio(tmp_path / "ok.wav", "sine=frequency=220:duration=3")) is None


@needs_ffmpeg
@pytest.mark.parametrize(
    ("source", "problem"),
    [
        ("anullsrc=r=24000:cl=mono,atrim=duration=3", "AUDIO_SILENT"),
        ("sine=frequency=220:duration=0.2", "AUDIO_TOO_SHORT"),
        (
            "sine=frequency=220:duration=1[a];anullsrc=r=44100:cl=mono,atrim=duration=3[s];"
            "sine=frequency=220:duration=1[b];[a][s][b]concat=n=3:v=0:a=1",
            "AUDIO_LONG_SILENCE",
        ),
    ],
)
def test_a_defective_narration_line_names_its_defect(tmp_path, source, problem):
    assert narration_problem(_audio(tmp_path / "bad.wav", source)) == problem


def test_a_missing_narration_file_is_unreadable(tmp_path):
    assert narration_problem(tmp_path / "missing.wav") == "AUDIO_UNREADABLE"
