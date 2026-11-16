"""Subtitle timestamps never write a four-digit millisecond field: a fraction that rounds up carries into the second,
the minute and the hour. The cases are OpenMontage's regression tests (tests/tools/test_subtitle_timestamps.py at
08e2151), given in microseconds, the unit our timelines use."""

from __future__ import annotations

import re

import pytest

from lib.presentation_renderer import _timestamp as srt_timestamp
from lib.speech_presentation import _vtt_timestamp as vtt_timestamp

_SRT = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}$")
_VTT = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}$")


def _us(seconds: float) -> int:
    return round(seconds * 1_000_000)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0.9999, "00:00:01,000"),
        (1.9996, "00:00:02,000"),
        (59.9999, "00:01:00,000"),
        (3599.9999, "01:00:00,000"),
        (7261.9999, "02:01:02,000"),
        (0.0, "00:00:00,000"),
        (1.5, "00:00:01,500"),
        (0.4994, "00:00:00,499"),
    ],
)
def test_srt_milliseconds_carry_into_the_second(seconds: float, expected: str):
    assert srt_timestamp(_us(seconds)) == expected


def test_vtt_truncates_to_the_millisecond_and_is_well_formed():
    assert vtt_timestamp(_us(83.25)) == "00:01:23.250"
    assert vtt_timestamp(_us(0.9999)) == "00:00:00.999"


@pytest.mark.parametrize("seconds", [0.0, 0.4995, 0.9995, 0.9999, 1.0, 59.9995, 3599.9999, 12345.9999])
def test_every_timestamp_is_well_formed(seconds: float):
    assert _SRT.match(srt_timestamp(_us(seconds)))
    assert _VTT.match(vtt_timestamp(_us(seconds)))
