from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from server.production_run.final_checks import picture_findings, sound_findings, subtitle_findings, timing_findings

NARRATION = "Ông lão lặng lẽ thả lưới giữa dòng sông. Bỗng chiếc hộp gỗ mắc vào lưới."
SRT = (
    "1\n00:00:00,300 --> 00:00:02,000\nÔng lão lặng lẽ thả lưới giữa dòng sông.\n\n"
    "2\n00:00:02,000 --> 00:00:04,000\nBỗng chiếc hộp gỗ mắc vào lưới.\n"
)


def _codes(srt: str, narration: str = NARRATION) -> list[str]:
    return [f.code for f in subtitle_findings(srt, narration, unit_key="episode:1")]


def test_subtitles_that_say_the_vietnamese_narration_pass() -> None:
    assert _codes(SRT) == []


@pytest.mark.parametrize(
    ("srt", "expected"),
    [
        (
            SRT.replace("Ông lão lặng lẽ thả lưới giữa dòng sông.", "The old man casts his net.").replace(
                "Bỗng chiếc hộp gỗ mắc vào lưới.", "A wooden box is caught."
            ),
            {"CHECK_SUBTITLES_NOT_VIETNAMESE", "CHECK_SUBTITLES_NOT_NARRATION"},
        ),
        (SRT.encode("utf-8").decode("latin-1"), {"CHECK_SUBTITLES_GARBLED", "CHECK_SUBTITLES_NOT_NARRATION"}),
        (
            "1\n00:00:00,000 --> 00:00:01,000\n[TODO: lời kể cảnh 1]\n",
            {"CHECK_PLACEHOLDER_TEXT", "CHECK_SUBTITLES_NOT_NARRATION"},
        ),
        ("", {"CHECK_SUBTITLES_MISSING"}),
    ],
)
def test_wrong_garbled_placeholder_or_missing_subtitles_are_critical(srt: str, expected: set[str]) -> None:
    found = subtitle_findings(srt, NARRATION, unit_key="episode:1")

    assert {f.code for f in found} == expected
    assert {f.severity for f in found} == {"CRITICAL"}


def _film(tmp_path: Path, source: str) -> Path:
    final = tmp_path / "final.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            source,
            "-t",
            "4",
            "-pix_fmt",
            "yuv420p",
            str(final),
        ],
        check=True,
    )
    return final


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("testsrc=s=576x1024:r=24", set()),
        ("color=c=black:s=576x1024:r=24", {"CHECK_BLACK_PICTURE"}),
        ("testsrc=s=96x170:r=24,pad=576:1024:240:427:black", {"CHECK_PICTURE_NOT_FILLING_FRAME"}),
    ],
)
def test_a_black_or_small_picture_is_critical(tmp_path: Path, source: str, expected: set[str]) -> None:
    assert {f.code for f in picture_findings(_film(tmp_path, source), unit_key="episode:1")} == expected


def test_well_timed_subtitles_raise_no_timing_finding() -> None:
    srt = SRT.replace("00:00:02,000 --> 00:00:04,000", "00:00:02,500 --> 00:00:04,500").replace(
        "00:00:00,300 --> 00:00:02,000", "00:00:00,300 --> 00:00:02,500"
    )

    assert timing_findings(srt, unit_key="episode:1") == []


@pytest.mark.parametrize(
    ("srt", "code"),
    [
        (
            "1\n00:00:00,000 --> 00:00:01,000\nÔng lão lặng lẽ thả lưới giữa dòng sông rộng.\n",
            "CHECK_SUBTITLE_TOO_FAST",
        ),
        ("1\n00:00:00,000 --> 00:00:00,500\nỪ.\n", "CHECK_SUBTITLE_TOO_SHORT"),
        ("1\n00:00:00,000 --> 00:00:08,000\nÔng lão lặng lẽ.\n", "CHECK_SUBTITLE_TOO_LONG"),
    ],
)
def test_badly_timed_subtitles_are_minor(srt: str, code: str) -> None:
    found = timing_findings(srt, unit_key="episode:1")

    assert [(f.code, f.severity) for f in found] == [(code, "MINOR")]


def _sound(tmp_path: Path, audio: str) -> Path:
    final = tmp_path / "sound.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=s=576x1024:r=24",
            "-f",
            "lavfi",
            "-i",
            audio,
            "-t",
            "8",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(final),
        ],
        check=True,
    )
    return final


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
@pytest.mark.parametrize(
    ("audio", "expected"),
    [
        ("sine=frequency=300:sample_rate=48000,volume=7dB", set()),
        ("sine=frequency=300:sample_rate=48000,volume=-20dB", {"CHECK_LOUDNESS_OFF_TARGET"}),
        (
            "sine=frequency=300:sample_rate=48000,volume=7dB,volume=enable='between(t,2,6)':volume=0",
            {"CHECK_DEAD_AIR"},
        ),
    ],
)
def test_quiet_finals_and_dead_air_are_minor(tmp_path: Path, audio: str, expected: set[str]) -> None:
    found = sound_findings(_sound(tmp_path, audio), unit_key="episode:1")

    assert {f.code for f in found} == expected
    assert {f.severity for f in found} <= {"MINOR"}
